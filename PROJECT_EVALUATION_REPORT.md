# PROJECT_EVALUATION_REPORT.md

> ## ⚠️ Superseded in part — fixes have since been applied
>
> This document is the **pre-fix baseline**. It is preserved deliberately: it records what
> was broken and is the reference the improvements are measured against. Several defects
> described below have since been fixed and re-measured.
>
> **See [`POST_FIX_EVALUATION_REPORT.md`](POST_FIX_EVALUATION_REPORT.md) for the current state.**
>
> | Metric | Before (this document) | After |
> |---|---:|---:|
> | Gemini initialises | No | **Yes** (live call verified) |
> | P(retrieved chunk reaches generator) | 33.3% | **100%** |
> | Causal grounding of questions | 0% | **100%** |
> | Exact duplicate rate (480 questions) | 63.5% | **15.0%** |
> | Same-answer score spread | 15 pts | **0 pts** |
> | Corpus page coverage | 6.2% | **18.6%** |
> | Production top-1 cosine | 0.162 | **0.209** |
> | Known-item Recall@1 (term, same corpus) | 0.973 | 0.973 *(control — unchanged)* |
> | Known-item Recall@1 (term, larger corpus) | — | 0.958 *(a decrease; explained)* |
> | End-to-end regression suite | none existed | **23/23 passing** |



**Evaluation audit of the PGAGI Candidate Screening system.**

Every number in this report was produced by running code in this repository against
this repository's own corpus. Nothing is estimated, borrowed, or invented. Where a
metric legitimately requires human annotation, it is **not computed**, and this is
stated explicitly rather than approximated.

- Date: 2026-09-10 · Commit `616df73` · Seed `20260910`
- Harness added: `evaluation/eval_retrieval.py`, `evaluation/eval_scorer.py`,
  `evaluation/eval_qgen.py`, `evaluation/human_eval_template.py`
- Raw outputs: `evaluation/results/*.json`

---

## 1. Executive Summary

**The honest headline: before today this project had zero evaluation of any kind.**
No test files, no metrics, no benchmark, no ground truth, no evaluation directory.
A repo-wide search for `accuracy|precision|recall|f1|mae|rmse|auc|ndcg|mrr|benchmark|ground.truth`
returns matches **only** inside the heuristic scorer's keyword lists
(`app/services/interview.py:30-33, 386`) — those are words the system *looks for in
candidate answers*, not metrics it computes. That distinction is the first thing a
sharp interviewer will probe.

What I was able to measure legitimately today, without inventing labels:

| Finding | Number | Source |
|---|---|---|
| Known-item retrieval, keyword queries | **Recall@1 = 0.973, Recall@5 = 1.000, MRR = 0.986** (n=299) | `eval_retrieval.py` |
| Known-item retrieval, sentence queries | **Recall@1 = 0.867, Recall@5 = 0.986, MRR = 0.926** (n=285) | `eval_retrieval.py` |
| Knowledge-base page coverage | **6.2%** (120 of 1,932 pages) | measured via PyPDF2 |
| Chunk ranking discarded by pipeline | **P(any retrieved chunk reaches the prompt) = 1/3**, independent of rank | `interview.py:163` + Monte Carlo (400k trials → 0.33224) |
| Causal grounding of the question text | **0%** on the path that actually runs | `interview.py:104-138` |
| Exact duplicate question rate | **63.5%** (305 of 480 simulated) | `eval_qgen.py` |
| Fluent-but-**factually wrong** answer vs correct answer | **70 vs 70 — identical** | `eval_scorer.py` |
| Pure filler + keywords, zero content | **scores 70** | `eval_scorer.py` ablation |
| Gemini evaluations ever performed | **0 of 10** stored questions | `storage/app.db` |

**The two sentences that make this defensible in an interview:**

> "The retriever itself is healthy — I measured Recall@1 of 0.97 and MRR of 0.99 on a
> 584-query known-item benchmark I built from the corpus. But I also measured that the
> pipeline throws that ranking away: `random.sample(top15, 5)` means any chunk has a flat
> 1/3 chance of reaching the prompt regardless of rank, and on the fallback path the
> retrieved text never enters the question at all. So my retrieval is good and my *use*
> of retrieval is broken — and I can show you exactly which line."

That is a far stronger position than any invented accuracy figure.

---

## 2. What Is Currently Evaluated

**In the original repository: nothing.**

| Artifact | Status |
|---|---|
| Test files | None. `test_key.py` is a DB inspector script, not a test, and is gitignored |
| CI | None |
| Evaluation code | None |
| Ground-truth data | None |
| Logged metrics | None. `gemini_eval.py:113, 223` compute an `elapsed` latency but only `print()` it — never aggregated, stored, or surfaced |
| Assertions about quality | None |

