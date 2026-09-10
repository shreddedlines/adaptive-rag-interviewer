import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

# Load .env BEFORE the Settings dataclass body executes. Dataclass field
# defaults are evaluated at class-definition time, so any os.getenv() below
# would otherwise read the environment before .env had been applied.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
except ImportError:  # python-dotenv is optional; real env vars still work
    pass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "PGAGI Candidate Screening")
    database_path: Path = ROOT_DIR / os.getenv("DATABASE_PATH", "storage/app.db")
    knowledge_base_path: Path = ROOT_DIR / os.getenv("KNOWLEDGE_BASE_PATH", "Knowledge Base Resources")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "900"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "160"))
    top_k: int = int(os.getenv("TOP_K", "5"))
    max_document_mb: int = int(os.getenv("MAX_DOCUMENT_MB", "25"))
    max_pages_per_document: int = int(os.getenv("MAX_PAGES_PER_DOCUMENT", "60"))


settings = Settings()
