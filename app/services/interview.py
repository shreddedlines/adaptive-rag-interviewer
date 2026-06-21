import random
import re
import uuid
from collections import Counter
from typing import Any

from app.config import settings
from app.database import db, decode_json, encode_json, utc_now
from app.models import HintResponse, Question, ResumeProfile, SessionSummary, SourceChunk
from app.services.documents import ROLE_DESCRIPTIONS
from app.services.retrieval import build_query, get_index
from app.services.gemini_eval import evaluate_with_gemini


MAX_QUESTIONS = 5

STOPWORDS = {
    "about","after","also","and","any","are","because","been","but","can",
    "could","for","from","had","has","have","how","into","its","more","not",
    "our","out","should","than","that","the","their","then","there","this",
    "was","were","what","when","where","which","will","with","would","you","your",
}

GENERIC_PHRASES = {
    "i do not know","i don't know","not sure","no idea",
    "random answer","anything","blah","hello","test answer",
}

TECHNICAL_TERMS = {
    "accuracy","api","architecture","batch","bias","classification","clustering",
    "deployment","embedding","evaluation","feature","latency","metric","model",
    "monitoring","pipeline","precision","recall","regression","retrieval",
    "scaling","testing","tradeoff","training","validation","vector",
}


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


# ── Running score helper ───────────────────────────────────────────────────────
def _get_running_score(session_id: str) -> float | None:
    with db() as conn:
        rows = conn.execute(
            "SELECT analysis FROM questions WHERE session_id = ? AND answer_text IS NOT NULL AND skipped = 0",
            (session_id,),
        ).fetchall()
    scores = [decode_json(r["analysis"], {}).get("score") for r in rows]
    valid = [s for s in scores if s is not None]
    return sum(valid) / len(valid) if valid else None


# ── Difficulty — 3 tiers ───────────────────────────────────────────────────────
def _difficulty(profile: ResumeProfile, answered_count: int, running_score: float | None) -> str:
    # Advanced: strong running score after at least 2 answers
    if running_score is not None and running_score >= 75 and answered_count >= 2:
        return "advanced"
    # Intermediate: experienced candidate or past Q2
    if profile.seniority_signal in {"experienced", "project-heavy"} or answered_count >= 2:
        return "intermediate"
    return "foundational"


# ── Topic picker ───────────────────────────────────────────────────────────────
def _topic(profile: ResumeProfile, sources: list[SourceChunk], used_topics: set[str]) -> str:
    candidates = profile.domains + profile.technologies + profile.skills
    available = [c for c in candidates if c not in used_topics]
    if available:
        return random.choice(available)
    text = " ".join(source.text for source in sources).lower()
    words = re.findall(r"[a-z][a-z\-]{4,}", text)
    common = [word for word, _ in Counter(words).most_common(20)]
    unused = [w for w in common if w not in used_topics]
    return unused[0] if unused else (common[0] if common else "machine learning fundamentals")


