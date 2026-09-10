"""
Retrieval evaluation harness for the PGAGI Candidate Screening RAG pipeline.

WHAT THIS DOES AND DOES NOT MEASURE
-----------------------------------
This script runs a KNOWN-ITEM (a.k.a. self-retrieval) benchmark against the
*actual* production index built by app/services/retrieval.py.

Ground truth is CONSTRUCTED, NOT FABRICATED: for a query taken verbatim from a
known chunk, the chunk it came from is, by construction, a relevant document.
No human judgement is invented anywhere in this file.

  * It DOES measure: whether the TF-IDF index + vectorizer + cosine ranking can
    find a passage when the query genuinely comes from that passage. This is an
    upper bound on retrieval capability and a lower bound on index health.
  * It does NOT measure: whether the chunks retrieved for a REAL production
    query ("ai-engineer interview experienced python pytorch ...") are
    topically appropriate interview material. That requires human relevance
    labels and is deliberately NOT estimated here.

Run:  python evaluation/eval_retrieval.py
Out:  evaluation/results/retrieval_results.json
"""
from __future__ import annotations

import json
import math
import random
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings                                    # noqa: E402
from app.models import ResumeProfile                               # noqa: E402
from app.services.documents import (                               # noqa: E402
    ROLE_DESCRIPTIONS, ROLE_KNOWLEDGE_BASE, list_role_documents,
    load_knowledge_chunks,
)
from app.services.retrieval import KnowledgeIndex, build_query      # noqa: E402

SEED = 20260910
COLLECTIONS = ["ai-ml", "data-science", "advanced-ml"]
K_VALUES = [1, 3, 5, 10, 15]

# Regex proxy for textbook front matter. This is a STATED, REPRODUCIBLE
# heuristic, not a human-labelled judgement. Reported as such.
FRONT_MATTER = re.compile(
    r"all rights reserved|copyright|isbn|table of contents|about the author|"
    r"acknowledg|preface|first edition|second edition|printed in|"
    r"no part of this publication",
    re.I,
)


# ─────────────────────────────────────────────────────────────────────────────
# Metric definitions (single-gold known-item retrieval)
# ─────────────────────────────────────────────────────────────────────────────
def success_at_k(rank: int | None, k: int) -> float:
    """1.0 if the gold chunk is within the top-k, else 0.0.
    With exactly one relevant document, Recall@K == Success@K."""
    return 1.0 if (rank is not None and rank <= k) else 0.0


def precision_at_k(rank: int | None, k: int) -> float:
    """With a single gold document, P@K = Success@K / K. Reported for
    completeness; it is bounded by 1/K and is NOT a useful quality signal
    in a single-gold setup. Included so the number cannot be misread."""
    return success_at_k(rank, k) / k


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank is not None else 0.0


