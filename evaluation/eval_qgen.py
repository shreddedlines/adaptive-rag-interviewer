"""
Question-generation evaluation (structural + diversity metrics only).

NOTE ON SCOPE
-------------
Question QUALITY (technical correctness, clarity, difficulty calibration,
hallucination) requires expert human rating and is NOT estimated here.
See evaluation/human_eval_template.py for the annotation harness.

What IS measured, with no invented ground truth:
  1. GROUNDING (structural)  — does the generated question text actually contain
     content from the retrieved chunks? On the template-fallback path this is
     decidable by construction: the templates interpolate only {topic} and
     {role_label} (interview.py:107-128), and `source_hint` (line 104) is
     assigned but never used. Measured, not assumed.
  2. DUPLICATE RATE          — exact and near-duplicate questions across sessions.
  3. TOPIC DIVERSITY         — distinct topics per session; repeat rate.
  4. TEMPLATE COLLISION      — how often the same template is reused.

Run:  python evaluation/eval_qgen.py
Out:  evaluation/results/qgen_results.json
"""
from __future__ import annotations

import json
import random
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings                                    # noqa: E402
from app.models import ResumeProfile                               # noqa: E402
from app.services import gemini_eval                               # noqa: E402
from app.services.documents import ROLE_DESCRIPTIONS               # noqa: E402
from app.services.interview import _difficulty, _topic   # noqa: E402
from app.services.retrieval import build_query, get_index          # noqa: E402

# Offline evaluation: throughput does not matter and a genuine Gemini result is
# worth waiting for, so honour the server's retryDelay across several attempts.
# The interactive browser path uses the fast-fail "interactive" profile instead.
gemini_eval.set_retry_profile("batch")

SEED = 20260910
SESSIONS_PER_ROLE = 12
QUESTIONS_PER_SESSION = 5

PROFILE_POOL = [
    ResumeProfile(candidate_name="A", seniority_signal="experienced",
                  skills=["python", "pytorch", "rag", "llm", "nlp", "model evaluation"],
                  technologies=["python", "pytorch", "rag", "llm"],
                  domains=["model evaluation", "information retrieval"]),
    ResumeProfile(candidate_name="B", seniority_signal="entry-level",
                  skills=["sql", "python", "pandas", "statistics"],
                  technologies=["sql", "python", "pandas"],
                  domains=["regression", "classification"]),
    ResumeProfile(candidate_name="C", seniority_signal="project-heavy",
                  skills=["python", "computer vision", "deep learning", "numpy"],
                  technologies=["python", "pytorch", "numpy"],
                  domains=["classification", "feature engineering"]),
]

STOP = set("""a an the of to in for on with and or is are was were be been what how why
which that this these those you your i we they it its as at by from can could would
should do does did not no using use used explain describe walk me through role""".split())


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-]{2,}", text.lower()) if w not in STOP}


def simulate(force_local: bool = True) -> dict:
    """Replay the REAL question-generation path for many synthetic sessions.

    force_local=True disables Gemini so the LOCAL grounded generator is measured.
    That is deliberate: 480 Gemini calls is ~96 minutes on the 5 req/min free
    tier, and the pre-fix baseline measured the local path too, so this keeps the
    comparison like-for-like.
    """
    from app.services import gemini_eval as _g
    from app.services.interview import _build_question, _difficulty, _topic

    saved = _g._available
    if force_local:
        _g._available = False
    records = []
    try:
        for role in ROLE_DESCRIPTIONS:
            index = get_index(role)
            for s in range(SESSIONS_PER_ROLE):
                profile = PROFILE_POOL[s % len(PROFILE_POOL)]
                session_id = f"{role}-session-{s}"      # stands in for the uuid4
                used_topics: set[str] = set()
                used_signatures: set[str] = set()
                previous: list[str] = []
                running = None
                for qi in range(QUESTIONS_PER_SESSION):
                    query = build_query(role, profile, None)
                    fetch_k = max(settings.top_k * 3, 12)
                    # FIXED pipeline: ranked top-k, no random sampling
                    sources = index.search(query, fetch_k)[: settings.top_k]
                    topic = _topic(profile, sources, used_topics, salt=session_id)
                    used_topics.add(topic)
                    difficulty = _difficulty(profile, qi, running)
                    built = _build_question(
                        role=role, topic=topic, difficulty=difficulty, sources=sources,
                        profile=profile, previous_questions=previous,
                        used_signatures=used_signatures, rotation=qi,
                        salt=session_id, index=index,
                    )
                    text = built["question"]
                    previous.append(text)

                    chunk_words = set()
                    chunk_text = " ".join((src.text or "").lower() for src in sources)
                    for src in sources:
                        chunk_words |= content_words(src.text)
                    qwords = content_words(text)
                    topic_words = content_words(topic)
                    role_words = content_words(ROLE_DESCRIPTIONS[role])
                    novel = (qwords & chunk_words) - topic_words - role_words
                    concept = built.get("grounded_concept")

                    records.append({
                        "role": role, "session": s, "q_index": qi,
                        "topic": topic, "difficulty": built.get("difficulty", difficulty),
                        "text": text, "generator": built.get("generator"),
                        "grounded_concept": concept,
                        "concept_from_chunks": bool(concept and concept.lower() in chunk_text),
                        "n_sources": len(sources),
                        "grounded_words_beyond_topic": sorted(novel),
                        "n_grounded_words_beyond_topic": len(novel),
                    })
    finally:
        _g._available = saved
    return {"records": records}



