/* ═══════════════════════════════════════════════════════════════════
   PGAGI Candidate Screening — All Features
   1. 🖼 Animated landing/hero screen
   2. ⏱ Per-question countdown timer (SVG ring)
   3. 💡 Hint system with score penalty (cap 60)
   4. ⏭ Skip question (score = 0)
   5. 📊 Radar/spider chart in summary
   6. 🎤 Voice input (Web Speech API)
   7. 🧠 Adaptive difficulty (3 tiers)
═══════════════════════════════════════════════════════════════════ */

const MAX_QUESTIONS = 5;
const TIMER_SECONDS = 120;
const CIRC = 2 * Math.PI * 40; // SVG ring circumference

/* ── State ─────────────────────────────────────────────────────── */
const state = {
  roles: [], role: "machine-learning",
  resume: null, session: null, question: null,
  questionIndex: 0, answer: "", latestAnalysis: null,
  summary: null, skillGap: [],
  loading: false, error: "",
  dark: false,
  // Timer
  timerSeconds: TIMER_SECONDS, timerInterval: null, timeTaken: 0,
  // Hint
  hintText: null, hintLoading: false,
  // Voice
  recognition: null, listening: false,
};

const stageCopy = {
  "Candidate Entry": "Upload resume & choose target role.",
  "Interview":       "Answer generated questions grounded in role documents.",
  "Summary":         "Review scoring, radar chart & session insights.",
};

/* ── Utils ─────────────────────────────────────────────────────── */
function esc(v){ return String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;"); }
function stage(){ return state.summary ? "Summary" : state.session ? "Interview" : "Candidate Entry"; }
function setState(p){ Object.assign(state,p); render(); }
function wordCount(t){ return (t.match(/\b\w+\b/g)||[]).length; }
function formatTime(s){ const m=Math.floor(s/60); return `${m}:${String(s%60).padStart(2,"0")}`; }

function qualityFromWords(n){
  if(n<20)  return {level:"Too short", cls:"ql-short",  pct:Math.min(n/20*25,25)};
  if(n<50)  return {level:"Fair",      cls:"ql-fair",   pct:25+(n-20)/30*25};
  if(n<100) return {level:"Good",      cls:"ql-good",   pct:50+(n-50)/50*25};
  return           {level:"Strong",    cls:"ql-strong", pct:Math.min(75+(n-100)/80*25,100)};
}

/* ── Theme ─────────────────────────────────────────────────────── */
function applyTheme(dark){
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}
function toggleDark(){ const d=!state.dark; applyTheme(d); setState({dark:d}); }

/* ══════════════════════════════════════════════════════════════════
   TIMER
══════════════════════════════════════════════════════════════════ */
function startTimer(){
  clearTimer();
  state.timerSeconds = TIMER_SECONDS;
  state.timeTaken    = 0;
  state.timerInterval = setInterval(()=>{
    state.timerSeconds = Math.max(0, state.timerSeconds - 1);
    state.timeTaken++;
    updateTimerDOM();
    if(state.timerSeconds <= 0){ clearTimer(); autoTimeoutSubmit(); }
  }, 1000);
}

function clearTimer(){
  if(state.timerInterval){ clearInterval(state.timerInterval); state.timerInterval=null; }
}

function updateTimerDOM(){
  const fill  = document.getElementById("timer-ring-fill");
  const value = document.getElementById("timer-value");
  if(!fill||!value) return;
  const pct = state.timerSeconds / TIMER_SECONDS;
  fill.style.strokeDashoffset = CIRC * (1 - pct);
  const cls = state.timerSeconds<=30 ? "timer-red" : state.timerSeconds<=60 ? "timer-yellow" : "timer-green";
  value.className = `timer-value ${cls}`;
  value.textContent = formatTime(state.timerSeconds);
  if(state.timerSeconds<=30){
    fill.style.stroke = "var(--rose)";
  } else if(state.timerSeconds<=60){
    fill.style.stroke = "var(--warning)";
  } else {
    fill.style.stroke = "var(--green)";
  }
}

async function autoTimeoutSubmit(){
  if(!state.answer.trim()){ await doSkip(); }
  else { await doSubmit(); }
}

/* ══════════════════════════════════════════════════════════════════
   VOICE INPUT
══════════════════════════════════════════════════════════════════ */
function toggleVoice(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    const btn = document.getElementById("mic-btn");
    if(btn){ btn.title="Voice input requires Chrome or Edge"; }
    return;
  }
  if(state.listening){
    state.recognition?.stop();
    state.recognition = null;
    state.listening = false;
    updateMicButton();
    return;
  }
  const rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";

  rec.onresult = (e)=>{
    let transcript = "";
    for(let i=0;i<e.results.length;i++){
      transcript += e.results[i][0].transcript;
    }
    state.answer = transcript;
    const ta = document.getElementById("answer-input");
    if(ta){
      ta.value = transcript;
      liveUpdateQuality();
    }
  };

  rec.onerror = (e)=>{
    console.warn("Speech error:", e.error);
    state.listening = false;
    state.recognition = null;
    updateMicButton();
  };

  rec.onend = ()=>{
    // Web Speech API stops after each pause — restart if user hasn't clicked Stop
    if(state.listening){
      try { rec.start(); }
      catch(e){
        state.listening = false;
        state.recognition = null;
        updateMicButton();
      }
    }
  };

  state.recognition = rec;
  state.listening = true;
  rec.start();
  updateMicButton();
}

