# POST_FIX_EVALUATION_REPORT.md

Engineering fixes applied to the PGAGI Candidate Screening system, and the measured
effect of each one.

Baseline: `PROJECT_ANALYSIS.md`, `PROJECT_EVALUATION_REPORT.md`,
`evaluation/results_before/*.json` (preserved, not overwritten).
After: `evaluation/results/*.json`. Seed `20260910` throughout.

**Ground rules honoured:** the retrieval benchmark, the 7 frozen answers and the
frozen question are byte-identical before and after. No metric was redefined after
seeing a result. Where a metric got worse, it is reported as worse.

---

## 1. What Was Broken

| # | Defect | Evidence (pre-fix) |
|---|---|---|
| 1 | `requirements.txt` named `google-generativeai`; the code imports `from google import genai` (`google-genai`). Gemini never initialised — locally **or** on the live Render deployment. | `_init()` raised `cannot import name 'genai' from 'google'`; 0/10 stored analyses had an `evaluator` field |
| 2 | `.env` was loaded at import of `gemini_eval`, i.e. **after** `app/config.py` had already evaluated its dataclass defaults. Eight of nine documented settings were silently ignored. | Proven by import-order experiment |
| 3 | `interview.py` did `random.sample(top15, 5)`, discarding the TF-IDF ranking. | P(chunk reaches generator) = 5/15 = 0.333, flat across ranks |
| 4 | The local question generator ignored the retrieved chunks entirely. `source_hint` was assigned at `interview.py:104` and never referenced. | Causal grounding = 0% |
| 5 | The answer evaluator never received the retrieved context, and the Gemini prompt contained no reference material. | Could not judge factual correctness |
| 6 | Scores were non-reproducible: the same answer varied by up to 15 points because grounding was computed against a randomly drawn chunk set. | spread 15, sd 2.74 |
| 7 | `MAX_PAGES_PER_DOCUMENT=20` limited the corpus to 120 of 1,932 pages. | 6.2% coverage |
| 8 | The local generator drew from 11 static templates. | 63.5% exact duplicate rate over 480 questions |
| 9 | Fallback was silent: the analysis JSON simply omitted `evaluator`. | Two different scoring systems averaged together indistinguishably |
| 10 | PDF export returned HTTP 500 when every question was skipped (`float(None)`). | `pdf_report.py:67` |
| 11 | Reviewer dashboard tested `status === 'completed'`; the backend writes `'complete'`. | "COMPLETED: 0" and no PDF link, verified on the live deployment |

---

## 2. What Was Fixed, and Why

| # | Fix | File | Why it was necessary |
|---|---|---|---|
| 1 | `google-generativeai` → `google-genai` | `requirements.txt` | Without it the headline feature never runs and the failure is invisible |
| 2 | `load_dotenv()` moved to the top of `config.py`, before the `Settings` body executes; `gemini_eval` now imports `app.config` so it works standalone | `app/config.py`, `app/services/gemini_eval.py` | Makes every documented setting actually configurable |
| 3 | `random.sample(pool, k)` → `all_sources[:settings.top_k]` | `app/services/interview.py` | Restores the ranking the retriever produced; makes scoring reproducible |
| 4 | New `_local_question()` composes questions from a concept term extracted from the **ranked retrieved chunks** (`_concept_terms`) | `app/services/interview.py` | The fallback is now genuinely grounded, and is labelled `local-grounded`, never "AI-generated" |
| 5 | Gemini question generation now receives ID-tagged ranked chunks and returns structured JSON (`question`, `topic`, `difficulty`, `source_ids`, `expected_points`) | `app/services/gemini_eval.py` | Real RAG: the question is built from retrieved material and cites what it used |
| 6 | Gemini evaluation now receives the question **plus** the same ranked context **plus** `expected_points`, and grades five dimensions with correctness weighted highest | `app/services/gemini_eval.py` | Lets the evaluator judge truth, not surface features |
| 7 | Evaluation runs at `temperature=0.0, top_p=1.0, seed=42, candidate_count=1`; a deterministic post-rule caps overall score at 35 when `correctness < 25` | `app/services/gemini_eval.py` | Reproducibility, and the correctness ceiling is enforced in code rather than trusted to the model |
| 8 | Session-salted deterministic rotation (`_stable_offset`, md5) for topic and frame selection | `app/services/interview.py` | Same session → identical output; different sessions → different questions. Diversity without randomness |
| 9 | `evaluator` is now **always** written: `"gemini"`, `"heuristic"`, or `"skipped"`; `generator` is recorded in `question_meta` | `app/services/interview.py`, `app/database.py` | No silent mixing of scoring systems |
| 10 | 429-aware retry with server-supplied `retryDelay`; rate-limit failures are reported distinctly | `app/services/gemini_eval.py` | The Gemini free tier is 5 req/min — without this the system silently degrades under load |
| 11 | `MAX_PAGES_PER_DOCUMENT` default 20 → 60 | `app/config.py`, `.env.example` | 3× coverage at acceptable cost (measured below) |
| 12 | Radar chart is evaluator-aware: Gemini's five real dimensions, or the heuristic's five components | `static/app.js` | The radar previously showed one score × five constants |
| 13 | `float(None)` guard in PDF export | `app/services/pdf_report.py` | All-skipped sessions returned HTTP 500 |
| 14 | `'completed'` → `'complete'` | `static/reviewer.html` | Reviewers could never download a report |
| 15 | Index on `questions(session_id)` | `app/database.py` | Every session query was a full scan |

