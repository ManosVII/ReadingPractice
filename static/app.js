/* ── State ──────────────────────────────────────────────────────────────── */
const state = {
  token: localStorage.getItem("token") || null,
  user:  JSON.parse(localStorage.getItem("user") || "null"),
  view:  "class-select",
  // Navigation hierarchy
  classes:        [],
  currentClass:   null,
  currentVolume:  null,
  currentChapter: null,
  volumeTexts:    [],
  volumeStats:    {},
  // Exercise
  currentText: null,
  currentMode: "normal",
  lastResult:  null,
  // History
  historySessions: [],
  sessionDetail:   null,
};

/* ── API helpers ────────────────────────────────────────────────────────── */
const API = (path, opts = {}) => {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  return fetch(path, { ...opts, headers }).then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Σφάλμα διακομιστή");
    return data;
  });
};

const APIform = (path, formData) =>
  fetch(path, {
    method: "POST",
    headers: { "Authorization": `Bearer ${state.token}` },
    body: formData,
  }).then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Σφάλμα διακομιστή");
    return data;
  });

/* ── Router ─────────────────────────────────────────────────────────────── */
function navigate(view, extra = {}) {
  Object.assign(state, extra);
  state.view = view;
  render();
}

/* ── Recording state ────────────────────────────────────────────────────── */
let mediaRecorder = null;
let audioChunks = [];
let recordingStartTime = null;
let timerInterval = null;
let wpmCountdown = null;

/* ── Main render ────────────────────────────────────────────────────────── */
function render() {
  const app = document.getElementById("app");
  if (!state.token) {
    app.innerHTML = renderAuth() + renderFooter();
    bindAuth();
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
        v === "history"        ? renderHistory()        :
        v === "session"        ? renderSessionDetail() : ""}
    </div>
    ${renderFooter()}
    ${renderAddTextModal()}`;
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
          <span class="bc-item${isLast ? " current" : ""}" data-crumb="${i}">${c.label}</span>`;
      }).join("")}
    </div>` : "";

  return `
    <nav class="navbar">
      <div class="navbar-top">
        <div class="navbar-brand">📖 Εξάσκηση Ανάγνωσης</div>
        <div class="navbar-right">
          <span class="user-name">👤 ${state.user?.full_name?.split(" ")[0] || ""}</span>
          <button class="btn-nav" id="btn-history-nav">Ιστορικό</button>
          <button class="btn-nav" id="btn-logout-nav">Έξοδος</button>
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

/* ── Auth ───────────────────────────────────────────────────────────────── */
function renderAuth(isRegister = false) {
  return `
    <div class="auth-wrap">
      <div class="auth-box card">
        <div class="auth-logo">📖</div>
        <h2 class="auth-title">${isRegister ? "Εγγραφή" : "Καλώς ήρθες!"}</h2>
        <p class="auth-subtitle">${isRegister ? "Δημιούργησε νέο λογαριασμό" : "Συνδέσου για να ξεκινήσεις!"}</p>
        <div id="auth-error" class="error-msg" style="display:none"></div>
        ${isRegister ? `<div class="form-group"><label>Ονοματεπώνυμο</label><input id="f-fullname" placeholder="π.χ. Μαρία Παπαδοπούλου"/></div>` : ""}
        <div class="form-group"><label>Όνομα χρήστη</label><input id="f-username" placeholder="username"/></div>
        <div class="form-group"><label>Κωδικός</label><input id="f-password" type="password" placeholder="••••"/></div>
        <button class="btn btn-primary btn-lg" style="width:100%" id="btn-auth-submit">
          ${isRegister ? "Εγγραφή ✓" : "Σύνδεση →"}
        </button>
        <div class="auth-toggle">
          ${isRegister
            ? `Έχεις ήδη λογαριασμό; <a id="toggle-auth">Σύνδεση</a>`
            : `Δεν έχεις λογαριασμό; <a id="toggle-auth">Εγγραφή</a>`}
        </div>
      </div>
    </div>`;
}

function bindAuth(isRegister = false) {
  document.getElementById("toggle-auth").onclick = () => {
    document.getElementById("app").innerHTML = renderAuth(!isRegister);
    bindAuth(!isRegister);
  };
  document.getElementById("btn-auth-submit").onclick = () => doAuth(isRegister);
  ["f-username","f-password","f-fullname"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") doAuth(isRegister); });
  });
}