# ── Question text — 3 difficulty tiers ────────────────────────────────────────
def _question_text(
    role: str,
    topic: str,
    difficulty: str,
    sources: list[SourceChunk],
    profile: "ResumeProfile | None" = None,
) -> str:
    # ── Try Gemini-generated question first (grounded in retrieved chunks) ──
    from app.services.gemini_eval import generate_question
    chunk_texts = [s.text for s in sources if s.text]
    background = ""
    if profile:
        background = ", ".join((profile.skills + profile.domains + profile.technologies)[:12])
    gemini_q = generate_question(
        role=role,
        topic=topic,
        difficulty=difficulty,
        candidate_background=background,
        chunk_texts=chunk_texts,
    )
    if gemini_q:
        return gemini_q

    # ── Fallback: hardcoded templates ────────────────────────────────
    source_hint = sources[0].document if sources else "the knowledge base"
    role_label = ROLE_DESCRIPTIONS.get(role, role.replace("-", " ").title())

    foundational_prompts = [
        f"For a {role_label} role, explain {topic} using an example from your own work. What tradeoffs would you watch for?",
        f"How would you explain {topic} to a junior engineer joining your team for the first time?",
        f"What is {topic} and why does it matter in a {role_label} context?",
        f"Walk me through how you would get started with {topic} on a new project.",
        f"What are the core concepts you need to understand before working with {topic}?",
    ]
    intermediate_prompts = [
        f"You are applying {topic} in a production system. What design decision would you make first and what metric would validate it?",
        f"Suppose a candidate mentions {topic} on their resume. What signals distinguish surface familiarity from practical depth?",
        f"How would you evaluate whether a {topic}-based solution is working well, and what failure modes would you expect?",
        f"Connect {topic} to the {role_label} role. What design decision would you make first, and what evidence would justify it?",
        f"You listed {topic} as a strength. Walk through a real scenario where it mattered and what you'd do differently now.",
        f"What are the most common misconceptions about {topic} you've seen in interviews or on the job?",
    ]
    advanced_prompts = [
        f"Defend your preferred architectural approach to {topic} against a senior peer who argues the opposite. What's your strongest counter-evidence?",
        f"Describe a real production failure related to {topic}. What broke, what was the blast radius, and what systemic fix did you put in place?",
        f"Given severe constraints — limited compute, 48-hour deadline, legacy codebase — how would you still deliver a {topic}-based solution without cutting corners on reliability?",
        f"How would you design an observability strategy specifically for a system built around {topic}? What signals would you monitor at each layer?",
        f"If you were reviewing a junior engineer's PR that implements {topic} incorrectly, what are the top three issues you'd flag and how would you explain why each matters?",
    ]

    if difficulty == "advanced":
        text = random.choice(advanced_prompts)
        text += " Be specific: name the system, the metric, and the failure mode."
    elif difficulty == "intermediate":
        text = random.choice(intermediate_prompts)
        text += " Include one concrete metric, system constraint, or edge case."
    else:
        text = random.choice(foundational_prompts)
    return text


# ── create_question ────────────────────────────────────────────────────────────
def create_question(
    session_id: str,
    role: str,
    profile: ResumeProfile,
    previous_answer: str | None = None,
) -> Question:
    with db() as conn:
        answered_count = conn.execute(
            "SELECT COUNT(*) AS count FROM questions WHERE session_id = ?",
            (session_id,),
        ).fetchone()["count"]
        used_topic_rows = conn.execute(
            "SELECT topic FROM questions WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        used_topics: set[str] = {row["topic"] for row in used_topic_rows}

    running_score = _get_running_score(session_id)
    query = build_query(role, profile, previous_answer)
    fetch_k = max(settings.top_k * 3, 12)
    all_sources = get_index(role).search(query, fetch_k)
    sources = random.sample(all_sources, min(settings.top_k, len(all_sources))) if all_sources else []
    topic = _topic(profile, sources, used_topics)
    difficulty = _difficulty(profile, answered_count, running_score)
    question_id = str(uuid.uuid4())
    question = Question(
        id=question_id,
        text=_question_text(role, topic, difficulty, sources, profile),
        topic=topic,
        difficulty=difficulty,
        sources=sources,
    )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO questions (
                id, session_id, question_text, topic, difficulty, source_chunks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question.id, session_id, question.text, question.topic,
                question.difficulty,
                encode_json([model_to_dict(s) for s in sources]),
                utc_now(),
            ),
        )
        conn.execute(
            "UPDATE sessions SET current_question_id = ?, updated_at = ? WHERE id = ?",
            (question.id, utc_now(), session_id),
        )
    return question


# ── start_session ──────────────────────────────────────────────────────────────
def start_session(
    role: str,
    resume_text: str,
    profile: ResumeProfile,
    contact_email: str | None = None,
    contact_phone: str | None = None,
) -> tuple[str, Question]:
    session_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                id, candidate_name, role, resume_text, resume_profile, status,
                contact_email, contact_phone, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, profile.candidate_name, role, resume_text,
                encode_json(model_to_dict(profile)), "active",
                contact_email or None, contact_phone or None,
                utc_now(), utc_now(),
            ),
        )
    question = create_question(session_id, role, profile)
    return session_id, question



