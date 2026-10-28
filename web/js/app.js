/* ============================================================
   Email Studio — SPA logic
   Vanilla JS, zero dependencies. Hash routing + fetch API.
   ============================================================ */

"use strict";

/* ============ Helpers ============ */

const $ = (sel, root = document) => root.querySelector(sel);

function esc(value) {
  // Entities are built via concatenation so they cannot be collapsed
  // by any downstream HTML processing of this file.
  return String(value ?? "")
    .replace(/&/g, "&" + "amp;")
    .replace(/</g, "&" + "lt;")
    .replace(/>/g, "&" + "gt;")
    .replace(/"/g, "&" + "quot;")
    .replace(/'/g, "&" + "#39;");
}

const fmtSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON response */ }
  if (!res.ok) {
    throw new Error(body?.error || `Request failed (${res.status})`);
  }
  return body;
}

/* ============ Toasts ============ */

function toast(message, kind = "info", timeout = 4200) {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${kind === "error" ? "error" : kind === "success" ? "success" : kind === "warn" ? "warn" : ""}`;
  const icon = { success: "✅", error: "⛔", warn: "⚠️", info: "ℹ️" }[kind] || "ℹ️";
  el.innerHTML = `<span>${icon}</span><span>${esc(message)}</span>`;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("hide");
    setTimeout(() => el.remove(), 300);
  }, timeout);
}

/* ============ Modal ============ */

function openModal(html, { wide = false } = {}) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal ${wide ? "modal-wide" : ""}">${html}</div>`;
  root.classList.add("open");
}

function closeModal() {
  const root = $("#modal-root");
  root.classList.remove("open");
  root.innerHTML = "";
}