function updateMicButton(){
  const btn = document.getElementById("mic-btn");
  if(!btn) return;
  btn.className = `voice-btn ${state.listening ? "voice-active" : ""}`;
  btn.innerHTML = state.listening
    ? `<span class="voice-dot"></span> Stop`
    : `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0">
        <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
        <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
      </svg> Voice`;
}

/* ══════════════════════════════════════════════════════════════════
   LIVE QUALITY BAR (DOM patch — no full re-render)
══════════════════════════════════════════════════════════════════ */
function liveUpdateQuality(){
  const wc = wordCount(state.answer);
  const meta = document.querySelector(".answer-meta");
  if(wc === 0){
    if(meta) meta.style.display = "none";
    return;
  }
  const q = qualityFromWords(wc);
  if(!meta){
    // Re-render to insert the bar for the first time
    const form = document.getElementById("answer-form");
    if(form){
      const existing = form.querySelector(".answer-meta");
      if(!existing){
        const div = document.createElement("div");
        div.innerHTML = qualityBarTemplate();
        const textarea = form.querySelector("textarea");
        if(textarea && textarea.parentNode){
          textarea.parentNode.insertBefore(div.firstElementChild, textarea.nextSibling);
        }
      }
    }
    return;
  }
  meta.style.display = "";
  const wordEl  = meta.querySelector(".word-count");
  const labelEl = meta.querySelector(".quality-label");
  const fillEl  = meta.querySelector(".quality-fill");
  if(wordEl)  wordEl.textContent  = `${wc} words`;
  if(labelEl){ labelEl.className = `quality-label ${q.cls}`; labelEl.textContent = q.level; }
  if(fillEl){  fillEl.className  = `quality-fill ${q.cls}`;  fillEl.style.width  = `${q.pct}%`; }
}

/* ══════════════════════════════════════════════════════════════════
   SCORE ANIMATION
══════════════════════════════════════════════════════════════════ */
function animateScore(target, elId, cls){
  const el = document.getElementById(elId);
  if(!el) return;
  el.className = `score-number ${cls}`;
  let cur = 0;
  const step = Math.max(1, Math.ceil(target/30));
  const iv = setInterval(()=>{
    cur = Math.min(cur+step, target);
    el.textContent = cur;
    if(cur>=target) clearInterval(iv);
  }, 28);
}

const scoreCls = {
  strong:"score-strong", adequate:"score-adequate",
  developing:"score-developing", thin:"score-thin",
  "off-topic":"score-off-topic", skipped:"score-skipped",
};

/* ══════════════════════════════════════════════════════════════════
   RADAR CHART
══════════════════════════════════════════════════════════════════ */
function drawRadarChart(){
  const canvas = document.getElementById("radar-canvas");
  if(!canvas || !state.summary) return;
  const ctx = canvas.getContext("2d");
  const W   = canvas.width, H = canvas.height;
  const cx  = W/2, cy = H/2;
  const R   = Math.min(cx,cy) - 44;
  // Axis set depends on which evaluator produced the scores.
  // Gemini returns real per-dimension judgements; the heuristic returns its own
  // five surface-feature components. Detect from the first scored question.
  const GEMINI_KEYS = ["correctness","relevance","completeness","reasoning","grounding"];
  const GEMINI_AXES = ["Correctness","Relevance","Completeness","Reasoning","Grounding"];
  const HEUR_KEYS   = ["relevance","technical","grounding","specificity","length"];
  const HEUR_AXES   = ["Relevance","Technical","Grounding","Specificity","Length"];

  const scored = state.summary.questions.filter(q => !q.skipped && q.analysis?.component_scores);
  const isGeminiRadar = scored.some(q => q.analysis.evaluator === "gemini"
                                      && "correctness" in q.analysis.component_scores);
  const keys = isGeminiRadar ? GEMINI_KEYS : HEUR_KEYS;
  const axes = isGeminiRadar ? GEMINI_AXES : HEUR_AXES;
  const n    = keys.length;
  const step = (2*Math.PI)/n;

  // Average component scores across all non-skipped questions
  const totals = {};
  keys.forEach(k => totals[k] = 0);
  let count = 0;
  for(const q of scored){
    const cs = q.analysis.component_scores;
    keys.forEach(k=>{ totals[k]+=(cs[k]||0); });
    count++;
  }
  const vals = keys.map(k=> count ? Math.round(totals[k]/count) : 0);

  ctx.clearRect(0,0,W,H);
  const isDark = state.dark;
  const gridC  = isDark ? "rgba(255,255,255,.1)" : "rgba(0,0,0,.1)";
  const labelC = isDark ? "#8b949e" : "#667085";
  const accentC= isDark ? "#2dd4bf" : "#0f766e";
  const fillC  = isDark ? "rgba(45,212,191,.18)" : "rgba(15,118,110,.18)";

  // Grid rings
  for(let ring=5;ring>=1;ring--){
    ctx.beginPath();
    for(let i=0;i<n;i++){
      const a=i*step-Math.PI/2, r=ring/5*R;
      const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a);
      i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.strokeStyle=gridC; ctx.lineWidth=1; ctx.stroke();
    if(ring%2===0){ ctx.fillStyle=isDark?"rgba(255,255,255,.02)":"rgba(0,0,0,.02)"; ctx.fill(); }
  }
  // Axes
  for(let i=0;i<n;i++){
    const a=i*step-Math.PI/2;
    ctx.beginPath();
    ctx.moveTo(cx,cy);
    ctx.lineTo(cx+R*Math.cos(a), cy+R*Math.sin(a));
    ctx.strokeStyle=gridC; ctx.lineWidth=1; ctx.stroke();
  }
  // Data polygon
  ctx.beginPath();
  for(let i=0;i<n;i++){
    const a=i*step-Math.PI/2, r=vals[i]/100*R;
    const x=cx+r*Math.cos(a), y=cy+r*Math.sin(a);
    i===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
  }
  ctx.closePath();
  ctx.fillStyle=fillC; ctx.fill();
  ctx.strokeStyle=accentC; ctx.lineWidth=2.5; ctx.stroke();
  // Dots
  for(let i=0;i<n;i++){
    const a=i*step-Math.PI/2, r=vals[i]/100*R;
    ctx.beginPath();
    ctx.arc(cx+r*Math.cos(a), cy+r*Math.sin(a), 4,0,2*Math.PI);
    ctx.fillStyle=accentC; ctx.fill();
  }
  // Labels
  for(let i=0;i<n;i++){
    const a=i*step-Math.PI/2, lR=R+24;
    const x=cx+lR*Math.cos(a), y=cy+lR*Math.sin(a);
    ctx.fillStyle=labelC; ctx.font="11px Inter,sans-serif"; ctx.textAlign="center";
    ctx.fillText(axes[i], x, y+4);
    ctx.fillStyle=accentC; ctx.font="bold 10px Inter,sans-serif";
    ctx.fillText(`${vals[i]}%`, x, y+17);
  }
}