---

## 3. Before / After Metrics

### 3.1 Headline table

| Metric | Before | After | Note |
|---|---:|---:|---|
| Gemini initialises | **No** | **Yes** | Live call verified: `PONG`, 1.42 s, 7 in / 2 out tokens |
| P(retrieved chunk reaches generator) | 33.3% | **100%** | Top-5 ranked chunks always pass through |
| Effective recall at the generator | Recall@15 × ⅓ = **0.333** | **= Recall@5** | 1.000 (term) / 0.986 (sentence) on the cap-20 corpus |
| Causal grounding of generated questions | **0%** | **100%** | 480/480 contain a concept term lifted from retrieved chunks |
| Exact duplicate rate (480 questions) | 63.5% | **15.4%** | |
| Distinct questions | 175 | **406** | |
| Distinct question shapes | 11 | **197** | |
| Most-repeated single question | 14× | **5×** | |
| Same-answer score spread | 15 pts (sd 2.74) | **0 pts (sd 0.00)** | All 7 frozen answers |
| Local evaluator determinism (20 reps) | 7/7 | 7/7 | Unchanged — was already pure |
| Corpus page coverage | 6.2% (120/1932) | **18.6% (360/1932)** | |
| Indexed chunks | 300 | **1,004** | |
| Production top-1 cosine | 0.162 | **0.209** | +29% on real queries |
| `evaluator` recorded in analysis | absent (0/10) | **always** | |
| Sessions with a repeated topic | 0/96 | 0/96 | Unchanged, still correct |

### 3.2 Retrieval — same 584-query known-item benchmark

The benchmark is unchanged. Two runs are reported because the corpus changed.

| Corpus | n (term) | R@1 | R@5 | MRR | n (sent) | R@1 | R@5 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Before**, cap=20 | 299 | 0.973 | 1.000 | 0.986 | 285 | 0.867 | 0.986 | 0.926 |
| **After**, cap=20 *(control)* | 299 | **0.973** | **1.000** | **0.986** | 285 | **0.867** | **0.986** | **0.926** |
| **After**, cap=60 *(new default)* | 1003 | 0.958 | 0.999 | 0.976 | 983 | 0.834 | 0.983 | 0.906 |

**The control is the important row.** Re-running the benchmark on the *identical* corpus
after all code changes reproduces the baseline **exactly**. That confirms none of the
fixes altered the retrieval mathematics — the pipeline changed, the retriever did not.

**A metric got worse, and here is why.** On the larger corpus, known-item Recall@1 falls
0.973 → 0.958 (term) and 0.867 → 0.834 (sentence). This is expected: 1,004 chunks compete
for the top slot instead of 300, so a known-item query has 3.3× more distractors. It is a
harder benchmark, not a worse retriever.