document.addEventListener("click", (e) => {
  if (e.target === $("#modal-root")) closeModal();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

/* ============ Status badge ============ */

function statusBadge(status) {
  const key = String(status || "").replace(/\s+/g, "");
  return `<span class="badge ${esc(key)}">${esc(status)}</span>`;
}

/* ============ Live-run polling ============ */

const LiveRun = {
  timer: null,

  start() {
    this.stop();
    this.timer = setInterval(async () => {
      try {
        const status = await api("/api/campaigns/status");
        this.render(status);

        if (status.state !== "running") {
          this.stop();
          this.announce(status);
          if (["dashboard", "campaigns"].includes(currentView)) render();
        }
      } catch { /* transient network error — keep polling */ }
    }, 1000);
  },

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  },

  announce(status) {
    const p = status.progress;
    if (status.state === "completed") {
      const mode = status.dry_run ? "Dry run" : "Live run";
      toast(
        `${mode} finished — ${p.successful} sent, ${p.failed} failed.`,
        status.failed ? "warn" : "success"
      );
    } else if (status.state === "failed") {
      toast(`Campaign failed: ${status.error}`, "error", 8000);
    } else if (status.state === "aborted") {
      toast("Campaign aborted — partial report saved.", "warn");
    }
  },

  panelHtml(status) {
    const p = status.progress;
    const pct = p.total ? Math.round((p.processed / p.total) * 100) : 0;
    const stateLabel = {
      running: "Running",
      completed: "Completed",
      aborted: "Aborted",
      failed: "Failed",
      idle: "Idle",
    }[status.state] || status.state;

    const stateClass =
      status.state === "running" ? "amber"
      : status.state === "completed" ? "green"
      : status.state === "failed" ? "red"
      : "gray";

    return `
      <div class="modal-sub" style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <span>${status.dry_run ? "🧪 Dry run" : "🚀 Live run"} —
          <b>${esc(status.email_type || "")}</b> via <b>${esc(status.backend || "")}</b>
          ${status.resume ? "· resume on" : ""}
        </span>
        <span class="badge ${stateClass}">${esc(stateLabel)}</span>
      </div>

      <div class="progress-track" style="margin-top:14px;">
        <div class="progress-fill ${status.state === "running" ? "active" : ""}" style="width:${pct}%"></div>
      </div>
      <div class="run-state-line">
        <span>${p.processed}/${p.total} processed (${pct}%)</span>
        ${status.state === "running" && p.current
          ? `<span>·</span><span>Now: <b>${esc(p.current)}</b></span>` : ""}
      </div>

      <div class="count-grid">
        <div class="count-cell ${status.dry_run ? "dim" : "ok"}"><b>${p.successful}</b><span>${status.dry_run ? "Rendered" : "Sent"}</span></div>
        <div class="count-cell bad"><b>${p.failed}</b><span>Failed</span></div>
        <div class="count-cell dim"><b>${p.suppressed}</b><span>Suppressed</span></div>
        <div class="count-cell dim"><b>${p.resumed}</b><span>Resumed</span></div>
      </div>

      ${status.error ? `<div class="warn-box">${esc(status.error)}</div>` : ""}

      <div class="modal-actions">
        ${status.state === "running"
          ? `<button class="btn btn-danger" onclick="LiveRun.cancel()">Abort campaign</button>` : ""}
        ${status.report_path ? `<a class="btn" href="#/reports" onclick="closeModal()">View reports</a>` : ""}
        <button class="btn btn-primary" onclick="closeModal()">
          ${status.state === "running" ? "Run in background" : "Close"}
        </button>
      </div>`;
  },

  render(status) {
    const panel = $("#live-panel");
    if (panel) panel.innerHTML = this.panelHtml(status);
    updateFooter(status);
  },

  async cancel() {
    try {
      await api("/api/campaigns/cancel", { method: "POST" });
      toast("Abort requested — finishing the current recipient…", "warn");
    } catch (e) {
      toast(e.message, "error");
    }
  },
};

async function showLiveRun() {
  try {
    const status = await api("/api/campaigns/status");
    openModal(`<div id="live-panel">${LiveRun.panelHtml(status)}</div>`);
    if (status.state === "running") LiveRun.start();
  } catch (e) {
    toast(e.message, "error");
  }
}

function updateFooter(status) {
  const label = $("#footer-backend");
  const dot = $("#sidebar-footer .dot");
  if (!label || !dot) return;

  if (status && status.state === "running") {
    label.textContent = `Campaign running (${status.email_type})`;
    dot.className = "dot dot-run";
  } else {
    label.textContent = status?.backend ? `Backend: ${status.backend}` : "Ready";
    dot.className = "dot dot-ok";
  }
}

/* ============ Views ============ */

const VIEWS = {
  dashboard: { title: "Dashboard", subtitle: "Overview of your email automation", render: renderDashboard },
  campaigns: { title: "Campaigns", subtitle: "Preview, test, and send campaigns", render: renderCampaigns },
  recipients: { title: "Recipients", subtitle: "Manage who receives your campaigns", render: renderRecipients },
  suppression: { title: "Suppression", subtitle: "Addresses never emailed — bounces, complaints, unsubscribes", render: renderSuppression },
  reports: { title: "Reports", subtitle: "Delivery reports from past runs", render: renderReports },
  registries: { title: "Auto-Resume", subtitle: "Sent registries per campaign — used by --resume", render: renderRegistries },
  settings: { title: "Settings", subtitle: "Active configuration (secrets are never shown)", render: renderSettings },
};

let currentView = "dashboard";
const viewData = {};

function setView(name) {
  if (!VIEWS[name]) name = "dashboard";
  currentView = name;

  const view = VIEWS[name];
  $("#page-title").textContent = view.title;
  $("#page-subtitle").textContent = view.subtitle;

  document.querySelectorAll("#nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.view === name);
  });

  render();
}

function render() {
  const root = $("#view-root");
  const view = currentView;

  root.innerHTML = `
    <div class="loading-skeleton">
      <div class="skel skel-card"></div>
      <div class="skel skel-card"></div>
    </div>`;

  VIEWS[view]
    .render()
    .then((html) => {
      if (currentView !== view) return; // user navigated away meanwhile
      root.innerHTML = html;
    })
    .catch((err) => {
      if (currentView !== view) return;
      root.innerHTML = `
        <div class="card">
          <div class="empty">
            <div class="empty-icon">⛔</div>
            <h4>Could not load</h4>
            <p>${esc(err.message)}</p>
          </div>
        </div>`;
    });
}