The only quantitative artifacts that existed were **implementation statistics** —
cosine scores stored in `questions.source_chunks`, and answer scores in
`questions.analysis`. Neither is an evaluation metric. See [§9](#9-existing-metrics).

---

## 3. What Is NOT Currently Evaluated

Component-by-component inventory (PART 1).

| # | Component | Input → Output | What ground truth would be | Right metric | Computable today? |
|---|---|---|---|---|---|
| 1 | **Resume field extraction** (`resume.py:174-225`) | PDF/text → name, email, phone | Hand-labelled name/email/phone for N real resumes | Exact-match accuracy per field; F1 for name | ❌ No labelled resumes in repo. Need ~100 resumes labelled (~2 h) |
| 2 | **Skill/keyword extraction** (`resume.py:228-235`) | text → skill list | Human-annotated true skill set per resume | Precision / Recall / F1 per resume, micro-averaged | ❌ Needs labels. Note: recall is *structurally capped* — the taxonomy is a closed 35+13 term list, so any skill outside it is an unavoidable false negative |
| 3 | **Seniority classification** (`resume.py:238-247`) | text → 4 classes | True seniority per candidate | Accuracy, macro-F1, confusion matrix | ❌ Needs labels. This is the one genuinely *classification-shaped* component — the natural home for "accuracy" |
| 4 | **Role → collection mapping** (`documents.py:34-43`) | role id → collection | Expert judgement of appropriateness | Qualitative; no metric needed | ⚠️ Not a learned component — it is a hard-coded dict. **8 roles collapse to 3 collections**; `ml-ops` and `data-analyst` both map to two intro-ML books |
| 5 | **Document ingestion** (`documents.py:140-149`) | PDF → pages | Pages successfully extracted vs total | Extraction success rate; **coverage %** | ✅ **Measured: 6.2%** (see §4.1) |
| 6 | **Chunking** (`documents.py:173-191`) | page text → chunks | — | Length distribution; boundary-quality rate | ✅ **Measured** (see §4.1) |
| 7 | **TF-IDF retrieval** (`retrieval.py:12-41`) | query → ranked chunks | Which chunks are relevant to a query | Recall@K, P@K, MRR, nDCG@K | ⚠️ **Partially**: known-item ✅ measured; topical relevance ❌ needs human labels |
| 8 | **Retrieved-context relevance** | query → 5 chunks | Human 0/1/2 relevance judgement | Graded P@K, nDCG@K | ❌ **Needs annotation.** Sheet generated: `evaluation/sheets/sheet1_retrieval_relevance.csv` (400 rows) |
| 9 | **Question generation** (`interview.py:80-138`) | topic+chunks → question | Expert 1–5 rubric ratings | Mean rating, % ≥ 4, Krippendorff α | ⚠️ Structural/diversity ✅ measured; quality ❌ needs annotation |
| 10 | **Question grounding** | chunks → question | Does the question use the chunks? | % of questions with chunk-derived content | ✅ **Measured: 0% causal** (see §5) |
| 11 | **Answer evaluation — Gemini** (`gemini_eval.py:78-140`) | answer → score | Expert 0–100 score | MAE, RMSE, Pearson, Spearman, QWK | ❌ **Needs annotation AND a working SDK.** Gemini has never run here |
| 12 | **Answer evaluation — heuristic** (`interview.py:348-437`) | answer → score | Expert 0–100 score | MAE, RMSE, Spearman, QWK | ⚠️ Behaviour ✅ measured; agreement with experts ❌ needs annotation |
| 13 | **Final candidate score** (`interview.py:537`) | 5 scores → mean | Hire/no-hire outcome | Predictive validity vs real outcomes | ❌ Needs longitudinal hiring data. Realistically out of scope |
| 14 | **Radar / component scores** (`interview.py:325-333`) | score → 5 axes | Per-dimension expert ratings | Per-axis MAE | ⚠️ **Invalid to evaluate under Gemini** — the axes are the overall score × fixed constants, so they carry no independent information (see §6.4) |
| 15 | **Skill-gap analysis** (`main.py:74-87`) | profile+role → match/partial/gap | Expert judgement per skill | Accuracy, confusion matrix | ❌ Needs labels. Cheap to do: 8 roles × ~9 skills = 74 judgements |
| 16 | **PDF report** (`pdf_report.py`) | summary → PDF | — | Render success rate; **crash rate on edge cases** | ✅ Partially — a known crash on `average_score = None` (`pdf_report.py:67`) |
| 17 | **End-to-end** | resume → report | Expert overall verdict agreement | Verdict agreement rate, Krippendorff α | ❌ Needs annotation (see §8) |

---

## 4. RAG Evaluation

### 4.1 The complete pipeline, traced in code

| Question | Answer | Code location |
|---|---|---|
| What documents? | 7 ML textbook PDFs | `Knowledge Base Resources/` |
| How many indexed? | **6** — one is silently skipped for exceeding `MAX_DOCUMENT_MB=25` (the 58 MB *Artificial Intelligence, ML & Deep Learning.pdf*) | `documents.py:165-169` |
| How many pages? | 1,932 pages exist in the 6 indexed PDFs; **only 120 are indexed** (20 per doc) → **6.2% coverage** | `documents.py:200`, `config.py:19` |
| How split? | Per page, then char-window with sentence-boundary snapping if a boundary falls past 55% of the window | `documents.py:173-191` |
| Chunk size / overlap | **900 chars / 160 chars** | `config.py:16-17` |
| Total chunks | **300** — ai-ml 100, data-science 113, advanced-ml 87 | measured |
| Vectorizer | `TfidfVectorizer(stop_words="english", max_features=18000, ngram_range=(1,2))` | `retrieval.py:15` |
| Tokenizer | scikit-learn default `token_pattern=r"(?u)\b\w\w+\b"` — no stemming, no lemmatisation | sklearn default |
| Actual vocabulary | 6,139 / 6,057 / 5,560 — **well under the 18,000 cap, so `max_features` never binds** | measured |
| Similarity | Cosine, on L2-normalised TF-IDF vectors | `retrieval.py:23` |
| K retrieved | `fetch_k = max(TOP_K*3, 12)` = **15** | `interview.py:161` |
| Is top-K deterministic? | **`KnowledgeIndex.search()` — yes, fully deterministic.** `np.argsort` descending | `retrieval.py:24` |
| Random sampling? | **Yes.** `random.sample(all_sources, 5)` on the 15 — un-seeded | `interview.py:163` |
| Where do chunks go? | (a) stored in `questions.source_chunks`; (b) into the Gemini question prompt; (c) the hint text; (d) the heuristic grounding score | `interview.py:185`, `gemini_eval.py:199`, `interview.py:238-245`, `interview.py:352` |
| Do chunks reach Gemini? | **Question generation: yes** (top 3, truncated to 1,200 chars). **Answer evaluation: NO** — `_PROMPT` contains no chunks at all | `gemini_eval.py:198-209` vs `44-75` |
| Does the fallback question use them? | **No.** `source_hint` is assigned at `interview.py:104` and **never referenced**; all 16 templates interpolate only `{topic}` and `{role_label}` | `interview.py:104-138` |
| Retrieval ground truth? | **None existed** | — |
| Existing evaluation? | **None existed** | — |

### 4.2 Can I claim "my RAG is X% accurate"?

**No — and here is precisely why, in the order an interviewer will press you:**

1. **"Accuracy" is not a retrieval metric.** Retrieval is a ranking problem over a
   corpus, not a classification problem over a fixed label set. The correct family is
   Recall@K / Precision@K / MRR / nDCG@K. Saying "RAG accuracy" signals you have not
   done IR evaluation.
2. **No relevance judgements exist for production queries.** The real query is
   `f"{role} interview {seniority} {profile_terms} {answer_terms}"` (`retrieval.py:49-53`).
   Nobody has ever labelled which chunks are relevant to such a query. Without labels
   there is no denominator, so no recall.
3. **Cosine similarity ≠ accuracy.** The observed production cosine is ~0.10. That is a
   *similarity score*, not a percentage correct. Reporting "0.10 → 10% accurate" would be
   a category error and is the single fastest way to fail this interview.
4. **Even a perfect retriever would be degraded by the pipeline.** `random.sample` throws
   the ranking away — so a "retrieval accuracy" number would not describe what the system
   actually does.

### 4.3 The benchmark I built and ran — known-item retrieval

**Design.** Ground truth is **constructed, not fabricated**: if a query is lifted
verbatim from chunk *c*, then *c* is by definition a relevant result for it. No human
judgement is invented. Two query families:

- **Sentence queries** — a verbatim 8–40 word sentence from the chunk (natural-language-ish).
- **Term queries** — the chunk's 6 highest-TF-IDF terms under the *production vectorizer* (keyword-ish).

**Dataset:** 584 queries — 285 sentence + 299 term — one per chunk per family across all
3 collections; 1 relevant chunk per query (single-gold known-item).

**Metric formulas** (single gold document, so Recall@K = Success@K):

```
Recall@K = (1/|Q|) · Σ_q  1[rank(gold_q) ≤ K]
MRR      = (1/|Q|) · Σ_q  1 / rank(gold_q)
nDCG@K   = (1/|Q|) · Σ_q  1[rank ≤ K] / log2(rank_q + 1)      (IDCG = 1)
P@K      = Recall@K / K                                        (bounded by 1/K — see caution)
```

**Results** (micro-averaged, weighted by query count):

| Query type | n | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| **Term (keyword)** | 299 | **0.973** | **1.000** | **1.000** | **1.000** | **0.986** | **0.989** |
| **Sentence (verbatim)** | 285 | **0.867** | **0.979** | **0.986** | **0.997** | **0.926** | **0.943** |

Per collection:

| Collection | chunks | vocab | R@1 (sent) | R@1 (term) | MRR (sent) | build |
|---|---|---|---|---|---|---|
| ai-ml | 100 | 6,139 | 0.828 | 0.940 | 0.894 | 0.046 s |
| data-science | 113 | 6,057 | 0.893 | 0.991 | 0.944 | 0.029 s |
| advanced-ml | 87 | 5,560 | 0.879 | 0.989 | 0.940 | 0.031 s |

**⚠️ P@K caution.** With exactly one relevant document, P@5 ≤ 0.20 by construction. The
harness computes it but flags it; quoting "Precision@5 = 0.20" as a weakness would be
misreading your own benchmark.

**What this does and does not prove.** It proves the **index, vectorizer, and cosine
ranking are working correctly** — the retriever finds a passage when the query genuinely
comes from it. It is an **upper bound** on retrieval capability. It says **nothing** about
whether the chunks returned for a real interview query are good interview material. That
remains unlabelled.

### 4.4 Production-query behaviour (similarity only — deliberately no recall)

From the **2 real stored sessions** (`storage/app.db`, 50 retained chunks):

| Statistic | Value |
|---|---|
| Cosine, mean | **0.1022** |
| Cosine, median | 0.0980 |
| Cosine, range | 0.0750 – 0.1851 |

From 24 synthetic role × profile runs (`eval_retrieval.py`): top-1 cosine mean **0.162**,
range 0.081 – 0.315.

**Interpretation, stated carefully:** production queries score roughly **6–10× lower**
than known-item queries against the same index. Since the index demonstrably retrieves at
R@1 ≈ 0.97 when the query matches the corpus, **the weak link is query formulation, not
the retriever.** `build_query` concatenates the role slug, a seniority token, and a bag of
resume keywords — a query that resembles no passage in a textbook. This is a diagnosis
supported by two measurements, not a guess.

### 4.5 The pipeline discards its own ranking — quantified

`interview.py:161-163`:

```python
fetch_k = max(settings.top_k * 3, 12)          # 15
all_sources = get_index(role).search(query, fetch_k)
sources = random.sample(all_sources, min(settings.top_k, len(all_sources)))   # 5 of 15
```

Any chunk in ranks 1–15 has probability **5/15 = 0.3333** of reaching the prompt —
**identical for rank 1 and rank 15.** Verified by Monte Carlo: **0.33224** over 400,000
trials (analytic 0.33333).

Effective end-to-end recall of the gold chunk reaching the LLM prompt:

```
Effective Recall = Recall@15 × P(survives sampling) = 1.000 × 0.3333 = 0.3333
```

So even under the most favourable known-item conditions where the retriever achieves
**Recall@15 = 1.000**, only **33.3%** of the time does the correct chunk actually reach
the generator. This is the most quantitatively striking defect in the system, and it is
**one line of code**.

---

## 5. Question Generation Evaluation

**Generator under test: the template fallback** — because Gemini has never initialised in
this environment (`requirements.txt` names `google-generativeai`; the code imports
`from google import genai`, which is the `google-genai` package).

**Simulation:** 480 questions across 96 sessions × 8 roles (`eval_qgen.py`, seed 20260910).

| Metric | Value |
|---|---|
| **Exact duplicate rate** | **63.5%** (305 of 480) |
| Distinct questions | 175 |
| Most-repeated single question | 14× |
| Distinct template signatures | **11** (5 foundational + 6 intermediate) |
| Most-used template | 75× |
| Mean uses per template | 43.6 |
| Distinct topics overall | 16 |
| Sessions with a repeated topic | **0 / 96** — topic dedup works correctly |
| Difficulty distribution | intermediate 416, foundational 64, **advanced 0** |
| Questions with zero chunk-word overlap | 48 / 480 (10.0%) |
| Mean chunk-derived words beyond the topic | 2.18 |

**Grounding — read this carefully.** The 2.18 "grounded words" figure is *coincidental
vocabulary overlap* (words like "data", "model", "learning" appear in both fixed templates
and textbook prose). **Causal grounding is 0% by construction**: the templates are literal
f-strings that interpolate only `{topic}` and `{role_label}`, and the one variable that
touches retrieval — `source_hint` at `interview.py:104` — is assigned and never used.
Retrieved chunks influence the fallback question **only** indirectly, via `_topic()`, and
only when the candidate's own resume keywords are exhausted.

**Limitation of my own simulation, stated honestly:** advanced difficulty showed 0
occurrences because I passed `running_score=None` throughout, and advanced requires
`running_score ≥ 75`. My simulation cannot rule advanced in or out. However the **real
database independently supports rarity**: 10 stored questions were 4 foundational,
6 intermediate, **0 advanced**, and a live 5-question trace stayed at intermediate
throughout because scores sat at 60–69.

### 5.1 Human evaluation protocol for question quality

Quality — correctness, clarity, difficulty calibration, hallucination — **cannot** be
measured without experts. **Human annotation is required; therefore I will not fabricate a
metric.** The harness is built and the sheet is generated.

| Parameter | Recommendation | Rationale |
|---|---|---|
| Sample size | **100 questions** (~12–13 per role) | At p≈0.8, the 95% CI half-width is ≈ ±8pp — tight enough to defend, small enough to actually finish |
| Annotators | **2 minimum, 3 preferred** | 2 gives you agreement; 3 lets you break ties and report a stable α |
| Scale | **1–5 Likert per dimension** | Standard, and QWK/α are well-defined on it |
| Dimensions | role relevance, topic relevance, grounding, technical correctness, clarity, difficulty-matches-claim | One per failure mode, so a low score localises the fault |
| Binary flags | is-duplicate, contains-hallucination | Rate metrics, not Likert |
| Blinding | Annotators must not see the difficulty label while rating difficulty | Prevents anchoring |

**Metrics to report:** mean ± 95% CI per dimension; **% scoring ≥ 4** (the headline
"pass rate"); duplicate rate; hallucination rate; and **Krippendorff's α** for
inter-rater agreement (use α, not raw agreement — it corrects for chance, and ordinal α
is the right variant for Likert data). Report α first: if α < 0.67 your rubric is
ambiguous and the means are not trustworthy.

Sheet ready at `evaluation/sheets/sheet2_question_quality.csv` (96 questions).

---

## 6. Answer Evaluation

### 6.1 What produces the score

`interview.analyze_answer()` (`interview.py:303-437`). **Gemini first, heuristic on any
failure.** Confirmed by execution: `gemini_eval._init()` returns `False`, so **the
heuristic is the only evaluator that has ever run** — 0 of 10 stored questions carry an
`evaluator` field.

### 6.2 Scoring dimensions and weights — hardcoded, never validated

| Component | Max | Rule | `interview.py` |
|---|---|---|---|
| Length | 15 | `min(original_words/60, 1) × 15` | 396 |
| Relevance | 30 | 10 per topic word, capped | 397 |
| Grounding | 25 | 5 per word shared with retrieved chunks, capped | 398 |
| Technical | 15 | 5 per term from a 26-word set, capped | 399 |
| Specificity | 15 | 15 if a digit/metric word appears | 400 |

Plus six caps at lines 405–410. **Are the weights empirically justified? No.** There is no
fitting procedure, no held-out set, no ablation, no sensitivity study, and no comment
explaining the choice. They are round numbers summing to 100. **[Inference]** they were
chosen so the total lands on a familiar 0–100 scale. Say "hand-designed", never
"optimised" or "tuned".

### 6.3 Determinism — measured

- **Function level: fully deterministic.** 7 answers × 20 repeats with fixed sources → a
  single distinct score each time.
- **Pipeline level: NOT deterministic.** Because `random.sample` changes which 5 chunks
  form the grounding vocabulary, the same answer scores differently across runs:

| Answer | mean | sd | range | spread |
|---|---|---|---|---|
| substantive_answer | 68.8 | 2.7 | [55, 70] | **15** |
| off_topic_fluent | 25.5 | 5.5 | [22, 34] | **12** |
| generic_nonanswer | 4.7 | 2.4 | [3, 8] | 5 |

**A candidate's score can move by up to 15 points on an identical answer**, purely from an
un-seeded RNG. That is the correct, precise answer to "can the same answer get different
scores, and why?"

### 6.4 The findings that matter most

**Behavioural specification: 5/5 checks pass.** The scorer honours its own stated rules
(copy-paste < 8 → scored 6; generic capped at 20 → 8; short answer capped → 0; off-topic
low → 22; hint caps at 60 → 70 became 60). *This is specification conformance, not
accuracy.*

**But the rules it does not have are the problem:**

| Probe | Score | Level |
|---|---|---|
| Substantive, correct, metric-rich answer | **70** | adequate |
| **Fluent but factually WRONG** ("always maximise accuracy… train and test on the same data") | **70** | adequate |
| Keyword-stuffed gibberish (no sentences) | **40** | developing |
| **"Use precision and recall."** (correct, terse) | **0** | off-topic |

Two conclusions, both measured:

1. **The heuristic cannot detect incorrectness.** A confidently wrong answer scores
   *identically* to a correct one. It measures lexical surface features only.
2. **It mis-orders quality.** A correct 4-word answer scores **0** — because
   `original_word_count < 10` trips the copy-paste guard (`interview.py:372`) — while
   keyword salad scores **40**.

**Cumulative ablation** — pure filler plus keywords, containing no argument whatsoever:

| Probe (60 filler words + …) | Score | Δ |
|---|---|---|
| filler only | 15 | +15 |
| + topic terms | 30 | +15 |
| + technical terms | 50 | +20 |
| + a number | 50 | +0 |
| + words copied from the retrieved chunks | **70** | +20 |

**A string with zero semantic content reaches 70 — the same as the genuinely good answer.**

**Radar validity.** Under Gemini the five axes are the single score × {1.00, 1.10, 0.95,
1.05, 0.90} (`interview.py:325-333`). They are a deterministic function of one number and
carry **zero independent information**. Evaluating them per-axis would be meaningless, so
the correct action is to **not evaluate them and not claim they measure skills**.

### 6.5 Benchmark design: automated evaluator vs human experts

**Not run — human annotation is required; therefore I will not fabricate a metric.**
Harness: `evaluation/human_eval_template.py`, sheet `sheet3_answer_scoring.csv`.

**Protocol.** 60 answers spanning the quality range (12 questions × 5 answer levels:
excellent / good / partial / wrong-but-fluent / non-answer). 2–3 experts score 0–100
**blind to the system score** (the sheet is column-ordered so the system score can be
deleted before handing it over). Then:

| Metric | Formula | Why it fits **this** system |
|---|---|---|
| **MAE** | `Σ\|s_i − e_i\| / n` | ✅ Primary. Same 0–100 units as the score, directly interpretable ("off by 12 points on average") |
| **RMSE** | `√(Σ(s_i − e_i)² / n)` | ✅ Report alongside MAE. RMSE ≫ MAE reveals rare large blow-ups — exactly the `very_short_real → 0` failure |
| **Spearman ρ** | Pearson on ranks | ✅ **Most important.** Screening is a *ranking* task — you only need the right candidates on top. Robust to the scorer's compressed range |
| **Pearson r** | covariance / σσ | ⚠️ Secondary. Assumes linearity; the hard caps at 20/25/40/45/60 make the mapping piecewise, so r will understate agreement |
| **Quadratic weighted κ** | on the 5 `level` bands | ✅ The right agreement metric for ordinal bands — penalises strong↔off-topic far more than strong↔adequate, and corrects for chance |
| **Band agreement** | `1[band(s)=band(e)]` | ⚠️ Report only next to QWK; raw agreement flatters an imbalanced distribution |
| **Accuracy** | — | ❌ Meaningless on a continuous 0–100 score. Only valid after bucketing, and then QWK is strictly better |

**Decision thresholds to state up front (pre-registration beats post-hoc rationalising):**
MAE ≤ 10 and Spearman ρ ≥ 0.70 would make the scorer defensible as a *first-pass filter*.
Below ρ ≈ 0.5 it should not gate humans at all.

---

## 7. Heuristic Fallback Evaluation

**Are the weights empirically justified? No — and say so plainly.** No fitting, no
validation set, no ablation in the original repo. What I *did* establish today:

- ✅ It is a **pure function** of its inputs (20 repeats × 7 answers).
- ✅ It **satisfies its own stated anti-gaming rules** (5/5).
- ❌ It **cannot distinguish correct from incorrect** (70 vs 70).
- ❌ It is **gameable**: content-free keyword filler reaches 70.
- ❌ It **penalises correct brevity** to 0.
- ❌ Its **inputs are randomised**, giving up to 15 points of score instability.

### The three-way comparison table

**I cannot fill this in — there are no expert labels and Gemini has never run.**
Producing numbers here would be fabrication. This is the table to produce, and exactly
what it takes:

| System | MAE | RMSE | Spearman ρ | QWK | Band agreement |
|---|---|---|---|---|---|
| Heuristic fallback | *pending* | *pending* | *pending* | *pending* | *pending* |
| Gemini 2.5 Flash | *pending* | *pending* | *pending* | *pending* | *pending* |
| Human expert #2 (ceiling) | *pending* | *pending* | *pending* | *pending* | *pending* |

**Steps to fill it, in order:**

1. `pip install google-genai` (fixes the wrong package) and confirm `_init()` returns True.
2. Assemble 60 answers spanning the quality range for 12 questions.
3. Have 2–3 experts score them 0–100 blind → `sheet3_answer_scoring.csv`.
4. Run both evaluators over the same 60 answers; **seed the RNG** or pin the source chunks,
   or the heuristic column carries ±15 points of noise that is not the scorer's fault.
5. `python evaluation/human_eval_template.py score`.

**The third row is essential.** Expert-vs-expert MAE is the **noise ceiling**: if two
humans disagree by 12 points on average, an automated scorer at MAE 13 is performing at
near-human level, and without that row you cannot tell a good result from a bad one.

---

## 8. End-to-End Evaluation

```
Resume → profile → role → retrieval → question → candidate answer → score → report
```

**Do not collapse this into one "accuracy".** Errors compound and a single number hides
which stage failed. Report a **staged scorecard**:

| Stage | Metric | Target | Status |
|---|---|---|---|
| Resume parsing | Per-field exact-match accuracy (name/email/phone) | ≥ 0.95 email/phone, ≥ 0.85 name | Needs 100 labelled resumes |
| Skill extraction | Micro-F1 vs annotated skills | ≥ 0.80 | Needs labels |
| Seniority | Macro-F1, 4 classes | ≥ 0.75 | Needs labels |
| Retrieval (sanity) | Known-item Recall@1 | ≥ 0.90 | ✅ **0.973 measured** |
| Retrieval (relevance) | Graded nDCG@5 | ≥ 0.70 | Needs 400 judgements |
| Question quality | % rated ≥ 4/5; duplicate rate | ≥ 70%; < 10% | ✅ duplicate **63.5%** measured (fails badly) |
| Question grounding | % with chunk-derived content | ≥ 80% | ✅ **0% measured** (fails) |
| Answer scoring | MAE, Spearman ρ vs experts | ≤ 10, ≥ 0.70 | Needs 60 labels |
| Score stability | sd of score on identical input | **0** | ✅ **2.7–5.5 measured** (fails) |
| Report generation | Render success rate over edge cases | 1.00 | ✅ known crash on all-skipped |
| System | p95 latency per question | < 5 s | Needs instrumentation |

**What "success" means at system level:** the ranking of candidates the system produces
should correlate with the ranking a panel of experts would produce — **Spearman ρ on
final session scores**, not per-answer accuracy. That is the metric that maps to the actual
business use (ordering a shortlist).

---

## 9. Existing Metrics

Every number that existed in the repo before today, audited (PART 8).

| Number | Where it comes from | Real evaluation metric? | Defensible? | Say it in an interview? |
|---|---|---|---|---|
| **Cosine similarity ≈ 0.10** (`questions.source_chunks`) | `retrieval.py:23` scoring output | ❌ **No** — a ranking score, not a quality measure | ✅ As a *similarity statistic* only | ✅ **Yes, if framed correctly.** "Production queries retrieve at ~0.10 cosine, versus ~0.97 R@1 on known-item queries — the query formulation is the weak link." ❌ **NEVER** "RAG is 10% accurate" |
| **Answer scores 0–100** (`questions.analysis.score`) | `interview.py:402` heuristic sum | ❌ No — a system *output*, not a validated measure | ⚠️ Only as a distribution | ⚠️ "n=6 scored answers, mean 37.3" — but immediately note n is tiny and unvalidated |
| **`elapsed` seconds** (`gemini_eval.py:113, 223`) | `time.time()` around the API call | ⚠️ Latency is a real metric, but it is only `print()`ed — never stored or aggregated | ✅ If you instrument it | ⚠️ Only after you actually collect it |
| **`document_count`** (`/api/roles`) | `len()` of a file list | ❌ No — an inventory count | ✅ As a corpus statistic | ✅ "2 documents per collection" |
| **`accuracy`, `precision`, `recall`, `f1`, `auc`, `rmse`, `mae`** in source | `interview.py:30-33` `TECHNICAL_TERMS`; `interview.py:386` specificity regex | ❌ **Absolutely not.** These are *words the scorer searches for inside candidate answers* | ❌ | ❌ **This is the trap.** A grep-happy interviewer may see these and ask "so you computed F1?" — the answer is *"No, those are keyword lists the heuristic looks for in an answer, not metrics."* Knowing this distinction cold is worth more than any number |

**Numbers produced today** (all reproducible via `evaluation/`): 6.2% coverage; 300
chunks; R@1 0.973/0.867; MRR 0.986/0.926; nDCG@10 0.989/0.943; P(chunk survives) 0.3333;
63.5% duplicate rate; 0% causal grounding; score spread 15; 5/5 behavioural checks.

---

## 10. Missing Metrics

Ranked by how badly their absence hurts you in an interview:

1. **Graded retrieval relevance** (nDCG@5, P@5) — the direct answer to "how did you
   evaluate your RAG?" Known-item only gets you halfway.
2. **Scorer vs expert agreement** (MAE, Spearman, QWK) — the direct answer to "why should
   I trust your score?"
3. **Question quality ratings** — the direct answer to "how did you evaluate generation?"
4. **Resume parsing accuracy** — the one place a plain, honest "accuracy" belongs.
5. **Seniority classification F1** — the only genuinely classification-shaped component.
6. **Latency percentiles** (p50/p95) per stage — cheap, needs no labels, and every systems
   interviewer asks.
7. **Gemini vs heuristic agreement** — cannot even start until the SDK is fixed.
8. **Predictive validity vs hiring outcomes** — the real goal, realistically unobtainable.

---

## 11. Recommended Benchmark

**Prefer a small rigorous benchmark over a large fake one.** Total ≈ 8–10 hours of
annotation for all three sheets.

| Sheet | Items | Annotators | Effort | Unlocks |
|---|---|---|---|---|
| `sheet1_retrieval_relevance.csv` | 40 queries × top-10 = **400 judgements** | 2 | ~4 h | Graded P@1/3/5/10, nDCG@K, Krippendorff α |
| `sheet2_question_quality.csv` | **96 questions** × 6 dimensions | 2 | ~3 h | Mean rating, % ≥ 4, duplicate + hallucination rate, α |
| `sheet3_answer_scoring.csv` | **60 answers** (populate first) | 2–3 | ~2 h | MAE, RMSE, Pearson, Spearman, QWK, band agreement |

Rationale for the sizes: 40 queries × 8 roles gives 5 per role — enough to detect a large
per-role difference without pretending to per-role precision. Judging the **top 10**
(not top 5) is what makes Recall@10 and nDCG@10 computable, and it costs almost nothing
extra per query.

Run `python evaluation/human_eval_template.py score` afterwards. It computes nothing on
empty sheets — by design.

---

## 12. Actual Results

Consolidated, all reproducible. Full JSON in `evaluation/results/`.

### Corpus (`eval_retrieval.py`)
- 7 PDFs on disk; **6 indexed**, 1 skipped by the 25 MB cap
- **1,932 pages available, 120 indexed → 6.2% coverage**
- **300 chunks**: ai-ml 100, data-science 113, advanced-ml 87
- Vocabulary 5,560–6,139 (the 18,000 `max_features` cap never binds)
- Index build 0.029–0.046 s warm; 0.9–2.2 s cold including PDF parsing
- Chunks from pages 1–5: 15.0% / 15.9% / 18.4%; explicit front-matter regex hits
  2.0% / 15.0% / 14.9%

> **Correction to my earlier analysis:** I previously characterised the corpus as "mostly
> front matter". Measured, that was an overstatement — only ~15–18% of chunks come from
> pages 1–5. The real defect is **coverage (6.2%)**, not front-matter contamination. Use
> the 6.2% figure; it is both accurate and more damning.

### Retrieval (n = 584)

| Query type | n | R@1 | R@3 | R@5 | R@10 | R@15 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|---|
| Term | 299 | 0.973 | 1.000 | 1.000 | 1.000 | 1.000 | 0.986 | 0.989 |
| Sentence | 285 | 0.867 | 0.979 | 0.986 | 0.997 | 1.000 | 0.926 | 0.943 |

- Production cosine (real sessions, n=50): mean **0.1022**, median 0.0980, range 0.075–0.185
- P(retrieved chunk reaches prompt) = **0.3333** (MC 0.33224 / 400k trials)
- **Effective recall reaching the generator = 1.000 × 0.3333 = 0.3333**

### Question generation (n = 480 over 96 sessions)
- Exact duplicate rate **63.5%**; 175 distinct; most-repeated 14×
- 11 template signatures; most-used 75×
- Topic dedup **0/96 sessions with a repeated topic** — works
- Difficulty: 416 intermediate / 64 foundational / 0 advanced *(advanced unreachable in
  this sim by construction; real DB independently shows 0/10 advanced)*
- **Causal grounding 0%**

### Answer scoring (heuristic — the only evaluator that has ever run)
- Deterministic given fixed inputs: **7/7 answers, 20 repeats**
- Pipeline variance: substantive answer sd **2.7**, spread **15** points
- Behavioural spec **5/5**
- Correct answer **70** vs factually wrong answer **70**
- Content-free filler + keywords **70**; keyword salad **40**; correct 4-word answer **0**
- Hint cap enforced: 70 → 60

### Production database (2 original sessions)
- 10 questions, 6 scored, 4 skipped
- Scores: mean **37.3**, median 34.0, range 8–70
- Levels: off-topic 3, adequate 3, skipped 4
- **`evaluator` field present in 0/10 → Gemini has never scored anything**

---

## 13. Numbers Safe for Interviews

### A. Supported by the implementation today (no extra work)

| Claim | Evidence |
|---|---|
| "6 PDFs, 300 chunks, 900-char windows with 160-char overlap, TF-IDF with 1–2 grams" | `config.py`, `retrieval.py:15`, measured |
| "The knowledge base indexes 120 of 1,932 pages — **6.2% coverage**" | measured via PyPDF2 |
| "Retrieval is deterministic; the *pipeline* is not, because of `random.sample` at `interview.py:163`" | code + Monte Carlo |
| "Index builds in under 50 ms warm, 0.9–2.2 s cold" | measured |
| "Production queries retrieve at ~0.10 cosine" — **as a similarity statistic** | `storage/app.db`, n=50 |
| "8 roles collapse onto 3 document collections" | `documents.py:34-43` |
| "Gemini has never actually run here — 0 of 10 stored evaluations used it, because `requirements.txt` names the wrong package" | DB + `_init()` failure |

### B. Obtained by running the evaluation I built today ✅ **these are real, run them live if asked**

| Claim | Number |
|---|---|
| "Known-item Recall@1 on keyword queries" | **0.973** (n=299) |
| "Known-item Recall@1 on sentence queries" | **0.867** (n=285) |
| "MRR" | **0.986 / 0.926** |
| "nDCG@10" | **0.989 / 0.943** |
| "Recall@5" | **1.000 / 0.986** |
| "Probability a retrieved chunk reaches the prompt" | **0.333** |
| "Effective recall reaching the generator" | **0.333** |
| "Exact duplicate question rate" | **63.5%** (n=480) |
| "Causal grounding of generated questions" | **0%** |
| "Score instability on an identical answer" | **up to 15 points**, sd 2.7 |
| "The heuristic scores a factually wrong answer identically to a correct one" | **70 vs 70** |
| "Anti-gaming rules conform to spec" | **5/5 checks** |

> Say **"I built a 584-query known-item benchmark"** — not "I evaluated my RAG". The
> specificity is what earns credibility.

### C. Require human annotation first

| Claim | Prerequisite |
|---|---|
| "nDCG@5 = X on relevance-judged queries" | 400 judgements, 2 annotators (~4 h) |
| "Question quality: X% rated ≥ 4/5" | 96 questions × 2 annotators (~3 h) |
| "Scorer MAE = X, Spearman = Y vs experts" | 60 answers, 2–3 experts blind (~2 h) |
| "Gemini outperforms the heuristic by X" | Fix the SDK **and** get the labels |
| "Resume parsing accuracy = X%" | ~100 labelled resumes |
| "Krippendorff α = X" | ≥ 2 independent annotators on any sheet |

### D. Numbers I must NOT claim

| ❌ Never say | Why it is wrong |
|---|---|
| "My RAG is 90% / X% accurate" | Accuracy is not an IR metric; no relevance labels exist |
| "Cosine 0.10 means 10% accuracy" | Category error — a similarity score is not a rate |
| "Retrieval precision is 97%" | 0.973 is **known-item Recall@1**, not precision, and not topical relevance |
| "The heuristic weights were optimised/tuned" | They are hand-picked round numbers; no fitting exists |
| "Gemini scores are validated / accurate" | Gemini has never run here, and there is no reference standard |
| "The radar chart shows candidate skill levels" | Under Gemini it is one score × 5 constants — zero independent information |
| "The system is 85% accurate at screening" | No hiring outcomes, no labels, no such measurement |
| "I tested the system" | There are **zero** test files; `test_key.py` is a DB inspector |
| "Questions are grounded in the knowledge base" | **0% causal grounding** on the path that runs |
| "Difficulty adapts to candidate performance" | True in code, but advanced fired **0/10** times in real sessions |

---

## 14. Numbers Not Safe to Claim

See §13.D. The governing rule: **never let an implementation statistic wear the costume of
an evaluation metric.** Cosine scores, document counts, chunk counts, and system-produced
answer scores are all *outputs*. A metric requires a reference standard the system did not
produce.

---

## 15. Recommended Project Improvements

### MUST ADD

| # | Item | Metric | Effort | Data needed | Interview value |
|---|---|---|---|---|---|
| 1 | **Fix `requirements.txt` → `google-genai`** | Gemini call success rate | 5 min | None | 🔴 Critical — without it the "AI" claim is false |
| 2 | **Seed or remove `random.sample`** | Restores Recall@5 = 1.000 → 0.333 becomes 1.000 | 15 min | None | 🔴 Highest ratio of impact to effort in the repo |
| 3 | **Relevance-judged retrieval benchmark** | nDCG@5, P@5, Recall@5 | 4 h annotation | Sheet 1 (ready) | 🔴 The literal answer to "how did you evaluate your RAG?" |
| 4 | **Scorer vs expert agreement** | MAE, RMSE, Spearman, QWK | 2 h annotation | Sheet 3 | 🔴 The literal answer to "why trust your score?" |
| 5 | **Pass retrieved chunks into the evaluation prompt** | Enables a grounded-scoring ablation | 30 min | None | 🟠 Currently the evaluator sees no source material |
| 6 | **Raise `MAX_PAGES_PER_DOCUMENT`** | Coverage 6.2% → ~100% | 1 line + reindex | None | 🟠 Then re-run §4.3 and show the before/after |

### SHOULD ADD

| # | Item | Metric | Effort | Interview value |
|---|---|---|---|---|
| 7 | Question-quality annotation | Mean 1–5, % ≥ 4, α | 3 h | 🟠 Completes the three-part story |
| 8 | Latency instrumentation (p50/p95 per stage) | Milliseconds | 1 h, no labels | 🟠 Every systems interviewer asks |
| 9 | Embeddings baseline vs TF-IDF on the same benchmark | Δ nDCG@5 | 3 h | 🟠 Turns "why TF-IDF?" into a measured comparison |
| 10 | Regression tests from the behavioural spec | Pass/fail | 1 h | 🟡 Proves you ship tests |
| 11 | Log `evaluator` explicitly (`"heuristic"`) | Fallback rate % | 20 min | 🟡 Makes silent degradation observable |

### OPTIONAL

| # | Item | Metric | Interview value |
|---|---|---|---|
| 12 | Resume parsing accuracy on 100 labelled resumes | Per-field accuracy, F1 | 🟡 The one honest "accuracy" |
| 13 | Seniority classifier macro-F1 + confusion matrix | Macro-F1 | 🟡 The only classification-shaped component |
| 14 | Chunk-size sweep (300/600/900/1200) | nDCG@5 per setting | 🟡 Shows systematic tuning |
| 15 | Cost/token telemetry | Tokens & $ per interview | ⚪ Nice for a systems discussion |

---

## 16. Interview Q&A

Format: **Testing** → **Strong** → **Weak** → **Follow-up** → **Evidence**

---

**1. How did you evaluate your RAG?**
- **Testing:** Do you know IR evaluation exists, or did you just ship a vector search?
- **Strong:** "Two layers. First, a known-item benchmark I built from the corpus — 584 queries, ground truth by construction: I pull a sentence or the top TF-IDF terms out of a chunk and check whether that chunk comes back. Recall@1 is 0.973 on keyword queries, 0.867 on sentence queries, MRR 0.986. That validates the index and ranking. Second — and I want to be upfront — topical relevance for *real* interview queries is **not** evaluated, because that needs human relevance judgements I haven't collected. I've built the annotation sheet: 40 queries, top-10 each, 400 judgements, which would give me graded nDCG@5."
- **Weak:** "I checked the retrieved chunks looked relevant." / "It works well."
- **Follow-up:** *"Why is known-item not enough?"* → "It only proves the index can find a passage when the query comes from it. It's an upper bound. It says nothing about whether a bag of resume keywords retrieves good interview material — and my production cosine scores of ~0.10 versus near-perfect known-item recall suggest it doesn't."
- **Evidence:** `evaluation/eval_retrieval.py`, `evaluation/results/retrieval_results.json`

---

**2. What was your Recall@K?**
- **Testing:** Can you quote a real number with its denominator and caveats?
- **Strong:** "On my known-item benchmark: Recall@1 0.973, Recall@3 1.000, Recall@5 1.000, Recall@10 1.000 for keyword queries over 299 queries; 0.867 / 0.979 / 0.986 / 0.997 for sentence queries over 285. But the number that matters more is the *effective* recall: the pipeline retrieves 15 then does `random.sample(15, 5)`, so any chunk has a flat 1/3 chance of reaching the prompt. Recall@15 of 1.000 becomes an effective 0.333."
- **Weak:** "About 90%." (no n, no K, no query definition)
- **Follow-up:** *"Single-gold — so what's your Precision@5?"* → "Bounded at 0.2 by construction, which is why I report it flagged rather than as a quality signal. Precision only becomes meaningful once I have multi-document graded judgements."
- **Evidence:** `evaluation/results/retrieval_results.json` → `micro_average`

---

**3. Why TF-IDF instead of embeddings?**
- **Testing:** Was it a decision or a default?
- **Strong:** "Cost and operational simplicity — no embedding API bill, no vector store, fully deterministic and debuggable. For a keyword-heavy query built from resume skills, lexical matching is a defensible starting point. But I'll be honest that I chose it *before* measuring, not because of a measurement. The right next step is running an embedding baseline over the same 584-query benchmark and comparing nDCG@5 — that's a 3-hour experiment and I'd want the number before defending the choice."
- **Weak:** "TF-IDF is faster." / "Embeddings were too expensive." (unquantified)
- **Follow-up:** *"Where would TF-IDF specifically fail here?"* → "Synonymy and paraphrase. A resume saying 'neural nets' won't match a chapter on 'deep learning'. My sentence-query Recall@1 is 0.867 versus 0.973 for keyword queries — that 10-point gap is exactly the lexical-mismatch penalty showing up in my own benchmark."
- **Evidence:** `retrieval.py:15`, benchmark deltas

---

**4. How did you know the retrieved documents were relevant?**
- **Testing:** Will you overclaim?
- **Strong:** "For production queries I don't, and I won't pretend otherwise. What I have is a similarity distribution — mean cosine 0.1022 across 50 retained chunks from real sessions — and that's a *ranking score*, not evidence of relevance. Establishing relevance requires human judgements; that's sheet 1 in my harness."
- **Weak:** "Cosine similarity was high, so they were relevant."
- **Follow-up:** *"Is 0.10 good?"* → "It's low in absolute terms, but the honest read comes from the contrast: the same index hits Recall@1 0.973 when the query actually matches the corpus. So 0.10 points at the *query formulation*, not the retriever."
- **Evidence:** `storage/app.db` `source_chunks`; `retrieval.py:49-53`

---

**5. What was your ground truth?**
- **Testing:** Do you understand what ground truth means?
- **Strong:** "For the retrieval benchmark, ground truth is *constructed*: a query lifted verbatim from a chunk has that chunk as a known relevant document — no human judgement invented. For everything else — relevance, question quality, answer scoring — there is **no ground truth in this project**, and that's the honest gap. I built the annotation harness rather than estimate around it."
- **Weak:** "Gemini's scores were the ground truth."
- **Follow-up:** *"Why not use Gemini as ground truth?"* → "Circular. Gemini is the system under test on the scoring path — grading it with itself measures self-consistency, not correctness. And LLM-as-judge needs its own validation against humans before it's a reference."
- **Evidence:** `evaluation/eval_retrieval.py` docstring; `human_eval_template.py`

---

**6. How did you evaluate question generation?**
- **Testing:** Generation eval is hard — do you know how to approach it?
- **Strong:** "Structurally and for diversity, over 480 simulated questions across 96 sessions. Exact duplicate rate is **63.5%** — 175 distinct out of 480 — because the fallback path draws from only 11 templates. Topic deduplication does work: 0 of 96 sessions repeated a topic. And grounding is **0%** — the templates interpolate only the topic and role label; `source_hint` at `interview.py:104` is assigned and never used, so retrieved text never reaches the question on the path that actually runs. Quality — correctness, clarity, hallucination — needs expert raters; that's 96 questions on a 1–5 rubric across 6 dimensions with 2 annotators and Krippendorff α."
- **Weak:** "The questions looked good."
- **Follow-up:** *"63.5% — is that the Gemini path?"* → "No, and that's the point: Gemini has never run here because of a wrong package name, so the template fallback is the *only* generator that has ever executed. With Gemini live I'd expect duplicates to drop sharply, but I'd measure it rather than assume."
- **Evidence:** `evaluation/eval_qgen.py`, `interview.py:104-138`

---

**7. How did you evaluate the answer evaluator?**
- **Testing:** The hardest question. Do you know you need humans?
- **Strong:** "Behaviourally, not against humans — because there are no expert labels. I ran a specification-conformance suite: it satisfies its own anti-gaming rules 5/5. But I also found where it breaks. A fluent, factually *wrong* answer scores **70** — identical to the correct answer. Content-free filler plus keywords also reaches 70. A correct four-word answer scores 0. So it measures lexical surface features, not correctness. To actually validate it I'd need 60 answers scored blind by 2–3 experts and report MAE, RMSE, Spearman and quadratic weighted kappa — plus expert-vs-expert as the noise ceiling."
- **Weak:** "Gemini is a strong model so the scores are reliable."
- **Follow-up:** *"Why Spearman rather than accuracy?"* → "Screening is a ranking task — I need the right people at the top, not exact point agreement. And accuracy is undefined on a continuous 0–100 score; once you bucket it, QWK is strictly better because it penalises strong-vs-off-topic more than strong-vs-adequate and corrects for chance."
- **Evidence:** `evaluation/results/scorer_results.json` → `gaming_probe`

---

**8. Why should I trust your AI-generated score?**
- **Testing:** Intellectual honesty.
- **Strong:** "Today you shouldn't, as a hiring decision — and I'd say that to a stakeholder too. It's unvalidated against human judgement, and I've measured two concrete failure modes: it can't tell correct from confidently wrong, and the same answer varies by up to 15 points because the source chunks are randomly resampled. I'd position it as a triage aid that flags obvious non-answers — where it does work, catching copy-paste at 6/100 — and I'd gate any real decision behind the MAE and Spearman study."
- **Weak:** "It uses Gemini 2.5 Flash with a strict rubric."
- **Follow-up:** *"What would change your mind?"* → "MAE ≤ 10 and Spearman ≥ 0.70 against a blind expert panel, with expert-vs-expert agreement measured alongside so I know the ceiling."
- **Evidence:** `pipeline_variance` and `gaming_probe` in `scorer_results.json`

---

**9. How did you validate the heuristic weights?**
- **Testing:** Will you claim optimisation you didn't do?
- **Strong:** "I didn't — they're hand-designed round numbers summing to 100: length 15, relevance 30, grounding 25, technical 15, specificity 15. No fitting, no held-out set, no ablation in the original code. What I did add is a cumulative ablation showing what each contributes: filler alone 15, plus topic terms 30, plus technical terms 50, plus chunk-overlap words 70. That's how I know a string with zero semantic content reaches 70 — the weights reward keyword presence, not reasoning."
- **Weak:** "I tuned them until the scores looked right."
- **Follow-up:** *"How would you actually fit them?"* → "Collect the 60 expert-scored answers, then fit a small regression or ordinal model on the five component features and compare its MAE against the hand-set weights on a held-out split. If hand-set weights win, keep them — but now I'd have a reason."
- **Evidence:** `interview.py:396-410`; `component_ablation` in `scorer_results.json`

---

**10. Why is there no Accuracy / Dice / R² metric?**
- **Testing:** Do you know which metrics fit which problem shape?
- **Strong:** "Because almost nothing here is a supervised prediction task. Retrieval is ranking, so it takes Recall@K, MRR and nDCG. Question generation is open-ended, so it takes human rubric ratings. Answer scoring is ordinal regression against expert judgement, so it takes MAE, Spearman and QWK — R² would technically compute but it assumes a linear fit, and my scorer has hard caps at 20/25/40/45/60 that make the mapping piecewise. Dice is a segmentation metric — there are no masks anywhere in this system. The one place plain accuracy genuinely belongs is seniority classification, four classes, and I haven't labelled it yet."
- **Weak:** "It's not that kind of project."
- **Follow-up:** *"So where does F1 belong?"* → "Skill extraction — it's set-vs-set, so micro-F1 across resumes. Though recall is structurally capped, since the taxonomy is a closed 35-term list and anything outside it is an unavoidable false negative."
- **Evidence:** `resume.py:8-59`, `interview.py:405-410`

---

**11. What happens when Gemini is unavailable?**
- **Testing:** Do you understand your own failure modes?
- **Strong:** "It falls back to the heuristic silently — `evaluate_with_gemini` catches every exception, prints to stdout and returns `None`. The candidate still gets a score, so nothing surfaces the degradation. In this repo that's not hypothetical: `requirements.txt` names `google-generativeai` but the code imports `from google import genai`, which is the `google-genai` package. So Gemini has **never** initialised, and all 10 stored evaluations used the heuristic — the `evaluator` field is absent in every row. Availability was preserved at the cost of silent, invisible quality loss."
- **Weak:** "There's a fallback so it keeps working."
- **Follow-up:** *"How would you make that observable?"* → "Write `evaluator: 'heuristic'` explicitly instead of omitting the key, emit a counter for fallback rate, and caveat the report when a session was heuristically scored — you can't average two different scoring systems into one number and present it as comparable."
- **Evidence:** `gemini_eval.py:138-140`; `requirements.txt:7`; `storage/app.db`

---

**12. Is your fallback deterministic?**
- **Testing:** Precision of thought — the answer is genuinely two-part.
- **Strong:** "The function is — I ran 7 answers × 20 repeats with fixed sources and got a single distinct score each time. The *pipeline* is not, because `interview.py:163` does an un-seeded `random.sample(top15, 5)` and grounding is scored against whichever 5 chunks were drawn. Measured over 200 trials, the same substantive answer ranges 55 to 70 — a 15-point spread, standard deviation 2.7. For a hiring tool that's unacceptable, and it's a one-line fix: seed it, or just take the top 5."
- **Weak:** "Yes, it's deterministic."
- **Follow-up:** *"Why was the sampling there at all?"* → "Question variety from a small corpus — reasonable intent. But it was applied at the wrong layer: vary the *topic* selection, not the evidence you score against."
- **Evidence:** `determinism` and `pipeline_variance` in `scorer_results.json`

---

**13. What are the biggest limitations of your evaluation?**
- **Testing:** Self-awareness.
- **Strong:** "Four. One: known-item retrieval is an upper bound — it proves the index works, not that results are topically relevant. Two: **zero human labels**, so no relevance, quality, or scorer-agreement metric exists. Three: the production sample is tiny — 2 real sessions, 10 questions, 6 scored answers; I won't generalise from that. Four: everything I measured about generation and scoring reflects the **fallback** paths, because Gemini has never run — so my numbers characterise the degraded system, not the intended one. I'd rather state that than quietly present fallback numbers as if they were the AI's."
- **Weak:** "More data would help."
- **Follow-up:** *"Which would you fix first?"* → "Fix the SDK, because right now I can't evaluate the system I actually designed."
- **Evidence:** entire `evaluation/` output set

---

**14. If you had another week, how would you improve evaluation?**
- **Testing:** Prioritisation.
- **Strong:** "Day 1: fix the package name and seed the sampler — those two lines change what I'm even measuring. Days 2–3: the 400 relevance judgements for graded nDCG@5, which is the number people actually ask for. Day 4: 60 answers scored blind by two experts, then MAE/Spearman/QWK for heuristic versus Gemini versus a second human as the ceiling. Day 5: raise the page cap from 20 to full documents and re-run the whole benchmark to show a before/after on 6.2% versus full coverage. Day 6: an embeddings baseline on the same benchmark so 'why TF-IDF' becomes a measured comparison. Day 7: wire the behavioural suite into CI as regression tests."
- **Weak:** "Add more tests and more data."
- **Follow-up:** *"What if you only had one day?"* → "The two-line fix plus the retrieval relevance judgements. That converts my weakest answer into my strongest."
- **Evidence:** §15

---

**15. What metric would you put on your resume?**
- **Testing:** Judgement about defensibility.
- **Strong:** "Something like: *'Built a 584-query known-item retrieval benchmark; measured Recall@1 0.97 and MRR 0.99, and identified that random chunk sampling reduced effective recall to 0.33.'* It's specific, reproducible from the repo, and the second half shows I found a real defect through measurement rather than just reporting a flattering number. I would **not** write 'RAG accuracy' — there's no such metric and no labels behind it."
- **Weak:** "95% accuracy on candidate screening."
- **Follow-up:** *"Isn't leading with a flaw risky?"* → "The flaw *is* the result. Anyone can quote a retrieval number; finding that the pipeline discards its own ranking is the part that shows engineering judgement."
- **Evidence:** `evaluation/results/retrieval_results.json`

---

## 17. 30-Second Evaluation Explanation

> "The project shipped without any evaluation, so I built one. For retrieval I created a
> 584-query known-item benchmark from the corpus itself — ground truth by construction, no
> invented labels — and measured Recall@1 of 0.97 and MRR of 0.99, which validates the
> index. Then I found the real problem: the pipeline retrieves 15 chunks and randomly
> samples 5, so effective recall collapses to 0.33, and on the fallback path the retrieved
> text never reaches the question at all. For answer scoring I have no human labels, so I
> ran behavioural tests instead — and found a factually wrong answer scores 70, exactly the
> same as the correct one. I built the annotation harness for the metrics that genuinely
> need humans rather than estimating them."

## 18. 2-Minute Evaluation Explanation

> "Let me separate what I can measure without labels from what I can't.
>
> **Retrieval.** I built a known-item benchmark: take a chunk, extract either a verbatim
> sentence or its top TF-IDF terms, query the index, and check whether that chunk comes
> back. Ground truth is constructed, not invented. 584 queries across three collections.
> Keyword queries: Recall@1 0.973, Recall@5 1.000, MRR 0.986. Sentence queries: 0.867 and
> 0.986, MRR 0.926. So the index and ranking are healthy.
>
> **But that's an upper bound**, and the interesting result is the contrast. Real
> production queries — which concatenate a role slug, a seniority token and a bag of resume
> keywords — retrieve at a mean cosine of about 0.10. Same index, near-perfect known-item
> recall. So the weak link is query formulation, not the retriever. That's a diagnosis from
> two measurements, not a guess.
>
> **Then the structural findings.** The knowledge base indexes 120 of 1,932 pages — 6.2%
> coverage — because of a 20-page-per-document cap. The pipeline retrieves 15 chunks then
> calls `random.sample` to pick 5, so every chunk has a flat one-in-three chance of
> reaching the prompt regardless of rank; I verified that with 400,000 Monte Carlo trials.
> And on the template fallback path, the retrieved text never enters the question at all —
> `source_hint` is assigned and never referenced. So causal grounding is zero percent.
>
> **Generation.** Over 480 simulated questions the exact duplicate rate is 63.5%, from
> only 11 templates. Topic deduplication does work — no session repeated a topic.
>
> **Scoring.** No human labels exist, so I did not compute MAE or correlation — I refuse to
> fabricate those. Instead I ran a behavioural suite. It satisfies its own anti-gaming
> rules 5 out of 5: copy-pasted questions score 6, generic non-answers cap at 20. But a
> fluent, factually *wrong* answer scores 70 — identical to the correct answer — and pure
> filler plus keywords also reaches 70, while a correct four-word answer scores 0. It
> measures lexical surface, not correctness. It's also unstable: the same answer varies by
> up to 15 points because the chunks it grounds against are resampled randomly.
>
> **What's missing and how I'd close it:** graded relevance judgements for nDCG, expert
> ratings for question quality, and 60 blind expert scores for MAE, Spearman and QWK
> against the automated scorer — with expert-versus-expert as the noise ceiling. That's
> about nine hours of annotation, and I've generated the sheets and written the scoring
> code so it computes nothing until real labels exist."

---

*All results reproducible: `python evaluation/eval_retrieval.py`, `eval_scorer.py`,
`eval_qgen.py`. Seed 20260910. Raw JSON in `evaluation/results/`.*