# ── Hint generation ────────────────────────────────────────────────────────────
def generate_hint(session_id: str) -> HintResponse:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND session_id = ?",
            (session["current_question_id"], session_id),
        ).fetchone()
        if question is None:
            raise ValueError("No active question found")

        sources = decode_json(question["source_chunks"], [])
        # Extract first meaningful sentence from source text as the hint
        hint_text = f"Think about how '{question['topic']}' applies in a real production context."
        if sources:
            raw = sources[0].get("text", "")
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if len(s.strip()) > 40]
            if sentences:
                hint_text = sentences[0]

        # Mark hint used
        conn.execute("UPDATE questions SET hint_used = 1 WHERE id = ?", (question["id"],))

    return HintResponse(
        hint=hint_text,
        penalty_note="Using a hint caps your score for this question at 60.",
    )


# ── Skip question ──────────────────────────────────────────────────────────────
def skip_current_question(session_id: str) -> tuple[dict[str, Any], Question | None, bool]:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND session_id = ?",
            (session["current_question_id"], session_id),
        ).fetchone()
        if question is None:
            raise ValueError("No active question found")

        skip_analysis: dict[str, Any] = {
            "score": 0, "level": "skipped",
            "grounding_terms": [], "relevance_terms": [], "technical_terms": [],
            "feedback": "Question was skipped.",
            "component_scores": {"length": 0, "relevance": 0, "grounding": 0, "technical": 0, "specificity": 0},
        }
        conn.execute(
            "UPDATE questions SET answer_text = ?, analysis = ?, skipped = 1, answered_at = ? WHERE id = ?",
            ("", encode_json(skip_analysis), utc_now(), question["id"]),
        )
        answered_count = conn.execute(
            "SELECT COUNT(*) AS count FROM questions WHERE session_id = ? AND answered_at IS NOT NULL",
            (session_id,),
        ).fetchone()["count"]

    profile = ResumeProfile(**decode_json(session["resume_profile"], {}))
    if answered_count >= MAX_QUESTIONS:
        with db() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, current_question_id = NULL, updated_at = ? WHERE id = ?",
                ("complete", utc_now(), session_id),
            )
        return skip_analysis, None, True

    next_question = create_question(session_id, session["role"], profile)
    return skip_analysis, next_question, False


# ── Answer analysis ────────────────────────────────────────────────────────────
def meaningful_words(text: str, min_length: int = 3) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9\-+#.]{%d,}" % (min_length - 1), text.lower())
    return {w for w in words if w not in STOPWORDS}


