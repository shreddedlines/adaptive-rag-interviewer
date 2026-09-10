import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def decode_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                candidate_name TEXT,
                role TEXT NOT NULL,
                resume_text TEXT NOT NULL,
                resume_profile TEXT NOT NULL,
                status TEXT NOT NULL,
                current_question_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                question_text TEXT NOT NULL,
                topic TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                source_chunks TEXT NOT NULL,
                answer_text TEXT,
                analysis TEXT,
                hint_used INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                time_taken_seconds INTEGER,
                question_meta TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_questions_session
                ON questions(session_id);
            """
        )
        # Safely migrate existing databases — add new columns if missing
        _safe_add_columns(conn, "questions", [
            ("hint_used",           "INTEGER DEFAULT 0"),
            ("skipped",             "INTEGER DEFAULT 0"),
            ("time_taken_seconds",  "INTEGER"),
            ("question_meta",       "TEXT"),
        ])
        _safe_add_columns(conn, "sessions", [
            ("contact_email", "TEXT"),
            ("contact_phone", "TEXT"),
        ])


def _safe_add_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col_name, col_def in columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
