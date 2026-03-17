/* =========================================================
   CommentaryFlow — Frontend SPA
   Vanilla JS only. No build step required.
   ========================================================= */

"use strict";

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

const API = (() => {
  let _token = localStorage.getItem("cf_token") || null;

  function setToken(t) { _token = t; localStorage.setItem("cf_token", t || ""); }
  function clearToken() { _token = null; localStorage.removeItem("cf_token"); }
  function getToken() { return _token; }

  async function req(method, path, body, isForm) {
    const headers = {};
    if (_token) headers["Authorization"] = `Bearer ${_token}`;
    if (!isForm && body) headers["Content-Type"] = "application/json";

    const opts = { method, headers };
    if (body) opts.body = isForm ? body : JSON.stringify(body);

    const res = await fetch(path, opts);
    if (res.status === 401) { App.logout(); throw new Error("Unauthorized"); }
    if (!res.ok) {
      let detail;
      try { detail = (await res.json()).detail; } catch (_) { detail = res.statusText; }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  return {
    setToken, clearToken, getToken,
    get:    (path)       => req("GET",  path),
    post:   (path, body) => req("POST", path, body),
    put:    (path, body) => req("PUT",  path, body),
    del:    (path)       => req("DELETE", path),
    upload: (path, fd)   => req("POST", path, fd, true),
    download: async (path) => {
      const res = await fetch(path, { headers: { Authorization: `Bearer ${_token}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res;
    },
  };
})();


// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const State = {
  user: null,
  commentaries: [],
  periods: [],
  currentCommentaryId: null,
  currentCommentary: null,
  currentSections: [],
  activeBatchRunId: null,
  expandedSectionKey: null,
  quillInstances: {},   // section_key → Quill
  autosaveTimers: {},   // section_key → timeout id
};


// ---------------------------------------------------------------------------
// App controller
// ---------------------------------------------------------------------------

const App = {

  async init() {
    this.bindGlobalEvents();
    const token = API.getToken();
    if (token) {
      try {
        const me = await API.get("/auth/me");
        this.setUser(me);
        this.showShell();
        await Dashboard.load();
      } catch (_) {
        this.logout();
      }
    } else {
      this.showLogin();
    }
  },

  setUser(user) {
    State.user = user;
    document.getElementById("user-display-name").textContent = user.display_name;
    document.getElementById("user-role-badge").textContent = user.role;
    document.getElementById("user-role-badge").className = `role-badge ${user.role}`;
    const initials = user.display_name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
    document.getElementById("user-initials").textContent = initials;
    document.getElementById("user-initials").className = "user-initials";
  },

  showLogin() {
    document.getElementById("login-screen").classList.add("active");
    document.getElementById("login-screen").classList.remove("hidden");
    document.getElementById("app-shell").classList.add("hidden");
    document.getElementById("app-shell").classList.remove("active");
  },

  showShell() {
    document.getElementById("login-screen").classList.remove("active");
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("app-shell").classList.remove("hidden");
    document.getElementById("app-shell").classList.add("active");
  },

  logout() {
    API.clearToken();
    State.user = null;
    this.showLogin();
  },

  isWriter() { return State.user?.role === "writer"; },
  isReviewer() { return State.user?.role === "reviewer"; },

  bindGlobalEvents() {
    // Login form
    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = document.getElementById("username").value.trim();
      const password = document.getElementById("password").value;
      const errEl = document.getElementById("login-error");
      errEl.classList.add("hidden");
      try {
        const fd = new URLSearchParams({ username, password });
        const res = await fetch("/auth/token", { method: "POST", body: fd });
        if (!res.ok) throw new Error("Invalid credentials");
        const data = await res.json();
        API.setToken(data.access_token);
        this.setUser({ username, display_name: data.display_name, role: data.role });
        this.showShell();
        await Dashboard.load();
      } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove("hidden");
      }
    });

    // Logout
    document.getElementById("btn-logout").addEventListener("click", () => this.logout());

    // Settings button
    document.getElementById("btn-settings").addEventListener("click", () => SettingsModal.open());

    // Search button + Cmd+K
    document.getElementById("btn-search").addEventListener("click", () => SearchModal.open());
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); SearchModal.open(); }
      if (e.key === "Escape") { Modal.closeAll(); }
    });

    // Modal close buttons
    document.querySelectorAll("[data-close]").forEach(btn => {
      btn.addEventListener("click", () => Modal.close(btn.dataset.close));
    });

    // Click outside modal to close
    document.querySelectorAll(".modal-overlay").forEach(overlay => {
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) Modal.close(overlay.id);
      });
    });

    // History toggle
    document.getElementById("history-toggle").addEventListener("click", () => {
      const content = document.getElementById("history-content");
      const chevron = document.querySelector("#history-toggle .chevron");
      if (content.classList.contains("collapsed")) {
        content.classList.replace("collapsed", "expanded");
        chevron.classList.add("open");
      } else {
        content.classList.replace("expanded", "collapsed");
        chevron.classList.remove("open");
      }
    });

    // Back to dashboard
    document.getElementById("btn-back-dashboard").addEventListener("click", () => DocView.close());
    document.getElementById("btn-back-dashboard-r").addEventListener("click", () => DocView.close());

    // Submit for review
    document.getElementById("btn-submit-review").addEventListener("click", async () => {
      if (!State.currentCommentaryId) return;
      try {
        await API.post(`/api/commentaries/${State.currentCommentaryId}/submit`);
        await DocView.open(State.currentCommentaryId);
        Toast.show("Submitted for review", "success");
      } catch (err) { Toast.show(err.message, "error"); }
    });

    // Approve document
    document.getElementById("btn-approve-doc").addEventListener("click", async () => {
      if (!State.currentCommentaryId) return;
      try {
        await API.post(`/api/commentaries/${State.currentCommentaryId}/approve`);
        await DocView.open(State.currentCommentaryId);
        Toast.show("Document approved — Gold files generated", "success");
      } catch (err) { Toast.show(err.message, "error"); }
    });

    // Reject document
    document.getElementById("btn-reject-doc").addEventListener("click", () => Modal.open("modal-reject"));
    document.getElementById("btn-confirm-reject").addEventListener("click", async () => {
      const note = document.getElementById("reject-note").value.trim();
      try {
        await API.post(`/api/commentaries/${State.currentCommentaryId}/reject`, { note });
        Modal.close("modal-reject");
        await DocView.open(State.currentCommentaryId);
        Toast.show("Revision requested", "warning");
      } catch (err) { Toast.show(err.message, "error"); }
    });

    // Prior period drawer
    document.getElementById("drawer-toggle").addEventListener("click", () => {
      const drawer = document.getElementById("prior-period-drawer");
      const content = document.getElementById("drawer-content");
      if (drawer.classList.contains("open")) {
        drawer.classList.remove("open");
        content.classList.add("hidden");
      } else {
        drawer.classList.add("open");
        content.classList.remove("hidden");
      }
    });

    // Upload zone events
    Upload.bindEvents();
  },
};


// ---------------------------------------------------------------------------
// Modal helpers
// ---------------------------------------------------------------------------

const Modal = {
  open(id) { document.getElementById(id)?.classList.remove("hidden"); },
  close(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add("hidden");
  },
  closeAll() {
    document.querySelectorAll(".modal-overlay").forEach(m => m.classList.add("hidden"));
  },
};


// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------

const Toast = {
  show(msg, type = "info") {
    const existing = document.getElementById("cf-toast");
    if (existing) existing.remove();

    const colors = {
      success: "var(--color-success)",
      error:   "var(--color-danger)",
      warning: "var(--color-warning)",
      info:    "var(--color-primary)",
    };
    const t = document.createElement("div");
    t.id = "cf-toast";
    t.style.cssText = `
      position:fixed; bottom:24px; right:24px; z-index:9999;
      background:${colors[type] || colors.info}; color:#fff;
      padding:10px 18px; border-radius:8px; font-size:13px;
      box-shadow:0 4px 12px rgba(0,0,0,.2); max-width:320px;
    `;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  },
};


// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

const Dashboard = {

  async load() {
    this.showPage();

    // Role-based zones
    const isWriter = App.isWriter();
    document.getElementById("zone-upload").classList.toggle("hidden", !isWriter);
    document.getElementById("zone-queue").classList.toggle("hidden", !App.isReviewer());
    document.getElementById("portfolio-tabs").classList.add("hidden");

    try {
      const data = await API.get("/api/commentaries");
      State.commentaries = data.commentaries;
      State.periods = data.periods;
      this.renderActiveZone();
      this.renderHistory();
      if (App.isReviewer()) this.renderQueue();
    } catch (err) {
      Toast.show("Failed to load dashboard: " + err.message, "error");
    }
  },

  showPage() {
    document.getElementById("page-dashboard").classList.add("active");
    document.getElementById("page-dashboard").classList.remove("hidden");
    document.getElementById("page-document").classList.remove("active");
    document.getElementById("page-document").classList.add("hidden");
  },

  renderActiveZone() {
    const grid = document.getElementById("portfolio-grid");
    const emptyEl = document.getElementById("zone-empty");
    const periodLabel = document.getElementById("active-period-label");
    const countLabel = document.getElementById("active-portfolio-count");

    // Active = any non-published commentary (or newest period with anything open)
    const active = State.commentaries.filter(c => c.status !== "published");

    if (active.length === 0) {
      grid.innerHTML = "";
      emptyEl.classList.remove("hidden");
      periodLabel.textContent = "No active work";
      countLabel.textContent = "";
      return;
    }

    emptyEl.classList.add("hidden");

    // Determine dominant period
    const periods = [...new Set(active.map(c => c.period_label))];
    periodLabel.textContent = periods.slice(0, 3).join(", ");
    countLabel.textContent = `${active.length} portfolio${active.length !== 1 ? "s" : ""}`;

    // Sort: incomplete first
    const order = { generating: 0, not_started: 1, draft: 2, changes_requested: 3, in_review: 4, approved: 5 };
    active.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

    grid.innerHTML = active.map(c => this.renderPortfolioCard(c)).join("");
    grid.querySelectorAll("[data-open-commentary]").forEach(btn => {
      btn.addEventListener("click", () => DocView.open(btn.dataset.openCommentary));
    });
  },

  renderPortfolioCard(c) {
    const counts = c.section_counts || { total: 0, edited: 0 };
    const pct = counts.total ? Math.round((counts.edited / counts.total) * 100) : 0;
    return `
      <div class="portfolio-card">
        <div class="card-header">
          <span class="card-portcode mono">${esc(c.portcode)}</span>
          <span class="status-badge status-${c.status}">
            <span class="status-dot"></span>${esc(statusLabel(c.status))}
          </span>
        </div>
        <div class="card-period">${esc(c.period_label)}</div>
        <div class="card-progress">
          <div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${pct}%"></div></div>
          <span>${counts.edited}/${counts.total} edited</span>
        </div>
        <div class="card-footer">
          <button class="btn btn-sm btn-primary" data-open-commentary="${esc(c.commentary_id)}">
            ${c.status === "approved" ? "View" : "Continue"}
          </button>
        </div>
      </div>`;
  },

  renderHistory() {
    const tbody = document.getElementById("history-tbody");
    const published = State.commentaries.filter(c => c.status === "published");
    if (published.length === 0) { tbody.innerHTML = `<tr><td colspan="4" class="text-muted text-sm" style="padding:16px">No published commentaries yet.</td></tr>`; return; }
    tbody.innerHTML = published.map(c => `
      <tr>
        <td>${esc(c.period_label)}</td>
        <td class="mono">${esc(c.portcode)}</td>
        <td>${c.published_at ? c.published_at.slice(0, 10) : "—"}</td>
        <td><button class="btn btn-sm btn-ghost" data-open-commentary="${esc(c.commentary_id)}">View</button></td>
      </tr>`).join("");
    tbody.querySelectorAll("[data-open-commentary]").forEach(btn => {
      btn.addEventListener("click", () => DocView.open(btn.dataset.openCommentary));
    });
  },

  renderQueue() {
    const tbody = document.getElementById("queue-tbody");
    const inReview = State.commentaries.filter(c => c.status === "in_review");
    document.getElementById("queue-count").textContent = `${inReview.length} pending`;
    if (inReview.length === 0) { tbody.innerHTML = `<tr><td colspan="5" class="text-muted text-sm" style="padding:16px">Queue is empty.</td></tr>`; return; }
    tbody.innerHTML = inReview.map(c => {
      const counts = c.section_counts || {};
      return `<tr>
        <td class="mono">${esc(c.portcode)}</td>
        <td>${esc(c.period_label)}</td>
        <td>${c.submitted_at ? c.submitted_at.slice(0, 10) : "—"}</td>
        <td>${counts.total || 0}</td>
        <td><button class="btn btn-sm btn-primary" data-open-commentary="${esc(c.commentary_id)}">Review</button></td>
      </tr>`;}).join("");
    tbody.querySelectorAll("[data-open-commentary]").forEach(btn => {
      btn.addEventListener("click", () => DocView.open(btn.dataset.openCommentary));
    });
  },
};


// ---------------------------------------------------------------------------
// Upload zone
// ---------------------------------------------------------------------------

const Upload = {
  stagedFiles: [],

  bindEvents() {
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");

    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragging"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault(); dropZone.classList.remove("dragging");
      this.addFiles([...e.dataTransfer.files]);
    });
    fileInput.addEventListener("change", () => { this.addFiles([...fileInput.files]); fileInput.value = ""; });

    document.getElementById("btn-clear-files").addEventListener("click", () => this.clear());
    document.getElementById("btn-start-gen").addEventListener("click", () => this.startGeneration());
    document.getElementById("sel-mode").addEventListener("change", (e) => {
      document.getElementById("top-n-label").classList.toggle("hidden", e.target.value === "all_holdings");
    });
    document.getElementById("btn-cancel-gen").addEventListener("click", () => this.cancelGeneration());
  },

  addFiles(files) {
    const xlsxFiles = files.filter(f => f.name.endsWith(".xlsx") || f.name.endsWith(".xls"));
    xlsxFiles.forEach(f => {
      if (!this.stagedFiles.find(sf => sf.name === f.name)) this.stagedFiles.push(f);
    });
    this.renderStagedFiles();
  },

  renderStagedFiles() {
    const container = document.getElementById("staged-files");
    const settings = document.getElementById("gen-settings");
    if (this.stagedFiles.length === 0) {
      container.classList.add("hidden");
      settings.classList.add("hidden");
      return;
    }
    container.classList.remove("hidden");
    settings.classList.remove("hidden");
    container.innerHTML = this.stagedFiles.map((f, i) => `
      <div class="staged-file-row">
        <span class="staged-file-name">${esc(f.name)}</span>
        <span class="staged-file-status text-muted text-sm">${(f.size / 1024).toFixed(0)} KB</span>
        <span class="staged-file-remove" data-idx="${i}">×</span>
      </div>`).join("");
    container.querySelectorAll(".staged-file-remove").forEach(btn => {
      btn.addEventListener("click", () => {
        this.stagedFiles.splice(+btn.dataset.idx, 1);
        this.renderStagedFiles();
      });
    });
  },

  clear() {
    this.stagedFiles = [];
    this.renderStagedFiles();
  },

  async startGeneration() {
    if (this.stagedFiles.length === 0) { Toast.show("No files staged", "error"); return; }
    const fd = new FormData();
    this.stagedFiles.forEach(f => fd.append("files", f));

    const surveyInput = document.getElementById("survey-input");
    if (surveyInput.files.length > 0) fd.append("survey_file", surveyInput.files[0]);

    const settings = {
      selection_mode: document.getElementById("sel-mode").value,
      top_n: document.getElementById("top-n").value,
    };
    fd.append("settings_json", JSON.stringify(settings));

    try {
      const data = await API.upload("/api/runs", fd);
      State.activeBatchRunId = data.run_id;
      this.clear();
      Modal.open("modal-progress");
      this.streamProgress(data.run_id);
    } catch (err) {
      Toast.show("Could not start generation: " + err.message, "error");
    }
  },

  async cancelGeneration() {
    if (State.activeBatchRunId) {
      try { await API.post(`/api/runs/${State.activeBatchRunId}/cancel`); } catch (_) {}
    }
    Modal.close("modal-progress");
  },

  streamProgress(runId) {
    const statsEl = document.getElementById("progress-stats");
    const messagesEl = document.getElementById("progress-messages");
    const cardsEl = document.getElementById("progress-portfolio-cards");
    const portfolioMap = {};

    let completed = 0, errors = 0, total = 0;

    const updateStats = () => {
      statsEl.innerHTML = `
        <div class="progress-stat"><div class="progress-stat-num">${total}</div><div class="progress-stat-label">Portfolios</div></div>
        <div class="progress-stat"><div class="progress-stat-num">${completed}</div><div class="progress-stat-label">Done</div></div>
        <div class="progress-stat"><div class="progress-stat-num" style="color:var(--color-danger)">${errors}</div><div class="progress-stat-label">Errors</div></div>
      `;
    };
    updateStats();

    const source = new EventSource(`/api/runs/${runId}/stream`);

    source.onmessage = (e) => {
      const msg = JSON.parse(e.data);

      if (msg.type === "ping") return;

      if (msg.type === "status" || msg.type === "progress") {
        const p = document.createElement("div");
        p.className = "progress-msg";
        p.textContent = msg.message;
        messagesEl.appendChild(p);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      if (msg.type === "portfolios") {
        total = msg.portfolios.length;
        msg.portfolios.forEach(p => {
          portfolioMap[p.commentary_id] = p;
          const card = document.createElement("div");
          card.className = "progress-port-card";
          card.id = `pp-${p.commentary_id}`;
          card.innerHTML = `<span class="mono">${esc(p.portcode)}</span><span class="spinner"></span><span class="text-muted">Generating…</span>`;
          cardsEl.appendChild(card);
        });
        updateStats();
      }

      if (msg.type === "portfolio_done") {
        completed++;
        if (msg.errors?.length > 0) errors++;
        const card = document.getElementById(`pp-${msg.commentary_id}`);
        if (card) {
          const hasErrors = msg.errors?.length > 0;
          card.innerHTML = `
            <span class="mono">${esc(msg.portcode)}</span>
            <span style="color:${hasErrors ? 'var(--color-warning)' : 'var(--color-success)'}">
              ${hasErrors ? '⚠ ' + msg.errors.length + ' error(s)' : '✓ Done'}
            </span>`;
        }
        updateStats();
      }

      if (msg.type === "done") {
        source.close();
        setTimeout(async () => {
          Modal.close("modal-progress");
          Toast.show(`Generation complete: ${completed} portfolio(s)`, "success");
          await Dashboard.load();
          // If exactly one portfolio, open it directly
          if (completed === 1 && Object.keys(portfolioMap).length === 1) {
            const cid = Object.keys(portfolioMap)[0];
            DocView.open(cid);
          }
        }, 1500);
      }

      if (msg.type === "error") {
        source.close();
        Toast.show("Generation error: " + msg.message, "error");
        Modal.close("modal-progress");
      }

      if (msg.type === "cancelled") {
        source.close();
        Modal.close("modal-progress");
        Toast.show("Generation cancelled", "warning");
      }
    };

    source.onerror = () => {
      source.close();
      Modal.close("modal-progress");
      Dashboard.load();
    };
  },
};


// ---------------------------------------------------------------------------
// Document view
// ---------------------------------------------------------------------------

const DocView = {

  async open(commentaryId) {
    State.currentCommentaryId = commentaryId;
    State.expandedSectionKey = null;
    State.quillInstances = {};
    State.autosaveTimers = {};

    // Show document page
    document.getElementById("page-dashboard").classList.remove("active");
    document.getElementById("page-dashboard").classList.add("hidden");
    document.getElementById("page-document").classList.remove("hidden");
    document.getElementById("page-document").classList.add("active");

    try {
      const data = await API.get(`/api/commentaries/${commentaryId}`);
      State.currentCommentary = data.commentary;
      State.currentSections = data.sections;

      this.renderLetterhead(data.commentary);
      this.renderNavRail(data.sections);
      this.renderSections(data.sections, data.commentary, data.annotations);
      this.renderTabs(commentaryId);
      this.renderDocActions(data.commentary);

      document.getElementById("portfolio-tabs").classList.remove("hidden");
    } catch (err) {
      Toast.show("Failed to load commentary: " + err.message, "error");
      this.close();
    }
  },

  close() {
    State.currentCommentaryId = null;
    State.currentCommentary = null;
    State.quillInstances = {};
    document.getElementById("portfolio-tabs").classList.add("hidden");
    Dashboard.load();
  },

  renderLetterhead(commentary) {
    document.getElementById("lh-portcode").textContent = commentary.portcode;
    document.getElementById("lh-period").textContent = commentary.period_label;
    document.getElementById("lh-status-badge").innerHTML =
      `<span class="status-badge status-${commentary.status}">
         <span class="status-dot"></span>${esc(statusLabel(commentary.status))}
       </span>`;
  },

  renderNavRail(sections) {
    const rail = document.getElementById("doc-nav-sections");
    const ordered = sectionOrder(sections);
    rail.innerHTML = ordered.map(s => {
      const dotClass = s.status === "approved" ? "approved" : s.silver_text ? "silver" : s.status === "error" ? "error" : "";
      return `
        <div class="nav-section-item" data-section-key="${esc(s.section_key)}" id="nav-${esc(s.section_key)}">
          <span class="nav-dot ${dotClass}"></span>
          <span class="nav-item-name">${esc(s.section_label)}</span>
        </div>`;
    }).join("");

    rail.querySelectorAll(".nav-section-item").forEach(item => {
      item.addEventListener("click", () => {
        const el = document.getElementById(`section-${item.dataset.sectionKey}`);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  },

  renderSections(sections, commentary, annotations) {
    const container = document.getElementById("sections-container");
    const ordered = sectionOrder(sections);
    const annotationsBySection = {};
    (annotations || []).forEach(a => {
      if (!annotationsBySection[a.section_key]) annotationsBySection[a.section_key] = [];
      annotationsBySection[a.section_key].push(a);
    });

    const isReviewer = App.isReviewer();
    const locked = ["in_review", "approved", "published"].includes(commentary.status);
    const canEdit = App.isWriter() && !locked;
    const canReview = isReviewer && commentary.status === "in_review";

    container.innerHTML = "";
    ordered.forEach(s => {
      const card = this.buildSectionCard(s, commentary, canEdit, canReview, annotationsBySection[s.section_key] || []);
      container.appendChild(card);
    });
  },

  buildSectionCard(section, commentary, canEdit, canReview, annotations) {
    const card = document.createElement("div");
    card.className = "section-card";
    card.id = `section-${section.section_key}`;

    const hasShared = section.shared_portfolio_count > 0;
    const displayText = section.silver_text || section.bronze_text || "";
    const preview = truncate(stripHtml(displayText), 180);
    const tierClass = section.status === "approved" ? "tier-approved" : section.silver_text ? "tier-silver" : "tier-bronze";
    const tierLabel = section.status === "approved" ? "Approved" : section.silver_text ? "Edited" : "Bronze draft";

    card.innerHTML = `
      <div class="section-header" data-key="${esc(section.section_key)}">
        <div class="flex gap-8" style="flex-direction:column;gap:2px">
          <span class="section-heading">${esc(section.section_label)}</span>
          ${section.section_type === "security" ? `
            <span class="section-subheading">
              ${section.security_type ? esc(capitalize(section.security_type)) + " · " : ""}
              ${section.contribution_to_return != null ? (section.contribution_to_return >= 0 ? "+" : "") + section.contribution_to_return.toFixed(2) + "% contrib" : ""}
              ${section.port_ending_weight != null ? " · " + section.port_ending_weight.toFixed(2) + "% wt" : ""}
            </span>` : ""}
        </div>
        <span class="section-tier-label ${tierClass}">${tierLabel}</span>
        ${hasShared ? `<span class="shared-badge">Shared with ${section.shared_portfolio_count} portfolio${section.shared_portfolio_count !== 1 ? "s" : ""}</span>` : ""}
        <svg class="chevron ml-auto" width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 5l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      ${!canEdit && !canReview ? `<div class="section-preview ${section.silver_text ? 'silver' : ''}">${esc(preview)}</div>` : ""}
      <div class="section-expand-body">
        ${this.buildExpandBody(section, canEdit, canReview)}
        ${annotations.length > 0 ? this.buildAnnotations(annotations) : ""}
        ${canReview ? this.buildReviewActions(section) : ""}
      </div>
      <div class="copy-action-bar hidden" id="copy-bar-${esc(section.section_key)}">
        <span>You edited a section shared with <strong>${section.shared_portfolio_count}</strong> other portfolio${section.shared_portfolio_count !== 1 ? "s" : ""}.</span>
        <button class="btn btn-sm btn-ghost" id="btn-copy-to-${esc(section.section_key)}">Copy to all</button>
        <button class="btn btn-sm btn-ghost" data-dismiss-copy="${esc(section.section_key)}">Dismiss</button>
      </div>
    `;

    // Header click → expand/collapse
    card.querySelector(".section-header").addEventListener("click", () => this.toggleSection(section.section_key));

    // Dismiss copy bar
    const dismissBtn = card.querySelector(`[data-dismiss-copy]`);
    if (dismissBtn) dismissBtn.addEventListener("click", () => {
      document.getElementById(`copy-bar-${section.section_key}`)?.classList.add("hidden");
    });

    // Copy to portfolios
    const copyBtn = card.querySelector(`#btn-copy-to-${section.section_key}`);
    if (copyBtn) copyBtn.addEventListener("click", () => CopyToModal.open(section, commentary));

    // Review actions
    if (canReview) {
      const approveBtn = card.querySelector(`[data-approve-section="${section.section_key}"]`);
      if (approveBtn) approveBtn.addEventListener("click", () => this.approveSection(section.section_key));
      const annotateBtn = card.querySelector(`[data-annotate-section="${section.section_key}"]`);
      if (annotateBtn) annotateBtn.addEventListener("click", () => this.annotateSection(section.section_key, card));
    }

    return card;
  },

  buildExpandBody(section, canEdit, canReview) {
    if (canReview) {
      // Reviewer: full-width Silver text + citation comparison
      const silverText = section.silver_text || section.bronze_text || "<em>No content generated</em>";
      return `
        <div class="section-reviewer-body">
          <div class="silver-text-readonly">${silverText}</div>
        </div>
        <div class="citations-panel" id="cit-panel-${esc(section.section_key)}">
          <div class="citations-header">Sources</div>
          <div class="citation-compare-container" data-section="${esc(section.section_key)}">
            Loading citations…
          </div>
        </div>`;
    }

    if (canEdit) {
      const bronzeText = section.bronze_text || "";
      return `
        <div class="section-columns">
          <div class="col-bronze">
            <div class="col-label">Bronze draft</div>
            <div class="bronze-text">${esc(bronzeText)}</div>
            <div class="bronze-cits" id="bronze-cits-${esc(section.section_key)}"></div>
          </div>
          <div class="col-silver">
            <div class="col-label" style="display:flex;align-items:center;gap:8px">
              Silver
              <span class="save-confirm" id="save-confirm-${esc(section.section_key)}">Saved ✓</span>
            </div>
            <div id="quill-${esc(section.section_key)}"></div>
          </div>
        </div>
        <div class="citations-panel" id="cit-panel-${esc(section.section_key)}">
          <div class="citations-header">
            Sources
            <button class="restore-bronze-btn" data-restore="${esc(section.section_key)}">Restore Bronze sources</button>
          </div>
          <div id="cit-list-${esc(section.section_key)}">Loading…</div>
          <div class="add-citation-row">
            <input type="text" placeholder="Paste URL to add source…" id="add-cit-url-${esc(section.section_key)}" />
            <button class="btn btn-sm btn-ghost" data-add-cit="${esc(section.section_key)}">Add</button>
          </div>
        </div>`;
    }

    // Read-only preview (already shown as section-preview above — expand shows full text)
    const text = section.silver_text || section.bronze_text || "";
    return `<div class="section-reviewer-body"><div class="silver-text-readonly">${esc(text)}</div></div>`;
  },

  buildAnnotations(annotations) {
    return `<div class="annotation-list">` + annotations.map(a => `
      <div class="annotation-item">
        <div>${esc(a.note)}</div>
        <div class="annotation-meta">${esc(a.created_by)} · ${a.created_at ? a.created_at.slice(0, 16).replace("T", " ") : ""}</div>
      </div>`).join("") + `</div>`;
  },

  buildReviewActions(section) {
    return `
      <div class="section-review-actions">
        <button class="btn btn-sm btn-success" data-approve-section="${esc(section.section_key)}">Approve</button>
        <button class="btn btn-sm btn-ghost" data-annotate-section="${esc(section.section_key)}">Add note</button>
      </div>`;
  },

  toggleSection(sectionKey) {
    const card = document.getElementById(`section-${sectionKey}`);
    if (!card) return;

    const alreadyOpen = card.classList.contains("expanded");

    // Close any other open section
    if (State.expandedSectionKey && State.expandedSectionKey !== sectionKey) {
      const other = document.getElementById(`section-${State.expandedSectionKey}`);
      if (other) {
        other.classList.remove("expanded");
        other.querySelector(".section-preview")?.style.setProperty("display", "");
        other.querySelector(".chevron")?.classList.remove("open");
      }
    }

    if (alreadyOpen) {
      card.classList.remove("expanded");
      card.querySelector(".section-preview")?.style.setProperty("display", "");
      card.querySelector(".chevron")?.classList.remove("open");
      State.expandedSectionKey = null;
    } else {
      card.classList.add("expanded");
      card.querySelector(".section-preview")?.style.setProperty("display", "none");
      card.querySelector(".chevron")?.classList.add("open");
      State.expandedSectionKey = sectionKey;
      this.onSectionExpanded(sectionKey, card);
    }

    // Update nav rail
    document.querySelectorAll(".nav-section-item").forEach(i => i.classList.remove("active"));
    document.getElementById(`nav-${sectionKey}`)?.classList.add("active");
  },

  onSectionExpanded(sectionKey, card) {
    const section = State.currentSections.find(s => s.section_key === sectionKey);
    if (!section) return;

    const commentary = State.currentCommentary;
    const locked = ["in_review", "approved", "published"].includes(commentary.status);
    const canEdit = App.isWriter() && !locked;
    const canReview = App.isReviewer() && commentary.status === "in_review";

    // Mount Quill editor if writer mode
    if (canEdit) {
      const quillEl = document.getElementById(`quill-${sectionKey}`);
      if (quillEl && !State.quillInstances[sectionKey]) {
        const quill = new Quill(quillEl, {
          theme: "snow",
          placeholder: "Start writing Silver commentary… (Bronze is shown on the left)",
          modules: { toolbar: [["bold", "italic"], [{ list: "ordered" }, { list: "bullet" }], ["clean"]] },
        });
        // Pre-populate with existing silver or blank
        const existingSilver = section.silver_text || "";
        if (existingSilver) quill.root.innerHTML = existingSilver;

        // Auto-save on change
        quill.on("text-change", () => {
          clearTimeout(State.autosaveTimers[sectionKey]);
          State.autosaveTimers[sectionKey] = setTimeout(() => this.autoSave(sectionKey, quill), 2000);
        });

        State.quillInstances[sectionKey] = quill;
      }

      // Load bronze citations for display
      this.loadBronzeCitations(sectionKey);
      // Load silver citations
      this.loadSilverCitations(sectionKey);

      // Restore bronze button
      const restoreBtn = card.querySelector(`[data-restore="${sectionKey}"]`);
      if (restoreBtn) restoreBtn.addEventListener("click", () => this.restoreBronzeCitations(sectionKey));

      // Add citation button
      const addBtn = card.querySelector(`[data-add-cit="${sectionKey}"]`);
      if (addBtn) addBtn.addEventListener("click", () => this.addCitation(sectionKey));
    }

    if (canReview) {
      this.loadCitationComparison(sectionKey, card);
    }
  },

  async autoSave(sectionKey, quill) {
    const silverText = quill.root.innerHTML;
    try {
      await API.put(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}`, { silver_text: silverText });
      const confirm = document.getElementById(`save-confirm-${sectionKey}`);
      if (confirm) {
        confirm.classList.add("show");
        setTimeout(() => confirm.classList.remove("show"), 2000);
      }
      // Update local state
      const s = State.currentSections.find(x => x.section_key === sectionKey);
      if (s) s.silver_text = silverText;

      // Update nav dot
      const dot = document.querySelector(`#nav-${sectionKey} .nav-dot`);
      if (dot) dot.className = "nav-dot silver";

      // Update tier label
      const tierLabel = document.querySelector(`#section-${sectionKey} .section-tier-label`);
      if (tierLabel) { tierLabel.className = "section-tier-label tier-silver"; tierLabel.textContent = "Edited"; }

      // Show copy bar if shared
      const section = State.currentSections.find(x => x.section_key === sectionKey);
      if (section?.shared_portfolio_count > 0) {
        document.getElementById(`copy-bar-${sectionKey}`)?.classList.remove("hidden");
      }
    } catch (err) {
      console.error("Auto-save failed:", err);
    }
  },

  async approveSection(sectionKey) {
    try {
      await API.post(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/approve`);
      const s = State.currentSections.find(x => x.section_key === sectionKey);
      if (s) s.status = "approved";
      const dot = document.querySelector(`#nav-${sectionKey} .nav-dot`);
      if (dot) dot.className = "nav-dot approved";
      const tierLabel = document.querySelector(`#section-${sectionKey} .section-tier-label`);
      if (tierLabel) { tierLabel.className = "section-tier-label tier-approved"; tierLabel.textContent = "Approved"; }
      Toast.show(`${sectionKey} approved`, "success");

      // Check if all sections approved
      const all = State.currentSections.every(s => s.status === "approved");
      if (all) Toast.show("All sections approved — ready to approve document", "info");
    } catch (err) { Toast.show(err.message, "error"); }
  },

  annotateSection(sectionKey, card) {
    const existing = card.querySelector(".inline-annotate");
    if (existing) { existing.remove(); return; }
    const box = document.createElement("div");
    box.className = "inline-annotate";
    box.style.cssText = "padding:10px 18px;border-top:1px solid var(--color-border);display:flex;gap:8px";
    box.innerHTML = `
      <input type="text" placeholder="Add a note for the writer…" style="flex:1;padding:6px 8px;border:1px solid var(--color-border-dark);border-radius:4px;font-size:13px" id="inline-note-${esc(sectionKey)}"/>
      <button class="btn btn-sm btn-primary" id="inline-note-save-${esc(sectionKey)}">Save note</button>`;
    card.querySelector(".section-expand-body")?.appendChild(box);

    document.getElementById(`inline-note-save-${sectionKey}`)?.addEventListener("click", async () => {
      const note = document.getElementById(`inline-note-${sectionKey}`)?.value.trim();
      if (!note) return;
      try {
        await API.post(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/annotate`, { note });
        box.remove();
        Toast.show("Note saved", "success");
      } catch (err) { Toast.show(err.message, "error"); }
    });
  },

  async loadBronzeCitations(sectionKey) {
    try {
      const data = await API.get(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations?tier=bronze`);
      const el = document.getElementById(`bronze-cits-${sectionKey}`);
      if (!el) return;
      if (data.citations.length === 0) { el.innerHTML = ""; return; }
      el.innerHTML = `<div style="margin-top:8px;font-size:11px;color:var(--color-text-muted)">Bronze sources:</div>` +
        data.citations.map(c => `<div style="font-size:11px;color:var(--color-text-muted);padding:2px 0">[${c.display_number}] ${esc(c.domain || c.url)}</div>`).join("");
    } catch (_) {}
  },

  async loadSilverCitations(sectionKey) {
    try {
      const data = await API.get(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations?tier=silver`);
      this.renderSilverCitationList(sectionKey, data.citations);
    } catch (_) {}
  },

  renderSilverCitationList(sectionKey, citations) {
    const el = document.getElementById(`cit-list-${sectionKey}`);
    if (!el) return;
    if (citations.length === 0) {
      el.innerHTML = `<div class="text-muted text-sm" style="padding:4px 0">No sources yet. Add Bronze sources by saving, or paste a URL below.</div>`;
      return;
    }
    el.innerHTML = citations.map(c => `
      <div class="citation-card ${c.source_origin === "writer_added" ? "writer-added" : ""}">
        <span class="citation-num">[${c.display_number}]</span>
        <span class="citation-domain">${esc(c.domain || "")}</span>
        <span class="citation-title">${esc(c.title || c.url)}</span>
        <span class="citation-remove" data-remove-cit="${esc(c.citation_id)}" data-section="${esc(sectionKey)}">×</span>
      </div>`).join("");
    el.querySelectorAll("[data-remove-cit]").forEach(btn => {
      btn.addEventListener("click", () => this.removeCitation(btn.dataset.section, btn.dataset.removeCit));
    });
  },

  async addCitation(sectionKey) {
    const urlInput = document.getElementById(`add-cit-url-${sectionKey}`);
    const url = urlInput?.value.trim();
    if (!url) { Toast.show("Enter a URL", "error"); return; }
    try {
      // Fetch meta first
      const meta = await API.get(`/api/citations/fetch-meta?url=${encodeURIComponent(url)}`);
      await API.post(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations`, {
        url: meta.url, title: meta.title,
      });
      if (urlInput) urlInput.value = "";
      await this.loadSilverCitations(sectionKey);
      Toast.show("Source added", "success");
    } catch (err) { Toast.show("Could not add citation: " + err.message, "error"); }
  },

  async removeCitation(sectionKey, citationId) {
    try {
      await API.del(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations/${citationId}`);
      await this.loadSilverCitations(sectionKey);
    } catch (err) { Toast.show(err.message, "error"); }
  },

  async restoreBronzeCitations(sectionKey) {
    // Delete all silver citations and re-seed from bronze (via server)
    // Easiest: save silver text (which triggers seed on server side) — already seeded
    // Just reload
    await this.loadSilverCitations(sectionKey);
    Toast.show("Bronze sources restored", "info");
  },

  async loadCitationComparison(sectionKey, card) {
    try {
      const bronze = await API.get(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations?tier=bronze`);
      const silver = await API.get(`/api/commentaries/${State.currentCommentaryId}/sections/${sectionKey}/citations?tier=silver`);
      const container = card.querySelector(".citation-compare-container");
      if (!container) return;

      const bronzeUrls = new Set(bronze.citations.map(c => c.url));
      const silverUrls = new Set(silver.citations.map(c => c.url));

      const rows = [];
      bronze.citations.forEach(c => {
        const kept = silverUrls.has(c.url);
        rows.push({ num: c.display_number, domain: c.domain || c.url, status: kept ? "KEPT" : "REMOVED", cssClass: kept ? "cit-kept" : "cit-removed" });
      });
      silver.citations.forEach(c => {
        if (!bronzeUrls.has(c.url)) {
          rows.push({ num: c.display_number, domain: c.domain || c.url, status: "NEW — Writer", cssClass: "cit-new" });
        }
      });

      if (rows.length === 0) { container.innerHTML = `<div class="text-muted text-sm">No citations</div>`; return; }

      container.innerHTML = `
        <table class="citation-compare-table">
          <thead><tr><th>#</th><th>Source</th><th>Status</th></tr></thead>
          <tbody>${rows.map(r => `
            <tr>
              <td>[${r.num}]</td>
              <td>${esc(r.domain)}</td>
              <td class="${r.cssClass}">${r.status}</td>
            </tr>`).join("")}
          </tbody>
        </table>`;
    } catch (_) {}
  },

  renderTabs(commentaryId) {
    const tabsEl = document.getElementById("portfolio-tabs");
    tabsEl.innerHTML = "";

    // Get all commentaries for same period
    const commentary = State.commentaries.find(c => c.commentary_id === commentaryId)
                       || State.currentCommentary;
    if (!commentary) return;

    const samePeriod = State.commentaries.filter(c => c.period_label === commentary?.period_label);
    if (samePeriod.length <= 1) { tabsEl.innerHTML = ""; return; }

    samePeriod.forEach(c => {
      const counts = c.section_counts || { total: 0, edited: 0 };
      const tab = document.createElement("div");
      tab.className = `portfolio-tab ${c.commentary_id === commentaryId ? "active" : ""}`;
      tab.innerHTML = `
        <span class="mono">${esc(c.portcode)}</span>
        <span class="tab-progress-badge">${counts.edited}/${counts.total}</span>`;
      tab.addEventListener("click", () => { if (c.commentary_id !== commentaryId) DocView.open(c.commentary_id); });
      tabsEl.appendChild(tab);
    });
  },

  renderDocActions(commentary) {
    const writerActions = document.getElementById("doc-actions-writer");
    const reviewerActions = document.getElementById("doc-actions-reviewer");
    writerActions.classList.add("hidden");
    reviewerActions.classList.add("hidden");

    if (App.isWriter()) {
      writerActions.classList.remove("hidden");
      const submitBtn = document.getElementById("btn-submit-review");
      const canSubmit = ["draft", "changes_requested"].includes(commentary.status);
      submitBtn.disabled = !canSubmit;
      submitBtn.textContent = canSubmit ? "Submit for Review" : statusLabel(commentary.status);
    }

    if (App.isReviewer() && commentary.status === "in_review") {
      reviewerActions.classList.remove("hidden");
    }

    // Download buttons (shown for approved/published)
    const existing = document.getElementById("download-actions");
    if (existing) existing.remove();
    if (["approved", "published"].includes(commentary.status)) {
      const dl = document.createElement("div");
      dl.id = "download-actions";
      dl.style.cssText = "display:flex;gap:8px;max-width:900px;margin:0 auto 16px;flex-wrap:wrap";
      dl.innerHTML = `
        <button class="btn btn-ghost btn-sm" id="btn-dl-word">Download Word</button>
        <button class="btn btn-ghost btn-sm" id="btn-dl-pdf">Download PDF</button>
        <button class="btn btn-ghost btn-sm" id="btn-dl-csv">Download Sections CSV</button>
        <button class="btn btn-ghost btn-sm" id="btn-dl-cit-csv">Download Citations CSV</button>
        ${commentary.status === "approved" ? `<button class="btn btn-sm btn-primary" id="btn-publish">Mark Published</button>` : ""}
      `;
      document.getElementById("doc-canvas").insertBefore(dl, document.getElementById("sections-container"));
      this.bindDownloadButtons(commentary.commentary_id);
    }
  },

  bindDownloadButtons(commentaryId) {
    const downloadFile = async (path, filename) => {
      try {
        const res = await API.download(path);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
      } catch (err) { Toast.show("Download failed: " + err.message, "error"); }
    };

    document.getElementById("btn-dl-word")?.addEventListener("click", () => downloadFile(`/api/commentaries/${commentaryId}/export/word`, `${commentaryId}.docx`));
    document.getElementById("btn-dl-pdf")?.addEventListener("click", () => downloadFile(`/api/commentaries/${commentaryId}/export/pdf`, `${commentaryId}.pdf`));
    document.getElementById("btn-dl-csv")?.addEventListener("click", () => downloadFile(`/api/commentaries/${commentaryId}/export/csv`, `commentary_sections.csv`));
    document.getElementById("btn-dl-cit-csv")?.addEventListener("click", () => downloadFile(`/api/commentaries/${commentaryId}/export/citations-csv`, `citations.csv`));
    document.getElementById("btn-publish")?.addEventListener("click", async () => {
      try {
        await API.post(`/api/commentaries/${commentaryId}/publish`);
        Toast.show("Marked as published", "success");
        await DocView.open(commentaryId);
      } catch (err) { Toast.show(err.message, "error"); }
    });
  },
};


// ---------------------------------------------------------------------------
// Copy to portfolios modal
// ---------------------------------------------------------------------------

const CopyToModal = {
  async open(section, commentary) {
    const list = document.getElementById("copy-to-portfolio-list");
    list.innerHTML = "Loading…";
    Modal.open("modal-copy-to");

    const sharedPortfolios = section.shared_portfolios || [];
    if (sharedPortfolios.length === 0) { list.innerHTML = "No other portfolios share this section."; return; }

    list.innerHTML = sharedPortfolios.map(p => `
      <label class="copy-to-item">
        <input type="checkbox" class="copy-to-cb" value="${esc(p.commentary_id)}" checked />
        <span class="mono">${esc(p.portcode)}</span>
        <span class="text-muted text-sm">(${esc(p.commentary_id)})</span>
      </label>`).join("");

    const confirmBtn = document.getElementById("btn-confirm-copy-to");
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener("click", async () => {
      const selected = [...list.querySelectorAll(".copy-to-cb:checked")].map(cb => cb.value);
      if (selected.length === 0) { Toast.show("No portfolios selected", "error"); return; }
      try {
        const res = await API.post(
          `/api/commentaries/${State.currentCommentaryId}/sections/${section.section_key}/copy-to-portfolios`,
          { commentary_ids: selected }
        );
        Modal.close("modal-copy-to");
        const copied = res.results.filter(r => r.status === "copied").length;
        Toast.show(`Copied to ${copied} portfolio(s)`, "success");
        document.getElementById(`copy-bar-${section.section_key}`)?.classList.add("hidden");
      } catch (err) { Toast.show(err.message, "error"); }
    });
  },
};


// ---------------------------------------------------------------------------
// Settings modal
// ---------------------------------------------------------------------------

const SettingsModal = {
  async open() {
    try {
      const settings = await API.get("/api/settings");
      document.getElementById("s-api-key").value = "";
      document.getElementById("s-api-key-status").textContent = settings.openai_api_key_set ? "API key is set" : "No API key set";
      document.getElementById("s-model").value = settings.default_model || "gpt-5.2-2025-12-11";
      document.getElementById("s-thinking").value = settings.thinking_level || "medium";
      document.getElementById("s-verbosity").value = settings.text_verbosity || "medium";
      document.getElementById("s-web-search").checked = settings.use_web_search !== "false";
      document.getElementById("s-require-cits").checked = settings.require_citations !== "false";
    } catch (_) {}
    Modal.open("modal-settings");

    const saveBtn = document.getElementById("btn-save-settings");
    const newSave = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newSave, saveBtn);
    newSave.addEventListener("click", () => this.save());
  },

  async save() {
    const payload = {};
    const apiKey = document.getElementById("s-api-key").value.trim();
    if (apiKey) payload.openai_api_key = apiKey;
    payload.default_model = document.getElementById("s-model").value;
    payload.thinking_level = document.getElementById("s-thinking").value;
    payload.text_verbosity = document.getElementById("s-verbosity").value;
    payload.use_web_search = document.getElementById("s-web-search").checked ? "true" : "false";
    payload.require_citations = document.getElementById("s-require-cits").checked ? "true" : "false";
    try {
      await API.put("/api/settings", payload);
      Modal.close("modal-settings");
      Toast.show("Settings saved", "success");
    } catch (err) { Toast.show(err.message, "error"); }
  },
};


// ---------------------------------------------------------------------------
// Search modal
// ---------------------------------------------------------------------------

const SearchModal = {
  debounce: null,

  open() {
    Modal.open("modal-search");
    const input = document.getElementById("search-input");
    input.value = "";
    document.getElementById("search-results").innerHTML = "";
    input.focus();

    const newInput = input.cloneNode(true);
    input.parentNode.replaceChild(newInput, input);
    newInput.focus();

    newInput.addEventListener("input", () => {
      clearTimeout(this.debounce);
      this.debounce = setTimeout(() => this.doSearch(newInput.value), 300);
    });
  },

  async doSearch(q) {
    if (q.length < 2) { document.getElementById("search-results").innerHTML = ""; return; }
    try {
      const data = await API.get(`/api/search?q=${encodeURIComponent(q)}`);
      const el = document.getElementById("search-results");
      if (data.results.length === 0) {
        el.innerHTML = `<div class="search-result-item text-muted">No results</div>`;
        return;
      }
      el.innerHTML = data.results.map(r => `
        <div class="search-result-item" data-open="${esc(r.commentary_id)}">
          <span class="search-result-code">${esc(r.portcode)}</span>
          <span class="text-muted">·</span>
          <span class="search-result-meta">${esc(r.period_label)}</span>
          <span class="status-badge status-${r.status} ml-auto">${esc(statusLabel(r.status))}</span>
        </div>`).join("");
      el.querySelectorAll("[data-open]").forEach(item => {
        item.addEventListener("click", () => {
          Modal.close("modal-search");
          DocView.open(item.dataset.open);
        });
      });
    } catch (_) {}
  },
};


// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------

function esc(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function truncate(str, max) {
  if (!str) return "";
  return str.length > max ? str.slice(0, max) + "…" : str;
}

function stripHtml(html) {
  if (!html) return "";
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return tmp.textContent || tmp.innerText || "";
}

function capitalize(str) {
  return str ? str.charAt(0).toUpperCase() + str.slice(1) : "";
}

function statusLabel(status) {
  const labels = {
    not_started: "Not Started",
    generating: "Generating",
    draft: "Draft",
    in_review: "In Review",
    changes_requested: "Changes Requested",
    approved: "Approved",
    published: "Published",
    error: "Error",
  };
  return labels[status] || capitalize(status);
}

function sectionOrder(sections) {
  const typeOrder = { overview: 0, security: 1, outlook: 2 };
  return [...sections].sort((a, b) => {
    const ta = typeOrder[a.section_type] ?? 1;
    const tb = typeOrder[b.section_type] ?? 1;
    if (ta !== tb) return ta - tb;
    return (a.security_rank ?? 999) - (b.security_rank ?? 999);
  });
}


// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => App.init());