async function doAuth(isRegister) {
  const errEl = document.getElementById("auth-error");
  errEl.style.display = "none";
  const username = document.getElementById("f-username").value.trim();
  const password = document.getElementById("f-password").value;
  const full_name = isRegister ? document.getElementById("f-fullname").value.trim() : undefined;
  try {
    const endpoint = isRegister ? "/api/auth/register" : "/api/auth/login";
    const body = isRegister ? { username, password, full_name } : { username, password };
    const data = await API(endpoint, { method: "POST", body: JSON.stringify(body) });
    state.token = data.token;
    state.user = { username: data.username, full_name: data.full_name };
    localStorage.setItem("token", state.token);
    localStorage.setItem("user", JSON.stringify(state.user));
    await loadClasses();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = "block";
  }
}

/* ── Class select ───────────────────────────────────────────────────────── */
async function loadClasses() {
  try {
    state.classes = await API("/api/classes");
  } catch (e) {
    state.classes = [];
    state.classesError = e.message;
  }
  navigate("class-select");
}

function renderClassSelect() {
  const firstName = state.user?.full_name?.split(" ")[0] || "";
  return `
    <div class="select-intro">
      <h2>Γεια σου, ${escapeHtml(firstName)}! 👋</h2>
      <p>Επίλεξε την τάξη σου</p>
    </div>
    ${state.classesError ? `<div class="error-msg">Σφάλμα φόρτωσης τάξεων: ${escapeHtml(state.classesError)} — Κάνε επανεκκίνηση του διακομιστή.</div>` : ""}
    <div class="class-grid">
      ${state.classes.map(cls => `
        <div class="class-card" data-cls-id="${cls.id}">
          <span class="class-emoji">${cls.emoji || "📚"}</span>
          <div class="class-name">${escapeHtml(cls.name)}</div>
          <div class="class-sub">${cls.volumes?.length || 0} τεύχη</div>
        </div>`).join("")}
    </div>`;
}