/* ══════════════════════════════════════════════════════════════════
   API
══════════════════════════════════════════════════════════════════ */
async function loadRoles(){
  try{
    const res = await fetch("/api/roles");
    const roles = await res.json();
    setState({roles, role: roles[0]?.id || "machine-learning"});
  } catch { setState({error:"Could not load roles."}); }
}

async function startInterview(e){
  e.preventDefault();

  // ── Validation ──────────────────────────────────────────────
  if(!state.resume){
    setState({error:"Please upload your resume before starting."});
    return;
  }
  if(state.resumeError){
    setState({error: state.resumeError});
    document.getElementById("resume-error-banner")?.scrollIntoView({behavior:"smooth"});
    return;
  }
  const nameEl  = document.getElementById("contact-name");
  const emailEl = document.getElementById("contact-email");
  const phoneEl = document.getElementById("contact-phone");

  if(!nameEl?.value.trim()){
    nameEl?.classList.add("field-error", "shake");
    setTimeout(()=>nameEl?.classList.remove("shake"), 500);
    setState({error:"Full name is required."});
    nameEl?.focus();
    return;
  }
  nameEl?.classList.remove("field-error");

  if(!emailEl?.value.trim()){
    emailEl?.classList.add("field-error", "shake");
    setTimeout(()=>emailEl?.classList.remove("shake"), 500);
    setState({error:"Email address is required."});
    emailEl?.focus();
    return;
  }
  emailEl?.classList.remove("field-error");

  if(!phoneEl?.value.trim()){
    phoneEl?.classList.add("field-error", "shake");
    setTimeout(()=>phoneEl?.classList.remove("shake"), 500);
    setState({error:"Phone number is required."});
    phoneEl?.focus();
    return;
  }
  phoneEl?.classList.remove("field-error");

  setState({loading:true, error:"", latestAnalysis:null, hintText:null});
  const form = new FormData();
  form.append("role", state.role);
  form.append("resume", state.resume);
  form.append("candidate_name", nameEl.value.trim());
  if(emailEl?.value.trim()) form.append("contact_email", emailEl.value.trim());
  if(phoneEl?.value.trim()) form.append("contact_phone", phoneEl.value.trim());
  try{
    const res  = await fetch("/api/sessions",{method:"POST",body:form});
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail||"Could not start interview.");
    setState({session:data, question:data.question, questionIndex:1,
              skillGap:data.skill_gap||[], loading:false, hintText:null});
  } catch(err){ setState({error:err.message, loading:false}); }
}


