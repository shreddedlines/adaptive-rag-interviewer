import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const MAX_QUESTIONS = 5;

const stageCopy = {
  "Candidate Entry": "Upload a resume and choose the target role.",
  Interview: "Answer generated questions grounded in role documents.",
  Summary: "Review scoring, traces, and session evidence.",
};

// ── Helpers ────────────────────────────────────────────────────
function wordCount(text) {
  return (text.match(/\b\w+\b/g) || []).length;
}

function qualityFromWords(count) {
  if (count < 20)  return { level: "Too short", cls: "ql-short",  pct: Math.min((count / 20) * 25, 25) };
  if (count < 50)  return { level: "Fair",      cls: "ql-fair",   pct: 25 + ((count - 20) / 30) * 25 };
  if (count < 100) return { level: "Good",      cls: "ql-good",   pct: 50 + ((count - 50) / 50) * 25 };
  return               { level: "Strong",   cls: "ql-strong", pct: Math.min(75 + ((count - 100) / 80) * 25, 100) };
}

// ── Animated counter hook ──────────────────────────────────────
function useAnimatedScore(target) {
  const [displayed, setDisplayed] = useState(0);
  useEffect(() => {
    if (target === null || target === undefined) return;
    setDisplayed(0);
    let current = 0;
    const step = Math.ceil(target / 30);
    const id = setInterval(() => {
      current = Math.min(current + step, target);
      setDisplayed(current);
      if (current >= target) clearInterval(id);
    }, 28);
    return () => clearInterval(id);
  }, [target]);
  return displayed;
}

