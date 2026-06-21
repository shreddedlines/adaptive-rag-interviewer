from typing import Any

from pydantic import BaseModel


class RoleInfo(BaseModel):
    id: str
    name: str
    description: str
    document_count: int
    required_skills: list[str] = []


class ResumeProfile(BaseModel):
    candidate_name: str | None = None
    skills: list[str]
    technologies: list[str]
    domains: list[str]
    seniority_signal: str


class SourceChunk(BaseModel):
    document: str
    role: str
    page: int | None = None
    score: float
    text: str


class Question(BaseModel):
    id: str
    text: str
    topic: str
    difficulty: str
    sources: list[SourceChunk]


class SkillGapItem(BaseModel):
    skill: str
    status: str   # "match" | "gap" | "partial"


class SessionCreated(BaseModel):
    session_id: str
    candidate_name: str | None
    role: str
    profile: ResumeProfile
    question: Question
    skill_gap: list[SkillGapItem] = []


class AnswerRequest(BaseModel):
    answer: str
    time_taken_seconds: int | None = None


class HintResponse(BaseModel):
    hint: str
    penalty_note: str


class AnswerResult(BaseModel):
    analysis: dict[str, Any]
    next_question: Question | None
    complete: bool


class SessionSummary(BaseModel):
    session_id: str
    role: str
    candidate_name: str | None
    profile: ResumeProfile
    status: str
    questions: list[dict[str, Any]]
    insights: dict[str, Any]
