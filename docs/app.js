/* Browser-only version of static/app.js for GitHub Pages.
 * No server: texts come from texts.js, speech recognition is the browser's
 * own (Web Speech API, Greek), scoring is evaluator.js, and each child's
 * history is kept in this browser's localStorage. */

/* ── Data ───────────────────────────────────────────────────────────────── */
const CLASS_HIERARCHY = [
  { id: "a",  name: "Α' Δημοτικού",  emoji: "🌱", volumes: [
    { id: "a_dimotikou",   name: "Τεύχος Α" },
    { id: "a_dimotikou_b", name: "Τεύχος Β" } ] },
  { id: "b",  name: "Β' Δημοτικού",  emoji: "📗", volumes: [
    { id: "b_dimotikou",   name: "Τεύχος Α" },
    { id: "b_dimotikou_b", name: "Τεύχος Β" },
    { id: "b_dimotikou_g", name: "Τεύχος Γ" } ] },
  { id: "g",  name: "Γ' Δημοτικού",  emoji: "📘", volumes: [
    { id: "g_dimotikou",   name: "Τεύχος Α" },
    { id: "g_dimotikou_b", name: "Τεύχος Β" },
    { id: "g_dimotikou_g", name: "Τεύχος Γ" } ] },
  { id: "d",  name: "Δ' Δημοτικού",  emoji: "📙", volumes: [
    { id: "d_dimotikou",   name: "Τεύχος Α" },
    { id: "d_dimotikou_b", name: "Τεύχος Β" },
    { id: "d_dimotikou_g", name: "Τεύχος Γ" } ] },
  { id: "e",  name: "Ε' Δημοτικού",  emoji: "📕", volumes: [
    { id: "e_dimotikou",   name: "Τεύχος Α" },
    { id: "e_dimotikou_b", name: "Τεύχος Β" },
    { id: "e_dimotikou_g", name: "Τεύχος Γ" } ] },
  { id: "st", name: "ΣΤ' Δημοτικού", emoji: "📓", volumes: [
    { id: "st_dimotikou",   name: "Τεύχος Α" },
    { id: "st_dimotikou_b", name: "Τεύχος Β" },
    { id: "st_dimotikou_g", name: "Τεύχος Γ" } ] },
];

// Same per-grade criteria as main.py (matched by source_id prefix)
const GRADE_CRITERIA = {
  "a_":  { wpm_target:  45, w_spd: 0.15 },
  "b_":  { wpm_target:  60, w_spd: 0.20 },
  "g_":  { wpm_target:  75, w_spd: 0.25 },
  "d_":  { wpm_target:  85, w_spd: 0.30 },
  "e_":  { wpm_target:  95, w_spd: 0.35 },
  "st_": { wpm_target: 110, w_spd: 0.35 },
};
const DEFAULT_CRITERIA = { wpm_target: 80, w_spd: 0.30 };

const ALL_TEXTS = window.TEXTS || [];
const TEXT_BY_ID = new Map(ALL_TEXTS.map(t => [t.id, t]));
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const MAX_HISTORY = 500;

/* ── Local storage (per browser) ────────────────────────────────────────── */
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch { return false; }
  },
  remove(key) { try { localStorage.removeItem(key); } catch {} },
};

const profiles = () => store.get("rp_profiles", []);
const historyKey = pid => `rp_history_${pid}`;
const loadHistory = () => state.user ? store.get(historyKey(state.user.id), []) : [];

function saveSession(session) {
  const list = loadHistory();
  list.unshift(session);
  while (list.length > MAX_HISTORY) list.pop();
  if (!store.set(historyKey(state.user.id), list)) {
    alert("Δεν χωράει άλλο ιστορικό σε αυτόν τον browser. Οι παλιότερες εγγραφές θα σβηστούν.");
    store.set(historyKey(state.user.id), list.slice(0, 100));
  }
}

function textStats(sourceId) {
  const stats = {};
  for (const s of loadHistory()) {
    if (s.source_id !== sourceId) continue;
    const st = stats[s.text_id] || (stats[s.text_id] = { attempts: 0, best_score: 0 });
    st.attempts++;
    st.best_score = Math.max(st.best_score, s.overall_score ?? 0);
  }
  return stats;
}

