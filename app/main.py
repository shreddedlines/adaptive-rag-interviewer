from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import io

from app.config import ROOT_DIR, settings
from app.database import init_db
from app.models import AnswerRequest, AnswerResult, HintResponse, RoleInfo, SessionCreated, SessionSummary, SkillGapItem
from app.services.documents import (
    ROLE_DESCRIPTIONS, ROLE_REQUIRED_SKILLS, ROLE_SUMMARIES,
    knowledge_role_for_target, list_role_documents,
)
from app.services.interview import (
    answer_current_question, generate_hint, session_summary,
    skip_current_question, start_session,
)
from app.services.resume import (
    build_resume_profile, extract_email, extract_phone,
    infer_candidate_name, parse_resume_upload,
    quick_validate_resume_text, validate_resume_file, validate_resume_text,
)


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


static_dir    = ROOT_DIR / "static"
frontend_dist = ROOT_DIR / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"

if frontend_assets.exists():
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    built = frontend_dist / "index.html"
    return FileResponse(built if built.exists() else static_dir / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/roles", response_model=list[RoleInfo])
def roles() -> list[RoleInfo]:
    documents = list_role_documents()
    return [
        RoleInfo(
            id=role_id, name=name,
            description=ROLE_SUMMARIES.get(role_id, f"Interview for {name}."),
            document_count=len(documents.get(knowledge_role_for_target(role_id), [])),
            required_skills=ROLE_REQUIRED_SKILLS.get(role_id, []),
        )
        for role_id, name in ROLE_DESCRIPTIONS.items()
    ]


def _build_skill_gap(role: str, profile) -> list[SkillGapItem]:
    required = ROLE_REQUIRED_SKILLS.get(role, [])
    candidate = {s.lower() for s in (profile.skills + profile.technologies + profile.domains)}
    result: list[SkillGapItem] = []
    for skill in required:
        sl = skill.lower()
        if sl in candidate:
            status = "match"
        elif any(sl in s or s in sl for s in candidate):
            status = "partial"
        else:
            status = "gap"
        result.append(SkillGapItem(skill=skill, status=status))
    return result


@app.post("/api/resume-preview")
async def resume_preview(resume: UploadFile = File(...)) -> dict:
    """Parse resume and return detected name/email/phone, or an error message."""
    content = await resume.read()
    if not content:
        return {"error": "The file is empty. Please upload a valid resume."}
    try:
        validate_resume_file(resume.filename or "", resume.content_type, content)
        text  = parse_resume_upload(resume.filename or "resume.txt", content)
        quick_validate_resume_text(text)   # lenient check only
        name  = infer_candidate_name(text)
        email = extract_email(text)
        phone = extract_phone(text)
        return {"name": name, "email": email, "phone": phone}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception:
        return {"error": "Could not read this file. Please upload a valid resume PDF."}



@app.post("/api/sessions", response_model=SessionCreated)
async def create_session(
    role: str = Form(...),
    resume: UploadFile = File(...),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    candidate_name: str = Form(default=""),
) -> SessionCreated:
    if role not in ROLE_DESCRIPTIONS:
        raise HTTPException(status_code=400, detail="Unknown role")
    content = await resume.read()
    if not content:
        raise HTTPException(status_code=400, detail="Resume file is empty")
    try:
        validate_resume_file(resume.filename or "", resume.content_type, content)
        resume_text = parse_resume_upload(resume.filename or "resume.txt", content)
        validate_resume_text(resume_text)
        profile = build_resume_profile(resume_text)
        # Allow form-provided name to override auto-detected one
        if candidate_name.strip():
            profile.candidate_name = candidate_name.strip()
        session_id, question = start_session(
            role, resume_text, profile,
            contact_email=contact_email.strip() or None,
            contact_phone=contact_phone.strip() or None,
        )
        return SessionCreated(
            session_id=session_id, candidate_name=profile.candidate_name,
            role=role, profile=profile, question=question,
            skill_gap=_build_skill_gap(role, profile),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/answer", response_model=AnswerResult)
def submit_answer(session_id: str, payload: AnswerRequest) -> AnswerResult:
    if len(payload.answer.strip()) < 10:
        raise HTTPException(status_code=400, detail="Answer is too short")
    try:
        analysis, next_q, complete = answer_current_question(
            session_id, payload.answer.strip(), payload.time_taken_seconds
        )
        return AnswerResult(analysis=analysis, next_question=next_q, complete=complete)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/skip", response_model=AnswerResult)
def skip_question(session_id: str) -> AnswerResult:
    try:
        analysis, next_q, complete = skip_current_question(session_id)
        return AnswerResult(analysis=analysis, next_question=next_q, complete=complete)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/hint", response_model=HintResponse)
def get_hint(session_id: str) -> HintResponse:
    try:
        return generate_hint(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/summary", response_model=SessionSummary)
def get_summary(session_id: str) -> SessionSummary:
    try:
        return session_summary(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/export")
def export_pdf(session_id: str):
    """Generate and stream a PDF report for the given session."""
    try:
        from app.database import db
        from app.services.pdf_report import generate_pdf_report

        summary = session_summary(session_id)
        # Fetch contact info from DB
        with db() as conn:
            row = conn.execute(
                "SELECT contact_email, contact_phone, candidate_name FROM sessions WHERE id = ?",
                (session_id,)
            ).fetchone()
        contact_email = row["contact_email"] if row else None
        contact_phone = row["contact_phone"] if row else None
        candidate_name = (row["candidate_name"] or "candidate") if row else "candidate"

        pdf_bytes = generate_pdf_report(
            summary=summary.model_dump(),
            contact_email=contact_email,
            contact_phone=contact_phone,
        )
        filename = f"interview_report_{candidate_name.replace(' ', '_').lower()}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc


# ── Reviewer dashboard ──────────────────────────────────────────────────────
@app.get("/api/reviewer/sessions")
def reviewer_sessions() -> list[dict]:
    """All sessions with candidate contact info and score for reviewer."""
    from app.database import db
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id, s.candidate_name, s.role,
                s.contact_email, s.contact_phone,
                s.status, s.created_at,
                COUNT(q.id) AS total_q,
                SUM(CASE WHEN q.answer_text IS NOT NULL AND q.skipped=0 THEN 1 ELSE 0 END) AS answered,
                SUM(CASE WHEN q.skipped=1 THEN 1 ELSE 0 END) AS skipped,
                AVG(CASE WHEN q.analysis IS NOT NULL
                         THEN json_extract(q.analysis, '$.score')
                         ELSE NULL END) AS avg_score
            FROM sessions s
            LEFT JOIN questions q ON q.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/reviewer", include_in_schema=False)
def reviewer_page():
    from fastapi.responses import FileResponse
    return FileResponse("static/reviewer.html", media_type="text/html")