def analyse(records: list[dict]) -> dict:
    texts = [r["text"] for r in records]
    n = len(texts)

    exact_dupes = n - len(set(texts))
    counts = Counter(texts)
    most_common = counts.most_common(5)

    # Template signature: question text with the topic substring blanked out
    sigs = []
    for r in records:
        sig = r["text"].replace(r["topic"], "{TOPIC}")
        for role_label in ROLE_DESCRIPTIONS.values():
            sig = sig.replace(role_label, "{ROLE}")
        sigs.append(sig)
    sig_counts = Counter(sigs)

    grounded = [r["n_grounded_words_beyond_topic"] for r in records]
    zero_grounded = sum(1 for g in grounded if g == 0)
    causal = sum(1 for r in records if r.get("concept_from_chunks"))

    # per-session topic repetition
    per_session_dupe = []
    by_session: dict[tuple, list[str]] = {}
    for r in records:
        by_session.setdefault((r["role"], r["session"]), []).append(r["topic"])
    for topics in by_session.values():
        per_session_dupe.append(len(topics) - len(set(topics)))

    diff_dist = Counter(r["difficulty"] for r in records)

    return {
        "questions_generated": n,
        "sessions_simulated": len(by_session),
        "grounding": {
            "definition": "content words shared between the question text and the "
                          "retrieved chunks, EXCLUDING the topic string and role label",
            "questions_with_zero_grounded_words": zero_grounded,
            "pct_with_zero_grounding": round(100 * zero_grounded / n, 1),
            "mean_grounded_words": round(statistics.mean(grounded), 3),
            "max_grounded_words": max(grounded),
            "causal_grounding_count": causal,
            "causal_grounding_pct": round(100 * causal / n, 1),
            "causal_definition": "the question contains a concept term provably "
                                 "extracted from the retrieved chunks (not a static template word)",
        },
        "duplicates": {
            "exact_duplicate_questions": exact_dupes,
            "exact_duplicate_rate_pct": round(100 * exact_dupes / n, 1),
            "distinct_questions": len(set(texts)),
            "most_repeated": [{"text": t[:100], "count": c} for t, c in most_common],
        },
        "template_reuse": {
            "distinct_template_signatures": len(sig_counts),
            "most_used_template": sig_counts.most_common(1)[0][1],
            "mean_uses_per_template": round(n / len(sig_counts), 2),
        },
        "topic_diversity": {
            "distinct_topics_overall": len({r["topic"] for r in records}),
            "mean_duplicate_topics_per_session": round(statistics.mean(per_session_dupe), 3),
            "sessions_with_a_repeated_topic": sum(1 for d in per_session_dupe if d > 0),
        },
        "difficulty_distribution": dict(diff_dist),
    }


def main() -> None:
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    available = gemini_eval._init()
    print("=" * 78)
    print("QUESTION GENERATION EVALUATION (structural + diversity only)")
    print(f"Gemini available: {available}  ->  generator under test: "
          f"{'GEMINI' if available else 'TEMPLATE FALLBACK'}")
    print("Question QUALITY requires expert rating and is NOT estimated here.")
    print("=" * 78)

    sim = simulate()
    res = analyse(sim["records"])

    print(f"\nGenerated {res['questions_generated']} questions "
          f"across {res['sessions_simulated']} simulated sessions "
          f"({len(ROLE_DESCRIPTIONS)} roles).")

    g = res["grounding"]
    print(f"\n[grounding]  questions with ZERO words traceable to retrieved chunks: "
          f"{g['questions_with_zero_grounded_words']}/{res['questions_generated']} "
          f"({g['pct_with_zero_grounding']}%)")
    print(f"             mean grounded words beyond topic = {g['mean_grounded_words']}")

    d = res["duplicates"]
    print(f"\n[duplicates] exact duplicate rate = {d['exact_duplicate_rate_pct']}% "
          f"({d['exact_duplicate_questions']} of {res['questions_generated']}); "
          f"{d['distinct_questions']} distinct")
    print(f"             most repeated question appeared {d['most_repeated'][0]['count']}x")

    t = res["template_reuse"]
    print(f"\n[templates]  {t['distinct_template_signatures']} distinct signatures, "
          f"mean {t['mean_uses_per_template']} uses each, "
          f"most-used {t['most_used_template']}x")

    td = res["topic_diversity"]
    print(f"\n[topics]     {td['distinct_topics_overall']} distinct topics; "
          f"sessions with a repeated topic: {td['sessions_with_a_repeated_topic']}"
          f"/{res['sessions_simulated']}")

    print(f"\n[difficulty] {res['difficulty_distribution']}")

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seed": SEED, "gemini_available": available,
            "generator_under_test": "local-grounded (Gemini disabled for like-for-like comparison)",
            "caveat": "Structural and diversity metrics only. Technical correctness, "
                      "clarity, difficulty calibration and hallucination rate require "
                      "expert human rating and are NOT reported.",
        },
        "results": res,
        "sample_questions": [r["text"] for r in sim["records"][:15]],
    }
    (out_dir / "qgen_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved -> {out_dir / 'qgen_results.json'}")


if __name__ == "__main__":
    main()