/* ── State ──────────────────────────────────────────────────────────────── */
const state = {
  user: (() => {
    const id = store.get("rp_current", null);
    return profiles().find(p => p.id === id) || null;
  })(),
  view: "class-select",
  currentClass:   null,
  currentVolume:  null,
  currentChapter: null,
  volumeTexts:    [],
  volumeStats:    {},
  currentText: null,
  currentMode: "normal",
  historySessions: [],
  sessionDetail:   null,
};

function navigate(view, extra = {}) {
  Object.assign(state, extra);
  state.view = view;
  render();
  window.scrollTo(0, 0);
}

/* ── Main render ────────────────────────────────────────────────────────── */
function render() {
  const app = document.getElementById("app");
  if (state.view !== "exercise") abortRecording();
  if (!state.user) {
    app.innerHTML = renderProfiles() + renderFooter();
    bindProfiles();
    return;
  }
  const v = state.view;
  app.innerHTML = `
    ${renderNavbar()}
    <div class="page">
      ${v === "class-select"   ? renderClassSelect()   :
        v === "volume-select"  ? renderVolumeSelect()  :
        v === "chapter-select" ? renderChapterSelect() :
        v === "text-select"    ? renderTextSelect()    :
        v === "exercise"       ? renderExercise()      :
        v === "history"        ? renderHistory()       :
        v === "session"        ? renderSessionDetail() : ""}
    </div>
    ${renderFooter()}`;
  bindView();
}

/* ── Navbar + breadcrumb ────────────────────────────────────────────────── */
function renderNavbar() {
  const crumbs = buildBreadcrumb();
  const crumbBar = crumbs.length > 0 ? `
    <div class="breadcrumb-bar">
      ${crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        return `${i > 0 ? '<span class="bc-sep">›</span>' : ''}
          <span class="bc-item${isLast ? " current" : ""}" data-crumb="${i}">${escapeHtml(c.label)}</span>`;
      }).join("")}
    </div>` : "";

  return `
    <nav class="navbar">
      <div class="navbar-top">
        <div class="navbar-brand">📖 Εξάσκηση Ανάγνωσης</div>
        <div class="navbar-right">
          <span class="user-name">👤 ${escapeHtml(state.user.name)}</span>
          <button class="btn-nav" id="btn-history-nav">Ιστορικό</button>
          <button class="btn-nav" id="btn-logout-nav">Αλλαγή παιδιού</button>
        </div>
      </div>
      ${crumbBar}
    </nav>`;
}

function buildBreadcrumb() {
  const v = state.view;
  const crumbs = [];
  if (v === "class-select" || v === "history" || v === "session") return crumbs;
  if (state.currentClass)   crumbs.push({ label: state.currentClass.name, view: "class-select" });
  if (state.currentVolume && v !== "volume-select")
    crumbs.push({ label: state.currentVolume.name, view: "volume-select" });
  if (state.currentChapter && (v === "text-select" || v === "exercise"))
    crumbs.push({ label: shortChapterName(state.currentChapter), view: "chapter-select" });
  if (v === "exercise" && state.currentText)
    crumbs.push({ label: state.currentText.title, view: "exercise" });
  return crumbs;
}

/* ── Profiles (who is reading) ──────────────────────────────────────────── */
function renderProfiles() {
  const list = profiles();
  return `
    <div class="auth-wrap">
      <div class="auth-box card">
        <div class="auth-logo">📖</div>
        <h2 class="auth-title">Καλώς ήρθες!</h2>
        <p class="auth-subtitle">${list.length ? "Ποιος θα διαβάσει;" : "Γράψε το όνομά σου για να ξεκινήσεις!"}</p>
        ${list.length ? `
          <div class="profile-list">
            ${list.map(p => `
              <div class="profile-item" data-pid="${escapeAttr(p.id)}">
                <span class="profile-name">👤 ${escapeHtml(p.name)}</span>
                <button class="profile-del" data-del-pid="${escapeAttr(p.id)}" title="Διαγραφή">✕</button>
              </div>`).join("")}
          </div>
          <p class="auth-subtitle" style="margin-top:18px">ή νέο παιδί:</p>` : ""}
        <div id="auth-error" class="error-msg" style="display:none"></div>
        <div class="form-group"><label>Όνομα</label><input id="f-name" placeholder="π.χ. Μαρία" maxlength="40"/></div>
        <button class="btn btn-primary btn-lg" style="width:100%" id="btn-add-profile">Ξεκινάμε →</button>
        <p class="privacy-note">Το ιστορικό μένει μόνο σε αυτόν τον υπολογιστή / browser.</p>
      </div>
    </div>`;
}

