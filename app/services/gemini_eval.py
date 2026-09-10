"""
Gemini 2.5 Flash — RAG-grounded question generation and answer evaluation.

Design notes
------------
* Both calls receive the RANKED retrieved chunks. Question generation grounds the
  question in them; answer evaluation uses them as reference context so the model
  can judge CORRECTNESS rather than surface features.
* Both calls run at temperature 0 with a fixed candidate count so repeated calls
  on identical input are as reproducible as the API allows. Remaining variation
  is server-side and is documented rather than hidden.
* Every failure returns None and the caller falls back to a local generator or
  scorer. The caller is responsible for recording WHICH path ran — see
  interview.py, which always writes an explicit "evaluator" / "generator" field.

The scoring rubric below is a DESIGN CHOICE, not an empirically validated
weighting. It has not been calibrated against human expert scores.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

# Importing app.config has the side effect of loading .env before anything reads
# os.environ. Import it explicitly so this module works even when it is imported
# directly (e.g. by a test or an evaluation script) rather than via app.main.
from app import config as _config  # noqa: F401

_client = None
_available: bool | None = None      # None = untested
_init_error: str | None = None
_MODEL = "gemini-2.5-flash"
_TIMEOUT_MS = 20_000

# Context budget: 5 chunks x 600 chars ~= 3000 chars ~= 750 tokens.
_MAX_CHUNKS = 5
_MAX_CHUNK_CHARS = 600


def _init(force: bool = False) -> bool:
    """Initialise the Gemini client. Set force=True to retry after a failure."""
    global _client, _available, _init_error
    if _available is not None and not force:
        return _available
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        _available, _init_error = False, "GEMINI_API_KEY is not set"
        print(f"[Gemini] Unavailable: {_init_error}")
        return False
    try:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
        _available, _init_error = True, None
        print(f"[Gemini] Initialised with model={_MODEL}")
        return True
    except Exception as exc:
        _available = False
        _init_error = f"{type(exc).__name__}: {exc}"
        print(f"[Gemini] Init failed: {_init_error}")
        return False


def availability() -> dict[str, Any]:
    """Introspection for diagnostics and the evaluation harness."""
    return {"available": _init(), "model": _MODEL, "error": _init_error,
            "retry_profile": _DEFAULT_RETRY_PROFILE}


def _format_context(chunks: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Render ranked chunks as an ID-tagged context block.

    Returns (context_text, source_ids). Chunks are assumed to arrive in rank
    order; the ID encodes the rank so the model can cite what it used.
    """
    lines: list[str] = []
    ids: list[str] = []
    for rank, ch in enumerate(chunks[:_MAX_CHUNKS], 1):
        text = (ch.get("text") or "").strip()
        if not text:
            continue
        sid = f"S{rank}"
        ids.append(sid)
        doc = ch.get("document", "unknown")
        page = ch.get("page")
        body = text[:_MAX_CHUNK_CHARS]
        lines.append(f"[{sid}] (source: {doc}, page {page})\n{body}")
    return "\n\n".join(lines), ids


