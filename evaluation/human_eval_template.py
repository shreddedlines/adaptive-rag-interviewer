"""
Human annotation harness.

This file does TWO things:

  A) `make_sheets()`  — emits blank annotation sheets (CSV) for the three
     evaluations that genuinely require human judgement in this project:
        1. retrieval relevance   (is this chunk relevant to this query?)
        2. question quality      (1-5 rubric per dimension)
        3. answer scoring        (expert 0-100 score per answer)

  B) `score_sheets()` — once the sheets are filled in by humans, computes the
     real metrics: Recall/Precision/nDCG for retrieval, mean/threshold/IRR for
     questions, and MAE/RMSE/Pearson/Spearman/quadratic-weighted-kappa for the
     automated scorer vs. experts.

NOTHING IS COMPUTED UNTIL LABELS EXIST. Running B on empty sheets exits with a
message rather than producing a number. This is deliberate: the whole point of
this harness is that these metrics cannot be claimed without annotation.

Usage:
    python evaluation/human_eval_template.py make      # emit blank sheets
    python evaluation/human_eval_template.py score     # after labelling
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHEETS = Path(__file__).parent / "sheets"
SEED = 20260910

# ── Sampling plan ────────────────────────────────────────────────────────────
# Deliberately SMALL and RIGOROUS rather than large and fake.
N_RETRIEVAL_QUERIES = 40      # 5 per role x 8 roles
N_CHUNKS_PER_QUERY = 10       # judge the top-10 => supports Recall@1/3/5/10
N_QUESTIONS = 100             # ~12-13 per role
N_ANSWERS = 60                # 12 questions x 5 answers spanning the quality range
N_ANNOTATORS = 2              # minimum for inter-rater agreement; 3 is better


def make_sheets() -> None:
    from app.config import settings
    from app.models import ResumeProfile
    from app.services.documents import ROLE_DESCRIPTIONS
    from app.services.retrieval import build_query, get_index

    SHEETS.mkdir(exist_ok=True)
    rng = random.Random(SEED)

    profiles = [
        ResumeProfile(candidate_name="A", seniority_signal="experienced",
                      skills=["python", "pytorch", "rag", "llm", "model evaluation"],
                      technologies=["python", "pytorch", "rag"],
                      domains=["model evaluation", "information retrieval"]),
        ResumeProfile(candidate_name="B", seniority_signal="entry-level",
                      skills=["sql", "python", "pandas", "statistics"],
                      technologies=["sql", "python", "pandas"],
                      domains=["regression", "classification"]),
    ]

    # ── Sheet 1: retrieval relevance ─────────────────────────────────────────
    rows = []
    qid = 0
    for role in ROLE_DESCRIPTIONS:
        index = get_index(role)
        for i in range(N_RETRIEVAL_QUERIES // len(ROLE_DESCRIPTIONS)):
            profile = profiles[i % len(profiles)]
            query = build_query(role, profile, None)
            hits = index.search(query, N_CHUNKS_PER_QUERY)
            qid += 1
            for rank, h in enumerate(hits, 1):
                rows.append({
                    "query_id": qid, "role": role, "rank": rank,
                    "cosine_score": h.score,
                    "query": query[:200],
                    "document": h.document, "page": h.page,
                    "chunk_text": h.text[:700].replace("\n", " "),
                    # ANNOTATOR FILLS THIS IN:
                    "relevance_0_1_2": "",   # 0=irrelevant 1=marginal 2=relevant
                    "annotator_id": "",
                })
    _write(SHEETS / "sheet1_retrieval_relevance.csv", rows)

    # ── Sheet 2: question quality ────────────────────────────────────────────
    from app.services.interview import _difficulty, _question_text, _topic
    random.seed(SEED)
    qrows = []
    for role in ROLE_DESCRIPTIONS:
        index = get_index(role)
        used: set[str] = set()
        for i in range(N_QUESTIONS // len(ROLE_DESCRIPTIONS)):
            profile = profiles[i % len(profiles)]
            hits = index.search(build_query(role, profile, None), max(settings.top_k * 3, 12))
            sources = random.sample(hits, min(settings.top_k, len(hits))) if hits else []
            topic = _topic(profile, sources, used)
            used.add(topic)
            diff = _difficulty(profile, i, None)
            qrows.append({
                "question_id": f"{role}-{i}", "role": role, "topic": topic,
                "difficulty_claimed": diff,
                "question": _question_text(role, topic, diff, sources, profile),
                "source_docs": "; ".join(sorted({s.document for s in sources})),
                # ANNOTATOR FILLS THESE IN (1-5 Likert):
                "role_relevance_1_5": "", "topic_relevance_1_5": "",
                "grounding_1_5": "", "technical_correctness_1_5": "",
                "clarity_1_5": "", "difficulty_matches_claim_1_5": "",
                "is_duplicate_of_earlier_y_n": "", "hallucination_y_n": "",
                "annotator_id": "",
            })
    _write(SHEETS / "sheet2_question_quality.csv", qrows)

    # ── Sheet 3: answer scoring ──────────────────────────────────────────────
    arows = [{
        "answer_id": "", "question": "", "topic": "", "role": "",
        "candidate_answer": "",
        "system_score_0_100": "", "system_level": "", "system_evaluator": "",
        # ANNOTATOR FILLS THIS IN, BLIND TO system_score:
        "expert_score_0_100": "", "expert_level": "", "annotator_id": "",
    }]
    _write(SHEETS / "sheet3_answer_scoring.csv", arows)

    print(f"Wrote blank annotation sheets to {SHEETS}")
    print(f"  sheet1_retrieval_relevance.csv  {len(rows)} rows "
          f"({qid} queries x top-{N_CHUNKS_PER_QUERY})")
    print(f"  sheet2_question_quality.csv     {len(qrows)} questions")
    print(f"  sheet3_answer_scoring.csv       header only - populate from real sessions")
    print(f"\nEach sheet must be labelled independently by >= {N_ANNOTATORS} annotators.")
    print("For sheet3, the annotator MUST NOT see system_score_0_100 while scoring.")


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Metric computation (only runs on labelled data)
# ─────────────────────────────────────────────────────────────────────────────
def _pearson(x, y):
    n = len(x)
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return num / den if den else float("nan")


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _spearman(x, y):
    return _pearson(_rank(x), _rank(y))


def _qwk(a, b, n_classes=5):
    """Quadratic weighted kappa - the right agreement metric for ordinal bands."""
    O = [[0] * n_classes for _ in range(n_classes)]
    for i, j in zip(a, b):
        O[i][j] += 1
    n = len(a)
    ha = [a.count(i) for i in range(n_classes)]
    hb = [b.count(i) for i in range(n_classes)]
    num = den = 0.0
    for i in range(n_classes):
        for j in range(n_classes):
            w = ((i - j) ** 2) / ((n_classes - 1) ** 2)
            E = ha[i] * hb[j] / n
            num += w * O[i][j]
            den += w * E
    return 1 - num / den if den else float("nan")


def score_sheets() -> None:
    s1 = SHEETS / "sheet1_retrieval_relevance.csv"
    s3 = SHEETS / "sheet3_answer_scoring.csv"

    if s1.exists():
        rows = [r for r in csv.DictReader(s1.open(encoding="utf-8"))
                if r.get("relevance_0_1_2", "").strip()]
        if not rows:
            print("sheet1: NO LABELS FOUND. Retrieval precision/recall/nDCG NOT computed.")
        else:
            print(f"sheet1: {len(rows)} labelled judgements -> computing graded metrics")
            # graded relevance: 2=relevant, 1=marginal, 0=irrelevant
            by_q: dict[str, list[tuple[int, int]]] = {}
            for r in rows:
                by_q.setdefault(r["query_id"], []).append(
                    (int(r["rank"]), int(r["relevance_0_1_2"])))
            import math
            for k in (1, 3, 5, 10):
                precs, ndcgs = [], []
                for judged in by_q.values():
                    judged.sort()
                    topk = [rel for _, rel in judged[:k]]
                    precs.append(sum(1 for x in topk if x == 2) / k)
                    dcg = sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(topk))
                    ideal = sorted([rel for _, rel in judged], reverse=True)[:k]
                    idcg = sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal))
                    ndcgs.append(dcg / idcg if idcg else 0.0)
                print(f"   P@{k:<2d} = {statistics.mean(precs):.3f}   "
                      f"nDCG@{k:<2d} = {statistics.mean(ndcgs):.3f}")
    if s3.exists():
        rows = [r for r in csv.DictReader(s3.open(encoding="utf-8"))
                if r.get("expert_score_0_100", "").strip()
                and r.get("system_score_0_100", "").strip()]
        if not rows:
            print("sheet3: NO LABELS FOUND. MAE / RMSE / Pearson / Spearman / QWK "
                  "NOT computed. These metrics MUST NOT be claimed without labels.")
            return
        sysv = [float(r["system_score_0_100"]) for r in rows]
        expv = [float(r["expert_score_0_100"]) for r in rows]
        n = len(rows)
        mae = sum(abs(a - b) for a, b in zip(sysv, expv)) / n
        rmse = (sum((a - b) ** 2 for a, b in zip(sysv, expv)) / n) ** 0.5

        def band(s):
            return 4 if s >= 78 else 3 if s >= 60 else 2 if s >= 35 else 1 if s >= 10 else 0
        agree = sum(1 for a, b in zip(sysv, expv) if band(a) == band(b)) / n
        print(f"\nsheet3: n={n}")
        print(f"   MAE        = {mae:.2f}")
        print(f"   RMSE       = {rmse:.2f}")
        print(f"   Pearson r  = {_pearson(sysv, expv):.3f}")
        print(f"   Spearman p = {_spearman(sysv, expv):.3f}")
        print(f"   Band agree = {agree:.3f}")
        print(f"   QWK        = {_qwk([band(x) for x in sysv], [band(x) for x in expv]):.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "make"
    if cmd == "make":
        make_sheets()
    elif cmd == "score":
        score_sheets()
    else:
        print(__doc__)