function bindProfiles() {
  document.querySelectorAll(".profile-item").forEach(el => {
    el.addEventListener("click", () => selectProfile(el.dataset.pid));
  });
  document.querySelectorAll(".profile-del").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const p = profiles().find(x => x.id === btn.dataset.delPid);
      if (!p) return;
      if (!confirm(`Να διαγραφεί το παιδί «${p.name}» και όλο το ιστορικό του;`)) return;
      store.set("rp_profiles", profiles().filter(x => x.id !== p.id));
      store.remove(historyKey(p.id));
      render();
    });
  });
  const add = () => {
    const name = document.getElementById("f-name").value.trim();
    const errEl = document.getElementById("auth-error");
    if (!name) {
      errEl.textContent = "Γράψε ένα όνομα.";
      errEl.style.display = "block";
      return;
    }
    const existing = profiles().find(p => p.name.toLowerCase() === name.toLowerCase());
    if (existing) return selectProfile(existing.id);
    const p = { id: "p" + Date.now().toString(36), name };
    store.set("rp_profiles", [...profiles(), p]);
    selectProfile(p.id);
  };
  document.getElementById("btn-add-profile").onclick = add;
  document.getElementById("f-name").addEventListener("keydown", e => { if (e.key === "Enter") add(); });
}

function selectProfile(pid) {
  const p = profiles().find(x => x.id === pid);
  if (!p) return;
  state.user = p;
  store.set("rp_current", p.id);
  navigate("class-select");
}

function logout() {
  state.user = null;
  store.remove("rp_current");
  navigate("class-select");
}

/* ── Class select ───────────────────────────────────────────────────────── */
function renderClassSelect() {
  return `
    <div class="select-intro">
      <h2>Γεια σου, ${escapeHtml(state.user.name)}! 👋</h2>
      <p>Επίλεξε την τάξη σου</p>
    </div>
    ${SpeechRec ? "" : `<div class="error-msg">Η αναγνώριση φωνής δεν υποστηρίζεται σε αυτόν τον browser. Άνοιξε τη σελίδα με <strong>Google Chrome</strong> ή <strong>Microsoft Edge</strong>.</div>`}
    <div class="class-grid">
      ${CLASS_HIERARCHY.map(cls => `
        <div class="class-card" data-cls-id="${cls.id}">
          <span class="class-emoji">${cls.emoji}</span>
          <div class="class-name">${escapeHtml(cls.name)}</div>
          <div class="class-sub">${cls.volumes.length} τεύχη</div>
        </div>`).join("")}
    </div>`;
}