def analyze_answer(
    answer: str,
    question_text: str,
    topic: str,
    sources: list[dict[str, Any]],
    hint_used: bool = False,
    role: str = "",
    difficulty: str = "foundational",
) -> dict[str, Any]:
    # ── Try Gemini first ───────────────────────────────────────────
    gemini = evaluate_with_gemini(
        answer=answer,
        question_text=question_text,
        topic=topic,
        difficulty=difficulty,
        role=role,
    )
    if gemini is not None:
        score = gemini["score"]
        if hint_used:
            score = min(score, 60)
        score = max(0, min(100, score))
        # Synthesise radar component scores from Gemini's overall score
        s = score / 100
        component_scores = {
            "length":      min(100, round(s * 100)),
            "relevance":   min(100, round(s * 110)),
            "grounding":   min(100, round(s * 95)),
            "technical":   min(100, round(s * 105)),
            "specificity": min(100, round(s * 90)),
        }
        return {
            "score":            score,
            "level":            gemini["level"],
            "feedback":         gemini["feedback"],
            "strengths":        gemini.get("strengths", []),
            "gaps":             gemini.get("gaps", []),
            "grounding_terms":  [],
            "relevance_terms":  [],
            "technical_terms":  [],
            "hint_used":        hint_used,
            "evaluator":        "gemini",
            "component_scores": component_scores,
        }

    # ── Heuristic fallback ─────────────────────────────────────────
    answer_words   = meaningful_words(answer)
    question_words = meaningful_words(question_text)
    topic_words    = meaningful_words(topic)
    source_words   = meaningful_words(" ".join(s.get("text", "") for s in sources), min_length=4)

    word_count   = len(re.findall(r"\b\w+\b", answer))
    lower_answer = answer.lower()

    # ── Copy-paste / mirroring detection ──────────────────────────
    # If the candidate's answer is largely the question text repeated back
    if question_words:
        copied_ratio = len(answer_words & question_words) / len(question_words)
    else:
        copied_ratio = 0.0

    # Original words = words in answer that are NOT from the question
    original_words = answer_words - question_words
    original_word_count = len(re.findall(
        r"\b\w+\b",
        " ".join(w for w in answer.lower().split() if w.strip(".,!?;:") not in {q.lower() for q in question_words})
    ))

    # Hard penalties for copy-paste
    if copied_ratio >= 0.55 or original_word_count < 10:
        return {
            "score": max(0, min(8, word_count // 5)),
            "level": "off-topic",
            "grounding_terms": [],
            "relevance_terms": [],
            "technical_terms": [],
            "feedback": "Your answer appears to repeat the question. Please provide an original response.",
            "hint_used": hint_used,
            "component_scores": {"length": 0, "relevance": 0, "grounding": 0, "technical": 0, "specificity": 0},
        }

    has_generic  = any(phrase in lower_answer for phrase in GENERIC_PHRASES)
    has_specific = bool(re.search(
        r"\b\d+(\.\d+)?%?\b|precision|recall|latency|accuracy|example|tradeoff|because|metric|failure|edge case|bottleneck|benchmark|throughput|f1|auc|rmse|mae",
        lower_answer,
    ))

    grounding_terms   = sorted(answer_words & source_words)
    # Relevance only credits ORIGINAL words (not copied from question)
    original_relevant = original_words & question_words  # will be empty — kept for consistency
    topic_overlap     = original_words & topic_words
    technical_overlap = answer_words & TECHNICAL_TERMS

    length_score      = min(original_word_count / 60, 1) * 15
    relevance_score   = min((len(topic_overlap) * 10), 30)
    grounding_score   = min(len(grounding_terms) * 5, 25)
    technical_score   = min(len(technical_overlap) * 5, 15)
    specificity_score = 15 if has_specific else 0

    score = round(length_score + relevance_score + grounding_score + technical_score + specificity_score)

    # Anti-gaming caps
    if has_generic:                         score = min(score, 20)
    if original_word_count < 20:           score = min(score, 25)
    if original_word_count < 35:           score = min(score, 40)
    if not topic_overlap and not grounding_terms: score = min(score, 22)
    if not grounding_terms and original_word_count < 80: score = min(score, 45)
    if hint_used:                           score = min(score, 60)

    score = max(0, min(100, score))

    if   score >= 78: level = "strong"
    elif score >= 60: level = "adequate"
    elif score >= 35: level = "developing"
    elif original_word_count < 20: level = "thin"
    else:             level = "off-topic"

    component_scores = {
        "length":      min(round(length_score / 15 * 100), 100),
        "relevance":   min(round(relevance_score / 30 * 100), 100),
        "grounding":   min(round(grounding_score / 25 * 100), 100),
        "technical":   min(round(technical_score / 15 * 100), 100),
        "specificity": 100 if has_specific else 0,
    }

    return {
        "score": score,
        "level": level,
        "grounding_terms":  grounding_terms[:10],
        "relevance_terms":  sorted(topic_overlap)[:10],
        "technical_terms":  sorted(technical_overlap)[:10],
        "feedback":         feedback_for_level(level),
        "hint_used":        hint_used,
        "component_scores": component_scores,
    }


def feedback_for_level(level: str) -> str:
    return {
        "strong":    "Clear, grounded answer with useful technical detail.",
        "adequate":  "Relevant answer; sharper examples and evaluation criteria would strengthen it.",
        "developing":"Partially relevant, but needs more concrete reasoning and source connection.",
        "thin":      "Too short to evaluate deeply — specifics, examples, and tradeoffs needed.",
        "off-topic": "The answer does not meaningfully address the question or context.",
        "skipped":   "Question was skipped.",
    }.get(level, "")


# ── answer_current_question ────────────────────────────────────────────────────
def answer_current_question(
    session_id: str,
    answer: str,
    time_taken_seconds: int | None = None,
) -> tuple[dict[str, Any], Question | None, bool]:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND session_id = ?",
            (session["current_question_id"], session_id),
        ).fetchone()
        if question is None:
            raise ValueError("No active question found")

        hint_used = bool(question["hint_used"])
        sources   = decode_json(question["source_chunks"], [])
        analysis  = analyze_answer(
            answer, question["question_text"], question["topic"], sources,
            hint_used=hint_used,
            role=session["role"],
            difficulty=question["difficulty"],
        )

        conn.execute(
            """
            UPDATE questions
            SET answer_text = ?, analysis = ?, answered_at = ?, time_taken_seconds = ?
            WHERE id = ?
            """,
            (answer, encode_json(analysis), utc_now(), time_taken_seconds, question["id"]),
        )
        answered_count = conn.execute(
            "SELECT COUNT(*) AS count FROM questions WHERE session_id = ? AND answered_at IS NOT NULL",
            (session_id,),
        ).fetchone()["count"]

    profile = ResumeProfile(**decode_json(session["resume_profile"], {}))
    if answered_count >= MAX_QUESTIONS:
        with db() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, current_question_id = NULL, updated_at = ? WHERE id = ?",
                ("complete", utc_now(), session_id),
            )
        return analysis, None, True

    next_question = create_question(session_id, session["role"], profile, answer)
    return analysis, next_question, False


