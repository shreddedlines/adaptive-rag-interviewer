"""
Capture README screenshots from the deployed instance.

Drives the real deployed app with Playwright and saves PNGs to docs/screenshots/.
Uses a clearly-labelled synthetic candidate ("Evaluation Testbot") so no real
candidate data is ever captured.

Run:  python evaluation/capture_screenshots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://adaptive-rag-interviewer.onrender.com"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
WIDTH = 1440

RESUME = """EVALUATION TESTBOT
readme-eval@example.com
+91 90000 00001

SKILLS
Python, PyTorch, RAG, LLM, NLP, FastAPI, Docker, machine learning, model evaluation

EXPERIENCE
AI Engineer with 4 years experience building retrieval augmented generation systems,
classification models, feature engineering pipelines and information retrieval services
deployed as microservices with an API layer for production workloads.

EDUCATION
B.Tech Computer Science
"""

ANSWER = (
    "I would fix the evaluation metric before touching the model because it encodes the "
    "business tradeoff. For a fraud classifier a false negative costs far more, so I optimise "
    "recall at a precision floor of 0.90 rather than accuracy, which is meaningless at 2 "
    "percent prevalence. I would use a temporal split rather than a random split because a "
    "random split leaks future information and inflated our offline AUC by 6 points. To "
    "validate it I track precision at fixed recall weekly and alert on drift. The failure "
    "mode is label delay of 30 days."
)

INJECT_RESUME = """
([text]) => {
  const f = new File([text], 'eval.txt', { type: 'text/plain' });
  const dt = new DataTransfer(); dt.items.add(f);
  const inp = document.getElementById('resume-input');
  inp.files = dt.files;
  inp.dispatchEvent(new Event('change', { bubbles: true }));
}
"""

ANSWER_LOOP = """
async ([ans]) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 6; i++) {
    if (state.summary) break;
    if (!state.question) break;
    state.answer = ans;
    await doSubmit();
    await sleep(2500);
  }
  return !!state.summary;
}
"""


def shot(page, name: str, height: int) -> None:
    page.set_viewport_size({"width": WIDTH, "height": height})
    page.wait_for_timeout(900)
    path = OUT / name
    page.screenshot(path=str(path))
    print(f"  saved {path.relative_to(OUT.parents[1])}  ({WIDTH}x{height})")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": 900})

        print("1/4  candidate entry (with resume auto-fill)")
        page.goto(BASE, wait_until="networkidle", timeout=120_000)
        page.wait_for_selector("#resume-input", timeout=60_000)
        page.evaluate(INJECT_RESUME, [RESUME])
        page.wait_for_timeout(6000)          # wait for /api/resume-preview
        shot(page, "01-candidate-entry.png", 900)

        print("2/4  interview screen")
        page.click("#start-btn")
        page.wait_for_function("() => !!state.question", timeout=120_000)
        page.wait_for_timeout(1500)
        shot(page, "02-interview.png", 900)

        print("3/4  summary with radar chart")
        ok = page.evaluate(ANSWER_LOOP, [ANSWER])
        if not ok:
            print("     WARNING: summary not reached", file=sys.stderr)
        page.wait_for_timeout(1500)
        page.evaluate("() => { document.querySelector('.main').scrollTop = 0; "
                      "if (window.drawRadarChart) drawRadarChart(); }")
        shot(page, "03-summary.png", 1250)

        print("4/4  reviewer dashboard")
        page.goto(f"{BASE}/reviewer", wait_until="networkidle", timeout=120_000)
        page.wait_for_selector("#tbody tr", timeout=60_000)
        page.wait_for_timeout(1200)
        shot(page, "04-reviewer-dashboard.png", 620)

        browser.close()
    print(f"\nDone. {len(list(OUT.glob('*.png')))} screenshots in {OUT}")


if __name__ == "__main__":
    main()