/* ── Volume select ──────────────────────────────────────────────────────── */
function renderVolumeSelect() {
  const cls = state.currentClass;
  const icons = ["📗", "📘", "📙"];
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back">←</button>
      <div>
        <h2>${escapeHtml(cls.name)}</h2>
        <p>Επίλεξε τεύχος</p>
      </div>
    </div>
    <div class="volume-grid">
      ${cls.volumes.map((vol, i) => `
        <div class="volume-card" data-vol-id="${vol.id}">
          <span class="vol-icon">${icons[i] || "📖"}</span>
          <div class="vol-name">${escapeHtml(vol.name)}</div>
          <div class="vol-count">Πάτα για να ξεκινήσεις →</div>
        </div>`).join("")}
    </div>`;
}

/* ── Chapter select ─────────────────────────────────────────────────────── */
function getChapters() {
  const seen = new Set();
  const chapters = [];
  state.volumeTexts.forEach(t => {
    const ch = t.chapter || "Χωρίς ενότητα";
    if (!seen.has(ch)) { seen.add(ch); chapters.push(ch); }
  });
  chapters.sort((a, b) => extractChapterNum(a) - extractChapterNum(b));
  return chapters;
}

function renderChapterSelect() {
  const chapters = getChapters();
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back">←</button>
      <div>
        <h2>${escapeHtml(state.currentVolume.name)}</h2>
        <p>Επίλεξε ενότητα</p>
      </div>
    </div>
    <div class="chapter-grid">
      ${chapters.map(ch => {
        const texts = state.volumeTexts.filter(t => (t.chapter || "Χωρίς ενότητα") === ch);
        const attempted = texts.filter(t => state.volumeStats[t.id]).length;
        const num = extractChapterNum(ch);
        return `
          <div class="chapter-card" data-chapter="${escapeAttr(ch)}">
            <div class="ch-num">${num < 999 ? num : "—"}</div>
            <div class="ch-info">
              <div class="ch-name">${escapeHtml(shortChapterName(ch))}</div>
              <div class="ch-sub">${texts.length} κείμενα${attempted > 0 ? ` · ${attempted} ολοκλήρωσες` : ""}</div>
            </div>
            <div class="ch-arrow">›</div>
          </div>`;
      }).join("")}
    </div>`;
}

/* ── Text select ────────────────────────────────────────────────────────── */
function renderTextSelect() {
  const texts = state.volumeTexts.filter(t =>
    (t.chapter || "Χωρίς ενότητα") === state.currentChapter
  );
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back">←</button>
      <div>
        <h2>${escapeHtml(shortChapterName(state.currentChapter))}</h2>
        <p>Επίλεξε κείμενο</p>
      </div>
    </div>
    <div class="text-grid">
      ${texts.map(t => {
        const st = state.volumeStats[t.id];
        const { cls: sCls, html: sHtml } = starsInfo(st?.best_score);
        return `
          <div class="text-card" data-tid="${escapeAttr(t.id)}">
            ${!st ? '<span class="badge-new">Νέο!</span>' : ""}
            <div class="tc-title">${escapeHtml(t.title)}</div>
            <div class="tc-meta">
              <span>${t.word_count || "?"} λέξεις</span>
              <span class="tc-dot">·</span>
              <span>Σελ. ${t.page_number || "—"}</span>
            </div>
            <span class="tc-stars ${sCls}">${sHtml}</span>
            <div class="tc-best">${st
              ? `Καλύτερο: <strong>${Math.round(st.best_score)}%</strong> · ${st.attempts} ${st.attempts === 1 ? "φορά" : "φορές"}`
              : "Δεν έχεις δοκιμάσει ακόμα"}</div>
          </div>`;
      }).join("")}
    </div>`;
}

/* ── Exercise ───────────────────────────────────────────────────────────── */
function renderExercise() {
  const t = state.currentText;
  if (!t) return '<p>Δεν επιλέχθηκε κείμενο.</p>';
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back">←</button>
      <div>
        <h2>${escapeHtml(t.title)}</h2>
        <p>${t.word_count || "?"} λέξεις · Σελ. ${t.page_number || "—"}</p>
      </div>
    </div>

    <div class="mode-tabs">
      <button class="mode-tab ${state.currentMode === "normal" ? "active" : ""}" data-mode="normal">📖 Κανονική</button>
      <button class="mode-tab ${state.currentMode === "wpm"    ? "active" : ""}" data-mode="wpm">⏱ Λέξεις/Λεπτό</button>
    </div>

    ${state.currentMode === "wpm" ? `
      <div class="wpm-info">⏱ Έχεις <strong>1 λεπτό</strong> για να διαβάσεις όσες περισσότερες λέξεις μπορείς!</div>` : ""}

    <div class="reading-text-box">${escapeHtml(t.content)}</div>

    <div class="card">
      <div class="record-area">
        <div class="timer-display${state.currentMode === "wpm" ? " wpm-timer" : ""}" id="timer-display">
          ${state.currentMode === "wpm" ? "1:00" : "0:00"}
        </div>
        <button class="record-btn" id="record-btn"${SpeechRec ? "" : " disabled"}>🎙</button>
        <span class="record-label" id="record-label">${SpeechRec
          ? "Πάτα για να ξεκινήσεις"
          : "Χρειάζεται Google Chrome ή Microsoft Edge"}</span>
        <div class="live-heard" id="live-heard"></div>
      </div>
    </div>

    <div id="results-area"></div>`;
}