async function autoFillFromResume(file){
  if(!file) return;

  // Clear any previous resume error
  state.resumeError = null;
  const errBanner = document.getElementById("resume-error-banner");
  if(errBanner) errBanner.style.display = "none";

  // Show scanning indicator
  const scanMsg = document.getElementById("resume-scan-msg");
  if(scanMsg){ scanMsg.textContent = "Scanning resume…"; scanMsg.style.display = "block"; }

  const fd = new FormData();
  fd.append("resume", file);
  try{
    const res  = await fetch("/api/resume-preview", {method:"POST", body:fd});
    if(scanMsg) scanMsg.style.display = "none";
    if(!res.ok){
      state.resumeError = "Could not read the resume file.";
      showResumeError(state.resumeError);
      return;
    }
    const data = await res.json();

    // Backend returned a validation error
    if(data.error){
      state.resumeError = data.error;
      state.resume = null; // reject the file
      showResumeError(data.error);
      // Reset the file input so user must pick again
      const fi = document.getElementById("resume-input");
      if(fi) fi.value = "";
      return;
    }

    // Valid resume — autofill detected fields
    const setField = (id, val, badgeId) => {
      const el    = document.getElementById(id);
      const badge = document.getElementById(badgeId);
      if(el && val){
        el.value = val;
        el.classList.add("autofilled");
        if(badge) badge.style.display = "inline-block";
      }
    };
    setField("contact-name",  data.name,  "name-badge");
    setField("contact-email", data.email, "email-badge");
    setField("contact-phone", data.phone, "phone-badge");
  } catch(_){
    if(scanMsg) scanMsg.style.display = "none";
    state.resumeError = "Could not read this file. Please upload a valid resume PDF.";
    showResumeError(state.resumeError);
  }
}

