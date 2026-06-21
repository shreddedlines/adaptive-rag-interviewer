# Adaptive RAG Interviewer

**Live Demo** -- [adaptive-rag-interviewer.onrender.com](https://adaptive-rag-interviewer.onrender.com)

An AI-powered technical interview platform that screens candidates for AI, ML, and data roles. The system parses a candidate's resume, identifies skill gaps against the target role, generates contextual questions from a curated knowledge base using retrieval-augmented generation (RAG), evaluates answers in real time with Google Gemini, adapts question difficulty based on performance, and produces a downloadable PDF report at the end of each session.

---

## Table of Contents

- [Key Features](#key-features)
- [Supported Roles](#supported-roles)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
- [Database Schema](#database-schema)
- [License](#license)

---

## Key Features

### Resume Intelligence
- Accepts PDF resumes and validates them at upload — rejects non-resume files such as books, blank documents, and unrelated PDFs with clear error feedback
- Extracts the candidate's full name from the first prominent line of the document using positional heuristics
- Detects email and phone number via pattern matching
- Identifies technical skills, technologies, and domain expertise using a curated keyword taxonomy
- Infers seniority level (fresher, junior, mid-level, senior, lead) from years of experience and title keywords
- Performs a skill-gap analysis comparing the candidate's profile against the target role's required competencies

### Adaptive Interview Engine
- Generates a 5-question session per role using TF-IDF retrieval over domain-specific PDF knowledge bases
- Covers distinct topics per session — built-in topic deduplication prevents repeated subject areas
- Three difficulty tiers — foundational, intermediate, and advanced — selected dynamically based on the candidate's running score
- Per-answer AI evaluation returns a score (0-100), performance level, detailed feedback, strengths, and identified gaps
- Heuristic fallback scoring activates automatically if the Gemini API is unavailable or rate-limited, ensuring uninterrupted sessions
- Built-in hint system (available once per question, with a score penalty cap)
- Skip question support for candidates who prefer to move forward
- Per-question countdown timer displayed to the candidate; time taken is stored per question

### Voice Input
- Integrated speech-to-text via the Web Speech API
- Candidates can dictate answers hands-free with a single click

### Reporting and Export
- Session summary with overall score, answered and skipped counts, recommendation text, and per-question breakdown
- Interactive radar chart visualizing performance across topic areas
- Downloadable PDF report generated with ReportLab — clean typography, structured layout, candidate name and contact in the header
- PDF filename is automatically derived from the candidate's name

### Reviewer Dashboard
- Internal-facing dashboard at `/reviewer` listing all completed sessions
- Displays candidate name, role, contact details, overall score, answered and skipped counts, and session timestamp
- Sortable and filterable view for quick candidate comparison

### Design and UX
- Light and dark theme toggle with smooth transitions
- Animated landing page with gradient orbs and cinematic entrance
- Responsive layout built with CSS custom properties and the Inter typeface
- Progress indicators, quality meters, and micro-animations throughout the interview flow

---

## Supported Roles

| Role | Knowledge Base |
|---|---|
| Machine Learning Engineer | AI and ML fundamentals |
| ML Ops Engineer | Data Science and Applied ML |
| AI Engineer | AI and ML fundamentals |
| Deep Learning Engineer | Advanced and Theoretical ML |
| Computer Vision Engineer | Advanced and Theoretical ML |
| NLP Engineer | AI and ML fundamentals |
| Data Engineer | Data Science and Applied ML |
| Data Analyst | Data Science and Applied ML |

Each role maps to a dedicated knowledge base collection and has a defined set of required skills used for skill-gap analysis during resume processing.

---

## Architecture

```
Browser (Single-Page Application)
        |
        | HTTP / JSON
        v
FastAPI Application Server
        |
        |--- Resume Parsing and Validation     (app/services/resume.py)
        |--- Knowledge Retrieval (TF-IDF)      (app/services/retrieval.py)
        |--- Interview Session Management      (app/services/interview.py)
        |--- Answer Evaluation (Gemini API)     (app/services/gemini_eval.py)
        |--- PDF Report Generation             (app/services/pdf_report.py)
        |--- Document and Chunk Loading        (app/services/documents.py)
        |
        v
SQLite Database (storage/app.db)
Knowledge Base PDFs (Knowledge Base Resources/)
```

---

## Project Structure

```
adaptive-rag-interviewer/
|
|-- app/
|   |-- main.py                  # FastAPI application with all API routes
|   |-- config.py                # Settings loaded from environment variables
|   |-- database.py              # SQLite connection, schema initialization, helpers
|   |-- models.py                # Pydantic data models for request/response validation
|   |-- services/
|       |-- documents.py         # PDF chunk loading, role definitions, skill mappings
|       |-- retrieval.py         # TF-IDF knowledge index and query construction
|       |-- resume.py            # Resume parsing, name/skill extraction, validation
|       |-- interview.py         # Session lifecycle, question flow, adaptive scoring
|       |-- gemini_eval.py       # Gemini API client, evaluation prompt, fallback scorer
|       |-- pdf_report.py        # ReportLab PDF report builder
|
|-- static/
|   |-- index.html               # Candidate-facing single-page application
|   |-- app.js                   # Frontend logic — state management, rendering, voice input
|   |-- styles.css               # Design system with light/dark tokens, animations
|   |-- reviewer.html            # Internal reviewer dashboard
|
|-- Knowledge Base Resources/
|   |-- AI or Machine Learning Role/
|   |-- Data Science or Applied ML Role/
|   |-- Advanced or Theoretical ML/
|
|-- storage/
|   |-- app.db                   # SQLite database (auto-created on first run)
|
|-- requirements.txt             # Python dependencies
|-- Procfile                     # Start command for Render / Railway deployment
|-- .env.example                 # Template for environment variable configuration
```

---

## How It Works

### 1. Resume Upload and Validation

Upload validation happens in two stages:

- **At upload (lenient)** — Rejects files that are empty, exceed 4,000 words, or lack any combination of contact information, resume section headers, and technical keywords.
- **At session start (strict)** — Confirms minimum content length and substantive resume material before creating a session.

The system reads the raw PDF line by line from the top. The first line containing 2-5 capitalized words with no digits, URLs, or contact-related keywords is accepted as the candidate's name. All-caps formatting is normalized to title case.

### 2. Knowledge Retrieval

For each new question, the system:

1. Builds a TF-IDF query from the candidate's role, extracted skills, seniority level, and previous answer context
2. Retrieves the top-K most relevant text chunks from the role-specific knowledge base index
3. Passes the chunk content and candidate context to Google Gemini to generate a targeted, grounded question
4. Excludes topics already covered in the session to ensure breadth

### 3. Adaptive Difficulty

- Questions begin at foundational difficulty for fresher-level candidates and intermediate for experienced candidates
- After two or more answered questions, difficulty escalates to advanced if the running average score is 75 or above
- Difficulty reverts to intermediate if the running score drops below 75

### 4. Answer Evaluation

Each answer is evaluated by Gemini with a structured prompt that includes the role, topic, difficulty, source material, and question text. The model returns:

| Field | Description |
|---|---|
| `score` | Integer from 0 to 100 |
| `level` | strong, adequate, developing, thin, or off-topic |
| `feedback` | Detailed paragraph explaining the evaluation |
| `strengths` | List of strong points in the answer |
| `gaps` | List of areas for improvement |

If the API call fails or times out, a heuristic evaluator scores the answer based on length, technical term density, and detection of generic non-answers — ensuring the session continues without interruption.

### 5. Report Generation

At the end of the 5-question session, the platform generates a structured summary including the overall score, per-question breakdown with individual evaluations, a recommendation, and a radar chart. The candidate can download a professionally formatted PDF report.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI with Uvicorn |
| AI Model | Google Gemini 2.5 Flash |
| Knowledge Retrieval | TF-IDF vectorization with scikit-learn |
| Resume Parsing | PyPDF2 |
| PDF Report Generation | ReportLab |
| Database | SQLite |
| Data Validation | Pydantic |
| Frontend | Vanilla HTML, CSS, JavaScript |
| Voice Input | Web Speech API |
| Typography | Inter (Google Fonts) |

---

## Getting Started

**Requirements:** Python 3.10 or higher

```bash
# Clone the repository
git clone https://github.com/shreddedlines/adaptive-rag-interviewer.git
cd adaptive-rag-interviewer

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Open .env and set GEMINI_API_KEY to your Google Gemini API key

# Start the development server
python -m uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser to access the candidate interface.

The reviewer dashboard is available at [http://localhost:8000/reviewer](http://localhost:8000/reviewer).

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/roles` | List all available roles with required skills |
| `POST` | `/api/resume-preview` | Parse resume and return extracted name, email, and phone |
| `POST` | `/api/sessions` | Create a new interview session and return the first question |
| `POST` | `/api/sessions/{id}/answer` | Submit an answer and receive evaluation with the next question |
| `POST` | `/api/sessions/{id}/skip` | Skip the current question |
| `GET` | `/api/sessions/{id}/hint` | Request a hint for the current question |
| `GET` | `/api/sessions/{id}/summary` | Retrieve the full session summary with insights and scores |
| `GET` | `/api/sessions/{id}/export` | Download the session report as a PDF |
| `GET` | `/api/reviewer/sessions` | Retrieve all sessions for the reviewer dashboard |

---

## Environment Variables

Create a `.env` file in the project root. See `.env.example` for reference.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | -- | Google Gemini API key |
| `DATABASE_PATH` | No | `storage/app.db` | Path to the SQLite database file |
| `KNOWLEDGE_BASE_PATH` | No | `Knowledge Base Resources` | Path to the knowledge base PDF directory |
| `CHUNK_SIZE` | No | `900` | Characters per text chunk for knowledge indexing |
| `CHUNK_OVERLAP` | No | `160` | Overlap between consecutive text chunks |
| `TOP_K` | No | `5` | Number of chunks retrieved per query |

---

## Deployment

### Render (Recommended -- Free Tier)

1. Push the repository to GitHub
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect your GitHub repository
4. Configure the service:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add the `GEMINI_API_KEY` environment variable in the Render dashboard
6. Deploy -- the app will be live at `https://your-service-name.onrender.com`

### Railway

1. Sign in to [railway.app](https://railway.app) with GitHub
2. Create a new project and select **Deploy from GitHub repo**
3. Add the `GEMINI_API_KEY` environment variable
4. Railway auto-detects Python and deploys automatically

> **Note:** Free-tier platforms use ephemeral filesystems. The SQLite database will reset on each deployment or container restart. For persistent storage in production, consider migrating to a hosted PostgreSQL instance.

---

## Database Schema

### sessions

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID session identifier |
| `candidate_name` | TEXT | Extracted from the resume |
| `role` | TEXT | Selected role identifier |
| `resume_text` | TEXT | Raw extracted resume text |
| `resume_profile` | TEXT | JSON object containing skills, technologies, domains, and seniority |
| `contact_email` | TEXT | Candidate email address |
| `contact_phone` | TEXT | Candidate phone number |
| `status` | TEXT | `active` or `completed` |
| `created_at` | TEXT | ISO 8601 timestamp |
| `updated_at` | TEXT | ISO 8601 timestamp |

### questions

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID question identifier |
| `session_id` | TEXT | Foreign key referencing sessions |
| `question_text` | TEXT | Generated question text |
| `topic` | TEXT | Topic category |
| `difficulty` | TEXT | foundational, intermediate, or advanced |
| `source_chunks` | TEXT | JSON array of retrieved knowledge base chunks |
| `answer_text` | TEXT | Candidate's submitted answer |
| `analysis` | TEXT | JSON object with score, level, feedback, strengths, and gaps |
| `hint_used` | INTEGER | 1 if a hint was requested |
| `skipped` | INTEGER | 1 if the question was skipped |
| `time_taken_seconds` | INTEGER | Seconds spent answering this question |
| `created_at` | TEXT | ISO 8601 timestamp |
| `answered_at` | TEXT | ISO 8601 timestamp |

---

## License

This project is open source and available under the [MIT License](LICENSE).