/* ── Speech recognition ─────────────────────────────────────────────────── */
const rec = {
  engine: null,
  active: false,      // the child is reading (between start and stop clicks)
  finals: [],
  interim: "",
  startTime: 0,
  duration: 0,
  timer: null,
  countdown: null,
  finishTimer: null,
  error: null,
};

function toggleRecording() {
  if (rec.active) stopRecording();
  else startRecording();
}

function startRecording() {
  if (!SpeechRec) return;
  const btn = document.getElementById("record-btn");
  const label = document.getElementById("record-label");
  document.getElementById("results-area").innerHTML = "";

  rec.finals = [];
  rec.interim = "";
  rec.error = null;
  rec.duration = 0;
  rec.active = true;
  rec.engine = makeEngine();
  try {
    rec.engine.start();
  } catch (e) {
    rec.active = false;
    alert("Δεν ξεκίνησε η αναγνώριση φωνής: " + e.message);
    return;
  }
  rec.startTime = Date.now();

  btn.classList.add("recording");
  btn.innerHTML = "⏹";
  label.textContent = "Διαβάζεις... (πάτα για να σταματήσεις)";
  label.classList.add("rec");

  if (state.currentMode === "wpm") {
    let remaining = 60;
    updateTimer(remaining);
    rec.countdown = setInterval(() => {
      remaining--;
      updateTimer(remaining);
      if (remaining <= 0) stopRecording();
    }, 1000);
  } else {
    updateTimer(0);
    rec.timer = setInterval(() => updateTimer((Date.now() - rec.startTime) / 1000), 500);
  }
}

function makeEngine() {
  const engine = new SpeechRec();
  engine.lang = "el-GR";
  engine.continuous = true;
  engine.interimResults = true;
  engine.maxAlternatives = 5;
  const vocab = new Set(tokenize(state.currentText.content));

  engine.onresult = e => {
    if (engine !== rec.engine) return;
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) {
        // Of the recogniser's guesses, keep the one closest to the text
        let best = r[0].transcript, bestHits = vocabHits(best, vocab);
        for (let k = 1; k < r.length; k++) {
          const hits = vocabHits(r[k].transcript, vocab);
          if (hits > bestHits) { best = r[k].transcript; bestHits = hits; }
        }
        rec.finals.push(best);
      }
      else interim += r[0].transcript;
    }
    rec.interim = interim;
    const live = document.getElementById("live-heard");
    if (live) live.textContent = [...rec.finals, interim].join(" ").trim().split(/\s+/).slice(-12).join(" ");
  };

  engine.onerror = e => {
    if (engine !== rec.engine) return;
    if (e.error === "no-speech" || e.error === "aborted") return;
    rec.error = e.error;
    if (e.error === "not-allowed" || e.error === "service-not-allowed" ||
        e.error === "audio-capture" || e.error === "network") {
      rec.active = false;
      clearTimers();
    }
  };

  // Chrome ends recognition on its own after a pause; keep listening until
  // the child presses stop.
  engine.onend = () => {
    if (engine !== rec.engine) return;
    if (rec.active) {
      if (rec.interim) { rec.finals.push(rec.interim); rec.interim = ""; }
      try { engine.start(); return; } catch {}
    }
    finishRecording();
  };
  return engine;
}

function clearTimers() {
  clearInterval(rec.timer);
  clearInterval(rec.countdown);
  rec.timer = rec.countdown = null;
}

function stopRecording() {
  if (!rec.active) return;
  rec.active = false;
  rec.duration = (Date.now() - rec.startTime) / 1000;
  clearTimers();
  const label = document.getElementById("record-label");
  if (label) label.textContent = "Μια στιγμή...";
  try { rec.engine.stop(); } catch { finishRecording(); }
  // If the browser never reports the end, finish anyway.
  rec.finishTimer = setTimeout(finishRecording, 4000);
}