def ndcg_at_k(rank: int | None, k: int) -> float:
    """Binary relevance, one gold doc => IDCG = 1, so nDCG@K = 1/log2(rank+1)."""
    if rank is None or rank > k:
        return 0.0
    return 1.0 / math.log2(rank + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Query construction (ground truth by construction)
# ─────────────────────────────────────────────────────────────────────────────
def sentence_query(text: str, rng: random.Random) -> str | None:
    """A verbatim sentence of 8-40 words lifted from the chunk."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)]
    usable = [s for s in sentences if 8 <= len(s.split()) <= 40]
    return rng.choice(usable) if usable else None


def term_query(text: str, index: KnowledgeIndex, n_terms: int = 6) -> str | None:
    """The n highest-TF-IDF terms of the chunk, joined — a keyword-style query.
    Uses the production vectorizer so the terms are exactly the ones the real
    index considers discriminative."""
    vec = index.vectorizer.transform([text])
    if vec.nnz == 0:
        return None
    names = index.vectorizer.get_feature_names_out()
    pairs = sorted(zip(vec.indices, vec.data), key=lambda p: -p[1])[:n_terms]
    terms = [names[i] for i, _ in pairs]
    return " ".join(terms) if terms else None


# ─────────────────────────────────────────────────────────────────────────────
def rank_of_gold(index: KnowledgeIndex, query: str, gold_idx: int, depth: int) -> int | None:
    """Rank (1-based) of the gold chunk in the ranked list, or None if outside depth.

    Ranks against the raw cosine scores rather than KnowledgeIndex.search(),
    because search() truncates text and drops score<=0 rows, which would make
    rank positions ambiguous. The ordering is identical: both use
    cosine_similarity + argsort descending (retrieval.py:23-24).
    """
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    qv = index.vectorizer.transform([query])
    scores = cosine_similarity(qv, index.matrix).flatten()
    order = np.argsort(scores)[::-1][:depth]
    for position, idx in enumerate(order, 1):
        if int(idx) == gold_idx:
            return position
    return None


def evaluate_collection(collection: str, rng: random.Random) -> dict:
    chunks = load_knowledge_chunks(collection)
    t0 = time.time()
    index = KnowledgeIndex(chunks)
    build_seconds = round(time.time() - t0, 3)

    n = len(chunks)
    lengths = [len(c.text) for c in chunks]
    docs = sorted({c.document for c in chunks})
    front_matter_hits = sum(1 for c in chunks if FRONT_MATTER.search(c.text))

    results: dict[str, dict] = {}
    per_query_records: list[dict] = []

    for qtype in ("sentence", "terms"):
        ranks: list[int | None] = []
        latencies: list[float] = []
        gold_scores: list[float] = []
        skipped = 0

        for gold_idx, chunk in enumerate(chunks):
            if qtype == "sentence":
                q = sentence_query(chunk.text, rng)
            else:
                q = term_query(chunk.text, index)
            if not q:
                skipped += 1
                continue

            t = time.time()
            rank = rank_of_gold(index, q, gold_idx, depth=max(K_VALUES))
            latencies.append((time.time() - t) * 1000)
            ranks.append(rank)

            per_query_records.append({
                "collection": collection, "query_type": qtype,
                "gold_chunk": chunk.id, "gold_page": chunk.page,
                "gold_doc": chunk.document, "rank": rank,
                "query_preview": q[:120],
            })

        evaluated = len(ranks)
        results[qtype] = {
            "queries_evaluated": evaluated,
            "queries_skipped_no_usable_text": skipped,
            "recall_at_k": {
                f"@{k}": round(sum(success_at_k(r, k) for r in ranks) / evaluated, 4)
                for k in K_VALUES
            } if evaluated else {},
            "precision_at_k": {
                f"@{k}": round(sum(precision_at_k(r, k) for r in ranks) / evaluated, 4)
                for k in K_VALUES
            } if evaluated else {},
            "mrr": round(sum(reciprocal_rank(r) for r in ranks) / evaluated, 4) if evaluated else None,
            "ndcg_at_k": {
                f"@{k}": round(sum(ndcg_at_k(r, k) for r in ranks) / evaluated, 4)
                for k in K_VALUES
            } if evaluated else {},
            "median_rank_of_gold": statistics.median([r for r in ranks if r]) if any(ranks) else None,
            "gold_outside_top_15": sum(1 for r in ranks if r is None),
            "mean_query_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        }

    return {
        "collection": collection,
        "corpus": {
            "documents_indexed": len(docs),
            "document_names": docs,
            "chunks": n,
            "pages_indexed_per_doc_cap": settings.max_pages_per_document,
            "chunk_size_setting": settings.chunk_size,
            "chunk_overlap_setting": settings.chunk_overlap,
            "chunk_len_chars_mean": round(statistics.mean(lengths), 1),
            "chunk_len_chars_median": statistics.median(lengths),
            "chunk_len_chars_min": min(lengths),
            "chunk_len_chars_max": max(lengths),
            "vocabulary_size": len(index.vectorizer.get_feature_names_out()),
            "tfidf_matrix_shape": list(index.matrix.shape),
            "tfidf_density_pct": round(
                100 * index.matrix.nnz / (index.matrix.shape[0] * index.matrix.shape[1]), 4
            ),
            "index_build_seconds": build_seconds,
            "front_matter_regex_hits": front_matter_hits,
            "front_matter_regex_pct": round(100 * front_matter_hits / n, 1),
        },
        "known_item_benchmark": results,
        "_records": per_query_records,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Production-shaped queries: score distribution ONLY (no relevance labels exist)
# ─────────────────────────────────────────────────────────────────────────────
PROFILES = {
    "experienced_ai": ResumeProfile(
        candidate_name="P1",
        skills=["python", "pytorch", "rag", "llm", "nlp", "machine learning",
                "information retrieval", "model evaluation"],
        technologies=["python", "pytorch", "rag", "llm", "fastapi", "docker"],
        domains=["information retrieval", "model evaluation", "classification"],
        seniority_signal="experienced",
    ),
    "entry_data": ResumeProfile(
        candidate_name="P2",
        skills=["sql", "python", "pandas", "statistics", "regression"],
        technologies=["sql", "python", "pandas"],
        domains=["regression", "classification"],
        seniority_signal="entry-level",
    ),
    "cv_engineer": ResumeProfile(
        candidate_name="P3",
        skills=["python", "pytorch", "computer vision", "deep learning", "numpy"],
        technologies=["python", "pytorch", "tensorflow", "numpy"],
        domains=["classification", "model evaluation"],
        seniority_signal="project-heavy",
    ),
}


def production_query_profile() -> dict:
    """Runs the REAL build_query() for every role x profile and reports the
    cosine score distribution of what the retriever actually returns.

    NOTE: these are similarity scores, NOT accuracy. No relevance labels exist
    for these queries, so no recall/precision is computed here. Intentionally.
    """
    out = []
    for role in ROLE_DESCRIPTIONS:
        collection = ROLE_KNOWLEDGE_BASE[role]
        index = KnowledgeIndex(load_knowledge_chunks(collection))
        for pname, profile in PROFILES.items():
            query = build_query(role, profile, previous_answer=None)
            fetch_k = max(settings.top_k * 3, 12)   # mirrors interview.py:161
            hits = index.search(query, fetch_k)
            scores = [h.score for h in hits]
            out.append({
                "role": role,
                "collection": collection,
                "profile": pname,
                "query_chars": len(query),
                "query_preview": query[:110],
                "hits_returned": len(hits),
                "fetch_k_requested": fetch_k,
                "top1_cosine": scores[0] if scores else None,
                "top5_mean_cosine": round(statistics.mean(scores[:5]), 4) if scores else None,
                "top15_mean_cosine": round(statistics.mean(scores), 4) if scores else None,
                "min_cosine_in_topk": min(scores) if scores else None,
                "distinct_source_docs_in_top15": len({h.document for h in hits}),
                "pages_in_top15": sorted({h.page for h in hits}),
            })
    return {
        "note": "Cosine similarity scores only. These are NOT accuracy and NOT "
                "recall. No relevance ground truth exists for production queries.",
        "runs": out,
        "overall_top1_cosine_mean": round(
            statistics.mean([r["top1_cosine"] for r in out if r["top1_cosine"]]), 4),
        "overall_top1_cosine_min": min(r["top1_cosine"] for r in out if r["top1_cosine"]),
        "overall_top1_cosine_max": max(r["top1_cosine"] for r in out if r["top1_cosine"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Effect of interview.py:163  random.sample(all_sources, 5)
# ─────────────────────────────────────────────────────────────────────────────
def sampling_loss(retrieval_results: list[dict], trials: int = 20000) -> dict:
    """Probability that a retrieved chunk actually reaches the generator.

    BEFORE the fix, interview.py did:
        all_sources = search(query, 15)
        sources     = random.sample(all_sources, 5)
    so any chunk ranked 1..15 had probability 5/15 = 1/3 of reaching the prompt,
    identically for rank 1 and rank 15.

    AFTER the fix, interview.py does:
        sources = all_sources[:top_k]
    so ranks 1..5 reach the prompt with probability 1.0 and ranks 6..15 with
    probability 0.0. Effective recall at the generator therefore equals
    Recall@top_k of the retriever, with no sampling loss.

    The Monte Carlo below re-measures the OLD regime for the comparison table.
    """
    rng = random.Random(SEED)
    kept = 0
    rank1_kept = 0
    for _ in range(trials):
        chosen = set(rng.sample(range(15), 5))
        if 0 in chosen:
            rank1_kept += 1
        kept += len(chosen & set(range(5))) / 5.0

    analytic_p = 5 / 15
    # Effective "gold reaches the prompt" rate = Recall@15 * P(survives sampling)
    top_k = settings.top_k
    effective = {}
    for entry in retrieval_results:
        for qtype, res in entry["known_item_benchmark"].items():
            r15 = res["recall_at_k"].get("@15")
            rtk = res["recall_at_k"].get(f"@{top_k}")
            if r15 is None or rtk is None:
                continue
            effective[f"{entry['collection']}::{qtype}"] = {
                "recall_at_15_of_retriever": r15,
                f"recall_at_{top_k}_of_retriever": rtk,
                "BEFORE_p_survives_random_sample": round(analytic_p, 4),
                "BEFORE_effective_recall_at_generator": round(r15 * analytic_p, 4),
                "AFTER_p_top_ranked_chunk_survives": 1.0,
                "AFTER_effective_recall_at_generator": rtk,
            }
    return {
        "before": "interview.py did random.sample(top15, 5): rank 1 and rank 15 were "
                  "equally likely to be kept; effective recall = Recall@15 x 1/3.",
        "after": f"interview.py now takes all_sources[:{top_k}]: the top-{top_k} ranked "
                 f"chunks always reach the generator; effective recall = Recall@{top_k}.",
        "analytic_p_before": round(analytic_p, 4),
        "monte_carlo_p_rank1_survives_before": round(rank1_kept / trials, 4),
        "monte_carlo_trials": trials,
        "p_after": 1.0,
        "effective_recall": effective,
    }


def main() -> None:
    rng = random.Random(SEED)
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    print("=" * 78)
    print("RETRIEVAL EVALUATION — PGAGI Candidate Screening")
    print("Known-item benchmark. Ground truth by construction, not fabricated.")
    print("=" * 78)

    per_collection = []
    all_records = []
    for c in COLLECTIONS:
        print(f"\n[{c}] building index and running benchmark ...")
        res = evaluate_collection(c, rng)
        all_records.extend(res.pop("_records"))
        per_collection.append(res)
        corp = res["corpus"]
        print(f"  docs={corp['documents_indexed']} chunks={corp['chunks']} "
              f"vocab={corp['vocabulary_size']} build={corp['index_build_seconds']}s "
              f"front_matter~{corp['front_matter_regex_pct']}%")
        for qt, r in res["known_item_benchmark"].items():
            print(f"  {qt:9s} n={r['queries_evaluated']:4d} "
                  f"R@1={r['recall_at_k']['@1']:.3f} R@5={r['recall_at_k']['@5']:.3f} "
                  f"R@10={r['recall_at_k']['@10']:.3f} MRR={r['mrr']:.3f} "
                  f"nDCG@10={r['ndcg_at_k']['@10']:.3f}")

    # Micro-average across all collections, weighted by query count
    micro = {}
    for qtype in ("sentence", "terms"):
        tot = sum(e["known_item_benchmark"][qtype]["queries_evaluated"] for e in per_collection)
        micro[qtype] = {
            "queries_evaluated": tot,
            "recall_at_k": {
                f"@{k}": round(sum(
                    e["known_item_benchmark"][qtype]["recall_at_k"][f"@{k}"] *
                    e["known_item_benchmark"][qtype]["queries_evaluated"]
                    for e in per_collection) / tot, 4)
                for k in K_VALUES
            },
            "mrr": round(sum(
                e["known_item_benchmark"][qtype]["mrr"] *
                e["known_item_benchmark"][qtype]["queries_evaluated"]
                for e in per_collection) / tot, 4),
            "ndcg_at_k": {
                f"@{k}": round(sum(
                    e["known_item_benchmark"][qtype]["ndcg_at_k"][f"@{k}"] *
                    e["known_item_benchmark"][qtype]["queries_evaluated"]
                    for e in per_collection) / tot, 4)
                for k in K_VALUES
            },
        }

    print("\n--- MICRO-AVERAGE ACROSS ALL 3 COLLECTIONS ---")
    for qt, m in micro.items():
        print(f"  {qt:9s} n={m['queries_evaluated']:4d} "
              f"R@1={m['recall_at_k']['@1']:.3f} R@3={m['recall_at_k']['@3']:.3f} "
              f"R@5={m['recall_at_k']['@5']:.3f} R@10={m['recall_at_k']['@10']:.3f} "
              f"MRR={m['mrr']:.3f}")

    print("\n[production queries] cosine distribution (NOT accuracy) ...")
    prod = production_query_profile()
    print(f"  top-1 cosine: mean={prod['overall_top1_cosine_mean']} "
          f"min={prod['overall_top1_cosine_min']} max={prod['overall_top1_cosine_max']}")

    print("\n[sampling loss] effect of random.sample(top15, 5) ...")
    loss = sampling_loss(per_collection)
    print(f"  BEFORE (random.sample): P(chunk reaches generator) = "
          f"{loss['analytic_p_before']}  (MC rank-1: {loss['monte_carlo_p_rank1_survives_before']})")
    print(f"  AFTER  (ranked top-{settings.top_k}):  P(top-ranked chunk reaches generator) = "
          f"{loss['p_after']}")

    payload = {
        "meta": {
            "seed": SEED,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "settings": {
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "top_k": settings.top_k,
                "max_pages_per_document": settings.max_pages_per_document,
                "max_document_mb": settings.max_document_mb,
            },
            "caveat": "Known-item retrieval measures index/vectorizer health. It is "
                      "an UPPER BOUND on retrieval capability and says nothing about "
                      "topical relevance for real interview queries, which would "
                      "require human relevance labels.",
        },
        "documents_on_disk": {
            k: [p.name for p in v] for k, v in list_role_documents().items()
        },
        "per_collection": per_collection,
        "micro_average": micro,
        "production_query_scores": prod,
        "sampling_loss": loss,
    }

    (out_dir / "retrieval_results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "retrieval_per_query.json").write_text(
        json.dumps(all_records, indent=2), encoding="utf-8")
    print(f"\nSaved -> {out_dir / 'retrieval_results.json'}")
    print(f"Saved -> {out_dir / 'retrieval_per_query.json'} ({len(all_records)} queries)")


if __name__ == "__main__":
    main()