function showResumeError(msg){
  // Remove any old banner
  document.getElementById("resume-error-banner")?.remove();

  const banner = document.createElement("div");
  banner.id = "resume-error-banner";
  banner.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
    </svg>
    <span>${msg}</span>`;
  Object.assign(banner.style, {
    display:"flex", alignItems:"center", gap:"10px",
    background:"#fef2f2", color:"#b91c1c",
    border:"1.5px solid #fecaca", borderRadius:"10px",
    padding:"11px 16px", fontSize:"13px", fontWeight:"600",
    marginTop:"10px", lineHeight:"1.4",
  });

  // Try to insert it right after the file input label or upload zone
  const target =
    document.querySelector(".upload-zone") ||
    document.querySelector("label[for='resume-input']") ||
    document.querySelector(".setup-form") ||
    document.querySelector(".panel");
  if(target){
    target.insertAdjacentElement("afterend", banner);
    banner.scrollIntoView({behavior:"smooth", block:"nearest"});
  }
}



async function fetchHint(){
  if(state.hintLoading || state.hintText) return;
  setState({hintLoading:true});
  try{
    const res  = await fetch(`/api/sessions/${state.session.session_id}/hint`);
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail||"Could not load hint.");
    setState({hintText:data.hint, hintLoading:false});
  } catch(err){ setState({error:err.message, hintLoading:false}); }
}

async function doSkip(){
  setState({loading:true, error:"", hintText:null});
  clearTimer();
  try{
    const res  = await fetch(`/api/sessions/${state.session.session_id}/skip`,{method:"POST"});
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail||"Could not skip.");
    if(data.complete){
      const summary = await fetchSummary(state.session.session_id);
      setState({latestAnalysis:null, answer:"", question:null, summary, loading:false, submittedToast:false});
    } else {
      setState({latestAnalysis:null, answer:"", question:data.next_question,
                questionIndex:state.questionIndex+1, loading:false, hintText:null, submittedToast:false});
    }
  } catch(err){ setState({error:err.message, loading:false}); }
}

async function doSubmit(){
  const trimmed = state.answer.trim();
  if(trimmed.length < 10){ setState({error:"Answer is too short (min 10 chars)."}); return; }
  clearTimer();
  setState({loading:true, error:"", submittedToast:false});
  try{
    const res  = await fetch(`/api/sessions/${state.session.session_id}/answer`,{
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({answer:trimmed, time_taken_seconds: state.timeTaken}),
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail||"Could not submit.");
    if(data.complete){
      const summary = await fetchSummary(state.session.session_id);
      setState({latestAnalysis:null, answer:"", question:null, summary, loading:false, submittedToast:false});
    } else {
      // Show brief toast then clear it — score stays hidden until summary
      setState({latestAnalysis:null, answer:"", question:data.next_question,
                questionIndex:state.questionIndex+1, loading:false, hintText:null, submittedToast:true});
      setTimeout(()=>{ setState({submittedToast:false}); }, 2000);
    }
  } catch(err){ setState({error:err.message, loading:false}); }
}

async function fetchSummary(sid){
  const res  = await fetch(`/api/sessions/${sid}/summary`);
  const data = await res.json();
  if(!res.ok) throw new Error(data.detail||"Could not load summary.");
  return data;
}

function resetInterview(){
  clearTimer();
  if(state.recognition) state.recognition.stop();
  setState({session:null,question:null,summary:null,latestAnalysis:null,
            answer:"",error:"",skillGap:[],questionIndex:0,
            hintText:null,listening:false,recognition:null,
            timerSeconds:TIMER_SECONDS, timeTaken:0});
}

/* ══════════════════════════════════════════════════════════════════
   TEMPLATES
══════════════════════════════════════════════════════════════════ */
function landingTemplate(){
  const roleCount = state.roles.length || 7;
  return `
    <div class="landing-overlay" id="landing-overlay">
      <div class="orb" style="width:500px;height:500px;top:-150px;left:-150px;background:#0f766e;animation-delay:0s;"></div>
      <div class="orb" style="width:400px;height:400px;bottom:-80px;right:-80px;background:#2457c5;animation-delay:3s;"></div>
      <div class="orb" style="width:250px;height:250px;top:40%;left:55%;background:#7c3aed;animation-delay:5.5s;"></div>

      <div class="landing-inner">
        <div class="landing-badge">✦ AI-Powered Interview Platform</div>
        <h1 class="landing-title">
          Technical<br><span>Screening</span>
        </h1>
        <p class="landing-desc">
          Role-aware interviews grounded in real knowledge documents.<br>
          Upload your resume and prove your depth.
        </p>
        <div class="landing-stats">
          <div class="landing-stat"><b>${roleCount}</b><span>Target Roles</span></div>
          <div class="landing-stat"><b>RAG</b><span>Knowledge Base</span></div>
          <div class="landing-stat"><b>3-Tier</b><span>Adaptive Difficulty</span></div>
          <div class="landing-stat"><b>AI</b><span>Score Analysis</span></div>
        </div>
        <button class="landing-cta" id="landing-begin-btn">
          Begin Interview <span class="cta-arrow">→</span>
        </button>
      </div>
    </div>
  `;
}

function sidebarTemplate(cur){
  return `
    <aside class="sidebar">
      <div class="brand">
        <h1>Candidate Screening</h1>
      </div>
      <div class="stage-list">
        ${["Candidate Entry","Interview","Summary"].map((s,i)=>`
          <div class="stage ${cur===s?"active":""}">
            <span>${i+1}</span>
            <strong>${s}</strong>
            <p>${stageCopy[s]}</p>
          </div>
        `).join("")}
      </div>
      <button id="theme-toggle-btn" class="theme-toggle ${state.dark?"on":""}">
        ${state.dark
          ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`
          : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
        }
        ${state.dark?"Dark":"Light"}
        <span class="toggle-track"><span class="toggle-thumb"></span></span>
      </button>
    </aside>
  `;
}

function progressTemplate(){
  const pct = Math.round((state.questionIndex/MAX_QUESTIONS)*100);
  return `
    <div style="margin-bottom:16px;">
      <div class="progress-label">
        <span>Question ${state.questionIndex} of ${MAX_QUESTIONS}</span>
        <span>${pct}% complete</span>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-bar-fill" style="width:${pct}%"></div>
      </div>
    </div>
  `;
}

function timerTemplate(){
  const pct = state.timerSeconds / TIMER_SECONDS;
  const off  = CIRC * (1 - pct);
  const cls  = state.timerSeconds<=30 ? "timer-red" : state.timerSeconds<=60 ? "timer-yellow" : "timer-green";
  const col  = state.timerSeconds<=30 ? "var(--rose)" : state.timerSeconds<=60 ? "var(--warning)" : "var(--green)";
  return `
    <div class="timer-wrap">
      <svg class="timer-svg" width="90" height="90" viewBox="0 0 90 90">
        <circle class="timer-track" cx="45" cy="45" r="40"/>
        <circle id="timer-ring-fill" class="timer-fill" cx="45" cy="45" r="40"
          style="stroke-dashoffset:${off};stroke:${col}"/>
      </svg>
      <span id="timer-value" class="timer-value ${cls}">${formatTime(state.timerSeconds)}</span>
      <span class="timer-label">TIME LEFT</span>
    </div>
  `;
}

function qualityBarTemplate(){
  const wc=wordCount(state.answer);
  if(wc===0) return ``;
  const q=qualityFromWords(wc);
  return `
    <div class="answer-meta">
      <span class="word-count">${wc} words</span>
      <div class="quality-wrap">
        <div class="quality-label ${q.cls}">${q.level}</div>
        <div class="quality-track">
          <div class="quality-fill ${q.cls}" style="width:${q.pct}%"></div>
        </div>
      </div>
    </div>
  `;
}

function scoreRevealTemplate(a){
  if(!a) return "";
  const cls = scoreCls[a.level] || "score-adequate";
  const isGemini = a.evaluator === "gemini";

  const strengthsHtml = isGemini && a.strengths?.length
    ? `<div style="margin-top:10px;">
        <div style="font-size:11px;font-weight:800;color:var(--green);letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px;">✓ Strengths</div>
        <div class="chips">${a.strengths.map(s=>`<span class="tag green">${esc(s)}</span>`).join("")}</div>
       </div>` : "";

  const gapsHtml = isGemini && a.gaps?.length
    ? `<div style="margin-top:8px;">
        <div style="font-size:11px;font-weight:800;color:var(--rose);letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px;">✗ Gaps</div>
        <div class="chips">${a.gaps.map(g=>`<span class="tag rose">${esc(g)}</span>`).join("")}</div>
       </div>` : "";

  const groundingHtml = !isGemini && a.grounding_terms?.length
    ? `<div class="chips" style="margin-top:8px;">${a.grounding_terms.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>` : "";

  return `
    <div class="score-reveal" id="score-reveal-block">
      <div class="score-number ${cls}" id="score-counter">0</div>
      <div class="score-detail">
        <span class="score-level">${esc(a.level)}${isGemini ? ' <span style="font-size:10px;opacity:.6;">· Gemini</span>' : ''}</span>
        <p class="score-feedback">${esc(a.feedback)}</p>
        ${strengthsHtml}${gapsHtml}${groundingHtml}
      </div>
    </div>
  `;
}

function hintPanelTemplate(){
  if(!state.hintText) return "";
  return `
    <div class="hint-panel">
      <div class="hint-title">💡 Hint</div>
      <p class="hint-text">${esc(state.hintText)}</p>
      <p class="hint-penalty">⚠ Score capped at 60 for this question</p>
    </div>
  `;
}

function skillGapTemplate(){
  if(!state.skillGap?.length) return "";
  const matched = state.skillGap.filter(s=>s.status==="match").length;
  const partial = state.skillGap.filter(s=>s.status==="partial").length;
  const total   = state.skillGap.length;
  const pct     = Math.round(matched/total*100);
  return `
    <div class="skill-gap-section">
      <hr class="divider">
      <h4>Role Skill Match — ${pct}% aligned</h4>
      <div class="skill-gap-grid">
        ${state.skillGap.map(item=>{
          const fp = item.status==="match" ? 100 : item.status==="partial" ? 55 : 15;
          return `<div class="skill-row">
            <span class="skill-name">${esc(item.skill)}</span>
            <div class="skill-bar-track"><div class="skill-bar-fill ${item.status}" style="width:${fp}%"></div></div>
            <span class="skill-status ${item.status}">${item.status==="match"?"✓":item.status==="partial"?"~":"✗"}</span>
          </div>`;
        }).join("")}
      </div>
      <div class="gap-legend">
        <span class="gap-legend-item"><span class="legend-dot match"></span>Match (${matched})</span>
        <span class="gap-legend-item"><span class="legend-dot partial"></span>Partial (${partial})</span>
        <span class="gap-legend-item"><span class="legend-dot gap"></span>Gap (${total-matched-partial})</span>
      </div>
    </div>
  `;
}

function setupTemplate(){
  const sel = state.roles.find(r=>r.id===state.role);
  return `
    <div class="workspace">
      <section class="panel form-panel">
        <div class="panel-head">
          <span class="eyebrow">Candidate Entry</span>
          <h3>Start role-based interview</h3>
        </div>
        <form class="form" id="start-form">

          <!-- Role + Resume -->
          <label>Target role
            <select id="role-select">
              ${state.roles.map(r=>`<option value="${esc(r.id)}" ${r.id===state.role?"selected":""}>${esc(r.name)}</option>`).join("")}
            </select>
          </label>
          <label>Resume <span class="field-hint">PDF, TXT or MD</span>
            <input id="resume-input" type="file" accept="application/pdf,text/plain,text/markdown,.pdf,.txt,.md"/>
          </label>

          <!-- Candidate info — always visible but populated after resume upload -->
          <div class="candidate-info-block">
            <div class="section-divider">
              <span>Candidate information</span>
            </div>

            <label>Full name
              <div class="autofill-wrap">
                <input id="contact-name" type="text" placeholder="e.g. John Smith" autocomplete="name" required/>
                <span class="autofill-badge" id="name-badge" style="display:none">Detected</span>
              </div>
            </label>

            <label>Email address
              <div class="autofill-wrap">
                <input id="contact-email" type="email" placeholder="e.g. john@example.com" autocomplete="email" required/>
                <span class="autofill-badge" id="email-badge" style="display:none">Detected</span>
              </div>
            </label>

            <label>Phone number
              <div class="autofill-wrap">
                <input id="contact-phone" type="tel" placeholder="e.g. +91 98765 43210" autocomplete="tel" required/>
                <span class="autofill-badge" id="phone-badge" style="display:none">Detected</span>
              </div>
            </label>
          </div>

          <button class="primary" id="start-btn" ${state.loading?"disabled":""}>
            ${state.loading?"Preparing…":"Start Interview"}
          </button>
        </form>


        ${sel?`
          <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--line);">
            <p style="font-size:13px;color:var(--muted);margin:0 0 10px;">${esc(sel.description)}</p>
            <div class="chips">${(sel.required_skills||[]).slice(0,6).map(s=>`<span class="tag">${esc(s)}</span>`).join("")}</div>
          </div>`:""
        }
      </section>
      <aside class="panel">
        <div class="panel-head"><span class="eyebrow">Available Tracks</span><h3>Target Roles</h3></div>
        <div class="role-grid">
          ${state.roles.map(r=>`
            <div class="card role-card ${r.id===state.role?"selected":""}" data-role="${esc(r.id)}">
              <strong>${esc(r.name)}</strong>
              <p>${esc(r.description)}</p>
            </div>
          `).join("")}
        </div>
      </aside>
    </div>
  `;
}