function abortRecording() {
  if (!rec.engine) return;
  const engine = rec.engine;
  rec.engine = null;
  rec.active = false;
  clearTimers();
  clearTimeout(rec.finishTimer);
  try { engine.abort(); } catch {}
}

function finishRecording() {
  clearTimeout(rec.finishTimer);
  if (!rec.engine) return;            // already finished or aborted
  rec.engine = null;
  clearTimers();

  const btn = document.getElementById("record-btn");
  const label = document.getElementById("record-label");
  const area = document.getElementById("results-area");
  if (!btn || !area) return;
  btn.classList.remove("recording");
  btn.innerHTML = "🎙";
  label.classList.remove("rec");
  label.textContent = "Πάτα για να ξεκινήσεις";
  document.getElementById("live-heard").textContent = "";

  if (rec.interim) rec.finals.push(rec.interim);
  const transcribed = rec.finals.join(" ").replace(/\s+/g, " ").trim();
  if (!rec.duration) rec.duration = (Date.now() - rec.startTime) / 1000;

  if (rec.error && !transcribed) {
    area.innerHTML = `<div class="card error-msg">${escapeHtml(speechErrorMessage(rec.error))}</div>`;
    return;
  }
  if (!transcribed) {
    area.innerHTML = `<div class="card error-msg">Δεν ακούστηκε τίποτα. Έλεγξε ότι το μικρόφωνο δουλεύει και διάβασε δυνατά.</div>`;
    return;
  }

  const t = state.currentText;
  const crit = Object.entries(GRADE_CRITERIA).find(([k]) => t.source_id.startsWith(k))?.[1] || DEFAULT_CRITERIA;
  const scores = state.currentMode === "wpm"
    ? evaluateWpmMode(t.content, transcribed, rec.duration)
    : evaluateReading(t.content, transcribed, rec.duration, crit);

  const result = { ...scores, transcribed, mode: state.currentMode };
  saveSession({
    id: Date.now(),
    created_at: new Date().toISOString(),
    source_id: t.source_id,
    text_id: t.id,
    text_title: t.title,
    transcribed_text: transcribed,
    mode: state.currentMode,
    word_accuracy: scores.word_accuracy,
    wpm: scores.wpm,
    overall_score: scores.overall_score,
    duration_sec: Math.round(rec.duration * 100) / 100,
    correct_words: scores.correct_words,
    total_words: scores.total_words,
    diff_tokens: scores.diff_tokens,
  });
  if (state.currentVolume) state.volumeStats = textStats(state.currentVolume.id);
  showResults(result);
}

function speechErrorMessage(code) {
  if (code === "not-allowed" || code === "service-not-allowed")
    return "Ο browser δεν επιτρέπει το μικρόφωνο. Πάτα το εικονίδιο 🔒 δίπλα στη διεύθυνση και επίτρεψε το μικρόφωνο.";
  if (code === "audio-capture") return "Δεν βρέθηκε μικρόφωνο.";
  if (code === "network") return "Η αναγνώριση φωνής χρειάζεται σύνδεση στο ίντερνετ.";
  if (code === "language-not-supported") return "Ο browser δεν υποστηρίζει ελληνικά. Δοκίμασε Google Chrome.";
  return "Σφάλμα αναγνώρισης φωνής: " + code;
}

