# AI Interview Platform

A full-stack, resume-aware technical interview system powered by Google Gemini. The platform screens candidates for AI/ML and data roles by parsing their resume, dynamically generating role-specific questions from a curated knowledge base, evaluating answers in real time, and producing a downloadable PDF report at the end of each session.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Supported Roles](#supported-roles)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [Deployment](#deployment)
- [Tech Stack](#tech-stack)

---

## Overview

The platform operates as a single-page web application backed by a FastAPI server. A candidate uploads their resume, fills in their contact details, and selects a target role. The system then:

1. Parses and validates the resume
2. Extracts the candidate's name, email, phone, skills, technologies, and seniority level
3. Performs a skill-gap analysis against the role's required competencies
4. Generates a personalised sequence of 5 questions using retrieval-augmented generation (RAG) over a domain knowledge base
5. Evaluates each answer with Gemini 2.5 Flash, scoring from 0–100 with per-answer feedback, strengths, and identified gaps
6. Adapts question difficulty based on the candidate's running score
7. Produces a structured session summary and a professionally formatted PDF report

A separate reviewer dashboard aggregates all completed sessions for internal review.

---

## Features

**Resume Processing**
- Accepts PDF resumes only; rejects non-resume files (books, random documents) at upload time with a clear inline error
- Preserves line-break structure during text extraction for reliable section and name detection
- Infers candidate name from the first prominent line of the document
- Extracts email and phone via pattern matching
- Identifies skills, technologies, and domains using a keyword taxonomy
- Detects seniority level (fresher / junior / mid-level / senior / lead) from years of experience and title keywords

**Interview Engine**
- 5-question sessions generated per role using TF-IDF retrieval over a curated PDF knowledge base
- Questions cover distinct topics to avoid repetition (topic deduplication)
- Three difficulty tiers — foundational, intermediate, advanced — selected dynamically based on real-time score
- Per-answer AI evaluation: score, level, feedback paragraph, strengths list, gaps list
- Heuristic fallback scoring if the Gemini API is unavailable or rate-limited
- Hint system (available once per question, with a score penalty note)
- Skip question support
- Per-answer timer displayed to candidate; time taken stored in database

**Reporting**
- Session summary with overall score, answered/skipped counts, recommendation text, and per-question breakdown
- Downloadable PDF report generated with ReportLab — clean typography, no borders, candidate name and contact in header
- PDF filename derived from candidate name automatically

**Reviewer Dashboard**
- Internal-facing page at `/reviewer` listing all sessions
- Displays candidate name, role, contact details, score, answered/skipped counts, and session date
- Sortable and filterable view

**Infrastructure**
- SQLite database with two tables: `sessions` and `questions`
- All session data, answers, and AI analysis JSON stored persistently
- Hot-reload development server via Uvicorn

---

## Supported Roles

| Role ID | Display Name |
|---|---|
| `machine-learning` | Machine Learning Engineer |
| `ml-ops` | ML Ops Engineer |
| `ai-engineer` | AI Engineer |
| `deep-learning` | Deep Learning Engineer |
| `computer-vision` | Computer Vision Engineer |
| `nlp` | NLP Engineer |
| `data-engineer` | Data Engineer |
| `data-analyst` | Data Analyst |

Each role maps to one of three knowledge base collections and has a defined required-skills list used for skill-gap analysis.

---

## Architecture

```
Browser (Single Page App)
        |
        | HTTP / JSON
        v
FastAPI Application (app/main.py)
        |
        |-- Resume parsing & validation  (app/services/resume.py)
        |-- Knowledge retrieval (TF-IDF) (app/services/retrieval.py)
        |-- Interview session logic      (app/services/interview.py)
        |-- Gemini answer evaluation     (app/services/gemini_eval.py)
        |-- PDF report generation        (app/services/pdf_report.py)
        |-- Document/chunk loading       (app/services/documents.py)
        |
        v
SQLite Database (storage/app.db)
Knowledge Base PDFs (Knowledge Base Resources/)
```

---

## Project Structure

```
PGAGI/
|
|-- app/
|   |-- main.py              # FastAPI application, all API routes
|   |-- config.py            # Settings loaded from environment variables
|   |-- database.py          # SQLite connection, schema init, helpers
|   |-- models.py            # Pydantic data models
|   |-- services/
|       |-- documents.py     # PDF chunk loading, role definitions, skill lists
|       |-- retrieval.py     # TF-IDF knowledge index and query builder
|       |-- resume.py        # Resume parsing, name/skill extraction, validation
|       |-- interview.py     # Session creation, question flow, scoring logic
|       |-- gemini_eval.py   # Gemini API client, prompt, fallback evaluator
|       |-- pdf_report.py    # ReportLab PDF report generator
|
|-- static/
|   |-- index.html           # Candidate-facing single-page app shell
|   |-- app.js               # All frontend logic (vanilla JS)
|   |-- styles.css           # Application styles
|   |-- reviewer.html        # Reviewer dashboard
|
|-- Knowledge Base Resources/
|   |-- AI or Machine Learning Role/
|   |-- Data Science or Applied ML Role/
|   |-- Advanced or Theoretical ML/
|
|-- storage/
|   |-- app.db               # SQLite database (auto-created on startup)
|
|-- requirements.txt
|-- Procfile                 # For Render / Railway deployment
|-- .env.example
|-- .gitignore
```

---

## How It Works

### Resume Validation

Upload validation happens in two stages:

1. **At upload (lenient)** — Rejects files that are empty, exceed 4,000 words (books/long documents), or have no contact information, no resume section headers, and no recognisable technical keywords.
2. **At session start (strict)** — Confirms minimum length and substantive content before creating a session.

### Name Detection

The system reads the raw PDF line by line from the top. The first line that contains 2–5 capitalised words with no digits, URLs, or contact keywords is accepted as the candidate's name. All-caps names are converted to title case.

### Question Generation

For each new question:
- A TF-IDF query is built from the candidate's role, skills, seniority, and previous answer
- The top-K most relevant chunks are retrieved from the knowledge base index for that role
- The chunk content and candidate context are passed to Gemini to generate a targeted question
- Topics already covered in the session are excluded from consideration

### Adaptive Difficulty

- Questions start at foundational difficulty for freshers and intermediate for experienced candidates
- After 2 or more answered questions, difficulty escalates to advanced if the running average score is 75 or above
- Falls back to intermediate if the running score drops below 75

### Answer Evaluation

Each answer is evaluated by Gemini with a structured prompt that includes the role, topic, difficulty, source material, and question. The model returns a JSON object with:
- `score` (0–100)
- `level` (poor / adequate / good / excellent)
- `feedback` (one paragraph)
- `strengths` (list of strings)
- `gaps` (list of strings)

If the API call fails or times out, a heuristic evaluator scores the answer based on length, technical term density, and detection of generic non-answers.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/roles` | List all available roles with required skills |
| `POST` | `/api/resume-preview` | Parse resume, return name/email/phone |
| `POST` | `/api/sessions` | Create a session and return first question |
| `POST` | `/api/sessions/{id}/answer` | Submit answer, receive evaluation and next question |
| `POST` | `/api/sessions/{id}/skip` | Skip current question |
| `GET` | `/api/sessions/{id}/hint` | Request a hint for the current question |
| `GET` | `/api/sessions/{id}/summary` | Get full session summary with insights |
| `GET` | `/api/sessions/{id}/export` | Download PDF report |
| `GET` | `/api/reviewer/sessions` | All sessions (reviewer dashboard data) |

---

## Environment Variables

Create a `.env` file in the project root. See `.env.example` for reference.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `DATABASE_PATH` | No | `storage/app.db` | Path to SQLite database |
| `KNOWLEDGE_BASE_PATH` | No | `Knowledge Base Resources` | Path to knowledge base PDFs |
| `CHUNK_SIZE` | No | `900` | Characters per knowledge chunk |
| `CHUNK_OVERLAP` | No | `160` | Overlap between consecutive chunks |
| `TOP_K` | No | `5` | Number of chunks retrieved per query |

---

## Running Locally

**Requirements:** Python 3.10+

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/ai-interview-platform.git
cd ai-interview-platform

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your Gemini API key
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here

# 5. Start the development server
python -m uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

The reviewer dashboard is available at [http://localhost:8000/reviewer](http://localhost:8000/reviewer).

---

## Deployment

### Render (recommended for free hosting)

1. Push the repository to GitHub
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect your GitHub repository
4. Set the following:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add the environment variable `GEMINI_API_KEY` in the Render dashboard
6. Deploy — your app will be live at `https://your-service-name.onrender.com`

### Railway

1. Sign in to [railway.app](https://railway.app) with GitHub
2. Create a new project and select **Deploy from GitHub repo**
3. Add the `GEMINI_API_KEY` environment variable
4. Railway auto-detects Python and deploys automatically

> Note: The free tier on both platforms uses an ephemeral filesystem. The SQLite database will reset on each deployment or restart. For persistent storage in production, migrate to a hosted PostgreSQL database.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI |
| Server | Uvicorn |
| AI evaluation | Google Gemini 2.5 Flash |
| Knowledge retrieval | TF-IDF (scikit-learn) |
| Resume parsing | PyPDF2 |
| PDF generation | ReportLab |
| Database | SQLite |
| Data validation | Pydantic |
| Frontend | Vanilla HTML, CSS, JavaScript |

---

## Database Schema

**sessions**

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID session identifier |
| `candidate_name` | TEXT | Extracted from resume |
| `role` | TEXT | Selected role ID |
| `resume_text` | TEXT | Raw extracted resume text |
| `resume_profile` | TEXT | JSON: skills, technologies, domains, seniority |
| `contact_email` | TEXT | Candidate email |
| `contact_phone` | TEXT | Candidate phone |
| `status` | TEXT | `active` or `completed` |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

**questions**

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID question identifier |
| `session_id` | TEXT | Foreign key to sessions |
| `question_text` | TEXT | Full question string |
| `topic` | TEXT | Topic category |
| `difficulty` | TEXT | foundational / intermediate / advanced |
| `source_chunks` | TEXT | JSON array of retrieved knowledge chunks |
| `answer_text` | TEXT | Candidate's answer |
| `analysis` | TEXT | JSON: score, level, feedback, strengths, gaps |
| `hint_used` | INTEGER | 1 if hint was requested |
| `skipped` | INTEGER | 1 if question was skipped |
| `time_taken_seconds` | INTEGER | Seconds spent on this question |
| `created_at` | TEXT | ISO timestamp |
| `answered_at` | TEXT | ISO timestamp |