def _extract_json(raw: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# ── Retry policy ─────────────────────────────────────────────────────────────
#
# Rate limiting is a real constraint on the Gemini free tier (5 requests/minute
# for gemini-2.5-flash), but the right response depends on WHO is waiting.
#
#   interactive : a candidate is sitting in front of a browser. Waiting out a
#                 60-second server-supplied retryDelay is worse than falling back
#                 to the heuristic, so we retry at most once and only when the
#                 server says the wait is short. If the server asks for longer
#                 than the budget, retrying is pointless (the quota window has
#                 not reset) so we fail immediately.
#   batch       : an offline evaluation script. Throughput does not matter and a
#                 genuine Gemini result is worth waiting for, so honour the
#                 server's delay across several attempts.
#
# The profile is chosen per call, with a module default that scripts can change.

RETRY_PROFILES: dict[str, dict[str, float]] = {
    "interactive": {"max_retries": 1, "max_delay_seconds": 2.0},
    "batch":       {"max_retries": 3, "max_delay_seconds": 65.0},
}
_DEFAULT_RETRY_PROFILE = os.getenv("GEMINI_RETRY_PROFILE", "interactive")


def set_retry_profile(name: str) -> None:
    """Set the module-wide default profile ("interactive" or "batch")."""
    global _DEFAULT_RETRY_PROFILE
    if name not in RETRY_PROFILES:
        raise ValueError(f"unknown retry profile {name!r}; "
                         f"expected one of {sorted(RETRY_PROFILES)}")
    _DEFAULT_RETRY_PROFILE = name


def get_retry_profile() -> str:
    return _DEFAULT_RETRY_PROFILE


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _server_retry_delay(exc: Exception) -> float | None:
    """The delay the server asked for, in seconds, or None if it did not say."""
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc))
    if m:
        return float(m.group(1))
    m = re.search(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", str(exc))
    if m:
        return float(m.group(1))
    return None


def _generate(config, prompt: str, what: str, profile: str | None = None):
    """Single call site for the API, with profile-aware 429 handling.

    Returns the API response, or raises so the caller can fall back. The caller
    always labels the result with the evaluator/generator that actually ran, so
    a fallback is never mislabelled as Gemini.
    """
    policy = RETRY_PROFILES[profile or _DEFAULT_RETRY_PROFILE]
    max_retries = int(policy["max_retries"])
    max_delay = float(policy["max_delay_seconds"])
    label = profile or _DEFAULT_RETRY_PROFILE

    last: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return _client.models.generate_content(
                model=_MODEL, contents=prompt, config=config)
        except Exception as exc:
            last = exc
            if not (_is_rate_limit(exc) and attempt < max_retries):
                raise
            asked = _server_retry_delay(exc)
            if asked is None:
                delay = min(2.0 ** attempt, max_delay)
            elif asked + 1.0 > max_delay:
                # The quota window will not have reset within our budget, so a
                # retry is guaranteed to fail. Give up now instead of stalling.
                print(f"[Gemini] {what}: rate limited, server asks {asked:.0f}s "
                      f"but the {label} budget is {max_delay:.0f}s - failing fast")
                raise
            else:
                delay = asked + 1.0
            print(f"[Gemini] {what}: rate limited, retrying in {delay:.1f}s "
                  f"(attempt {attempt + 1}/{max_retries}, profile={label})")
            time.sleep(delay)
    raise last if last else RuntimeError("unreachable")


# ═════════════════════════════════════════════════════════════════════════════
# QUESTION GENERATION
# ═════════════════════════════════════════════════════════════════════════════
_QUESTION_PROMPT = """\
You are a senior technical interviewer designing ONE interview question.

ROLE BEING INTERVIEWED FOR: {role}
CANDIDATE BACKGROUND (skills from their resume): {background}
TOPIC TO FOCUS ON: {topic}
TARGET DIFFICULTY: {difficulty}

REFERENCE KNOWLEDGE (ranked by relevance; [S1] is the best match):
---
{context}
---

QUESTIONS ALREADY ASKED IN THIS SESSION (do NOT repeat or paraphrase these):
{previous}

Write ONE interview question that:
- Is grounded in the REFERENCE KNOWLEDGE above. Use a specific concept from it.
- Tests UNDERSTANDING AND REASONING, not keyword recall. The candidate should
  have to explain a tradeoff, justify a decision, diagnose a failure, or apply
  the concept to a situation.
- Is tailored to the candidate's background and the role.
- Matches the target difficulty:
    foundational -> explain a concept and give a concrete example
    intermediate -> apply the concept to a production scenario with a constraint or metric
    advanced     -> defend a design, handle a failure mode, or critique an approach
- Does NOT state facts that are absent from the reference knowledge. You may ask
  about widely known general engineering practice, but do not invent specifics.
- Is materially different from every question already asked.
- Never mentions PDF filenames, page numbers, source IDs, or the reference material.
  Do NOT use phrases like "as mentioned", "according to the context", "the provided
  material", or "the text states". Present the concept as your own framing.
- Keep the question under 60 words. One scenario, one clear ask.
- Is a single self-contained question with no preamble and no sub-bullets.

Return ONLY a JSON object:
{{
  "question": "<the interview question>",
  "topic": "<short topic label, 1-4 words>",
  "difficulty": "<foundational|intermediate|advanced>",
  "source_ids": ["<IDs of the reference blocks you actually used, e.g. S1, S3>"],
  "expected_points": ["<up to 4 short strings: what a strong answer should cover>"]
}}
"""


def generate_question(
    role: str,
    topic: str,
    difficulty: str,
    candidate_background: str,
    chunks: list[dict[str, Any]],
    previous_questions: list[str] | None = None,
    retry_profile: str | None = None,
) -> dict[str, Any] | None:
    """Generate a RAG-grounded question.

    Returns a dict with question/topic/difficulty/source_ids/expected_points,
    or None if Gemini is unavailable or the response is unusable.
    """
    if not _init():
        return None
    context, valid_ids = _format_context(chunks)
    if not context:
        return None

    prev = previous_questions or []
    prev_block = "\n".join(f"- {q}" for q in prev[-8:]) if prev else "(none yet)"

    prompt = _QUESTION_PROMPT.format(
        role=role,
        background=candidate_background or "general ML/AI background",
        topic=topic,
        difficulty=difficulty,
        context=context,
        previous=prev_block,
    )

    try:
        from google.genai import types

        t0 = time.time()
        response = _generate(
            types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=700,
                candidate_count=1,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
            prompt, "question generation", profile=retry_profile,
        )
        elapsed = round(time.time() - t0, 2)
        data = _extract_json((response.text or "").strip())
        if not data:
            print("[Gemini] Question generation: no JSON in response")
            return None

        question = str(data.get("question", "")).strip().strip('"').strip("'")
        if len(question) < 30:
            print(f"[Gemini] Question too short ({len(question)} chars), using fallback")
            return None
        # Guard against the model leaking source markers into the question text
        if re.search(r"\[S\d\]|page \d+\.pdf|\.pdf", question, re.I):
            print("[Gemini] Question leaked source markers, using fallback")
            return None

        used = [s for s in (data.get("source_ids") or []) if s in valid_ids]
        out = {
            "question": question,
            "topic": str(data.get("topic") or topic).strip()[:60] or topic,
            "difficulty": (data.get("difficulty")
                           if data.get("difficulty") in ("foundational", "intermediate", "advanced")
                           else difficulty),
            "source_ids": used,
            "expected_points": [str(p) for p in (data.get("expected_points") or [])][:4],
            "generator": "gemini",
            "latency_seconds": elapsed,
        }
        print(f"[Gemini] Question in {elapsed}s (sources={used}): {question[:70]}...")
        return out

    except Exception as exc:
        kind = "RATE LIMITED (quota exhausted)" if _is_rate_limit(exc) else type(exc).__name__
        print(f"[Gemini] Question generation FAILED [{kind}] -> local fallback")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# ANSWER EVALUATION
# ═════════════════════════════════════════════════════════════════════════════
_EVAL_PROMPT = """\
You are a strict but fair technical interviewer grading a candidate's answer.

ROLE: {role}
TOPIC: {topic}
TARGET DIFFICULTY: {difficulty}

QUESTION ASKED:
{question}

REFERENCE KNOWLEDGE the question was built from (use this to judge factual
correctness; the candidate was NOT shown this):
---
{context}
---
{expected}
CANDIDATE'S ANSWER:
---
{answer}
---

Grade the answer on five dimensions, each 0-100:

1. correctness  - Is what they said factually TRUE? This is the most important
                  dimension. A confident, fluent, well-written answer that is
                  factually WRONG must score below 25 here.
2. relevance    - Does it actually answer the question that was asked?
3. completeness - Does it cover the substance the question calls for, at the
                  target difficulty?
4. reasoning    - Do they justify claims, weigh tradeoffs, and explain WHY,
                  rather than listing terms?
5. grounding    - Do they support claims with concrete examples, metrics,
                  numbers, or real scenarios?

Then give an overall score 0-100. Weight correctness most heavily: an answer
containing clear factual errors must not exceed 35 overall regardless of how
articulate it is.

Hard rules:
- An answer that repeats or paraphrases the question back must score below 8.
- Text that is a list of technical keywords without sentences or argument must
  score below 25, no matter how many correct terms it contains.
- An answer that is off-topic must score below 20.
- A SHORT answer that is nonetheless correct and directly responsive should be
  judged on its content, not its length. Do not score it 0 for brevity; a
  correct but minimal answer typically lands in the 30-50 range.
- Do not reward verbosity. Filler text with no substance scores low.

Return ONLY a JSON object:
{{
  "correctness": <0-100>,
  "relevance": <0-100>,
  "completeness": <0-100>,
  "reasoning": <0-100>,
  "grounding": <0-100>,
  "score": <0-100 overall>,
  "level": "<strong|adequate|developing|thin|off-topic>",
  "feedback": "<one concise, honest, actionable sentence>",
  "strengths": ["<up to 3 short strings; empty list if none>"],
  "gaps": ["<up to 3 short strings of what was missing or wrong>"],
  "factual_errors": ["<up to 3 specific incorrect claims the candidate made; empty if none>"]
}}
"""

_DIMENSIONS = ("correctness", "relevance", "completeness", "reasoning", "grounding")


def evaluate_with_gemini(
    answer: str,
    question_text: str,
    topic: str,
    difficulty: str,
    role: str,
    chunks: list[dict[str, Any]] | None = None,
    expected_points: list[str] | None = None,
    retry_profile: str | None = None,
) -> dict[str, Any] | None:
    """Evaluate an answer against the question AND its reference context.

    Returns an evaluation dict, or None so the caller can fall back.
    """
    if not _init():
        return None

    context, _ = _format_context(chunks or [])
    if not context:
        context = "(no reference context was retained for this question)"

    expected = ""
    if expected_points:
        bullets = "\n".join(f"- {p}" for p in expected_points)
        expected = f"\nPOINTS A STRONG ANSWER WAS EXPECTED TO COVER:\n{bullets}\n"

    prompt = _EVAL_PROMPT.format(
        role=role or "AI/ML",
        topic=topic,
        difficulty=difficulty,
        question=question_text.strip(),
        context=context,
        expected=expected,
        answer=answer.strip(),
    )

    try:
        from google.genai import types

        t0 = time.time()
        response = _generate(
            types.GenerateContentConfig(
                temperature=0.0,
                top_p=1.0,
                seed=42,
                candidate_count=1,
                max_output_tokens=900,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
            prompt, "evaluation", profile=retry_profile,
        )
        elapsed = round(time.time() - t0, 2)
        data = _extract_json((response.text or "").strip())
        if not data:
            print("[Gemini] Evaluation: no JSON in response")
            return None

        def clamp(value: Any, default: int = 0) -> int:
            try:
                return max(0, min(100, int(float(value))))
            except (TypeError, ValueError):
                return default

        score = clamp(data.get("score"))
        dims = {d: clamp(data.get(d)) for d in _DIMENSIONS}

        # Enforce the correctness ceiling deterministically rather than trusting
        # the model to have applied its own rule.
        if dims["correctness"] < 25:
            score = min(score, 35)

        level = data.get("level")
        if level not in ("strong", "adequate", "developing", "thin", "off-topic"):
            level = _level_from_score(score)

        result = {
            "score": score,
            "level": level,
            "feedback": str(data.get("feedback", "")).strip(),
            "strengths": [str(s) for s in (data.get("strengths") or [])][:3],
            "gaps": [str(g) for g in (data.get("gaps") or [])][:3],
            "factual_errors": [str(e) for e in (data.get("factual_errors") or [])][:3],
            "dimension_scores": dims,
            "evaluator": "gemini",
            "latency_seconds": elapsed,
        }
        print(f"[Gemini] score={score} level={level} correctness={dims['correctness']} "
              f"elapsed={elapsed}s")
        return result

    except Exception as exc:
        kind = "RATE LIMITED (quota exhausted)" if _is_rate_limit(exc) else type(exc).__name__
        print(f"[Gemini] Evaluation FAILED [{kind}] -> falling back to heuristic")
        return None


def _level_from_score(score: int) -> str:
    if score >= 78:
        return "strong"
    if score >= 60:
        return "adequate"
    if score >= 35:
        return "developing"
    if score >= 10:
        return "thin"
    return "off-topic"