# ── session_summary ────────────────────────────────────────────────────────────
def session_summary(session_id: str) -> SessionSummary:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        rows = conn.execute(
            "SELECT * FROM questions WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()

    profile = ResumeProfile(**decode_json(session["resume_profile"], {}))
    questions: list[dict[str, Any]] = []
    scores: list[int] = []
    grounding: Counter[str] = Counter()

    for row in rows:
        analysis = decode_json(row["analysis"], {})
        if "score" in analysis and not row["skipped"]:
            scores.append(int(analysis["score"]))
        grounding.update(analysis.get("grounding_terms", []))
        questions.append({
            "id":                 row["id"],
            "question":           row["question_text"],
            "topic":              row["topic"],
            "difficulty":         row["difficulty"],
            "answer":             row["answer_text"],
            "analysis":           analysis,
            "hint_used":          bool(row["hint_used"]),
            "skipped":            bool(row["skipped"]),
            "time_taken_seconds": row["time_taken_seconds"],
            "sources":            decode_json(row["source_chunks"], []),
        })

    average_score = round(sum(scores) / len(scores), 1) if scores else None
    skipped_count = sum(1 for q in questions if q["skipped"])
    hints_used    = sum(1 for q in questions if q["hint_used"])

    insights = {
        "average_score":      average_score,
        "questions_answered": len(scores),
        "skipped_count":      skipped_count,
        "hints_used":         hints_used,
        "strong_terms":       [t for t, _ in grounding.most_common(8)],
        "recommendation":     recommendation(average_score),
    }

    return SessionSummary(
        session_id=session["id"],
        role=session["role"],
        candidate_name=session["candidate_name"],
        profile=profile,
        status=session["status"],
        questions=questions,
        insights=insights,
    )


def recommendation(score: float | None) -> str:
    if score is None:
        return "Complete the interview to generate a recommendation."
    if score >= 75:
        return "Strong candidate — proceed to a deeper technical round."
    if score >= 60:
        return "Promising — consider a focused follow-up on weaker topics."
    return "Needs more evidence before proceeding to the next round."