/* ---------- Dashboard ---------- */

function statCard(icon, color, value, label) {
  return `
    <div class="stat-card">
      <div class="stat-icon ${color}">${icon}</div>
      <div>
        <div class="stat-value">${esc(value)}</div>
        <div class="stat-label">${esc(label)}</div>
      </div>
    </div>`;
}

async function renderDashboard() {
  const [overview, status] = await Promise.all([
    api("/api/overview"),
    api("/api/campaigns/status"),
  ]);
  viewData.overview = overview;

  const running = status.state === "running";

  const runsTable = overview.recent_runs.length
    ? `
      <div class="card">
        <h3>Recent runs</h3>
        <div class="card-sub">Latest delivery reports, newest first</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Report</th><th>Size</th><th>Modified</th><th></th></tr></thead>
            <tbody>
              ${overview.recent_runs
                .map(
                  (r) => `
                <tr class="report-file-row" onclick="viewReport('${esc(r.file)}')">
                  <td class="mono">${esc(r.file)}</td>
                  <td>${fmtSize(r.size)}</td>
                  <td class="muted">${esc(r.modified)}</td>
                  <td class="actions-cell"><button class="btn btn-sm">Open</button></td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>`
    : `
      <div class="card">
        <div class="empty">
          <div class="empty-icon">📭</div>
          <h4>No runs yet</h4>
          <p>Start with a dry run from the Campaigns page.</p>
        </div>
      </div>`;

  return `
    ${running ? `
      <div class="run-banner" onclick="showLiveRun()">
        <span class="dot dot-run"></span>
        A campaign is running — click to watch live progress
      </div>` : ""}
    <div class="grid-stats">
      ${statCard("👥", "blue", overview.recipients, "Recipients")}
      ${statCard("✈️", "grad", overview.campaigns.length, "Campaign types")}
      ${statCard("🛡️", "red", overview.suppressed, "Suppressed")}
      ${statCard("🔁", "green", overview.sent_total, "Sent (registry)")}
    </div>
    <div class="grid-2">
      <div class="card">
        <h3>Delivery setup</h3>
        <div class="card-sub">How mail leaves this machine</div>
        <div class="kv-list">
          <div class="kv-row"><span class="k">Backend</span><span class="v">${esc(overview.backend)}</span></div>
          <div class="kv-row"><span class="k">Sender</span><span class="v">${esc(overview.sender_name)} <${esc(overview.sender_email_masked || "not set")}></span></div>
          <div class="kv-row"><span class="k">Unsubscribe</span>
            <span class="v">${overview.unsubscribe_enabled
              ? `<span class="badge green">${esc(overview.unsubscribe_mode)}</span>`
              : `<span class="badge red">Not configured</span>`}</span></div>
          <div class="kv-row"><span class="k">SMTP</span><span class="v mono">${esc(overview.smtp_server || "-")}</span></div>
        </div>
      </div>
      ${runsTable}
    </div>`;
}

/* ---------- Campaigns ---------- */

async function renderCampaigns() {
  const [campaigns, overview] = await Promise.all([
    api("/api/campaigns"),
    api("/api/overview"),
  ]);
  viewData.campaigns = campaigns;
  viewData.overview = overview;

  const cards = campaigns
    .map((c) => `
      <div class="campaign-card">
        <div class="campaign-head"><span class="campaign-badge">${esc(c.type)}</span></div>
        <div class="campaign-subject">“${esc(c.subject)}”</div>
        <div class="chip-row">
          ${c.attachments.length
            ? c.attachments
                .map(
                  (a) =>
                    `<span class="chip">📎 ${esc(a.name)}${a.exists ? "" : ' <span class="chip-missing">missing</span>'}</span>`
                )
                .join("")
            : `<span class="chip">No attachments</span>`}
        </div>
        <div class="campaign-actions">
          <button class="btn btn-sm" onclick="previewCampaign('${esc(c.type)}')">Preview</button>
          <button class="btn btn-sm" onclick="testRun('${esc(c.type)}')">Dry run</button>
          <button class="btn btn-sm btn-primary" onclick="launchModal('${esc(c.type)}')">Send</button>
        </div>
      </div>`)
    .join("");

  return `
    ${overview.unsubscribe_enabled
      ? ""
      : `<div class="warn-box">⚠️ No unsubscribe configuration found — live bulk sending without one violates CAN-SPAM/GDPR. Set UNSUBSCRIBE_SECRET plus UNSUBSCRIBE_BASE_URL / UNSUBSCRIBE_MAILTO in your .env.</div>`}
    <div class="grid-campaigns">${cards}</div>`;
}

async function previewCampaign(type) {
  openModal(`<h2>Loading preview…</h2>`);

  try {
    const data = await api(`/api/campaigns/preview?type=${encodeURIComponent(type)}`);

    openModal(
      `
      <h2>Preview — ${esc(type)}</h2>
      <div class="modal-sub">
        Subject: <b>${esc(data.subject)}</b> ·
        To: <b>${esc(data.recipient.Name)}</b> <${esc(data.recipient.Email)}>
      </div>
      <iframe class="preview-frame" sandbox=""
              srcdoc="${esc(data.html_body || data.text_body)}"></iframe>
      <hr class="divider">
      <h3 style="font-size:13px;">Plain-text version</h3>
      <div class="preview-text">${esc(data.text_body)}</div>
      <div class="modal-actions">
        <button class="btn btn-sm" onclick="testRun('${esc(type)}')">Dry run</button>
        <button class="btn btn-sm btn-primary" onclick="launchModal('${esc(type)}')">Send campaign</button>
      </div>`,
      { wide: true }
    );
  } catch (e) {
    openModal(`
      <h2>Preview failed</h2>
      <div class="modal-sub">${esc(e.message)}</div>
      <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`);
  }
}

async function testRun(type) {
  closeModal();
  try {
    // No backend in the body: the API falls back to DELIVERY_BACKEND.
    await api("/api/campaigns/run", {
      method: "POST",
      body: JSON.stringify({ email_type: type, dry_run: true, resume: false }),
    });
    showLiveRun();
    toast("Dry run started — nothing will be sent.", "info");
  } catch (e) {
    toast(e.message, "error");
  }
}

function launchModal(type) {
  const campaign =
    (viewData.campaigns || []).find((c) => c.type === type) || { type };
  const defaultBackend = viewData.overview?.backend || "smtp";

  openModal(`
    <h2>Send “${esc(campaign.subject || type)}”</h2>
    <div class="modal-sub">Campaign <b>${esc(type)}</b> — choose how it should be delivered</div>

    <div class="field" style="margin-bottom:14px;">
      <label>Delivery backend</label>
      <select id="run-backend">
        ${["smtp", "gmail", "sendgrid", "ses"]
          .map(
            (b) =>
              `<option value="${b}" ${b === defaultBackend ? "selected" : ""}>${b}</option>`
          )
          .join("")}
      </select>
    </div>

    <label class="check" style="margin-bottom:10px;">
      <input type="checkbox" id="run-resume">
      <span>
        <span class="check-title">Resume mode</span><br>
        <span class="check-sub">Skip recipients already sent in a previous run of this campaign</span>
      </span>
    </label>

    <label class="check" style="margin-bottom:14px;">
      <input type="checkbox" id="run-dry" checked>
      <span>
        <span class="check-title">Dry run first (recommended)</span><br>
        <span class="check-sub">Renders everything and produces a report, but sends nothing</span>
      </span>
    </label>

    <div id="live-confirm" style="display:none;">
      <div class="warn-box">⚠️ A live run sends real emails to everyone on the list. This is the same rule as typing “YES” in the CLI.</div>
      <label class="check danger">
        <input type="checkbox" id="run-confirmed">
        <span><span class="check-title">I understand — send the emails</span></span>
      </label>
    </div>

    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="run-launch-btn" onclick="doLaunch('${esc(type)}')">Start dry run</button>
    </div>
  `);

  const dry = $("#run-dry");
  const launchBtn = $("#run-launch-btn");
  const liveBlock = $("#live-confirm");

  function refresh() {
    const isLive = !dry.checked;
    liveBlock.style.display = isLive ? "block" : "none";
    launchBtn.textContent = isLive ? "Send live campaign" : "Start dry run";
    const confirmed = $("#run-confirmed").checked;
    launchBtn.disabled = isLive && !confirmed;
  }

  dry.addEventListener("change", refresh);
  $("#run-confirmed").addEventListener("change", refresh);
  refresh();
}

async function doLaunch(type) {
  const backend = $("#run-backend").value;
  const dryRun = $("#run-dry").checked;
  const resume = $("#run-resume").checked;
  const confirmed = dryRun || $("#run-confirmed").checked;

  try {
    await api("/api/campaigns/run", {
      method: "POST",
      body: JSON.stringify({ email_type: type, backend, dry_run: dryRun, resume, confirmed }),
    });
    closeModal();
    showLiveRun();
    toast(
      dryRun ? "Dry run started — nothing will be sent." : "Live campaign started.",
      dryRun ? "info" : "success"
    );
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Recipients ---------- */

async function renderRecipients() {
  const recipients = await api("/api/recipients");

  const rows = recipients.length
    ? recipients
        .map(
          (r) => `
        <tr>
          <td><b>${esc(r.Name)}</b></td>
          <td class="mono">${esc(r.Email)}</td>
          <td class="actions-cell">
            <button class="btn btn-sm btn-danger-soft"
                    onclick="deleteRecipient('${encodeURIComponent(r.Email)}')">Remove</button>
          </td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="3">
        <div class="empty">
          <div class="empty-icon">👥</div>
          <h4>No recipients</h4>
          <p>Add the first one below.</p>
        </div>
      </td></tr>`;

  return `
    <div class="card">
      <div class="form-row" style="margin-bottom:16px;">
        <div class="field"><label>Name</label><input type="text" id="rec-name" placeholder="Jane Doe"></div>
        <div class="field"><label>Email</label><input type="email" id="rec-email" placeholder="jane@example.com"></div>
        <button class="btn btn-primary" style="margin-top:22px;" onclick="addRecipient()">Add recipient</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th style="text-align:right;">Actions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="small muted" style="margin-top:12px;">
        ${recipients.length} recipient(s) · duplicates and malformed rows are rejected by validation
      </div>
    </div>`;
}

async function addRecipient() {
  const name = $("#rec-name").value.trim();
  const email = $("#rec-email").value.trim();
  if (!name || !email) return toast("Name and email are required.", "warn");

  try {
    await api("/api/recipients", {
      method: "POST",
      body: JSON.stringify({ name, email }),
    });
    toast(`${name} added.`, "success");
    render();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function deleteRecipient(encodedEmail) {
  const email = decodeURIComponent(encodedEmail);
  if (!confirm(`Remove ${email} from the recipient list?`)) return;

  try {
    await api(`/api/recipients/${encodedEmail}`, { method: "DELETE" });
    toast("Recipient removed.", "success");
    render();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Suppression ---------- */

async function renderSuppression() {
  const rows = await api("/api/suppression");

  const body = rows.length
    ? rows
        .map(
          (r) => `
        <tr>
          <td class="mono">${esc(r.Email)}</td>
          <td>${esc(r.Reason)}</td>
          <td><span class="badge gray">${esc(r.Source || "-")}</span></td>
          <td class="muted">${esc(r.Date)}</td>
          <td class="actions-cell">
            <button class="btn btn-sm" onclick="unsuppress('${encodeURIComponent(r.Email)}')">Unsuppress</button>
          </td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="5">
        <div class="empty">
          <div class="empty-icon">🛡️</div>
          <h4>Nothing suppressed</h4>
          <p>Bounced, complained, and unsubscribed addresses will appear here.</p>
        </div>
      </td></tr>`;

  return `
    <div class="card">
      <div class="form-row" style="margin-bottom:16px;">
        <div class="field"><label>Email</label><input type="email" id="sup-email" placeholder="bounced@example.com"></div>
        <div class="field"><label>Reason</label><input type="text" id="sup-reason" placeholder="hard bounce"></div>
        <button class="btn btn-primary" style="margin-top:22px;" onclick="addSuppressed()">Suppress</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Email</th><th>Reason</th><th>Source</th><th>Date</th><th style="text-align:right;">Actions</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      <div class="small muted" style="margin-top:12px;">
        Suppressed addresses are skipped in every campaign, CLI or web.
      </div>
    </div>`;
}

async function addSuppressed() {
  const email = $("#sup-email").value.trim();
  const reason = $("#sup-reason").value.trim() || "manual (web)";
  if (!email) return toast("An email address is required.", "warn");

  try {
    const res = await api("/api/suppression", {
      method: "POST",
      body: JSON.stringify({ email, reason }),
    });
    toast(
      res.added ? `${email} suppressed.` : `${email} was already suppressed.`,
      "success"
    );
    render();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function unsuppress(encodedEmail) {
  const email = decodeURIComponent(encodedEmail);
  if (!confirm(`Remove ${email} from the suppression list? They will receive campaigns again.`)) return;

  try {
    await api(`/api/suppression/${encodedEmail}`, { method: "DELETE" });
    toast("Address unsuppressed.", "success");
    render();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Reports ---------- */

async function renderReports() {
  const reports = await api("/api/reports");

  const rows = reports.length
    ? reports
        .map(
          (r) => `
        <tr class="report-file-row" onclick="viewReport('${esc(r.file)}')">
          <td class="mono">${esc(r.file)}</td>
          <td>${fmtSize(r.size)}</td>
          <td class="muted">${esc(r.modified)}</td>
          <td class="actions-cell">
            <a class="btn btn-sm" href="/api/reports/${encodeURIComponent(r.file)}/download"
               onclick="event.stopPropagation();">Download</a>
          </td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="4">
        <div class="empty">
          <div class="empty-icon">📊</div>
          <h4>No reports yet</h4>
          <p>Run a dry run from the Campaigns page to generate one.</p>
        </div>
      </td></tr>`;

  return `
    <div class="card">
      <h3>Delivery reports</h3>
      <div class="card-sub">Timestamped CSV files — one per run, never overwritten</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>File</th><th>Size</th><th>Modified</th><th style="text-align:right;">Actions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

async function viewReport(file) {
  try {
    const data = await api(`/api/reports/${encodeURIComponent(file)}`);

    const rows = data.rows
      .map(
        (r) => `
      <tr>
        <td><b>${esc(r.Name)}</b></td>
        <td class="mono">${esc(r.Email)}</td>
        <td>${statusBadge(r.Status)}</td>
        <td class="small muted">${esc(r.Error)}</td>
      </tr>`
      )
      .join("");

    openModal(
      `
      <h2>${esc(data.file)}</h2>
      <div class="modal-sub">
        ${data.rows.length} row(s) ·
        <a href="/api/reports/${encodeURIComponent(data.file)}/download">Download CSV</a>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Error</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`,
      { wide: true }
    );
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Registries (auto-resume) ---------- */

async function renderRegistries() {
  const registries = await api("/api/registries");

  const cards = registries
    .map(
      (r) => `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
        <div>
          <h3 style="text-transform:capitalize;">${esc(r.campaign)}</h3>
          <div class="card-sub">${r.count} address(es) recorded as sent · used by --resume</div>
        </div>
        ${r.count
          ? `<button class="btn btn-sm btn-danger-soft" onclick="clearRegistry('${esc(r.campaign)}')">Clear registry</button>`
          : `<span class="badge gray">Empty</span>`}
      </div>
      ${r.count
        ? `
      <div class="chip-row" style="margin-top:12px;">
        ${r.emails
          .slice(0, 12)
          .map((e) => `<span class="chip mono">${esc(e)}</span>`)
          .join("")}
        ${r.emails.length > 12 ? `<span class="chip">+${r.emails.length - 12} more</span>` : ""}
      </div>`
        : ""}
    </div>`
    )
    .join("");

  return (
    cards +
    `
    <div class="card section-gap">
      <div class="small muted">
        Live sends are recorded here the moment they succeed, so a crashed run can be resumed with
        <b>--resume</b> (CLI) or the resume option (web). Clear a registry before an intentional re-send.
      </div>
    </div>`
  );
}

async function clearRegistry(campaign) {
  if (!confirm(`Clear the sent registry for '${campaign}'? The next run of this campaign will send to everyone again.`)) return;

  try {
    await api(`/api/registries/${encodeURIComponent(campaign)}`, { method: "DELETE" });
    toast(`Registry for '${campaign}' cleared.`, "success");
    render();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- Settings ---------- */

async function renderSettings() {
  const overview = await api("/api/overview");
  viewData.overview = overview;

  return `
    <div class="grid-2">
      <div class="card">
        <h3>Delivery</h3>
        <div class="card-sub">Active backend and sender identity</div>
        <div class="kv-list">
          <div class="kv-row"><span class="k">Backend (.env default)</span><span class="v">${esc(overview.backend)}</span></div>
          <div class="kv-row"><span class="k">Sender name</span><span class="v">${esc(overview.sender_name)}</span></div>
          <div class="kv-row"><span class="k">Sender address</span><span class="v mono">${esc(overview.sender_email_masked || "not set")}</span></div>
          <div class="kv-row"><span class="k">SMTP server</span><span class="v mono">${esc(overview.smtp_server || "-")}</span></div>
        </div>
      </div>
      <div class="card">
        <h3>Compliance & safety</h3>
        <div class="card-sub">Unsubscribe and suppression health</div>
        <div class="kv-list">
          <div class="kv-row"><span class="k">Unsubscribe</span>
            <span class="v">${overview.unsubscribe_enabled
              ? `<span class="badge green">${esc(overview.unsubscribe_mode)}</span>`
              : `<span class="badge red">Not configured</span>`}</span></div>
          <div class="kv-row"><span class="k">Suppressed addresses</span><span class="v">${overview.suppressed}</span></div>
          <div class="kv-row"><span class="k">Sent registry total</span><span class="v">${overview.sent_total}</span></div>
          <div class="kv-row"><span class="k">Live-send confirmation</span><span class="v"><span class="badge green">Required</span></span></div>
        </div>
      </div>
    </div>
    <div class="card section-gap">
      <h3>Where things live</h3>
      <div class="card-sub">Everything is local to this project folder</div>
      <div class="kv-list">
        <div class="kv-row"><span class="k">Recipients file</span><span class="v mono">recipients.csv</span></div>
        <div class="kv-row"><span class="k">Suppression list</span><span class="v mono">suppression.csv</span></div>
        <div class="kv-row"><span class="k">Sent registries</span><span class="v mono">state/sent_<type>.csv</span></div>
        <div class="kv-row"><span class="k">Delivery reports</span><span class="v mono">reports/email_report_*.csv</span></div>
        <div class="kv-row"><span class="k">Logs (rotating)</span><span class="v mono">logs/automation.log</span></div>
      </div>
    </div>
    <div class="card section-gap">
      <h3>Security notes</h3>
      <div class="card-sub">
        This panel binds to 127.0.0.1 — do not expose it to the internet without adding authentication.
        API responses never include secrets: addresses are masked, and credentials are never returned.
      </div>
    </div>`;
}

/* ============ Boot ============ */

function routeFromHash() {
  const view = (location.hash || "#/dashboard").replace("#/", "").split("?")[0];
  setView(view);
}

window.addEventListener("hashchange", routeFromHash);

window.LiveRun = LiveRun;
window.closeModal = closeModal;
window.showLiveRun = showLiveRun;
window.previewCampaign = previewCampaign;
window.testRun = testRun;
window.launchModal = launchModal;
window.doLaunch = doLaunch;
window.addRecipient = addRecipient;
window.deleteRecipient = deleteRecipient;
window.addSuppressed = addSuppressed;
window.unsuppress = unsuppress;
window.viewReport = viewReport;
window.clearRegistry = clearRegistry;

/* Check for an in-flight run on load, then route */
api("/api/campaigns/status")
  .then((status) => {
    updateFooter(status);
    if (status.state === "running") LiveRun.start();
  })
  .catch(() => {});

routeFromHash();