/* ── Volume select ──────────────────────────────────────────────────────── */
function renderVolumeSelect() {
  const cls = state.currentClass;
  return `
    <div class="section-header">
      <button class="btn-icon" id="btn-back">←</button>
      <div>
        <h2>${escapeHtml(cls.name)}</h2>
        <p>Επίλεξε τεύχος</p>
      </div>
    </div>
    <div class="volume-grid">
      ${cls.volumes.map((vol, i) => {
        const icons = ["📗","📘","📙"];
        return `
          <div class="volume-card" data-vol-id="${vol.id}">
            <span class="vol-icon">${icons[i] || "📖"}</span>
            <div class="vol-name">${escapeHtml(vol.name)}</div>
            <div class="vol-count">Πάτα για να ξεκινήσεις →</div>
          </div>`;
      }).join("")}
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
        const name = shortChapterName(ch);
        return `
          <div class="chapter-card" data-chapter="${escapeAttr(ch)}">
            <div class="ch-num">${num < 999 ? num : "—"}</div>
            <div class="ch-info">
              <div class="ch-name">${escapeHtml(name)}</div>
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
      <button class="btn btn-ghost btn-sm" data-add-src="${state.currentVolume.id}">+ Προσθήκη</button>
    </div>
    <div class="text-grid">
      ${texts.map(t => {
        const st = state.volumeStats[t.id];
        const { cls: sCls, html: sHtml } = starsInfo(st?.best_score);
        return `
          <div class="text-card" data-tid="${t.id}">
            ${!st ? '<span class="badge-new">Νέο!</span>' : ""}
            <button class="tc-edit-btn" data-edit-tid="${t.id}" title="Επεξεργασία">✏️</button>
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
        <button class="record-btn" id="record-btn">🎙</button>
        <span class="record-label" id="record-label">Πάτα για να ξεκινήσεις</span>
      </div>
    </div>

    <div id="results-area"></div>`;
}

/* ── History ────────────────────────────────────────────────────────────── */
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
             const cls = score >= 80 ? "good" : score >= 50 ? "medium" : "poor";
             const date = new Date(s.created_at).toLocaleDateString("el-GR", {
               day: "2-digit", month: "short", year: "numeric",
               hour: "2-digit", minute: "2-digit"
             });
             return `
               <div class="history-item" data-sid="${s.id}">
                 <div class="hi-score score-card ${cls}">
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

/* ── Session detail ─────────────────────────────────────────────────────── */
function renderSessionDetail() {
  const s = state.sessionDetail;
  if (!s) return "<p>Φόρτωση...</p>";
  const diff = s.diff_tokens
    ? renderDiff(JSON.parse(s.diff_tokens || "[]"))
    : escapeHtml(s.original_text || "");
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

/* ── Add text modal ─────────────────────────────────────────────────────── */
let _addTextSourceId = null;

function renderAddTextModal() {
  return `
    <div id="add-text-modal" class="modal-overlay">
      <div class="card modal-box">
        <div class="modal-header">
          <h3>Προσθήκη Κειμένου</h3>
          <button class="btn-icon" id="add-text-cancel">✕</button>
        </div>
        <div id="add-text-error" class="error-msg" style="display:none"></div>
        <div class="form-group">
          <label>Τίτλος</label>
          <input id="add-title" placeholder="π.χ. Κεφάλαιο 1"/>
        </div>
        <div class="form-group">
          <label>Κείμενο</label>
          <textarea id="add-content" placeholder="Επικόλλησε εδώ το κείμενο..."></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" id="add-text-cancel2">Άκυρο</button>
          <button class="btn btn-primary" id="add-text-save">Αποθήκευση</button>
        </div>
      </div>
    </div>

    <div id="edit-text-modal" class="modal-overlay">
      <div class="card modal-box">
        <div class="modal-header">
          <h3>✏️ Επεξεργασία Κειμένου</h3>
          <button class="btn-icon" id="edit-text-cancel">✕</button>
        </div>
        <div id="edit-text-error" class="error-msg" style="display:none"></div>
        <div class="form-group">
          <label>Τίτλος</label>
          <input id="edit-title" placeholder="Τίτλος κειμένου"/>
        </div>
        <div class="form-group">
          <label>Κείμενο</label>
          <textarea id="edit-content" placeholder="Κείμενο..."></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" id="edit-text-cancel2">Άκυρο</button>
          <button class="btn btn-primary" id="edit-text-save">💾 Αποθήκευση</button>
        </div>
      </div>
    </div>`;
}

/* ── Bind events ────────────────────────────────────────────────────────── */
function bindView() {
  // Navbar
  document.getElementById("btn-logout-nav")?.addEventListener("click", logout);
  document.getElementById("btn-history-nav")?.addEventListener("click", openHistory);

  // Breadcrumb clicks
  document.querySelectorAll(".bc-item:not(.current)").forEach(el => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.dataset.crumb);
      const crumbs = buildBreadcrumb();
      if (crumbs[idx]) navigate(crumbs[idx].view);
    });
  });

  // Back buttons
  const v = state.view;
  document.getElementById("btn-back")?.addEventListener("click", () => {
    if (v === "volume-select")  navigate("class-select");
    if (v === "chapter-select") navigate("volume-select");
    if (v === "text-select")    navigate("chapter-select");
    if (v === "exercise")       navigate("text-select");
  });
  document.getElementById("btn-back-home")?.addEventListener("click", () => navigate("class-select"));
  document.getElementById("btn-back-hist")?.addEventListener("click", openHistory);

  // Class cards
  document.querySelectorAll(".class-card").forEach(card => {
    card.addEventListener("click", () => {
      const cls = state.classes.find(c => c.id === card.dataset.clsId);
      if (cls) navigate("volume-select", { currentClass: cls });
    });
  });

  // Volume cards
  document.querySelectorAll(".volume-card").forEach(card => {
    card.addEventListener("click", () => {
      const vol = state.currentClass?.volumes.find(v => v.id === card.dataset.volId);
      if (vol) loadVolume(vol);
    });
  });

  // Chapter cards
  document.querySelectorAll(".chapter-card").forEach(card => {
    card.addEventListener("click", () => {
      navigate("text-select", { currentChapter: card.dataset.chapter });
    });
  });

  // Text cards
  document.querySelectorAll(".text-card").forEach(card => {
    card.addEventListener("click", () => openExercise(card.dataset.tid));
  });

  // Mode tabs
  document.querySelectorAll(".mode-tab").forEach(tab => {
    tab.addEventListener("click", () => navigate("exercise", { currentMode: tab.dataset.mode }));
  });

  // Record button
  document.getElementById("record-btn")?.addEventListener("click", toggleRecording);

  // History items
  document.querySelectorAll(".history-item").forEach(item => {
    item.addEventListener("click", () => openSessionDetail(parseInt(item.dataset.sid)));
  });

  // Add text modal
  document.querySelectorAll("[data-add-src]").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); openAddTextModal(btn.dataset.addSrc); });
  });
  document.getElementById("add-text-cancel")?.addEventListener("click", closeAddTextModal);
  document.getElementById("add-text-cancel2")?.addEventListener("click", closeAddTextModal);
  document.getElementById("add-text-save")?.addEventListener("click", saveNewText);

  // Edit text modal
  document.querySelectorAll(".tc-edit-btn").forEach(btn => {
    btn.addEventListener("click", e => { e.stopPropagation(); openEditModal(btn.dataset.editTid); });
  });
  document.getElementById("edit-text-cancel")?.addEventListener("click", closeEditModal);
  document.getElementById("edit-text-cancel2")?.addEventListener("click", closeEditModal);
  document.getElementById("edit-text-save")?.addEventListener("click", saveEditedText);
}

/* ── Volume loading ─────────────────────────────────────────────────────── */
async function loadVolume(vol) {
  state.currentVolume = vol;
  try {
    const [textsData, statsData] = await Promise.all([
      API(`/api/texts/${vol.id}`),
      API(`/api/stats/texts?source_id=${vol.id}`),
    ]);
    state.volumeTexts = textsData.texts || [];
    state.volumeStats = statsData || {};
    navigate("chapter-select");
  } catch (e) {
    alert("Σφάλμα φόρτωσης: " + e.message);
  }
}

async function refreshVolStats() {
  if (!state.currentVolume) return;
  try {
    state.volumeStats = await API(`/api/stats/texts?source_id=${state.currentVolume.id}`);
  } catch {}
}

/* ── Exercise logic ─────────────────────────────────────────────────────── */
async function openExercise(textId) {
  try {
    const text = await API(`/api/texts/${state.currentVolume.id}/${textId}`);
    state.currentText = text;
    state.currentMode = "normal";
    navigate("exercise");
  } catch (e) {
    alert("Σφάλμα φόρτωσης κειμένου: " + e.message);
  }
}

function toggleRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") stopRecording();
  else startRecording();
}

async function startRecording() {
  const btn = document.getElementById("record-btn");
  const label = document.getElementById("record-label");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
    mediaRecorder.onstop = onRecordingStop;
    mediaRecorder.start();
    recordingStartTime = Date.now();

    btn.classList.add("recording");
    btn.innerHTML = "⏹";
    label.textContent = "Διαβάζεις... (πάτα για να σταματήσεις)";
    label.classList.add("rec");

    if (state.currentMode === "wpm") {
      let remaining = 60;
      updateTimer(remaining, true);
      wpmCountdown = setInterval(() => {
        remaining--;
        updateTimer(remaining, true);
        if (remaining <= 0) { clearInterval(wpmCountdown); stopRecording(); }
      }, 1000);
    } else {
      updateTimer(0, false);
      timerInterval = setInterval(() => {
        updateTimer((Date.now() - recordingStartTime) / 1000, false);
      }, 500);
    }
  } catch (e) {
    alert("Δεν ήταν δυνατή η πρόσβαση στο μικρόφωνο: " + e.message);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  clearInterval(timerInterval);
  clearInterval(wpmCountdown);
  timerInterval = null;
  wpmCountdown = null;
}

async function onRecordingStop() {
  const btn = document.getElementById("record-btn");
  const label = document.getElementById("record-label");
  const resultsArea = document.getElementById("results-area");

  btn.disabled = true;
  btn.classList.remove("recording");
  btn.innerHTML = "🎙";
  label.classList.remove("rec");
  label.textContent = "";
  resultsArea.innerHTML = `
    <div class="card processing-msg">
      <div class="spinner"></div>
      <div>Επεξεργασία ήχου... (μπορεί να πάρει λίγα δευτερόλεπτα)</div>
    </div>`;

  const duration = (Date.now() - recordingStartTime) / 1000;
  const fd = new FormData();
  fd.append("audio", new Blob(audioChunks, { type: "audio/webm" }), "recording.webm");
  fd.append("text_id", state.currentText.id);
  fd.append("duration_sec", duration.toFixed(2));
  fd.append("mode", state.currentMode);

  try {
    const result = await APIform("/api/evaluate", fd);
    state.lastResult = result;
    showResults(result);
    refreshVolStats();
  } catch (e) {
    resultsArea.innerHTML = `<div class="card error-msg">Σφάλμα: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

function showResults(result) {
  const area = document.getElementById("results-area");
  const diff = result.diff_tokens ? renderDiff(result.diff_tokens) : "";
  area.innerHTML = `
    <div class="card results-box">
      <h3>📊 Αποτελέσματα</h3>
      ${renderScoreGrid(result)}
      <hr class="divider"/>
      <div class="diff-section">
        <h4>📄 Κείμενο — χρωματισμός ανάγνωσης</h4>
        <div class="diff-text">${diff}</div>
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
}

/* ── Score helpers ──────────────────────────────────────────────────────── */
function renderScoreGrid(data) {
  const acc = data.word_accuracy ?? 0;
  const wpm = data.wpm ?? 0;
  const punc = data.punctuation_score ?? 0;
  const overall = data.overall_score ?? 0;
  const mode = data.mode || state.currentMode;

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
      ${mode !== "wpm" ? `
      <div class="score-card ${scoreClass(punc)}">
        <div class="score-val">${punc.toFixed(0)}%</div>
        <div class="score-lbl">Στίξη</div>
      </div>` : ""}
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

function updateTimer(seconds, countdown) {
  const el = document.getElementById("timer-display");
  if (!el) return;
  const s = Math.max(0, Math.round(seconds));
  el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ── History ────────────────────────────────────────────────────────────── */
async function openHistory() {
  try {
    state.historySessions = await API("/api/history");
    navigate("history");
  } catch (e) {
    alert("Σφάλμα: " + e.message);
  }
}

async function openSessionDetail(sessionId) {
  try {
    state.sessionDetail = await API(`/api/history/${sessionId}`);
    navigate("session");
  } catch (e) {
    alert("Σφάλμα: " + e.message);
  }
}

/* ── Add text modal ─────────────────────────────────────────────────────── */
function openAddTextModal(sourceId) {
  _addTextSourceId = sourceId;
  document.getElementById("add-text-modal").classList.add("open");
  document.getElementById("add-title").value = "";
  document.getElementById("add-content").value = "";
  document.getElementById("add-text-error").style.display = "none";
}

function closeAddTextModal() {
  document.getElementById("add-text-modal").classList.remove("open");
}

/* ── Edit text modal ────────────────────────────────────────────────────── */
let _editTextId = null;

async function openEditModal(textId) {
  _editTextId = textId;
  const errEl = document.getElementById("edit-text-error");
  errEl.style.display = "none";
  document.getElementById("edit-title").value = "Φόρτωση...";
  document.getElementById("edit-content").value = "";
  document.getElementById("edit-text-modal").classList.add("open");

  try {
    const text = await API(`/api/texts/${state.currentVolume.id}/${textId}`);
    document.getElementById("edit-title").value = text.title;
    document.getElementById("edit-content").value = text.content;
  } catch (e) {
    errEl.textContent = "Σφάλμα φόρτωσης: " + e.message;
    errEl.style.display = "block";
  }
}

function closeEditModal() {
  document.getElementById("edit-text-modal").classList.remove("open");
}

async function saveEditedText() {
  const title   = document.getElementById("edit-title").value.trim();
  const content = document.getElementById("edit-content").value.trim();
  const errEl   = document.getElementById("edit-text-error");
  if (!title || !content) {
    errEl.textContent = "Τίτλος και κείμενο δεν μπορούν να είναι κενά.";
    errEl.style.display = "block";
    return;
  }
  const saveBtn = document.getElementById("edit-text-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Αποθήκευση...";
  try {
    await API(`/api/texts/${_editTextId}`, {
      method: "PUT",
      body: JSON.stringify({ title, content }),
    });
    closeEditModal();
    await loadVolume(state.currentVolume);
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = "block";
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Αποθήκευση";
  }
}

async function saveNewText() {
  const title = document.getElementById("add-title").value.trim();
  const content = document.getElementById("add-content").value.trim();
  const errEl = document.getElementById("add-text-error");
  if (!title || !content) {
    errEl.textContent = "Συμπλήρωσε τίτλο και κείμενο.";
    errEl.style.display = "block";
    return;
  }
  try {
    await API("/api/texts/add", {
      method: "POST",
      body: JSON.stringify({ source_id: _addTextSourceId, title, content, page_number: 0 }),
    });
    closeAddTextModal();
    await loadVolume(state.currentVolume);
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = "block";
  }
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
function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  render();
}

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
  return String(str).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ── Boot ───────────────────────────────────────────────────────────────── */
(async () => {
  if (state.token) {
    try {
      const me = await API("/api/auth/me");
      state.user = me;
      localStorage.setItem("user", JSON.stringify(me));
      await loadClasses();
    } catch {
      logout();
    }
  } else {
    render();
  }
})();
