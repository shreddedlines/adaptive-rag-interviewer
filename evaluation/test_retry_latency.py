"""
Latency test for the Gemini retry policy under a rate-limited condition.

The 429 is SIMULATED with a stub that raises the exact exception text the real
API returns (including the server-supplied retryDelay). That makes the test
deterministic and independent of the live quota state, and it exercises the real
_generate() retry loop, not a mock of it.

Measures:
  * OLD policy   (3 retries, honour server delay up to 65s)   -> the reported ~2.5 min
  * NEW batch    (3 retries, honour server delay up to 65s)   -> unchanged, offline only
  * NEW interactive (<=1 retry, 2s budget)                    -> browser path

Also asserts the fallback is labelled evaluator="heuristic", never "gemini".

Run:  python evaluation/test_retry_latency.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import gemini_eval  # noqa: E402
from app.services.interview import analyze_answer  # noqa: E402

# Verbatim shape of a real gemini-2.5-flash free-tier 429, including retryDelay.
RATE_LIMIT_TEXT = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota, please check your plan and billing details. "
    "* Quota exceeded for metric: generativelanguage.googleapis.com/"
    "generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash. "
    "Please retry in 59.0s.', 'status': 'RESOURCE_EXHAUSTED', 'details': "
    "[{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '59s'}]}}"
)

QUESTION = ("You are applying model evaluation in a production system. What design "
            "decision would you make first and what metric would validate it?")
ANSWER = ("I would optimise recall at a fixed precision floor of 0.90 rather than "
          "accuracy, because at 2 percent prevalence accuracy is meaningless. I would "
          "use a temporal split to avoid leaking future information from the test set.")
SOURCES = [{"text": "Accuracy can be misleading for imbalanced classes. A held-out "
                    "test set is required to estimate generalisation.",
            "document": "example.pdf", "page": 1}]


class AlwaysRateLimited:
    """Stub client whose generate_content always raises a 429."""

    def __init__(self):
        self.calls = 0
        self.models = self

    def generate_content(self, **kwargs):
        self.calls += 1
        raise RuntimeError(RATE_LIMIT_TEXT)


def _old_policy_generate(config, prompt, what, profile=None):
    """The PRE-FIX retry loop, reconstructed for the before/after comparison.

    3 retries, each honouring the server's retryDelay capped at 65s.
    """
    import re
    last = None
    for attempt in range(4):
        try:
            return gemini_eval._client.models.generate_content(
                model=gemini_eval._MODEL, contents=prompt, config=config)
        except Exception as exc:
            last = exc
            if gemini_eval._is_rate_limit(exc) and attempt < 3:
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc))
                delay = min(float(m.group(1)) + 1.0, 65.0) if m else min(2.0 ** attempt, 60.0)
                print(f"      [old] rate limited, sleeping {delay:.0f}s "
                      f"(attempt {attempt + 1}/3)")
                time.sleep(delay)
                continue
            raise
    raise last


def measure(label: str, *, profile: str | None, use_old: bool = False,
            simulate_sleep: bool = False) -> tuple[float, dict]:
    stub = AlwaysRateLimited()
    saved_client, saved_gen, saved_avail = (
        gemini_eval._client, gemini_eval._generate, gemini_eval._available)
    slept: list[float] = []

    if simulate_sleep:                      # account the sleep without serving it
        real_sleep = time.sleep
        gemini_eval.time.sleep = lambda s: slept.append(s)

    gemini_eval._client = stub
    gemini_eval._available = True
    if use_old:
        gemini_eval._generate = _old_policy_generate

    try:
        t0 = time.time()
        result = analyze_answer(answer=ANSWER, question_text=QUESTION,
                                topic="model evaluation", sources=SOURCES,
                                role="ai-engineer", difficulty="intermediate")
        elapsed = time.time() - t0 + sum(slept)
    finally:
        gemini_eval._client, gemini_eval._available = saved_client, saved_avail
        gemini_eval._generate = saved_gen
        if simulate_sleep:
            gemini_eval.time.sleep = real_sleep

    print(f"  {label:52s} {elapsed:7.2f}s  api_calls={stub.calls}  "
          f"evaluator={result.get('evaluator')!r}")
    if slept:
        print(f"      (sleep accounted, not served: {[round(x) for x in slept]})")
    return elapsed, result


def main() -> None:
    print("=" * 82)
    print("GEMINI RETRY LATENCY UNDER A SIMULATED 429 (server asks for 59s)")
    print("=" * 82)

    print("\nBEFORE - old policy (3 retries, honour server delay):")
    old_t, old_r = measure("old policy", profile=None, use_old=True, simulate_sleep=True)

    print("\nAFTER - batch profile (offline scripts, unchanged behaviour):")
    gemini_eval.set_retry_profile("batch")
    batch_t, batch_r = measure("batch profile", profile="batch", simulate_sleep=True)

    print("\nAFTER - interactive profile (browser path):")
    gemini_eval.set_retry_profile("interactive")
    inter_t, inter_r = measure("interactive profile", profile="interactive")

    print("\n" + "=" * 82)
    print(f"{'BEFORE (old policy)':40s} {old_t:8.2f}s")
    print(f"{'AFTER  (batch, offline scripts)':40s} {batch_t:8.2f}s   (deliberately unchanged)")
    print(f"{'AFTER  (interactive, browser)':40s} {inter_t:8.2f}s")
    if inter_t > 0:
        print(f"{'interactive speedup':40s} {old_t / max(inter_t, 1e-6):8.0f}x")
    print("=" * 82)

    failures = []
    for name, r in [("old", old_r), ("batch", batch_r), ("interactive", inter_r)]:
        if r.get("evaluator") != "heuristic":
            failures.append(f"{name}: evaluator={r.get('evaluator')!r}, expected 'heuristic'")
    if inter_t > 5.0:
        failures.append(f"interactive path took {inter_t:.2f}s, expected < 5s")
    if not isinstance(inter_r.get("score"), int):
        failures.append("interactive fallback did not produce a score")

    print()
    if failures:
        for f in failures:
            print("  FAIL:", f)
        sys.exit(1)
    print("  PASS: rate-limited fallback is fast, scored, and labelled 'heuristic'")


if __name__ == "__main__":
    main()