The metric that reflects real use moved the other way: **production top-1 cosine rose from
0.162 to 0.209 (+29%)**, and the minimum across all 24 role × profile probes rose from
0.081 to 0.113. Real interview queries now find materially better matches. I judge that
trade worth 1.5 points of known-item Recall@1, and both numbers are reported.

One side effect worth noting: at cap=60 the `advanced-ml` collection hits
`max_features=18000` exactly, so the TF-IDF vocabulary cap now **binds** where it
previously never did. That is a new tuning knob that did not matter before.

### 3.3 Knowledge-base coverage — measured tradeoff

All three collections, cold (PDF parse + chunk + TF-IDF fit), peak traced memory:

| `MAX_PAGES_PER_DOCUMENT` | Pages | Coverage | Chunks | Build time | Peak memory |
|---:|---:|---:|---:|---:|---:|
| 20 *(old)* | 120 | 6.2% | 300 | 13.2 s | 74 MB |
| **60 (new default)** | **360** | **18.6%** | **1,004** | **40.7 s** | **84 MB** |
| 120 | 720 | 37.3% | 2,004 | 86.8 s | 104 MB |
| 250 | 1,193 | 61.7% | 3,299 | 686.5 s | 1,219 MB |
| 800 (all) | 1,932 | 100% | 5,793 | 587.7 s | 1,268 MB |

**Why 60 and not 100%.** There is a cliff between 120 and 250 pages: build time jumps
5–8× and peak memory jumps from ~104 MB to ~1.2 GB, because the two largest PDFs
(Bishop, 758 pp; *Introduction to ML*, 392 pp) start being parsed in bulk. The live
deployment is a **Render free instance with a 512 MB limit**, so 250+ would OOM. Build
cost is also paid lazily on the first request per role, so 60 keeps a cold start around
14 s per collection rather than 29 s (cap 120) or 230 s (cap 250).

The limit stays configurable via `MAX_PAGES_PER_DOCUMENT`. On a paid instance, 120 is
safe and roughly doubles coverage again.

### 3.4 Question generation — 480 questions, 96 sessions, 8 roles

Local generator on both sides (Gemini would need ~96 minutes at 5 req/min, so a
like-for-like local comparison is used, exactly as in the baseline).

| Metric | Before | After |
|---|---:|---:|
| Exact duplicate rate | 63.5% | **15.4%** |
| Distinct questions | 175 / 480 | **406 / 480** |
| Distinct question shapes | 11 | **197** |
| Most-repeated question | 14× | **5×** |
| Causal grounding | 0% | **100%** |
| Questions with zero chunk-word overlap | 10.0% | **0.8%** |
| Multiword (bigram) concepts | 0% (unigrams only) | **98.3%** |
| Concepts on the unusable-word list | 15.6% | **3.1%** |
| Verb-phrase-shaped concepts (stricter proxy) | not measured | **12.1%** *(residual)* |
| Sessions with a repeated topic | 0 / 96 | 0 / 96 |
| Difficulty distribution | 416 int / 64 found / 0 adv | 416 / 64 / 0 |

**An intermediate result worth recording.** My first attempt made topic selection fully
deterministic (`available[0]` instead of `random.choice`). Duplicates got **worse**:
63.5% → **88.8%**, because every session sharing a resume profile then produced an
identical topic sequence. Determinism had removed cross-session diversity.

The fix was to make the rotation deterministic *given the session* rather than globally:
`_stable_offset(session_id)` (md5, stable across processes) rotates the candidate list, so
the same session always yields the same sequence while different sessions start at
different points. Verified directly:

```
sess-aaa: ['pytorch', 'rag', 'llm', 'nlp', 'model evaluation']
sess-bbb: ['rag', 'llm', 'nlp', 'model evaluation', 'information retrieval']
sess-ccc: ['nlp', 'model evaluation', 'information retrieval', 'python', 'pytorch']
sess-aaa repeated 3x -> identical each time
```

**Concept-extraction rewrite (second iteration).** The first grounded fallback selected
single words by rank-weighted raw frequency, producing unusable concepts: `machine` (a
bigram fragment), `however` (a connective), `excused` (a PDF artifact). Measured at
**15.6% of questions**.

