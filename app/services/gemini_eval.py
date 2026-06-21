"""
Gemini 2.5 Flash — answer evaluator.
Falls back silently to heuristic scoring if the API is unavailable or times out.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_client = None
_available: bool | None = None   # None = untested
_MODEL = "gemini-2.5-flash"


def _init() -> bool:
    global _client, _available
    if _available is not None:
        return _available
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        _available = False
        return False
    try:
        from google import genai
        _client = genai.Client(api_key=api_key)
        _available = True
        print(f"[Gemini] Initialised with model={_MODEL}")
        return True
    except Exception as exc:
        print(f"[Gemini] Init failed: {exc}")
        _available = False
        return False


_PROMPT = """\
You are a strict technical interviewer evaluating a candidate's answer.

ROLE: {role}
TOPIC: {topic}
DIFFICULTY: {difficulty}

QUESTION:
{question}

CANDIDATE'S ANSWER:
{answer}

Return ONLY a valid JSON object with these exact keys:
{{
  "score": <integer 0-100>,
  "level": <"strong"|"adequate"|"developing"|"thin"|"off-topic">,
  "feedback": <one concise sentence of honest, actionable feedback>,
  "strengths": <list of up to 3 short strings — what was done well. Empty list if none>,
  "gaps": <list of up to 3 short strings — what was missing or wrong>
}}

Scoring rules (be strict):
- 80-100: Accurate, detailed, uses concrete examples/metrics, discusses tradeoffs
- 60-79:  Mostly correct, some depth, minor gaps
- 35-59:  Partially relevant, lacks specifics or real examples
- 10-34:  Very shallow, vague, or mostly incorrect
- 0-9:    Off-topic, copy-pasted question, random/gibberish text

An answer that repeats or closely mirrors the question text must score below 8.
A correct but one-line answer should not exceed 45.
"""


def evaluate_with_gemini(
    answer: str,
    question_text: str,
    topic: str,
    difficulty: str,
    role: str,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """
    Returns evaluation dict or None (caller falls back to heuristic).
    """
    if not _init():
        return None

    prompt = _PROMPT.format(
        role=role or "AI/ML",
        topic=topic,
        difficulty=difficulty,
        question=question_text.strip(),
        answer=answer.strip(),
    )

    try:
        from google.genai import types
        t0 = time.time()
        response = _client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        elapsed = round(time.time() - t0, 2)
        raw = response.text.strip()

        # Robustly extract first {...} JSON block — handles thinking tokens / extra text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            print(f"[Gemini] No JSON found in response: {raw[:200]}")
            return None
        data = json.loads(match.group())

        score = max(0, min(100, int(data.get("score", 0))))
        level = data.get("level", "off-topic")
        if level not in ("strong", "adequate", "developing", "thin", "off-topic"):
            level = _level_from_score(score)

        print(f"[Gemini] score={score} level={level} elapsed={elapsed}s")
        return {
            "score":     score,
            "level":     level,
            "feedback":  str(data.get("feedback", "")),
            "strengths": list(data.get("strengths", [])),
            "gaps":      list(data.get("gaps", [])),
            "evaluator": "gemini",
        }

    except Exception as exc:
        print(f"[Gemini] Evaluation error ({type(exc).__name__}): {exc}")
        return None


def _level_from_score(score: int) -> str:
    if score >= 80: return "strong"
    if score >= 60: return "adequate"
    if score >= 35: return "developing"
    if score >= 10: return "thin"
    return "off-topic"


# ── Question generation ────────────────────────────────────────────────────────

_QUESTION_PROMPT = """\
You are a senior technical interviewer designing a structured interview question.

ROLE: {role}
CANDIDATE BACKGROUND (skills & domains from resume): {background}
TOPIC TO FOCUS ON: {topic}
DIFFICULTY: {difficulty}

RETRIEVED KNOWLEDGE BASE CONTENT (use this as your source material):
---
{chunks}
---

Write ONE interview question that:
- Is directly grounded in the retrieved content above (use specific concepts from it)
- Is tailored to the candidate's background
- Matches the difficulty level:
    foundational  → ask them to explain a concept and give a real example
    intermediate  → ask them to apply a concept to a production scenario with a constraint or metric
    advanced      → ask them to defend a design, handle a failure mode, or critique an approach
- Reflects conceptual AND/OR applied understanding
- Does NOT mention any PDF filenames, document names, or "retrieved material"
- Is a single clear question (no sub-bullets, no preamble)

Return ONLY the question text. Nothing else.
"""


def generate_question(
    role: str,
    topic: str,
    difficulty: str,
    candidate_background: str,
    chunk_texts: list[str],
    timeout: float = 10.0,
) -> str | None:
    """
    Generate a grounded interview question using the retrieved chunks.
    Returns the question string, or None if Gemini is unavailable (caller uses template fallback).
    """
    if not _init():
        return None
    if not chunk_texts:
        return None

    # Combine top chunks (cap at ~1200 chars to keep prompt tight and fast)
    combined = "\n\n".join(chunk_texts[:3])
    if len(combined) > 1200:
        combined = combined[:1200] + "…"

    prompt = _QUESTION_PROMPT.format(
        role=role,
        background=candidate_background or "general ML/AI background",
        topic=topic,
        difficulty=difficulty,
        chunks=combined,
    )

    try:
        from google.genai import types
        t0 = time.time()
        response = _client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,          # some creativity for varied questions
                max_output_tokens=256,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        elapsed = round(time.time() - t0, 2)
        question = response.text.strip().strip('"').strip("'")
        # Sanity check — must be at least a real sentence
        if len(question) < 30 or "\n\n" in question:
            print(f"[Gemini] Question generation returned unexpected output, using fallback")
            return None
        print(f"[Gemini] Generated question in {elapsed}s: {question[:80]}…")
        return question

    except Exception as exc:
        print(f"[Gemini] Question generation error ({type(exc).__name__}): {exc}")
        return None
