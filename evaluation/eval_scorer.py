"""
Answer-scorer evaluation harness.

IMPORTANT — BENCHMARK STABILITY
-------------------------------
The QUESTION and the ANSWERS dict below are UNCHANGED from the pre-fix baseline
run (evaluation/results_before/scorer_results.json). They must stay unchanged so
before/after numbers are directly comparable. Do not edit them to improve results.

WHAT THIS MEASURES (no invented ground truth)
---------------------------------------------
  1. DETERMINISM       - is the evaluator a pure function of its inputs?
  2. PIPELINE VARIANCE - can the SAME answer score differently because of how the
                         pipeline selects source chunks?
  3. BEHAVIOURAL SPEC  - conformance to rules the code/prompt itself states.
  4. COMPONENT ABLATION- contribution of each heuristic component.
  5. GAMING PROBE      - can a non-answer built from keywords score well?
  6. DISCRIMINATION    - does the evaluator separate CORRECT from FACTUALLY WRONG?

Still NOT measured: agreement with human experts (MAE/RMSE/Spearman/QWK).
No expert labels exist. See human_eval_template.py.

Run:  python evaluation/eval_scorer.py            # both evaluators
      python evaluation/eval_scorer.py heuristic  # force heuristic only
Out:  evaluation/results/scorer_results.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings                                     # noqa: E402
from app.models import ResumeProfile                                # noqa: E402
from app.services import gemini_eval                                # noqa: E402
from app.services.documents import load_knowledge_chunks            # noqa: E402
from app.services.interview import analyze_answer, model_to_dict    # noqa: E402
from app.services.retrieval import KnowledgeIndex, build_query      # noqa: E402

# Offline evaluation: throughput does not matter and a genuine Gemini result is
# worth waiting for, so honour the server's retryDelay across several attempts.
# The interactive browser path uses the fast-fail "interactive" profile instead.
gemini_eval.set_retry_profile("batch")

ROLE = "ai-engineer"
COLLECTION = "ai-ml"
TOPIC = "model evaluation"

# ── FROZEN BENCHMARK INPUTS (identical to the pre-fix baseline) ───────────────
QUESTION = ("You are applying model evaluation in a production system. What design "
            "decision would you make first and what metric would validate it? "
            "Include one concrete metric, system constraint, or edge case.")

PROFILE = ResumeProfile(
    candidate_name="Eval Harness",
    skills=["python", "pytorch", "rag", "llm", "model evaluation", "classification"],
    technologies=["python", "pytorch", "rag", "llm", "fastapi"],
    domains=["model evaluation", "classification", "information retrieval"],
    seniority_signal="experienced",
)

ANSWERS = {
    "verbatim_question_copy": QUESTION,
    "generic_nonanswer": "I do not know much about this topic, not sure, no idea really.",
    "very_short_real": "Use precision and recall.",
    "substantive_answer": (
        "First I would decide the evaluation metric before touching the model, because the "
        "metric encodes the business tradeoff. For a fraud classifier the cost of a false "
        "negative dominates, so I would optimise recall at a fixed precision floor of 0.90 "
        "rather than accuracy, which is meaningless at 2 percent prevalence. The design "
        "decision is a held-out temporal split instead of a random split, since a random "
        "split leaks future information and inflated our offline AUC by 6 points. To "
        "validate it I would track precision at fixed recall on a rolling weekly window "
        "and alert on drift. The main failure mode is label delay: chargebacks arrive 30 "
        "days late, so the recent window looks artificially clean."
    ),
    "keyword_stuffed_nonanswer": (
        "accuracy precision recall latency model evaluation pipeline training validation "
        "vector embedding retrieval monitoring deployment classification regression "
        "clustering feature metric architecture batch bias scaling testing tradeoff 42 "
        "percent because for example the data learning training model"
    ),
    "fluent_but_wrong": (
        "Model evaluation means you should always maximise accuracy, because accuracy is "
        "the only metric that matters in production systems. Precision and recall are "
        "academic ideas that do not apply once you deploy. You should train and test on "
        "the same data so the model sees every example, and a 99 percent training accuracy "
        "guarantees the system will work correctly for all future users without drift."
    ),
    "off_topic_fluent": (
        "I really enjoy hiking in the mountains during the summer months because the "
        "weather is pleasant and the trails are quiet. Last year we walked for about 12 "
        "kilometres each day and camped near a lake, which was a wonderful experience for "
        "the whole family and something I would recommend to anyone who enjoys nature."
    ),
}

_index: KnowledgeIndex | None = None


def _get_index() -> KnowledgeIndex:
    global _index
    if _index is None:
        _index = KnowledgeIndex(load_knowledge_chunks(COLLECTION))
    return _index


def ranked_pool() -> list[dict]:
    """The fetch_k candidate pool, in rank order (mirrors interview.py)."""
    hits = _get_index().search(build_query(ROLE, PROFILE, None), max(settings.top_k * 3, 12))
    return [model_to_dict(h) for h in hits]


def top_sources() -> list[dict]:
    """What the FIXED pipeline now passes downstream: the ranked top-k."""
    return ranked_pool()[: settings.top_k]


def score(answer: str, sources: list[dict], hint_used: bool = False,
          force_heuristic: bool = False) -> dict:
    if force_heuristic:
        saved = gemini_eval._available
        gemini_eval._available = False
        try:
            return analyze_answer(answer=answer, question_text=QUESTION, topic=TOPIC,
                                  sources=sources, hint_used=hint_used, role=ROLE,
                                  difficulty="intermediate")
        finally:
            gemini_eval._available = saved
    return analyze_answer(answer=answer, question_text=QUESTION, topic=TOPIC,
                          sources=sources, hint_used=hint_used, role=ROLE,
                          difficulty="intermediate")


# ─────────────────────────────────────────────────────────────────────────────
def test_determinism(sources, repeats=20, force_heuristic=True) -> dict:
    out = {}
    for name, ans in ANSWERS.items():
        scores = [score(ans, sources, force_heuristic=force_heuristic)["score"]
                  for _ in range(repeats)]
        out[name] = {
            "repeats": repeats,
            "distinct_scores": sorted(set(scores)),
            "n_distinct": len(set(scores)),
            "stdev": round(statistics.pstdev(scores), 4),
            "range": max(scores) - min(scores),
            "deterministic": len(set(scores)) == 1,
        }
    return out


def test_pipeline_variance() -> dict:
    """Score spread attributable to HOW the pipeline picks source chunks.

    BEFORE the fix: interview.py did random.sample(pool_of_15, 5), so 3003
    distinct chunk-sets were reachable and grounding varied with the draw.
    AFTER the fix: the pipeline always passes the ranked top-5, so exactly ONE
    chunk-set is reachable and the spread is 0 by construction.

    Both regimes are measured here over the same candidate pool.
    """
    import itertools
    import random as _r

    pool = ranked_pool()
    k = min(settings.top_k, len(pool))
    fixed = pool[:k]
    rng = _r.Random(7)
    out = {}
    for name, ans in ANSWERS.items():
        # AFTER: the single chunk-set the pipeline can now produce
        after = [score(ans, fixed, force_heuristic=True)["score"] for _ in range(20)]
        # BEFORE-regime simulation: random 5-of-15 draws, same as the old pipeline
        before = []
        for _ in range(200):
            before.append(score(ans, rng.sample(pool, k), force_heuristic=True)["score"])
        out[name] = {
            "after_fixed_topk": {
                "trials": len(after), "min": min(after), "max": max(after),
                "spread": max(after) - min(after),
                "stdev": round(statistics.pstdev(after), 3),
                "reachable_chunk_sets": 1,
            },
            "before_random_sample_regime": {
                "trials": len(before), "min": min(before), "max": max(before),
                "spread": max(before) - min(before),
                "stdev": round(statistics.pstdev(before), 3),
                "reachable_chunk_sets": len(list(itertools.combinations(range(len(pool)), k)))
                if len(pool) <= 15 else None,
            },
        }
    return out


BEHAVIOURAL_SPEC = {
    "copy_paste_under_8": ("verbatim_question_copy", lambda r: r["score"] < 8,
        "A mirrored question must score below 8"),
    "generic_capped_20": ("generic_nonanswer", lambda r: r["score"] <= 20,
        "Generic non-answers cap at 20"),
    "one_liner_capped_45": ("very_short_real", lambda r: r["score"] <= 45,
        "A correct one-liner should not exceed 45"),
    "substantive_scores_above_50": ("substantive_answer", lambda r: r["score"] > 50,
        "A detailed, correct, metric-rich answer clears the developing band"),
    "off_topic_scores_low": ("off_topic_fluent", lambda r: r["score"] < 45,
        "Off-topic answers score low"),
    "wrong_below_correct": (None, None,
        "A factually wrong answer must score strictly below the correct one"),
    "gibberish_below_correct": (None, None,
        "Keyword-stuffed text must score strictly below the correct answer"),
}


def test_behavioural_spec(sources, force_heuristic: bool, cache=None) -> dict:
    out = {}
    if cache is None:
        cache = {k: score(v, sources, force_heuristic=force_heuristic)
                 for k, v in ANSWERS.items()}
    for name, (akey, predicate, rule) in BEHAVIOURAL_SPEC.items():
        if akey is None:
            olabel = ("fluent_but_wrong" if name == "wrong_below_correct"
                      else "keyword_stuffed_nonanswer")
            a, b = cache["substantive_answer"], cache[olabel]
            # A comparison is only meaningful if BOTH sides came from the same
            # evaluator. Mixing a Gemini score with a heuristic fallback score
            # (e.g. after a rate-limit) would be a fabricated result.
            same = a.get("evaluator") == b.get("evaluator")
            out[name] = {
                "rule": rule, "correct_score": a["score"],
                "other_answer": olabel, "other_score": b["score"],
                "margin": a["score"] - b["score"],
                "evaluator_a": a.get("evaluator"), "evaluator_b": b.get("evaluator"),
                "comparable": same,
                "passes": bool(same and b["score"] < a["score"]),
                "invalid_reason": None if same else
                    f"evaluator mismatch ({a.get('evaluator')} vs {b.get('evaluator')}) "
                    f"- result EXCLUDED, not counted as a pass",
            }
            continue
        r = cache[akey]
        out[name] = {"rule": rule, "answer_used": akey, "score": r["score"],
                     "level": r["level"], "passes": bool(predicate(r))}
    passed = sum(1 for v in out.values() if v.get("passes"))
    excluded = sum(1 for v in out.values() if v.get("comparable") is False)
    out["_summary"] = {"checks": len(BEHAVIOURAL_SPEC), "passed": passed,
                       "excluded_evaluator_mismatch": excluded,
                       "note": "Specification conformance, NOT an accuracy metric. "
                               "Cross-evaluator comparisons are excluded, not counted."}
    return out


def test_component_ablation(sources) -> dict:
    filler = ["something"] * 60
    base = " ".join(filler)
    topic = base + " model evaluation"
    technical = topic + " precision recall latency monitoring pipeline"
    number = technical + " 42 percent"
    src_words = set()
    for s in sources:
        src_words.update(w for w in (s.get("text") or "").lower().split() if len(w) > 4)
    grounded = number + " " + " ".join(sorted(src_words)[:12])
    probes = {"1_filler_only": base, "2_plus_topic_terms": topic,
              "3_plus_technical_terms": technical, "4_plus_numeric_specificity": number,
              "5_plus_grounding_terms": grounded}
    out, prev = {}, 0
    for name, txt in probes.items():
        r = score(txt, sources, force_heuristic=True)
        out[name] = {"score": r["score"], "delta_vs_previous": r["score"] - prev,
                     "level": r["level"]}
        prev = r["score"]
    out["_note"] = "Cumulative probes; deltas include interacting caps."
    return out


def run_suite(sources, force_heuristic: bool, label: str, throttle: float = 0.0) -> dict:
    """Evaluate every frozen answer ONCE and reuse the result everywhere.

    Gemini's free tier allows 5 requests/minute for gemini-2.5-flash, so the
    suite must budget calls. Caching also guarantees the behavioural spec and
    the score table are computed from the same evaluations.
    """
    print("=" * 74)
    print(f"EVALUATOR UNDER TEST: {label}")
    print("=" * 74)

    scores: dict[str, dict] = {}
    for i, (k, v) in enumerate(ANSWERS.items()):
        if throttle and i:
            time.sleep(throttle)
        scores[k] = score(v, sources, force_heuristic=force_heuristic)
        got = scores[k].get("evaluator")
        if not force_heuristic and got != "gemini":
            print(f"    !! {k}: expected gemini, got {got!r} - EXCLUDED as invalid")
            scores[k]["_invalid"] = True
    actual = scores["substantive_answer"].get("evaluator", "unknown")
    print(f"evaluator field returned: {actual!r}")
    print("\n[scores on the frozen 7-answer benchmark]")
    for k, r in scores.items():
        extra = ""
        if r.get("dimension_scores"):
            extra = f"  correctness={r['dimension_scores'].get('correctness')}"
        if r.get("factual_errors"):
            extra += f"  errors={len(r['factual_errors'])}"
        print(f"    {k:28s} {r['score']:3d}  {r['level']:<12s}{extra}")

    beh = test_behavioural_spec(sources, force_heuristic, cache=scores)
    print(f"\n[behavioural spec] {beh['_summary']['passed']}/{beh['_summary']['checks']} pass")
    for k, v in beh.items():
        if k.startswith("_"):
            continue
        mark = "PASS" if v["passes"] else "FAIL"
        if "margin" in v:
            if v.get("comparable") is False:
                print(f"    SKIP  {k:30s} {v['invalid_reason']}")
            else:
                print(f"    {mark}  {k:30s} correct={v['correct_score']} "
                      f"vs {v['other_answer']}={v['other_score']} (margin {v['margin']:+d})")
        else:
            print(f"    {mark}  {k:30s} score={v['score']:3d}")

    if force_heuristic:
        det = test_determinism(sources, force_heuristic=True)
        ndet = sum(1 for v in det.values() if v["deterministic"])
        print(f"[determinism] {ndet}/{len(det)} answers deterministic over 20 repeats")
        for k, v in det.items():
            if not v["deterministic"]:
                print(f"    NON-DET  {k}: {v['distinct_scores']} (sd={v['stdev']})")
    else:
        # API budget: repeat ONE answer a few times instead of 20x7.
        reps = int(os.getenv("GEMINI_DET_REPEATS", "3"))
        vals = []
        for i in range(reps):
            if throttle and i:
                time.sleep(throttle)
            r = score(ANSWERS["substantive_answer"], sources, force_heuristic=False)
            if r.get("evaluator") == "gemini":
                vals.append(r["score"])
        det = {"substantive_answer": {
            "repeats": len(vals), "distinct_scores": sorted(set(vals)),
            "n_distinct": len(set(vals)),
            "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "range": (max(vals) - min(vals)) if vals else None,
            "deterministic": (len(set(vals)) == 1) if vals else None,
            "note": f"Limited to 1 answer x {reps} repeats by the 5 req/min free-tier quota.",
        }}
        print(f"[determinism] gemini, 1 answer x {len(vals)} valid repeats -> "
              f"scores={sorted(set(vals))} deterministic={det['substantive_answer']['deterministic']}")

    return {
        "evaluator_label": label,
        "evaluator_field_returned": actual,
        "scores": {k: {"score": r["score"], "level": r["level"],
                       "evaluator": r.get("evaluator"),
                       "dimension_scores": r.get("dimension_scores"),
                       "factual_errors": r.get("factual_errors", []),
                       "component_scores": r.get("component_scores")}
                   for k, r in scores.items()},
        "behavioural_spec": beh,
        "determinism": det,
    }


def main() -> None:
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    avail = gemini_eval.availability()
    print("=" * 74)
    print("ANSWER SCORER EVALUATION")
    print(f"Gemini availability: {avail}")
    print("Benchmark inputs are FROZEN and identical to the pre-fix baseline.")
    print("No human labels exist; MAE/RMSE/correlation are NOT computed.")
    print("=" * 74)

    sources = top_sources()
    print(f"\nranked top-{len(sources)} sources passed downstream:")
    for i, s in enumerate(sources, 1):
        print(f"   rank {i}: {s['document'][:40]:40s} p{s['page']:<4} score={s['score']}")

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "gemini": avail, "role": ROLE, "topic": TOPIC, "question": QUESTION,
            "benchmark_frozen": True,
            "caveat": "No human-labelled scores exist. MAE, RMSE, Pearson, Spearman "
                      "and QWK against expert judgement are NOT computed.",
        },
        "answers_used": ANSWERS,
        "ranked_sources": [{"rank": i, "document": s["document"], "page": s["page"],
                            "score": s["score"]} for i, s in enumerate(sources, 1)],
    }

    if only != "gemini":
        payload["heuristic"] = run_suite(sources, force_heuristic=True, label="HEURISTIC")
        payload["component_ablation"] = test_component_ablation(sources)
        print("\n[component ablation]")
        for k, v in payload["component_ablation"].items():
            if not k.startswith("_"):
                print(f"    {k:28s} score={v['score']:3d} (+{v['delta_vs_previous']})")

    if avail["available"] and only != "heuristic":
        thr = float(os.getenv("GEMINI_THROTTLE_SECONDS", "13"))
        print(f"(throttling Gemini calls by {thr}s for the 5 req/min free tier)")
        payload["gemini"] = run_suite(sources, force_heuristic=False, label="GEMINI", throttle=thr)
    elif not avail["available"]:
        print("\nGemini unavailable - Gemini suite SKIPPED (not estimated).")

    print("\n[pipeline variance: before-regime vs after-fix]")
    payload["pipeline_variance"] = test_pipeline_variance()
    for k, v in payload["pipeline_variance"].items():
        b, a = v["before_random_sample_regime"], v["after_fixed_topk"]
        print(f"    {k:28s} before spread={b['spread']:3d} (sd={b['stdev']:5.2f})  ->  "
              f"after spread={a['spread']:3d} (sd={a['stdev']:.2f})")

    (out_dir / "scorer_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved -> {out_dir / 'scorer_results.json'}")


if __name__ == "__main__":
    main()
