import re
from dataclasses import dataclass
from pathlib import Path

from PyPDF2 import PdfReader

from app.config import settings


ROLE_DESCRIPTIONS = {
    "machine-learning": "Machine Learning Engineer",
    "ml-ops": "ML Ops Engineer",
    "ai-engineer": "AI Engineer",
    "deep-learning": "Deep Learning Engineer",
    "computer-vision": "Computer Vision Engineer",
    "nlp": "NLP Engineer",
    "data-engineer": "Data Engineer",
    "data-analyst": "Data Analyst",
}


ROLE_SUMMARIES = {
    "machine-learning": "Interview focused on modeling, evaluation, feature work, and applied ML problem solving.",
    "ml-ops": "Interview focused on model deployment, monitoring, pipelines, reproducibility, and production ML systems.",
    "ai-engineer": "Interview focused on AI application design, RAG, model integration, evaluation, and system orchestration.",
    "deep-learning": "Interview focused on neural networks, representation learning, optimization, and deep learning tradeoffs.",
    "computer-vision": "Interview focused on image pipelines, CNNs, vision model evaluation, and applied perception systems.",
    "nlp": "Interview focused on text processing, embeddings, retrieval, language models, and NLP evaluation.",
    "data-engineer": "Interview focused on data pipelines, storage, quality, transformations, and ML-ready data systems.",
    "data-analyst": "Interview focused on data querying, visualisation, statistical analysis, business insights, and reporting.",
}


ROLE_KNOWLEDGE_BASE = {
    "machine-learning": "ai-ml",
    "ml-ops": "data-science",
    "ai-engineer": "ai-ml",
    "deep-learning": "advanced-ml",
    "computer-vision": "advanced-ml",
    "nlp": "ai-ml",
    "data-engineer": "data-science",
    "data-analyst": "data-science",
}


ROLE_DIR_HINTS = {
    "ai-ml": "AI or  Machine Learning Role",
    "data-science": "Data Science or Applied ML Role",
    "advanced-ml": "Advanced or  Theoretical ML",
}


# Core skills expected for each target role (used for skill-gap analysis)
ROLE_REQUIRED_SKILLS: dict[str, list[str]] = {
    "machine-learning": [
        "python", "scikit-learn", "pandas", "numpy", "machine learning",
        "model evaluation", "feature engineering", "classification",
        "regression", "statistics",
    ],
    "ml-ops": [
        "python", "docker", "kubernetes", "aws", "data pipelines",
        "machine learning", "sql", "model evaluation", "distributed systems",
    ],
    "ai-engineer": [
        "python", "llm", "rag", "machine learning", "api",
        "deep learning", "nlp", "fastapi", "information retrieval",
    ],
    "deep-learning": [
        "python", "pytorch", "tensorflow", "deep learning", "numpy",
        "machine learning", "classification", "model evaluation",
        "natural language processing",
    ],
    "computer-vision": [
        "python", "pytorch", "tensorflow", "computer vision",
        "deep learning", "numpy", "classification", "model evaluation",
    ],
    "nlp": [
        "python", "nlp", "pytorch", "natural language processing",
        "information retrieval", "machine learning", "classification",
        "deep learning", "rag",
    ],
    "data-engineer": [
        "python", "sql", "postgresql", "aws", "docker", "data pipelines",
        "distributed systems", "databases", "pandas", "numpy",
    ],
    "data-analyst": [
        "sql", "python", "excel", "statistics", "data visualisation",
        "pandas", "power bi", "tableau", "reporting", "business intelligence",
    ],
}


def knowledge_role_for_target(role_id: str) -> str:
    return ROLE_KNOWLEDGE_BASE.get(role_id, role_id)


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    role: str
    document: str
    page: int | None
    text: str


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_pdf_text(path: Path) -> str:
    """Extract text and collapse whitespace (for knowledge-base docs)."""
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return normalize_text("\n".join(pages))


def extract_pdf_text_raw(path: Path) -> str:
    """
    Extract text preserving newlines (for resumes).
    PyPDF2 extract_text preserves line breaks — we keep them here
    so that name/section detection works correctly.
    """
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        # Collapse only multiple blank lines, keep single newlines
        raw = re.sub(r"\x00", " ", raw)
        raw = re.sub(r"\r\n", "\n", raw)
        raw = re.sub(r"[ \t]+", " ", raw)        # collapse spaces/tabs
        raw = re.sub(r"\n{3,}", "\n\n", raw)    # max 2 consecutive blank lines
        pages.append(raw.strip())
    return "\n".join(pages).strip()


def extract_pdf_pages(path: Path, max_pages: int | None = None) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for page_number, page in enumerate(reader.pages, 1):
        if max_pages and page_number > max_pages:
            break
        text = normalize_text(page.extract_text() or "")
        if text:
            pages.append((page_number, text))
    return pages


def role_from_path(path: Path) -> str:
    normalized = str(path.parent).lower()
    for role_id, hint in ROLE_DIR_HINTS.items():
        if hint.lower() in normalized:
            return role_id
    return "ai-ml"


def list_role_documents() -> dict[str, list[Path]]:
    documents: dict[str, list[Path]] = {role_id: [] for role_id in ROLE_DIR_HINTS}
    if not settings.knowledge_base_path.exists():
        return documents

    for path in settings.knowledge_base_path.rglob("*.pdf"):
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > settings.max_document_mb:
            continue
        documents.setdefault(role_from_path(path), []).append(path)
    return documents


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        window = text[start:end]
        boundary = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
        if boundary > chunk_size * 0.55 and end < len(text):
            end = start + boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def load_knowledge_chunks(role_filter: str | None = None) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for role, paths in list_role_documents().items():
        if role_filter and role != role_filter:
            continue
        for path in paths:
            for page_number, page_text in extract_pdf_pages(path, settings.max_pages_per_document):
                for index, chunk in enumerate(
                    chunk_text(page_text, settings.chunk_size, settings.chunk_overlap), 1
                ):
                    chunks.append(
                        DocumentChunk(
                            id=f"{role}:{path.name}:{page_number}:{index}",
                            role=role,
                            document=path.name,
                            page=page_number,
                            text=chunk,
                        )
                    )
    return chunks