function interviewTemplate(){
  const q = state.question;
  const p = state.session.profile;
  const diffTag = q.difficulty==="advanced"
    ? `<span class="tag adv">⚡ ${esc(q.difficulty)}</span>`
    : `<span class="tag blue">${esc(q.difficulty)}</span>`;
  return `
    <div class="workspace">
      <section class="panel question">
        ${progressTemplate()}
        <div class="meta-row" style="margin-bottom:8px;">
          <span class="tag">${esc(q.topic)}</span>
          ${diffTag}
        </div>
        <p class="question-text">${esc(q.text)}</p>
        <form class="form" id="answer-form">
          <label>Your answer
            <textarea id="answer-input" placeholder="Speak or type your answer…">${esc(state.answer)}</textarea>
          </label>
          ${qualityBarTemplate()}
          <div class="actions">
            <button class="primary" type="submit" ${state.loading?"disabled":""}>
              ${state.loading?"Evaluating…":"Submit Answer"}
            </button>
            <button class="skip-btn" type="button" id="skip-btn" ${state.loading?"disabled":""}>
              ⏭ Skip
            </button>
            <button class="voice-btn ${state.listening?"voice-active":""}" type="button" id="mic-btn">
              ${state.listening
                ? `<span class="voice-dot"></span> Stop`
                : `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg> Voice`
              }
            </button>
          </div>
        </form>
        ${state.submittedToast ? `<div class="submitted-toast">Answer recorded</div>` : ""}
      </section>
      <aside class="panel">
        <h4>Resume Profile</h4>
        <div class="chips" style="margin-bottom:4px;">
          <span class="tag warn">${esc(p.seniority_signal)}</span>
          ${p.skills.slice(0,8).map(s=>`<span class="tag">${esc(s)}</span>`).join("")}
        </div>
        ${skillGapTemplate()}
      </aside>
    </div>
  `;
}