function showResults(result) {
  const area = document.getElementById("results-area");
  area.innerHTML = `
    <div class="card results-box">
      <h3>📊 Αποτελέσματα</h3>
      ${renderScoreGrid(result)}
      <hr class="divider"/>
      <div class="diff-section">
        <h4>📄 Κείμενο — χρωματισμός ανάγνωσης</h4>
        <div class="diff-text">${renderDiff(result.diff_tokens)}</div>
      </div>
      <div class="transcribed-section" style="margin-top:16px">
        <h4>🎙 Αυτό που ακούστηκε</h4>
        <div class="transcribed-text">${escapeHtml(result.transcribed)}</div>
      </div>
      <div class="result-actions">
        <button class="btn btn-primary" id="btn-retry">🔄 Ξαναδοκίμασε</button>
        <button class="btn btn-ghost" id="btn-to-texts">← Επιλογή κειμένου</button>
      </div>
    </div>`;
  document.getElementById("btn-retry").onclick = () => navigate("exercise");
  document.getElementById("btn-to-texts").onclick = () => navigate("text-select");
  area.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ── History ────────────────────────────────────────────────────────────── */
function openHistory() {
  navigate("history", { historySessions: loadHistory() });
}

function renderHistory() {
  const sessions = state.historySessions || [];
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back-home">←</button>
      <h2>📊 Ιστορικό Αναγνώσεων</h2>
    </div>
    ${sessions.length === 0
      ? `<div class="empty-state">
           <span class="empty-icon">📭</span>
           <strong>Δεν υπάρχουν εγγραφές ακόμα</strong>
           Κάνε ανάγνωση για να δεις το ιστορικό σου!
         </div>`
      : `<div class="history-list">
           ${sessions.map(s => {
             const score = s.overall_score ?? 0;
             const date = new Date(s.created_at).toLocaleDateString("el-GR", {
               day: "2-digit", month: "short", year: "numeric",
               hour: "2-digit", minute: "2-digit"
             });
             return `
               <div class="history-item" data-sid="${s.id}">
                 <div class="hi-score score-card ${scoreClass(score)}">
                   <span class="score-val">${Math.round(score)}%</span>
                 </div>
                 <div class="hi-info">
                   <div class="hi-title">${escapeHtml(s.text_title || "—")}</div>
                   <div class="hi-meta">${date} · ${(s.word_accuracy ?? 0).toFixed(0)}% ακρίβεια</div>
                   <div class="hi-wpm">⚡ ${(s.wpm ?? 0).toFixed(0)} λεξ/λ</div>
                 </div>
                 <span class="mode-badge ${s.mode}">${s.mode === "wpm" ? "ΛΑΛ" : "Κανονική"}</span>
               </div>`;
           }).join("")}
         </div>`}`;
}

function renderSessionDetail() {
  const s = state.sessionDetail;
  if (!s) return "<p>Δεν βρέθηκε η εγγραφή.</p>";
  const original = TEXT_BY_ID.get(s.text_id)?.content || "";
  const diff = s.diff_tokens ? renderDiff(s.diff_tokens) : escapeHtml(original);
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back-hist">←</button>
      <h2>${escapeHtml(s.text_title || "Λεπτομέρειες")}</h2>
    </div>
    <div class="card results-box">
      ${renderScoreGrid(s)}
      <hr class="divider"/>
      <div class="diff-section">
        <h4>📄 Κείμενο</h4>
        <div class="diff-text">${diff}</div>
      </div>
      <div class="transcribed-section" style="margin-top:16px">
        <h4>🎙 Αυτό που ακούστηκε</h4>
        <div class="transcribed-text">${escapeHtml(s.transcribed_text || "")}</div>
      </div>
    </div>`;
}

/* ── Bind events ────────────────────────────────────────────────────────── */
function bindView() {
  document.getElementById("btn-logout-nav")?.addEventListener("click", logout);
  document.getElementById("btn-history-nav")?.addEventListener("click", openHistory);

  document.querySelectorAll(".bc-item:not(.current)").forEach(el => {
    el.addEventListener("click", () => {
      const crumbs = buildBreadcrumb();
      const c = crumbs[parseInt(el.dataset.crumb)];
      if (c) navigate(c.view);
    });
  });

  const v = state.view;
  document.getElementById("btn-back")?.addEventListener("click", () => {
    if (v === "volume-select")  navigate("class-select");
    if (v === "chapter-select") navigate("volume-select");
    if (v === "text-select")    navigate("chapter-select");
    if (v === "exercise")       navigate("text-select");
  });
  document.getElementById("btn-back-home")?.addEventListener("click", () => navigate("class-select"));
  document.getElementById("btn-back-hist")?.addEventListener("click", openHistory);

  document.querySelectorAll(".class-card").forEach(card => {
    card.addEventListener("click", () => {
      const cls = CLASS_HIERARCHY.find(c => c.id === card.dataset.clsId);
      if (cls) navigate("volume-select", { currentClass: cls });
    });
  });

  document.querySelectorAll(".volume-card").forEach(card => {
    card.addEventListener("click", () => {
      const vol = state.currentClass?.volumes.find(x => x.id === card.dataset.volId);
      if (vol) navigate("chapter-select", {
        currentVolume: vol,
        volumeTexts: ALL_TEXTS.filter(t => t.source_id === vol.id),
        volumeStats: textStats(vol.id),
      });
    });
  });

  document.querySelectorAll(".chapter-card").forEach(card => {
    card.addEventListener("click", () => navigate("text-select", { currentChapter: card.dataset.chapter }));
  });

  document.querySelectorAll(".text-card").forEach(card => {
    card.addEventListener("click", () => {
      const t = TEXT_BY_ID.get(card.dataset.tid);
      if (t) navigate("exercise", { currentText: t, currentMode: "normal" });
    });
  });

  document.querySelectorAll(".mode-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      abortRecording();
      navigate("exercise", { currentMode: tab.dataset.mode });
    });
  });

  document.getElementById("record-btn")?.addEventListener("click", toggleRecording);

  document.querySelectorAll(".history-item").forEach(item => {
    item.addEventListener("click", () => {
      const s = state.historySessions.find(x => String(x.id) === item.dataset.sid);
      navigate("session", { sessionDetail: s || null });
    });
  });
}

