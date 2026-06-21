import re
from pathlib import Path

from app.models import ResumeProfile
from app.services.documents import extract_pdf_text_raw, normalize_text


SKILL_KEYWORDS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "fastapi",
    "flask",
    "django",
    "react",
    "next.js",
    "node.js",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "postgresql",
    "mongodb",
    "redis",
    "machine learning",
    "deep learning",
    "nlp",
    "computer vision",
    "rag",
    "llm",
    "tensorflow",
    "pytorch",
    "scikit-learn",
    "pandas",
    "numpy",
    "data analysis",
    "statistics",
    "api",
    "microservices",
}

DOMAIN_KEYWORDS = {
    "recommendation systems",
    "classification",
    "regression",
    "clustering",
    "time series",
    "information retrieval",
    "natural language processing",
    "backend",
    "distributed systems",
    "databases",
    "data pipelines",
    "model evaluation",
    "feature engineering",
}


ALLOWED_RESUME_EXTENSIONS = {".pdf", ".txt", ".md"}
ALLOWED_RESUME_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}

RESUME_SIGNAL_WORDS = {
    "resume",
    "curriculum",
    "cv",
    "experience",
    "education",
    "project",
    "projects",
    "skills",
    "technologies",
    "intern",
    "engineer",
    "developer",
    "degree",
    "university",
    "college",
    "certification",
    "github",
    "linkedin",
    "email",
}

RESUME_SECTION_WORDS = {
    "experience",
    "education",
    "project",
    "projects",
    "skills",
    "technologies",
    "certification",
    "certifications",
    "internship",
    "work",
    "summary",
    "objective",
}


def validate_resume_file(filename: str, content_type: str | None, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_RESUME_EXTENSIONS:
        raise ValueError("Upload only a resume as PDF, TXT, or MD.")

    if content_type and content_type not in ALLOWED_RESUME_MIME_TYPES:
        raise ValueError("Unsupported resume file type. Use PDF, TXT, or MD.")

    if suffix == ".pdf" and not content.startswith(b"%PDF"):
        raise ValueError("The uploaded file is not a valid PDF resume.")

    if suffix in {".txt", ".md"}:
        sample = content[:2048]
        if b"\x00" in sample:
            raise ValueError("The uploaded text resume appears to be a binary file.")


def parse_resume_upload(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        tmp_path = Path("storage") / "_latest_resume.pdf"
        tmp_path.parent.mkdir(exist_ok=True)
        tmp_path.write_bytes(content)
        return extract_pdf_text_raw(tmp_path)   # preserve line breaks for resumes
    return content.decode("utf-8", errors="ignore")


def validate_resume_text(text: str) -> None:
    """Full validation used at session creation — checks content is plausibly a resume."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]*", text.lower())
    if len(words) < 40:
        raise ValueError("Resume is too short. Please upload a complete resume.")
    if len(words) > 3000:
        raise ValueError("This PDF is too long to be a resume. Please upload your resume, not a book or document.")


def quick_validate_resume_text(text: str) -> None:
    """Lenient check at upload time — only rejects files that are clearly useless."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]*", text.lower())
    if len(words) < 15:
        raise ValueError("This file has almost no readable text. Please upload a valid resume PDF.")
    if len(words) > 4000:
        raise ValueError("This PDF is too long to be a resume. Please upload your resume, not a book or document.")

    # For files in the middle range: check if it looks nothing like a resume.
    # A resume should have at least one of: contact info, section headers, or tech keywords.
    has_contact = bool(re.search(
        r"[\w.+-]+@[\w-]+\.[\w.-]+|linkedin|github|\+\d{6,}|\b\d{10}\b",
        text, re.I,
    ))
    # Section headers must appear as their own line (standalone), not buried in prose
    has_sections = bool(re.search(
        r"(?m)^\s*(experience|education|skills|projects?|certifications?|"
        r"internship|employment|technologies|achievements|work experience|"
        r"technical skills|academic background)\s*$",
        text, re.I,
    ))
    has_tech = len(find_keywords(text, SKILL_KEYWORDS)) > 0

    if not has_contact and not has_sections and not has_tech:
        raise ValueError(
            "This file doesn't look like a resume. "
            "Please upload a resume with your experience, skills, and contact details."
        )


def infer_candidate_name(text: str) -> str | None:
    """
    Grab the candidate name from the very top of the resume.
    The name is almost always the first non-empty line — usually
    in ALL CAPS or Title Case with 2-4 words.
    """
    NON_NAME = re.compile(
        r"resume|curriculum|vitae|email|phone|linkedin|github|address|"
        r"objective|summary|profile|portfolio|http|www|@|\||tel:|mob:",
        re.I,
    )
    ALLOWED = re.compile(r"^[A-Za-z][A-Za-z\s\-\']{2,60}$")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:10]:
        words = line.split()
        if not (2 <= len(words) <= 5):
            continue
        if any(ch.isdigit() for ch in line):
            continue
        if not ALLOWED.match(line):
            continue
        if NON_NAME.search(line):
            continue
        # Accept title case or ALL CAPS
        title_ok = all(w[0].isupper() for w in words if w)
        allcaps  = all(w.isupper() for w in words if w)
        if title_ok or allcaps:
            return line.title() if allcaps else line
    return None



def extract_email(text: str) -> str | None:
    """Pull the first email address found in the resume text."""
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    """Pull the first phone/mobile number found in the resume text."""
    # Matches: +91 98765 43210 / (123) 456-7890 / 9876543210 / +1-800-555-0100
    patterns = [
        r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}",  # international
        r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}",                         # US style
        r"\b\d{10}\b",                                                      # plain 10-digit
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            return match.group(0).strip()
    return None


def find_keywords(text: str, keywords: set[str]) -> list[str]:
    lowered = text.lower()
    matches = []
    for keyword in sorted(keywords):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            matches.append(keyword)
    return matches


def seniority_signal(text: str) -> str:
    lowered = text.lower()
    years = [int(value) for value in re.findall(r"(\d+)\+?\s+years?", lowered)]
    if years and max(years) >= 3:
        return "experienced"
    if any(word in lowered for word in ["intern", "fresher", "student", "trainee"]):
        return "early-career"
    if len(text.split()) > 700:
        return "project-heavy"
    return "entry-level"


def build_resume_profile(text: str) -> ResumeProfile:
    technologies = find_keywords(text, SKILL_KEYWORDS)
    domains = find_keywords(text, DOMAIN_KEYWORDS)
    skills = sorted(set(technologies + domains))
    return ResumeProfile(
        candidate_name=infer_candidate_name(text),
        skills=skills[:18],
        technologies=technologies[:14],
        domains=domains[:10],
        seniority_signal=seniority_signal(text),
    )