`_concept_terms` now draws candidates from the **KnowledgeIndex vocabulary** rather than a
raw regex. That vocabulary is built with `stop_words="english"` and `ngram_range=(1,2)`,
so connectives and out-of-vocabulary artifacts are excluded for free and bigrams become
first-class candidates. On top of that:

- a **document-frequency band** (1%–30% of chunks) drops corpus-ubiquitous fillers
  (`machine` appears in 50.2% of ai-ml chunks) and one-off artifacts;
- a **contiguity check** requires a bigram to occur as a literal phrase in the chunk text,
  removing sentence-boundary artifacts such as `languages machine` (from "languages.
  Machine");
- **bigram preference**, with unigram backfill only when fewer than three bigrams survive;
- **adverb/participle-head rejection** (`widely used`, `called feature`) while keeping
  gerund nouns (`deep learning`, `gradient boosting`).

This changed the extraction *method*; it is not a blacklist.

**Residual, reported honestly:** 12.1% of concepts are still verb-phrase-shaped
(`recommend using` = 36 occurrences, `learning include` = 11, `looks like` = 10). Removing
these properly needs part-of-speech tagging, which would add a spaCy/NLTK dependency.
Separately, some concepts are grammatical but odd for an interview (`microsoft excel`,
`bitcoin price`, `jupyter notebook`) — those reflect *what the retriever returned*, not the
extractor, and are an instance of the unlabelled production-relevance limitation.

**A measurement bug this exposed.** The harness scored causal grounding by testing
`concept in chunk_words`, a set of single words. That is correct for unigram concepts and
always False for multiword ones, so it reported 1.7% after the rewrite. The stated
definition — "a concept term provably extracted from the retrieved chunks" — is faithfully
tested by substring containment in the chunk text, which handles both cases and yields the
identical result for the pre-fix unigram concepts. Corrected, causal grounding is **100%
(480/480)**. This was a fix to a broken measurement, not a redefinition to improve a score.

Difficulty distribution is unchanged; `advanced` still shows 0 because the simulation
passes `running_score=None`, which makes that tier unreachable by construction. That is a
limitation of the simulation, not a measurement of the system.

### 3.5 Score stability — identical answer, identical question

| Answer | Before: spread (sd) | After: spread (sd) |
|---|---:|---:|
| substantive_answer | 15 (2.74) | **0 (0.00)** |
| off_topic_fluent | 12 (5.47) | **0 (0.00)** |
| generic_nonanswer | 5 (2.38) | **0 (0.00)** |
| verbatim_question_copy | 0 (0.00) | 0 (0.00) |
| very_short_real | 0 (0.00) | 0 (0.00) |
| keyword_stuffed_nonanswer | 0 (0.00) | 0 (0.00) |
| fluent_but_wrong | 0 (0.00) | 0 (0.00) |

Before, the pipeline could reach C(15,5) = 3,003 distinct chunk sets. After, exactly one.
PHASE 6 target met: **distinct scores = 1, sd = 0, range = 0** over 20 repeats for all
seven answers.

---

## 4. Retrieval Methodology

Unchanged from the baseline report, and deliberately so — it is the control.

584 known-item queries (299 term + 285 sentence at cap=20; 1,003 + 983 at cap=60), one per
chunk per family. Ground truth is **constructed, not fabricated**: a query lifted verbatim
from a chunk has that chunk as a known relevant document. Single-gold, so Recall@K =
Success@K.

```
Recall@K = (1/|Q|) · Σ_q 1[rank(gold_q) ≤ K]
MRR      = (1/|Q|) · Σ_q 1 / rank(gold_q)
nDCG@K   = (1/|Q|) · Σ_q 1[rank ≤ K] / log2(rank_q + 1)      (IDCG = 1)
```

**What it establishes:** the index, vectorizer and cosine ranking work. It is an upper
bound on retrieval capability.
**What it does not establish:** that chunks retrieved for a *real* interview query are
topically appropriate. That needs human relevance labels, which still do not exist.

The pipeline-level number is now trivial rather than probabilistic: the top-`top_k` ranked
chunks reach the generator with probability 1.0, so effective recall at the generator
equals Recall@5 instead of Recall@15 × ⅓.

## 5. Question-Generation Methodology

```
resume profile ─┐
role + topic ───┼─→ TF-IDF query ─→ top-15 ─→ ranked top-5 ─→ Gemini (JSON) ─→ question
difficulty ─────┘                                    │                 │
                                                     │                 └─ source_ids, expected_points
                                                     └─→ if Gemini unavailable:
                                                         _concept_terms(ranked chunks)
                                                         + deterministic frame  ─→ question
```

Gemini receives up to 5 ID-tagged chunks, each truncated to 600 characters (~750 tokens
total), plus the questions already asked, and is instructed to test reasoning rather than
recall, to avoid inventing specifics beyond the context, and to stay under 60 words. Output
is validated: too short, containing source markers, or a near-duplicate (Jaccard ≥ 0.82
against earlier questions) → rejected, local fallback used.

The local fallback extracts a rank-weighted salient term from the retrieved chunks and
fills a difficulty-appropriate frame. It is labelled `generator: "local-grounded"` and
never claims to be AI-generated.

## 6. Answer-Evaluation Methodology

```
QUESTION + RANKED REFERENCE CONTEXT + EXPECTED POINTS + CANDIDATE ANSWER → Gemini → JSON
```

Five dimensions, each 0–100: **correctness** (weighted highest), relevance, completeness,
reasoning, grounding. Plus overall score, level, feedback, strengths, gaps and an explicit
`factual_errors` list. Hard rules in the prompt: mirroring the question < 8; keyword lists
< 25; off-topic < 20; a correct-but-short answer judged on content, not length.

A deterministic post-rule in code caps the overall score at 35 whenever `correctness < 25`,
so the ceiling does not depend on the model remembering its own instruction.

> **This rubric is a design choice, not a validated weighting.** It has not been calibrated
> against human expert scores. Do not describe it as optimised or validated.

The heuristic remains as the fallback, unchanged in its scoring logic, and is now always
labelled `evaluator: "heuristic"`.

---

## 7. Controlled Adversarial Tests

Same frozen question, same seven frozen answers, before and after.

### 7.1 Heuristic fallback — unchanged by design

| Answer | Before | After |
|---|---:|---:|
| verbatim_question_copy | 6 | 6 |
| generic_nonanswer | 8 | 8 |
| very_short_real | 0 | 0 |
| substantive_answer | 70 | 70 |
| keyword_stuffed_nonanswer | 40 | 40 |
| **fluent_but_wrong** | **70** | **70** |
| off_topic_fluent | 22 | 22 |

The heuristic still cannot tell correct from incorrect (70 vs 70). **That is expected and
was not "fixed"** — it is a lexical scorer and cannot judge truth. The fix was to demote it
to a fallback and make Gemini primary. Behavioural spec: 6/7 (the failing check is exactly
`wrong_below_correct`).

### 7.2 Gemini evaluator — measured

5 of the 7 frozen answers were evaluated by Gemini before the free-tier daily quota was
exhausted. Results are reported only for genuine Gemini evaluations:

| Answer | Score | Level | correctness | Before (heuristic) |
|---|---:|---|---:|---:|
| substantive_answer | **92** | strong | 95 | 70 |
| very_short_real | **25** | thin | **80** | **0** |
| keyword_stuffed_nonanswer | **10** | off-topic | 10 | 40 |
| verbatim_question_copy | **0** | off-topic | 0 | 6 |
| generic_nonanswer | **0** | off-topic | 0 | 8 |
| fluent_but_wrong | *not measured on the frozen question — quota exhausted* | | | 70 |
| off_topic_fluent | *not measured — quota exhausted* | | | 22 |

Two results stand out:

- **`very_short_real` ("Use precision and recall.")**: heuristic 0 / "off-topic";
  Gemini 25 / "thin" with **correctness = 80**. Gemini correctly recognises a terse answer
  as factually right but incomplete, where the heuristic's copy-paste guard scored it zero.
- **`keyword_stuffed_nonanswer`**: 40 → **10**. Keyword stuffing no longer pays.

**Does the improved evaluator distinguish correct from incorrect?** On the evidence I have,
yes — but I am labelling the strength of that evidence precisely:

In a separate, fully logged Gemini call (against a Gemini-generated RAG question rather
than the frozen benchmark question), the same `fluent_but_wrong` text scored **0** with
**correctness = 0**, and the model returned three specific factual errors it had detected:

```
'"accuracy is the only metric that matters in production."'
'"Precision and recall are academic ideas that do not apply once you deploy."'
'"You should train and test on the same data ... 99 percent training accuracy guarantees ..."'
```

The correct answer scored 92 in the same regime. So the discrimination is demonstrated —
but **the head-to-head on the frozen benchmark question is not complete**, and I will not
quote a "92 vs 0 on the frozen benchmark" margin until that call succeeds.

### 7.3 A harness bug this exposed

The first combined run reported "behavioural spec 7/7" including
`wrong_below_correct: correct=92 vs fluent_but_wrong=70, margin +22`. That comparison was
**invalid**: 92 came from Gemini and 70 from a heuristic fallback after a rate-limit. The
harness now refuses cross-evaluator comparisons, marks them `comparable: false`, excludes
them from the pass count, and prints the reason. Mixing evaluators in one number is exactly
the failure mode the fixes were meant to eliminate, so the harness had to enforce it too.

---

## 8. End-to-End Tests

`evaluation/test_e2e.py`, run against a live local server. **23/23 passing.**

| Group | Checks |
|---|---|
| Phase 9 — nothing broken | server health; 8 roles with indexed docs; resume upload + name/email/phone extraction; invalid file rejected; session creation + profile; skill gap; full 5-question interview; summary; radar components present; PDF export (5,188 bytes); reviewer lists session; reviewer status `complete` |
| Regression | PDF export on an all-skipped session — **4,113 bytes** (previously HTTP 500) |
| Test A — question generation | 5/5 distinct within a session; no repeated topic; every question has sources; **sources verified in descending rank order** (proves random sampling is gone); two sessions on the same resume share **0/5** questions |
| Test C — repeatability | local evaluator: 20 runs → 1 distinct score, sd 0 |
| Test D — Gemini failure | fallback still scores; labelled `evaluator: "heuristic"`; every stored analysis records its evaluator |

Test A also exercised the Gemini question path live earlier: a generated question cited
`source_ids: ['S4','S2']` and returned four `expected_points`, confirming the model used
the retrieved material and that structured output round-trips.

---

## 9. Remaining Limitations

1. **The Gemini free tier is 5 requests/minute and has a daily cap.** A full 5-question
   interview needs ~10 calls. Under load, sessions will fall back to the heuristic. The
   retry now handles bursts, but sustained use needs a paid tier. This is the single
   biggest operational constraint.
2. **`fluent_but_wrong` and `off_topic_fluent` were not evaluated by Gemini on the frozen
   benchmark question** — quota exhausted mid-run. Re-run `evaluation/eval_scorer.py` when
   quota resets to complete the table.
3. **Gemini determinism is unverified.** `temperature=0, top_p=1, seed=42, candidate_count=1`
   is set, but I could not complete the repeat-measurement (quota). Server-side
   non-determinism may remain and is not claimed either way.
4. **The heuristic fallback is still a lexical scorer** and still scores a fluent-but-wrong
   answer identically to a correct one. It was demoted, not repaired.
5. **Heuristic weights remain hand-designed**, not fitted. Unchanged.
6. **Corpus coverage is 18.6%, not 100%** — a deliberate memory/latency tradeoff for a
   512 MB free instance.
7. **Known-item Recall@1 decreased** on the larger corpus (0.973 → 0.958). Reported above.
8. **The `advanced` difficulty tier is still rarely reached** in practice.
9. **The deployed instance has not been redeployed** with these fixes; it still runs the
   old code and the heuristic.
10. **No regression suite in CI.** `test_e2e.py` must be run manually against a live server.

---

## 10. Metrics That Still Require Human Annotation

Unchanged from the baseline report. **No labels were fabricated.**

| Metric | Needs | Sheet |
|---|---|---|
| Graded Precision@K, nDCG@K on production queries, Krippendorff α | 400 judgements, 2 annotators (~4 h) | `evaluation/sheets/sheet1_retrieval_relevance.csv` |
| Question quality: mean rating, 95% CI, % ≥ 4/5, hallucination rate, α | 96 questions × 6 dimensions × 2 annotators (~3 h) | `evaluation/sheets/sheet2_question_quality.csv` |
| Answer scoring: MAE, RMSE, Pearson, Spearman, QWK, band agreement, expert-vs-expert | 60 answers, 2–3 experts, blind (~2 h) | `evaluation/sheets/sheet3_answer_scoring.csv` |

`python evaluation/human_eval_template.py score` still computes nothing on empty sheets.

---

## 11. Numbers I Can Safely Say In An Interview

### Safe — measured today, reproducible

| Claim | Number |
|---|---|
| Known-item Recall@1, term queries (cap 20, n=299) | 0.973 |
| Known-item Recall@1, sentence queries (cap 20, n=285) | 0.867 |
| MRR | 0.986 / 0.926 |
| Control: identical corpus reproduces baseline exactly after all changes | yes |
| P(retrieved chunk reaches generator) | 33.3% → **100%** |
| Causal grounding of generated questions | 0% → **100%** |
| Exact duplicate rate | 63.5% → **15.4%** |
| Distinct questions (of 480) | 175 → **406** |
| Same-answer score spread | 15 pts → **0** |
| Corpus coverage | 6.2% → **18.6%** (120 → 360 of 1,932 pages) |
| Production top-1 cosine | 0.162 → **0.209** |
| Known-item Recall@1 on the larger corpus | 0.958 (a **decrease**, explained) |
| End-to-end regression suite | **23/23 passing** |
| Gemini live call | verified — 1.42 s, 7 in / 2 out tokens |
| Gemini on frozen answers | substantive **92**, keyword-stuffed **10**, copy-paste **0** |

### Not safe — do not claim

- "RAG accuracy" of any value — no such metric, no relevance labels
- Cosine 0.209 as "20.9% accurate"
- Any Gemini MAE / correlation / agreement figure — no human labels
- "92 vs 0 on the frozen benchmark" for correct-vs-wrong — that head-to-head is incomplete
- That the rubric weights are validated or optimised
- That the system is validated for real hiring decisions

---

## 12. INTERVIEW CHEAT SHEET

### "How did you evaluate your RAG?"

> "Two layers. First a known-item benchmark I built from the corpus itself — 584 queries,
> ground truth by construction: I lift a sentence or the top TF-IDF terms out of a chunk
> and check whether that chunk comes back. Recall@1 is 0.973 on keyword queries and 0.867
> on sentence queries, MRR 0.986. That validates the index and ranking. Second, and more
> useful: the benchmark is what let me find that the pipeline was throwing the ranking
> away. `random.sample(top15, 5)` meant any chunk had a flat one-in-three chance of
> reaching the prompt regardless of rank. I fixed that to take the ranked top-5, so
> effective recall at the generator went from Recall@15 × ⅓ to Recall@5. I'll be upfront
> that topical relevance for real production queries is still unlabelled — that needs human
> judgements and I've built the annotation sheet but not collected them."

### "What was your Recall@K?"

> "On the known-item benchmark at the original corpus size: Recall@1 0.973, Recall@3 1.000,
> Recall@5 1.000, MRR 0.986 over 299 keyword queries; 0.867 / 0.979 / 0.986, MRR 0.926 over
> 285 sentence queries. Two caveats. One, it's single-gold known-item, so it measures index
> health, not topical relevance — it's an upper bound. Two, after I expanded the corpus from
> 300 to 1,004 chunks, Recall@1 dropped to 0.958 and 0.834, because there are 3.3× more
> distractors competing. I report that decrease because the benchmark got harder, not
> because the retriever got worse — and production cosine went up 29% on the same change."

### "How did you evaluate question generation?"

> "Structurally and for diversity, over 480 questions across 96 simulated sessions.
> Causal grounding went from 0% to 100% — before, the fallback templates interpolated only
> the topic and role, and the one variable touching retrieval was assigned and never used;
> now every question contains a concept term provably extracted from the ranked chunks.
> Exact duplicate rate went from 63.5% to 15.4%, distinct questions from 175 to 406.
> Semantic quality — correctness, clarity, difficulty calibration — I did **not** measure,
> because that needs expert raters. The sheet is built: 96 questions, six dimensions, two
> annotators, and I'd report mean rating, percent scoring 4 or higher, and Krippendorff's
> alpha."

### "How did you evaluate answer scoring?"

> "Behaviourally, not against humans, because I have no expert labels and I won't invent
> them. I ran seven frozen adversarial answers through both evaluators. The old heuristic
> scored a correct answer and a fluent-but-factually-wrong answer identically at 70 — it
> measures lexical surface, not truth. So I made Gemini primary and gave it the question
> plus the ranked reference context plus the expected points, and had it grade correctness
> as a separate weighted dimension. On the frozen benchmark Gemini scored the substantive
> answer 92 with correctness 95, keyword-stuffed text 10, and a copied question 0. The most
> telling one: a correct four-word answer scored 0 on the heuristic and 25 with correctness
> 80 on Gemini — it recognised it as true but thin. I also hit a real limit: the free tier
> is 5 requests a minute and I exhausted the daily quota, so two of the seven answers
> aren't measured on Gemini yet. To actually validate the scorer I'd need 60 answers scored
> blind by two or three experts and report MAE, Spearman and quadratic weighted kappa, with
> expert-versus-expert as the noise ceiling."

### "Why did you choose TF-IDF?"

> "Cost and operational simplicity — no embedding API bill, no vector store, deterministic
> and debuggable. And I have evidence it's working: 0.973 Recall@1 on known-item retrieval.
> But I'll be honest that I have measured evidence of its limits too. Sentence queries hit
> 0.867 Recall@1 versus 0.973 for keyword queries — that ten-point gap is lexical mismatch
> showing up in my own benchmark, and it's exactly what embeddings would close. Production
> queries also retrieve at ~0.21 cosine versus near-perfect known-item recall, which says
> the query formulation is the weak link. The right next step is an embedding baseline over
> the same 584 queries, comparing nDCG@5. I'd want that number before defending the choice
> further."

### "What did you improve after evaluation?"

> "Five things, all measured. One: the Gemini dependency was wrong — `requirements.txt`
> said `google-generativeai`, the code imported `google-genai` — so the AI had never run,
> locally or in production. Fixed and verified with a live call. Two: `random.sample` was
> discarding the retrieval ranking; effective recall at the generator went from 33% to 100%.
> Three: questions weren't grounded at all — causal grounding 0% to 100%. Four: scores
> weren't reproducible — the same answer varied by 15 points; now the spread is exactly
> zero. Five: duplicates 63.5% to 15%. And one honest detour: my first determinism fix made
> duplicates *worse*, 63.5% to 88.8%, because every session with the same resume got an
> identical topic sequence. I fixed it with a session-salted rotation — deterministic given
> the session, varied across sessions."

### "What are the limitations?"

> "Four that matter. First, the Gemini free tier is 5 requests a minute with a daily cap,
> and a full interview needs about ten calls, so under load it falls back — I added
> 429-aware retry and explicit evaluator labelling so it's never silent, but sustained use
> needs a paid tier. Second, I still have no human labels, so I cannot quote relevance
> nDCG, question quality, or scorer agreement — the harnesses are built and compute nothing
> on empty sheets, deliberately. Third, the heuristic fallback still can't tell correct from
> wrong; I demoted it rather than repaired it, because a lexical scorer fundamentally can't
> judge truth. Fourth, corpus coverage is 18.6%, not 100% — I measured the tradeoff and
> going past 120 pages per document jumps peak memory to 1.2 GB, which won't fit the 512 MB
> free instance."

---

*Reproduce: `python evaluation/eval_retrieval.py`, `eval_scorer.py`, `eval_qgen.py`,
`test_e2e.py`. Seed 20260910. Baseline preserved in `evaluation/results_before/`.*