/* ── Score helpers ──────────────────────────────────────────────────────── */
function renderScoreGrid(data) {
  const acc = data.word_accuracy ?? 0;
  const wpm = data.wpm ?? 0;
  const overall = data.overall_score ?? 0;
  return `
    <div class="score-grid">
      <div class="score-card overall">
        <div class="score-val">${Math.round(overall)}%</div>
        <div class="score-lbl">Συνολική</div>
      </div>
      <div class="score-card ${scoreClass(acc)}">
        <div class="score-val">${acc.toFixed(0)}%</div>
        <div class="score-lbl">Ακρίβεια</div>
      </div>
      <div class="score-card ${scoreClass(wpm / 80 * 100)}">
        <div class="score-val">${wpm.toFixed(0)}</div>
        <div class="score-lbl">Λέξ/λεπτό</div>
      </div>
      <div class="score-card">
        <div class="score-val">${data.correct_words ?? 0}</div>
        <div class="score-lbl">Σωστές λέξεις</div>
      </div>
    </div>`;
}

function scoreClass(val) {
  return val >= 80 ? "good" : val >= 50 ? "medium" : "poor";
}

function starsInfo(bestScore) {
  if (bestScore == null) return { cls: "s0", html: "☆☆☆" };
  if (bestScore >= 80)   return { cls: "s3", html: "★★★" };
  if (bestScore >= 50)   return { cls: "s2", html: "★★☆" };
  return                        { cls: "s1", html: "★☆☆" };
}

function renderDiff(tokens) {
  if (!Array.isArray(tokens)) return "";
  return tokens.map(t => {
    if (t.status === "correct") return `<span class="w-correct">${escapeHtml(t.word)} </span>`;
    if (t.status === "wrong")   return `<span class="w-wrong">${escapeHtml(t.word)} </span>`;
    if (t.status === "missing") return `<span class="w-missing">[${escapeHtml(t.word)}] </span>`;
    return escapeHtml(t.word) + " ";
  }).join("");
}

function updateTimer(seconds) {
  const el = document.getElementById("timer-display");
  if (!el) return;
  const s = Math.max(0, Math.round(seconds));
  el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */
function renderFooter() {
  return `
    <footer class="site-footer">
      Created by <strong>Manos Chatzidakis</strong> · Special Education Teacher ·
      <a href="mailto:manoshatzidakis93@gmail.com">manoshatzidakis93@gmail.com</a>
    </footer>`;
}

/* ── Utils ──────────────────────────────────────────────────────────────── */
function extractChapterNum(ch) {
  const m = ch.match(/(\d+)/);
  return m ? parseInt(m[1]) : 999;
}

function shortChapterName(ch) {
  return ch.replace(/^Ενότητα\s*\d+\s*[—–\-]\s*/u, "") || ch;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/\n/g, "<br/>");
}

function escapeAttr(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ── Boot ───────────────────────────────────────────────────────────────── */
render();
