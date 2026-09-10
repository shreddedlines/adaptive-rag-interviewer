"""
End-to-end regression tests for the PGAGI Candidate Screening system.

Covers PHASE 9 (nothing broken) and PHASE 12 (Tests A-D).

Runs against a live local server. Start one first:
    python -m uvicorn app.main:app --port 8099

    python evaluation/test_e2e.py                 # local generator/evaluator path
    GEMINI_E2E=1 python evaluation/test_e2e.py    # also exercise the Gemini path

The Gemini path is opt-in because the free tier allows only 5 requests/minute,
and a full 5-question session needs ~10 calls.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.getenv("E2E_BASE", "http://127.0.0.1:8099")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESUME = (
    "PRIYA SHARMA\npriya.sharma@example.com\n+91 98765 43210\n\n"
    "SKILLS\nPython, PyTorch, RAG, LLM, NLP, FastAPI, Docker, machine learning,\n"
    "model evaluation, classification, information retrieval, pandas, numpy\n\n"
    "EXPERIENCE\nAI Engineer with 4 years experience building retrieval augmented\n"
    "generation systems, classification models, feature engineering pipelines and\n"
    "information retrieval services deployed as microservices behind an API layer\n"
    "for production workloads across several teams and reporting cycles.\n\n"
    "EDUCATION\nB.Tech Computer Science, Example University\n"
).encode()

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def post(path, files=None, data=None, timeout=180):
    if files is not None:
        b = "----b" + uuid.uuid4().hex
        body = b""
        for k, v in files.items():
            if isinstance(v, tuple):
                fn, content = v
                body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; '
                         f'filename="{fn}"\r\nContent-Type: text/plain\r\n\r\n').encode() + content + b"\r\n"
            else:
                body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(BASE + path, data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(BASE + path,
                                     data=json.dumps(data).encode() if data is not None else b"",
                                     headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return {"HTTP_ERROR": e.code, "body": e.read().decode()[:300]}


def get(path, timeout=180, raw=False):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=timeout)
        return (r.read(), r.headers) if raw else json.load(r)
    except urllib.error.HTTPError as e:
        return {"HTTP_ERROR": e.code, "body": e.read().decode()[:300]}


ANSWER = (
    "I would fix the evaluation metric before touching the model because it encodes the "
    "business tradeoff. For a fraud classifier a false negative costs far more, so I optimise "
    "recall at a precision floor of 0.90 rather than accuracy, which is meaningless at 2 "
    "percent prevalence. I use a temporal split, not a random split, because a random split "
    "leaks future information and inflated our offline AUC by 6 points. The failure mode is "
    "label delay of 30 days."
)


def run_session(role="ai-engineer", name="Priya Sharma", answers=None, skip_first=False):
    s = post("/api/sessions", files={"role": role, "resume": ("cv.txt", RESUME),
                                     "candidate_name": name,
                                     "contact_email": "priya.sharma@example.com",
                                     "contact_phone": "+91 98765 43210"})
    if "session_id" not in s:
        return s, []
    sid = s["session_id"]
    qs = [s["question"]]
    n = 0
    while True:
        if skip_first and n == 0:
            r = post(f"/api/sessions/{sid}/skip")
        else:
            r = post(f"/api/sessions/{sid}/answer",
                     data={"answer": (answers or ANSWER), "time_taken_seconds": 45})
        n += 1
        if "HTTP_ERROR" in r:
            break
        if r.get("complete"):
            break
        qs.append(r["next_question"])
    return s, qs


def main() -> None:
    print("=" * 74)
    print(f"END-TO-END REGRESSION SUITE  ->  {BASE}")
    gem = os.getenv("GEMINI_E2E") == "1"
    print(f"Gemini path exercised: {gem}  (set GEMINI_E2E=1 to enable)")
    print("=" * 74)

    h = get("/api/health")
    if not check("server reachable", h == {"status": "ok"}, str(h)):
        print("\nStart the server first:  python -m uvicorn app.main:app --port 8099")
        sys.exit(1)

    print("\n--- PHASE 9: existing functionality preserved ---")
    roles = get("/api/roles")
    check("GET /api/roles returns 8 roles", isinstance(roles, list) and len(roles) == 8,
          f"{len(roles) if isinstance(roles, list) else roles}")
    check("roles report indexed documents", all(r["document_count"] > 0 for r in roles))

    prev = post("/api/resume-preview", files={"resume": ("cv.txt", RESUME)})
    check("resume upload + field extraction",
          prev.get("name") == "Priya Sharma" and "@" in (prev.get("email") or ""),
          json.dumps(prev))

    bad = post("/api/resume-preview", files={"resume": ("x.exe", b"MZ\x90\x00" * 10)})
    check("invalid file rejected", "error" in bad, bad.get("error", "")[:60])

    s, qs = run_session()
    check("session created + profile extracted", "session_id" in s and s["profile"]["skills"],
          f"{len(s.get('profile', {}).get('skills', []))} skills")
    check("skill gap computed", bool(s.get("skill_gap")), f"{len(s.get('skill_gap', []))} entries")
    check("full 5-question interview completes", len(qs) == 5, f"{len(qs)} questions")

    sid = s["session_id"]
    summary = get(f"/api/sessions/{sid}/summary")
    check("summary endpoint", "insights" in summary and summary["status"] == "complete",
          f"avg={summary.get('insights', {}).get('average_score')}")
    check("radar component scores present",
          all(q["analysis"].get("component_scores") for q in summary["questions"] if not q["skipped"]))

    pdf = get(f"/api/sessions/{sid}/export", raw=True)
    check("PDF export", isinstance(pdf, tuple) and pdf[0][:4] == b"%PDF",
          f"{len(pdf[0])} bytes" if isinstance(pdf, tuple) else str(pdf))

    rev = get("/api/reviewer/sessions")
    row = next((r for r in rev if r["id"] == sid), None) if isinstance(rev, list) else None
    check("reviewer lists the session", row is not None)
    check("reviewer status is 'complete'", row and row["status"] == "complete",
          row["status"] if row else "")

    # all-skipped session must still export (was a 500 before)
    s2, _ = run_session(role="nlp", name="Skip Case", skip_first=False, answers=None)
    s3 = post("/api/sessions", files={"role": "nlp", "resume": ("cv.txt", RESUME),
                                      "candidate_name": "All Skipped"})
    sid3 = s3["session_id"]
    for _ in range(5):
        post(f"/api/sessions/{sid3}/skip")
    pdf3 = get(f"/api/sessions/{sid3}/export", raw=True)
    check("PDF export with average_score=None (regression)",
          isinstance(pdf3, tuple) and pdf3[0][:4] == b"%PDF",
          f"{len(pdf3[0])} bytes" if isinstance(pdf3, tuple) else str(pdf3))

    print("\n--- TEST A: question generation ---")
    texts = [q["text"] for q in qs]
    check("all 5 questions distinct within a session", len(set(texts)) == 5,
          f"{len(set(texts))} distinct")
    topics = [q["topic"] for q in qs]
    check("no repeated topic in a session", len(set(topics)) == len(topics), str(topics))
    check("each question has ranked sources", all(len(q["sources"]) > 0 for q in qs))
    ranks_ok = all(
        [x["score"] for x in q["sources"]] == sorted([x["score"] for x in q["sources"]], reverse=True)
        for q in qs)
    check("sources are in descending rank order (no random sampling)", ranks_ok)

    # two different sessions, same resume -> different questions
    sB, qsB = run_session(name="Priya Sharma")
    overlap = len(set(texts) & {q["text"] for q in qsB})
    check("different sessions produce different questions", overlap < 5,
          f"{overlap}/5 shared")

    print("\n--- TEST C: repeatability (same inputs -> same score) ---")
    from app.services.interview import analyze_answer
    from app.services import gemini_eval as ge
    saved = ge._available
    ge._available = False
    try:
        src = summary["questions"][0]["sources"]
        qt = summary["questions"][0]["question"]
        vals = [analyze_answer(ANSWER, qt, summary["questions"][0]["topic"], src,
                               role="ai-engineer", difficulty="intermediate")["score"]
                for _ in range(20)]
    finally:
        ge._available = saved
    check("local evaluator deterministic over 20 runs", len(set(vals)) == 1,
          f"distinct={sorted(set(vals))} sd=0" if len(set(vals)) == 1 else f"distinct={sorted(set(vals))}")

    print("\n--- TEST D: Gemini failure -> labelled fallback ---")
    ge._available = False
    try:
        r = analyze_answer(ANSWER, "What is model evaluation?", "model evaluation",
                           summary["questions"][0]["sources"], role="ai-engineer",
                           difficulty="intermediate")
    finally:
        ge._available = saved
    check("fallback still produces a score", isinstance(r.get("score"), int), str(r.get("score")))
    check("fallback labelled evaluator='heuristic'", r.get("evaluator") == "heuristic",
          repr(r.get("evaluator")))
    evs = {q["analysis"].get("evaluator") for q in summary["questions"]}
    check("every stored analysis records its evaluator", None not in evs, str(evs))

    if gem:
        print("\n--- TEST A/B (Gemini path) ---")
        sG, qsG = run_session(role="machine-learning", name="Gemini Case")
        smG = get(f"/api/sessions/{sG['session_id']}/summary")
        gen_used = set()
        for q in smG["questions"]:
            meta = q.get("analysis", {})
            gen_used.add(meta.get("evaluator"))
        check("at least one Gemini evaluation occurred", "gemini" in gen_used, str(gen_used))

    print("\n" + "=" * 74)
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("=" * 74)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