function summaryTemplate(){
  const s   = state.summary;
  const avg = Math.round(parseFloat(s.insights.average_score ?? 0));
  const acls = avg>=75 ? "score-strong" : avg>=60 ? "score-adequate" : "score-developing";
  const verdict = avg>=75 ? "Strong Candidate" : avg>=60 ? "Adequate" : avg>=40 ? "Needs Development" : "Not Recommended";
  const verdictCls = avg>=75 ? "verdict-strong" : avg>=60 ? "verdict-adequate" : "verdict-weak";

  const qCards = s.questions.map((item, i) => {
    const sc    = item.analysis?.score;
    const lvl   = item.analysis?.level || (item.skipped ? "skipped" : "");
    const lvlCls= scoreCls[lvl] || "score-adequate";
    const isGemini = item.analysis?.evaluator === "gemini";

    const strengthsHtml = isGemini && item.analysis?.strengths?.length
      ? `<div class="qa-section">
          <div class="qa-section-label qa-label-green">✓ Strengths</div>
          <div class="chips">${item.analysis.strengths.map(t=>`<span class="tag green">${esc(t)}</span>`).join("")}</div>
         </div>` : "";

    const gapsHtml = isGemini && item.analysis?.gaps?.length
      ? `<div class="qa-section">
          <div class="qa-section-label qa-label-rose">✗ Gaps</div>
          <div class="chips">${item.analysis.gaps.map(t=>`<span class="tag rose">${esc(t)}</span>`).join("")}</div>
         </div>` : "";

    return `
      <article class="qa-card">
        <div class="qa-card-header">
          <div class="qa-meta">
            <span class="qa-num">Q${i+1}</span>
            <span class="tag blue">${esc(item.topic)}</span>
            <span class="tag">${esc(item.difficulty)}</span>
            ${item.skipped ? `<span class="skipped-badge">Skipped</span>` : ""}
            ${item.time_taken_seconds ? `<span class="qa-time">⏱ ${item.time_taken_seconds}s</span>` : ""}
          </div>
          ${sc !== undefined
            ? `<div class="qa-score-badge ${lvlCls}">
                <span class="qa-score-num">${sc}</span>
                <span class="qa-score-label">${lvl}</span>
               </div>`
            : ""}
        </div>

        <p class="qa-question">${esc(item.question)}</p>

        ${!item.skipped && item.answer
          ? `<div class="qa-answer-block">
              <div class="qa-section-label" style="margin-bottom:4px;">Your Answer</div>
              <p class="qa-answer-text">${esc(item.answer)}</p>
             </div>` : ""}

        ${item.analysis?.feedback
          ? `<div class="qa-feedback">${esc(item.analysis.feedback)}</div>` : ""}

        ${strengthsHtml}${gapsHtml}
      </article>
    `;
  }).join("");

  return `
    <section class="summary-root">

      <!-- ── Header ── -->
      <div class="summary-header">
        <div class="summary-hero">
          <div class="summary-score-ring ${acls}" id="summary-score">0</div>
          <div>
            <h2 class="summary-name">${esc(s.candidate_name || "Candidate")}</h2>
            <p class="summary-role">${esc(s.role)}</p>
            <span class="verdict-pill ${verdictCls}">${verdict}</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
          <a class="pdf-btn" id="pdf-download-btn" href="/api/sessions/${esc(s.session_id)}/export" target="_blank" download>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zm-7 9H5v2h14v-2h-7z"/></svg>
            Download PDF Report
          </a>
          <button class="secondary" id="reset-button">New Interview</button>
        </div>
      </div>

      <!-- ── Stats row ── -->
      <div class="summary-stats">
        <div class="stat-box">
          <span class="stat-val">${s.insights.questions_answered}</span>
          <span class="stat-label">Answered</span>
        </div>
        <div class="stat-box">
          <span class="stat-val">${s.insights.skipped_count ?? 0}</span>
          <span class="stat-label">Skipped</span>
        </div>
        <div class="stat-box">
          <span class="stat-val">${avg}%</span>
          <span class="stat-label">Overall Score</span>
        </div>
      </div>

      <!-- ── Recommendation ── -->
      <div class="recommendation-box">
        <div class="rec-label">Recommendation</div>
        <p class="rec-text">${esc(s.insights.recommendation)}</p>
        ${s.insights.strong_terms?.length
          ? `<div class="chips" style="margin-top:10px;">${s.insights.strong_terms.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>`
          : ""}
      </div>

      <!-- ── Radar ── -->
      <div class="radar-wrap">
        <div class="radar-title">Performance Radar</div>
        <canvas id="radar-canvas" width="280" height="280"></canvas>
      </div>

      <!-- ── Q&A breakdown ── -->
      <div class="qa-breakdown">
        <h3 class="breakdown-title">Question Breakdown</h3>
        ${qCards}
      </div>

    </section>
  `;
}


/* ══════════════════════════════════════════════════════════════════
   EVENTS
══════════════════════════════════════════════════════════════════ */
function bindEvents(){
  // Theme
  document.getElementById("theme-toggle-btn")?.addEventListener("click", toggleDark);

  // Landing
  document.getElementById("landing-begin-btn")?.addEventListener("click", ()=>{
    const el = document.getElementById("landing-overlay");
    if(el){ el.classList.add("exiting"); setTimeout(()=>setState({showLanding:false}), 600); }
    else   setState({showLanding:false});
  });

  // Setup
  const startForm = document.getElementById("start-form");
  if(startForm){
    startForm.addEventListener("submit", startInterview);
    document.getElementById("role-select")?.addEventListener("change", e=>setState({role:e.target.value}));
    document.getElementById("resume-input")?.addEventListener("change", e=>{
      const file = e.target.files[0];
      state.resume = file;
      autoFillFromResume(file);
    });
    document.querySelectorAll(".role-card[data-role]").forEach(c=>{
      c.addEventListener("click", ()=>{
        document.getElementById("role-select").value = c.dataset.role;
        setState({role:c.dataset.role});
      });
    });
  }

  // Interview form
  const answerForm = document.getElementById("answer-form");
  if(answerForm){
    answerForm.addEventListener("submit", e=>{ e.preventDefault(); doSubmit(); });
    document.getElementById("answer-input")?.addEventListener("input", e=>{
      state.answer = e.target.value;
      liveUpdateQuality();
    });
    document.getElementById("skip-btn")?.addEventListener("click", ()=>{
      if(confirm("Skip this question? Your score for it will be 0.")) doSkip();
    });
    document.getElementById("mic-btn")?.addEventListener("click", toggleVoice);
  }

  // Summary reset
  document.getElementById("reset-button")?.addEventListener("click", resetInterview);
}

function postRenderAnimations(){
  // Score counter on answer submit
  if(state.latestAnalysis && document.getElementById("score-counter")){
    const cls = scoreCls[state.latestAnalysis.level] || "score-adequate";
    animateScore(state.latestAnalysis.score, "score-counter", cls);
  }
  // Average score counter on summary
  if(state.summary && document.getElementById("summary-score")){
    const avg = Math.round(parseFloat(state.summary.insights.average_score ?? 0));
    const cls = avg>=75 ? "score-strong" : avg>=60 ? "score-adequate" : "score-developing";
    animateScore(avg, "summary-score", cls);
    drawRadarChart();
  }
  // Timer removed — kept in state but not started
}

/* ══════════════════════════════════════════════════════════════════
   RENDER
══════════════════════════════════════════════════════════════════ */
function render(){
  const cur = stage();
  const app = `
    <div class="app">
      ${sidebarTemplate(cur)}
      <main class="main">
        <div class="topbar">
          <div>
            <span class="eyebrow">${esc(cur)} Flow</span>
            <h2>${esc(cur)}</h2>
          </div>
          <span class="pill">${state.roles.length ? `${state.roles.length} roles` : "Loading…"}</span>
        </div>
        ${state.error ? `<p class="error">${esc(state.error)}</p>` : ""}
        ${!state.session && !state.summary ? setupTemplate() : ""}
        ${state.session && state.question && !state.summary ? interviewTemplate() : ""}
        ${state.summary ? summaryTemplate() : ""}
      </main>
    </div>
  `;
  document.getElementById("root").innerHTML = app;
  bindEvents();
  postRenderAnimations();
}

/* ── Boot ─────────────────────────────────────────────────────── */
applyTheme(state.dark);
render();
loadRoles();