// ── App root ───────────────────────────────────────────────────
function App() {
  const [roles, setRoles]               = useState([]);
  const [role, setRole]                 = useState("machine-learning");
  const [resume, setResume]             = useState(null);
  const [session, setSession]           = useState(null);
  const [question, setQuestion]         = useState(null);
  const [questionIndex, setQuestionIdx] = useState(0);
  const [answer, setAnswer]             = useState("");
  const [latestAnalysis, setAnalysis]   = useState(null);
  const [summary, setSummary]           = useState(null);
  const [skillGap, setSkillGap]         = useState([]);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState("");
  const [dark, setDark]                 = useState(false);

  // Persist dark mode to <html>
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    fetch("/api/roles")
      .then((r) => r.json())
      .then((data) => { setRoles(data); if (data[0]) setRole(data[0].id); })
      .catch(() => setError("Could not load role configuration."));
  }, []);

  const stage = useMemo(() => {
    if (summary) return "Summary";
    if (session) return "Interview";
    return "Candidate Entry";
  }, [session, summary]);

  async function startInterview(e) {
    e.preventDefault();
    if (!resume) { setError("Upload a resume first."); return; }
    setLoading(true); setError(""); setAnalysis(null);
    const form = new FormData();
    form.append("role", role);
    form.append("resume", resume);
    try {
      const res  = await fetch("/api/sessions", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not start interview.");
      setSession(data);
      setQuestion(data.question);
      setQuestionIdx(1);
      setSkillGap(data.skill_gap || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function submitAnswer(e) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const res  = await fetch(`/api/sessions/${session.session_id}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not submit answer.");
      setAnalysis(data.analysis);
      setAnswer("");
      if (data.complete) {
        const final = await loadSummary(session.session_id);
        setSummary(final);
        setQuestion(null);
      } else {
        setQuestion(data.next_question);
        setQuestionIdx((q) => q + 1);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadSummary(id) {
    const res  = await fetch(`/api/sessions/${id}/summary`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load summary.");
    return data;
  }

  function reset() {
    setSession(null); setQuestion(null); setSummary(null);
    setAnalysis(null); setAnswer(""); setError("");
    setSkillGap([]); setQuestionIdx(0);
  }

  return (
    <div className="app">
      <Sidebar stage={stage} dark={dark} onToggleDark={() => setDark((d) => !d)} />
      <main className="main">
        <div className="topbar">
          <div>
            <span className="eyebrow">{stage} Flow</span>
            <h2>{stage}</h2>
          </div>
          <span className="pill">{roles.length ? `${roles.length} target roles` : "Loading…"}</span>
        </div>
        {error && <p className="error">{error}</p>}

        {!session && !summary && (
          <Setup
            roles={roles}
            role={role}
            setRole={setRole}
            setResume={setResume}
            startInterview={startInterview}
            loading={loading}
          />
        )}

        {session && question && !summary && (
          <Interview
            session={session}
            question={question}
            questionIndex={questionIndex}
            answer={answer}
            setAnswer={setAnswer}
            submitAnswer={submitAnswer}
            loading={loading}
            latestAnalysis={latestAnalysis}
            skillGap={skillGap}
          />
        )}

        {summary && <Summary summary={summary} reset={reset} />}
      </main>
    </div>
  );
}

// ── Sidebar ────────────────────────────────────────────────────
function Sidebar({ stage, dark, onToggleDark }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="eyebrow">PGAGI Interview</span>
        <h1>Candidate Screening</h1>
      </div>
      <div className="stage-list">
        {["Candidate Entry", "Interview", "Summary"].map((item, i) => (
          <div className={`stage ${stage === item ? "active" : ""}`} key={item}>
            <span>{i + 1}</span>
            <strong>{item}</strong>
            <p>{stageCopy[item]}</p>
          </div>
        ))}
      </div>
      <button
        className={`theme-toggle ${dark ? "on" : ""}`}
        onClick={onToggleDark}
        aria-label="Toggle dark mode"
      >
        <span className="toggle-icon">{dark ? "🌙" : "☀️"}</span>
        {dark ? "Dark mode" : "Light mode"}
        <span className="toggle-track"><span className="toggle-thumb" /></span>
      </button>
    </aside>
  );
}

// ── Setup view ─────────────────────────────────────────────────
function Setup({ roles, role, setRole, setResume, startInterview, loading }) {
  const selectedRole = roles.find((r) => r.id === role);
  return (
    <div className="workspace setup-workspace">
      <section className="panel form-panel">
        <div className="panel-head">
          <span className="eyebrow">Candidate Entry</span>
          <h3>Start a role-based interview</h3>
        </div>
        <form className="form" onSubmit={startInterview}>
          <label>
            Target role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </label>
          <label>
            Resume (PDF, TXT, or MD)
            <input
              type="file"
              accept="application/pdf,text/plain,text/markdown,.pdf,.txt,.md"
              onChange={(e) => setResume(e.target.files[0])}
            />
          </label>
          <button className="primary" disabled={loading}>
            {loading ? "Preparing interview…" : "Start Interview"}
          </button>
        </form>
        {selectedRole && (
          <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
            <p style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>{selectedRole.description}</p>
            <div className="chips" style={{ marginTop: 10 }}>
              {(selectedRole.required_skills || []).slice(0, 6).map((s) => (
                <span className="tag" key={s}>{s}</span>
              ))}
            </div>
          </div>
        )}
      </section>
      <aside className="panel roles-panel">
        <div className="panel-head">
          <span className="eyebrow">Target Roles</span>
          <h3>Available tracks</h3>
        </div>
        <div className="role-grid">
          {roles.map((r) => (
            <div
              className={`card role-card ${r.id === role ? "selected" : ""}`}
              key={r.id}
              onClick={() => setRole(r.id)}
              style={{ cursor: "pointer" }}
            >
              <strong>{r.name}</strong>
              <p>{r.description}</p>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

// ── Progress bar ───────────────────────────────────────────────
function ProgressBar({ index }) {
  const pct = Math.round((index / MAX_QUESTIONS) * 100);
  return (
    <div style={{ marginBottom: 20 }}>
      <div className="progress-label">
        <span>Question {index} of {MAX_QUESTIONS}</span>
        <span>{pct}% complete</span>
      </div>
      <div className="progress-bar-wrap">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Live quality bar ───────────────────────────────────────────
function QualityBar({ text }) {
  const wc = wordCount(text);
  const q  = qualityFromWords(wc);
  return (
    <div className="answer-meta">
      <span className="word-count">{wc} words</span>
      <div className="quality-wrap">
        <div className={`quality-label ${q.cls}`}>{q.level}</div>
        <div className="quality-track">
          <div className={`quality-fill ${q.cls}`} style={{ width: `${q.pct}%` }} />
        </div>
      </div>
    </div>
  );
}

// ── Animated score reveal ──────────────────────────────────────
function ScoreReveal({ analysis }) {
  const displayed = useAnimatedScore(analysis?.score ?? null);
  if (!analysis) return null;
  const colorMap = {
    strong: "score-strong",
    adequate: "score-adequate",
    developing: "score-developing",
    thin: "score-thin",
    "off-topic": "score-off-topic",
  };
  const cls = colorMap[analysis.level] || "score-adequate";
  return (
    <div className="score-reveal">
      <div className={`score-number ${cls}`}>{displayed}</div>
      <div className="score-detail">
        <span className="score-level">{analysis.level}</span>
        <p className="score-feedback">{analysis.feedback}</p>
        {analysis.grounding_terms?.length > 0 && (
          <div className="chips" style={{ marginTop: 8 }}>
            {analysis.grounding_terms.map((t) => (
              <span className="tag" key={t}>{t}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Skill gap panel ────────────────────────────────────────────
function SkillGap({ skillGap }) {
  if (!skillGap || skillGap.length === 0) return null;
  const matched = skillGap.filter((s) => s.status === "match").length;
  const partial = skillGap.filter((s) => s.status === "partial").length;
  const total   = skillGap.length;
  const pct     = Math.round((matched / total) * 100);
  return (
    <div className="skill-gap-section">
      <hr className="divider" />
      <h4>Role Skill Match — {pct}% aligned</h4>
      <div className="skill-gap-grid">
        {skillGap.map((item) => {
          const fillPct = item.status === "match" ? 100 : item.status === "partial" ? 55 : 15;
          return (
            <div className="skill-row" key={item.skill}>
              <span className="skill-name">{item.skill}</span>
              <div className="skill-bar-track">
                <div className={`skill-bar-fill ${item.status}`} style={{ width: `${fillPct}%` }} />
              </div>
              <span className={`skill-status ${item.status}`}>
                {item.status === "match" ? "✓" : item.status === "partial" ? "~" : "✗"}
              </span>
            </div>
          );
        })}
      </div>
      <div className="gap-legend">
        <span className="gap-legend-item"><span className="legend-dot match" />Match ({matched})</span>
        <span className="gap-legend-item"><span className="legend-dot partial" />Partial ({partial})</span>
        <span className="gap-legend-item"><span className="legend-dot gap" />Gap ({total - matched - partial})</span>
      </div>
    </div>
  );
}

// ── Interview view ─────────────────────────────────────────────
function Interview({ session, question, questionIndex, answer, setAnswer, submitAnswer, loading, latestAnalysis, skillGap }) {
  return (
    <div className="workspace">
      <section className="panel question">
        <ProgressBar index={questionIndex} />
        <div className="meta-row">
          <span className="tag">{question.topic}</span>
          <span className="tag blue">{question.difficulty}</span>
        </div>
        <p className="question-text">{question.text}</p>
        <form className="form" onSubmit={submitAnswer}>
          <label>
            Your answer
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer here…"
            />
          </label>
          <QualityBar text={answer} />
          <div className="actions">
            <button className="primary" disabled={loading}>
              {loading ? "Evaluating…" : "Submit Answer"}
            </button>
          </div>
        </form>
        <ScoreReveal analysis={latestAnalysis} />
      </section>

      <aside className="panel">
        <h4>Resume Profile</h4>
        <div className="chips">
          <span className="tag warn">{session.profile.seniority_signal}</span>
          {session.profile.skills.slice(0, 8).map((s) => (
            <span className="tag" key={s}>{s}</span>
          ))}
        </div>

        <SkillGap skillGap={skillGap} />
      </aside>
    </div>
  );
}

// ── Summary view ───────────────────────────────────────────────
function Summary({ summary, reset }) {
  const avg        = summary.insights.average_score ?? 0;
  const displayed  = useAnimatedScore(Math.round(parseFloat(avg)));
  const colorClass = avg >= 75 ? "score-strong" : avg >= 60 ? "score-adequate" : "score-developing";

  return (
    <section className="panel">
      <div className="topbar">
        <div>
          <h3>Interview Summary</h3>
          <p className="muted">{summary.candidate_name || "Candidate"} — {summary.role}</p>
        </div>
        <button className="secondary" onClick={reset}>New Interview</button>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <b className={colorClass}>{displayed}</b>
          <span className="muted">Average score</span>
        </div>
        <div className="metric">
          <b>{summary.insights.questions_answered}</b>
          <span className="muted">Questions answered</span>
        </div>
        <div className="metric">
          <b>{summary.status}</b>
          <span className="muted">Session status</span>
        </div>
      </div>

      <p><strong>Recommendation:</strong> {summary.insights.recommendation}</p>
      <div className="chips">
        {summary.insights.strong_terms.map((t) => (
          <span className="tag" key={t}>{t}</span>
        ))}
      </div>

      <div className="summary-list" style={{ marginTop: 22 }}>
        {summary.questions.map((item, i) => (
          <article className="card qa" key={item.id}>
            <span className="tag blue">Q{i + 1}: {item.topic}</span>
            <p><strong>{item.question}</strong></p>
            <p className="muted">{item.answer || "No answer recorded."}</p>
            {item.analysis?.score !== undefined && (
              <p>Score: <strong>{item.analysis.score}/100</strong> — {item.analysis.feedback}</p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")).render(<App />);
