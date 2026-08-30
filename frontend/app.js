/**
 * Skylark Business Intelligence — Enterprise Client Application
 * Dependency-free, deterministic provenance, responsive SPA architecture.
 */

const API = "";

// Global State
const state = {
  currentView: "overview",
  overviewData: null,
  insightsData: null,
  reportsData: null,
  qualityData: null,
  boardsData: null,
  chatHistory: [],
  recentAnalyses: [],
  isBusy: false,
};

// DOM helper object resolved safely
const DOM = {};

function resolveDOM() {
  DOM.sidebar = document.getElementById("sidebar");
  DOM.mobileMenuBtn = document.getElementById("mobileMenuBtn");
  DOM.mobileCloseBtn = document.getElementById("mobileCloseBtn");
  DOM.viewTitle = document.getElementById("viewTitle");
  DOM.boardStatus = document.getElementById("boardStatus");
  DOM.refreshDataBtn = document.getElementById("refreshDataBtn");
  DOM.sidebarSyncDot = document.getElementById("sidebarSyncDot");
  DOM.sidebarSyncTitle = document.getElementById("sidebarSyncTitle");
  DOM.sidebarSyncDetails = document.getElementById("sidebarSyncDetails");

  // Overview View
  DOM.heroQueryForm = document.getElementById("heroQueryForm");
  DOM.heroQuestionInput = document.getElementById("heroQuestionInput");
  DOM.heroSuggestedChips = document.getElementById("heroSuggestedChips");
  DOM.executiveAlertContainer = document.getElementById("executiveAlertContainer");
  DOM.kpiGrid = document.getElementById("kpiGrid");
  DOM.secondaryMetricsBar = document.getElementById("secondaryMetricsBar");
  DOM.operationalRisksBody = document.getElementById("operationalRisksBody");
  DOM.overviewQualityBody = document.getElementById("overviewQualityBody");
  DOM.categorizedQuestionsGrid = document.getElementById("categorizedQuestionsGrid");
  DOM.recentAnalysesGrid = document.getElementById("recentAnalysesGrid");
  DOM.clearHistoryBtn = document.getElementById("clearHistoryBtn");

  // Chat View
  DOM.chatStarterHero = document.getElementById("chatStarterHero");
  DOM.chatStarterGrid = document.getElementById("chatStarterGrid");
  DOM.chatQuickChips = document.getElementById("chatQuickChips");
  DOM.chatThread = document.getElementById("chatThread");
  DOM.chatComposerForm = document.getElementById("chatComposerForm");
  DOM.chatQuestionInput = document.getElementById("chatQuestionInput");
  DOM.chatSendButton = document.getElementById("chatSendButton");

  // Insights View
  DOM.insightsCoverageBadge = document.getElementById("insightsCoverageBadge");
  DOM.sectorMatrixContainer = document.getElementById("sectorMatrixContainer");
  DOM.accountsRiskBody = document.getElementById("accountsRiskBody");
  DOM.ownerPerformanceBody = document.getElementById("ownerPerformanceBody");

  // Reports View
  DOM.reportTitleHeader = document.getElementById("reportTitleHeader");
  DOM.copyTalkingPointsBtn = document.getElementById("copyTalkingPointsBtn");
  DOM.reportTalkingPointsList = document.getElementById("reportTalkingPointsList");
  DOM.reportRankedRisks = document.getElementById("reportRankedRisks");
  DOM.quarterlyTrendBody = document.getElementById("quarterlyTrendBody");
  DOM.funnelStageBody = document.getElementById("funnelStageBody");

  // Quality View
  DOM.qualityScoreNum = document.getElementById("qualityScoreNum");
  DOM.qualityDealsBody = document.getElementById("qualityDealsBody");
  DOM.qualityWorkOrdersBody = document.getElementById("qualityWorkOrdersBody");
  DOM.qualityLedgerTableBody = document.getElementById("qualityLedgerTableBody");

  // Sources & Settings
  DOM.sourcesBoardGrid = document.getElementById("sourcesBoardGrid");
  DOM.settingsLlmStatus = document.getElementById("settingsLlmStatus");

  // Provenance Modal
  DOM.provenanceModal = document.getElementById("provenanceModal");
  DOM.modalMetricTitle = document.getElementById("modalMetricTitle");
  DOM.modalMetricBody = document.getElementById("modalMetricBody");
  DOM.modalCloseBtn = document.getElementById("modalCloseBtn");
}

/* ================= UTILITY HELPERS ================= */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function textInto(parent, value) {
  parent.appendChild(document.createTextNode(value == null ? "" : String(value)));
  return parent;
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

function renderSparklineSVG(series) {
  if (!series || series.length < 2) return "";
  const max = Math.max(...series, 1);
  const min = Math.min(...series, 0);
  const range = max - min || 1;
  const w = 180, h = 28;

  const points = series.map((v, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const linePath = `M ${points.join(" L ")}`;
  const areaPath = `M 0,${h} L ${points.join(" L ")} L ${w},${h} Z`;

  return `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path class="sparkline-area" d="${areaPath}" />
      <path class="sparkline-path" d="${linePath}" />
    </svg>
  `;
}

/* ================= ROUTING & VIEW NAVIGATION ================= */

function switchView(viewName) {
  state.currentView = viewName;

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });

  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `view-${viewName}`);
  });

  const titles = {
    overview: "Overview",
    chat: "Ask AI",
    insights: "Insights",
    reports: "Reports",
    quality: "Data Quality",
    sources: "Data Sources",
    settings: "Settings",
  };
  if (DOM.viewTitle) DOM.viewTitle.textContent = titles[viewName] || "Overview";
  if (DOM.sidebar) DOM.sidebar.classList.remove("open");

  // Always trigger a load when navigating to a view that hasn't loaded yet
  if (viewName === "insights" && !state.insightsData) loadInsights();
  if (viewName === "reports" && !state.reportsData) loadReports();
  if (viewName === "quality" && !state.qualityData) loadDataQuality();
  if (viewName === "sources" && !state.boardsData) loadBoardStatus();

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function initNavigation() {
  document.querySelectorAll("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  if (DOM.mobileMenuBtn) {
    DOM.mobileMenuBtn.addEventListener("click", () => DOM.sidebar && DOM.sidebar.classList.add("open"));
  }
  if (DOM.mobileCloseBtn) {
    DOM.mobileCloseBtn.addEventListener("click", () => DOM.sidebar && DOM.sidebar.classList.remove("open"));
  }
}

/* ================= PROVENANCE MODAL ================= */

function openProvenanceModal(metric, labelFallback) {
  if (!DOM.provenanceModal) return;

  if (DOM.modalMetricTitle) {
    DOM.modalMetricTitle.textContent = metric?.label || labelFallback || "Metric Provenance";
  }
  if (!DOM.modalMetricBody) return;
  DOM.modalMetricBody.replaceChildren();

  const body = DOM.modalMetricBody;

  // Stat Box
  const statBox = el("div", "provenance-section");
  const grid = el("div", "prov-grid");

  const valCard = el("div", "prov-stat-box");
  valCard.appendChild(el("div", "prov-stat-val", metric?.display || "-"));
  valCard.appendChild(el("div", "prov-stat-lbl", "Computed Value"));
  grid.appendChild(valCard);

  const coverageCard = el("div", "prov-stat-box");
  const covText = metric?.rows_considered
    ? `${metric.rows_included} / ${metric.rows_considered} records`
    : "Verified deterministic";
  coverageCard.appendChild(el("div", "prov-stat-val", covText));
  coverageCard.appendChild(el("div", "prov-stat-lbl", "Record Universe"));
  grid.appendChild(coverageCard);

  statBox.appendChild(grid);
  body.appendChild(statBox);

  // Definition
  if (metric?.definition) {
    const defSec = el("div", "provenance-section");
    defSec.appendChild(el("div", "prov-title", "Business Definition"));
    defSec.appendChild(el("div", "prov-text", metric.definition));
    body.appendChild(defSec);
  }

  // Formula
  if (metric?.formula) {
    const formSec = el("div", "provenance-section");
    formSec.appendChild(el("div", "prov-title", "Exact Calculation Formula"));
    formSec.appendChild(el("div", "prov-code", metric.formula));
    body.appendChild(formSec);
  }

  // Exclusions Breakdown
  if (metric?.exclusion_reasons && Object.keys(metric.exclusion_reasons).length > 0) {
    const excSec = el("div", "provenance-section");
    excSec.appendChild(el("div", "prov-title", "Excluded Records Breakdown"));
    const ul = el("ul", "ledger-list");
    Object.entries(metric.exclusion_reasons).forEach(([reason, count]) => {
      const li = el("li");
      const c = el("span", "count", String(count));
      li.appendChild(c);
      textInto(li, ` records excluded — ${reason}`);
      ul.appendChild(li);
    });
    excSec.appendChild(ul);
    body.appendChild(excSec);
  }

  // Note
  if (metric?.note) {
    const noteSec = el("div", "provenance-section");
    noteSec.appendChild(el("div", "prov-title", "Data Context & Caveats"));
    noteSec.appendChild(el("div", "prov-text", metric.note));
    body.appendChild(noteSec);
  }

  DOM.provenanceModal.classList.add("active");
}

function initModal() {
  if (DOM.modalCloseBtn) {
    DOM.modalCloseBtn.addEventListener("click", () => {
      DOM.provenanceModal && DOM.provenanceModal.classList.remove("active");
    });
  }
  if (DOM.provenanceModal) {
    DOM.provenanceModal.addEventListener("click", (e) => {
      if (e.target === DOM.provenanceModal) DOM.provenanceModal.classList.remove("active");
    });
  }
}

/* ================= DATA LOADERS & RENDERERS ================= */

// 1. Board Status
async function loadBoardStatus() {
  try {
    const res = await fetch(`${API}/api/boards`);
    if (!res.ok) throw new Error("Boards endpoint unreachable");
    const data = await res.json();
    state.boardsData = data;

    if (DOM.boardStatus) DOM.boardStatus.replaceChildren();

    if (!data.monday_configured) {
      if (DOM.boardStatus) {
        const chip = el("span", "chip chip-muted");
        chip.appendChild(el("span", "dot"));
        textInto(chip, "Local CSV Mode");
        DOM.boardStatus.appendChild(chip);
      }
      if (DOM.sidebarSyncDot) DOM.sidebarSyncDot.className = "status-indicator local";
      if (DOM.sidebarSyncTitle) DOM.sidebarSyncTitle.textContent = "Local CSV Dataset";
      if (DOM.sidebarSyncDetails) DOM.sidebarSyncDetails.textContent = "Deterministic pipeline active";
    } else {
      if (DOM.sidebarSyncDot) DOM.sidebarSyncDot.className = "status-indicator live";
      if (DOM.sidebarSyncTitle) DOM.sidebarSyncTitle.textContent = "Monday.com Connected";
      if (DOM.sidebarSyncDetails) DOM.sidebarSyncDetails.textContent = `${data.boards?.length || 2} boards synchronized`;

      (data.boards || []).forEach((b) => {
        if (DOM.boardStatus) {
          const chip = el("span", b.error ? "chip chip-error" : "chip");
          chip.appendChild(el("span", "dot"));
          textInto(chip, b.error ? `${b.name}: error` : `${b.name} · ${b.item_count} items`);
          DOM.boardStatus.appendChild(chip);
        }
      });
    }

    if (DOM.sourcesBoardGrid) renderSourcesView(data);
    if (DOM.settingsLlmStatus) {
      DOM.settingsLlmStatus.textContent = data.llm_configured
        ? `Active (${data.llm_provider.toUpperCase()})`
        : "Deterministic rule-based narration (No API Key required)";
    }
  } catch (err) {
    if (DOM.boardStatus) {
      DOM.boardStatus.replaceChildren();
      const chip = el("span", "chip chip-error");
      chip.appendChild(el("span", "dot"));
      textInto(chip, "backend offline");
      DOM.boardStatus.appendChild(chip);
    }
  }
}

// 2. Overview Command Center
async function loadOverview() {
  try {
    const res = await fetch(`${API}/api/overview`);
    if (!res.ok) throw new Error("Overview endpoint unreachable");
    const data = await res.json();
    state.overviewData = data;

    renderHeroChips(data.suggested_questions || []);
    renderExecutiveAlert(data.alert);
    renderKpiCards(data.cards || []);
    renderSecondaryMetrics(data.secondary || []);
    renderOperationalRisks(data.delayed_preview, data.secondary);
    renderOverviewQuality(data.quality);
    renderCategorizedQuestions(data.suggested_questions || []);
  } catch (err) {
    console.error("Failed to load overview:", err);
  }
}

function renderHeroChips(questions) {
  if (!DOM.heroSuggestedChips) return;
  DOM.heroSuggestedChips.replaceChildren();
  questions.slice(0, 4).forEach((q) => {
    const chip = el("button", "prompt-chip");
    chip.type = "button";
    textInto(chip, q.question);
    chip.addEventListener("click", () => executeQuery(q.question));
    DOM.heroSuggestedChips.appendChild(chip);
  });
}

function renderExecutiveAlert(alert) {
  if (!DOM.executiveAlertContainer) return;
  DOM.executiveAlertContainer.replaceChildren();
  if (!alert) return;

  const banner = el("div", alert.tone === "danger" ? "alert-banner danger" : "alert-banner");
  
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "alert-banner-icon");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("fill", "none");
  icon.setAttribute("stroke", "currentColor");
  icon.setAttribute("stroke-width", "2");
  icon.innerHTML = `<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>`;
  banner.appendChild(icon);

  const content = el("div", "alert-banner-content");
  content.appendChild(el("div", "alert-banner-title", alert.title));
  content.appendChild(el("div", "alert-banner-detail", alert.detail));

  if (alert.question) {
    const btn = el("button", "alert-cta-btn");
    textInto(btn, `${alert.cta || "Analyze Issue"} →`);
    btn.addEventListener("click", () => executeQuery(alert.question));
    content.appendChild(btn);
  }

  banner.appendChild(content);
  DOM.executiveAlertContainer.appendChild(banner);
}

function renderKpiCards(cards) {
  if (!DOM.kpiGrid) return;
  DOM.kpiGrid.replaceChildren();

  cards.forEach((c) => {
    const card = el("div", "kpi-card");
    card.addEventListener("click", () => openProvenanceModal(c.provenance, c.label));

    const head = el("div", "kpi-head");
    const label = el("div", "kpi-label");
    textInto(label, c.label);
    label.appendChild(el("span", "kpi-info-trigger", "i"));
    head.appendChild(label);

    if (c.trend) {
      const pill = el("span", `kpi-trend-pill ${c.trend.direction}`);
      textInto(pill, `${c.trend.direction === "up" ? "↑" : "↓"} ${c.trend.percent.toFixed(0)}%`);
      head.appendChild(pill);
    }
    card.appendChild(head);

    const valRow = el("div", "kpi-value-row");
    valRow.appendChild(el("div", "kpi-value", c.display));
    card.appendChild(valRow);

    if (c.sub) card.appendChild(el("div", "kpi-sub", c.sub));

    if (c.series && c.series.length > 1) {
      const sparkWrap = el("div", "kpi-sparkline-wrap");
      sparkWrap.innerHTML = renderSparklineSVG(c.series);
      card.appendChild(sparkWrap);
    }

    DOM.kpiGrid.appendChild(card);
  });
}

function renderSecondaryMetrics(secondary) {
  if (!DOM.secondaryMetricsBar) return;
  DOM.secondaryMetricsBar.replaceChildren();
  secondary.forEach((m) => {
    const item = el("div", "secondary-metric-item");
    item.addEventListener("click", () => openProvenanceModal(m.provenance, m.label));
    item.appendChild(el("span", "secondary-label", `${m.label}:`));
    item.appendChild(el("span", "secondary-val", m.display));
    DOM.secondaryMetricsBar.appendChild(item);
  });
}

function renderOperationalRisks(delayedPreview) {
  if (!DOM.operationalRisksBody) return;
  const body = DOM.operationalRisksBody;
  body.replaceChildren();

  if (!delayedPreview || !delayedPreview.rows || !delayedPreview.rows.length) {
    body.appendChild(el("div", "loading-shimmer-box", "No critical work order delays recorded."));
    return;
  }

  const tableWrap = el("div", "table-wrap");
  const table = el("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Work Order</th>
        <th>Sector</th>
        <th>Status</th>
        <th>Delay</th>
        <th>Value</th>
      </tr>
    </thead>
  `;
  const tbody = el("tbody");
  delayedPreview.rows.slice(0, 5).forEach((r) => {
    const tr = el("tr");
    tr.innerHTML = `
      <td class="name">${escapeHtml(r.label)}</td>
      <td>${escapeHtml(r.display.sector || "-")}</td>
      <td><span class="badge-pill badge-red">${escapeHtml(r.display.status || "Delayed")}</span></td>
      <td><strong>${escapeHtml(r.display.delay_days || "-")}</strong></td>
      <td>${escapeHtml(r.display.value || "-")}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  body.appendChild(tableWrap);
}

function renderOverviewQuality(quality) {
  if (!DOM.overviewQualityBody) return;
  const body = DOM.overviewQualityBody;
  body.replaceChildren();

  if (!quality) {
    body.appendChild(el("div", "loading-shimmer-box", "All dataset fields meet quality thresholds."));
    return;
  }

  const container = el("div");
  const title = el("div", null, quality.title);
  title.style.fontWeight = "600";
  title.style.color = "var(--warning)";
  title.style.marginBottom = "6px";
  container.appendChild(title);

  const desc = el("div", null, quality.detail);
  desc.style.fontSize = "13px";
  desc.style.color = "var(--text-secondary)";
  desc.style.lineHeight = "1.5";
  container.appendChild(desc);

  const cta = el("button", "alert-cta-btn");
  cta.style.marginTop = "10px";
  textInto(cta, "Inspect full data quality ledger →");
  cta.addEventListener("click", () => switchView("quality"));
  container.appendChild(cta);

  body.appendChild(container);
}

function renderCategorizedQuestions(questions) {
  if (!DOM.categorizedQuestionsGrid) return;
  DOM.categorizedQuestionsGrid.replaceChildren();
  questions.forEach((q) => {
    const card = el("div", "question-card");
    card.addEventListener("click", () => executeQuery(q.question));

    card.appendChild(el("div", "q-category-tag", q.category));
    card.appendChild(el("div", "q-title", q.question));
    card.appendChild(el("div", "q-caption", q.caption));

    DOM.categorizedQuestionsGrid.appendChild(card);
  });
}

const CANONICAL_QUESTIONS = [
  {
    category: "Pipeline & Forecast",
    question: "What's our total and weighted pipeline?",
    caption: "Examine total open opportunity value and probability-weighted pipeline.",
  },
  {
    category: "Revenue Performance",
    question: "How much revenue have we won?",
    caption: "Review closed-won deal value, deal count, and historical bookings.",
  },
  {
    category: "Operational Risk",
    question: "How many work orders are delayed?",
    caption: "Break down active delivery delays, average delay days, and backlog.",
  },
  {
    category: "Sector Demand",
    question: "Which sector has the strongest pipeline?",
    caption: "Rank open sales pipeline opportunities across all industry sectors.",
  },
  {
    category: "Cross-Board Strategy",
    question: "Which sectors have strong pipeline but weak delivery?",
    caption: "Cross-board 4-quadrant matrix matching sales demand against delivery completion.",
  },
  {
    category: "Accounts at Risk",
    question: "Which customers have both high pipeline and delivery risk?",
    caption: "Identify accounts being sold new deals while having delayed active work orders.",
  },
  {
    category: "Billing Risk",
    question: "How much work is completed but not yet billed?",
    caption: "Spot delivered work orders without invoice to recover unbilled revenue.",
  },
  {
    category: "Data Governance",
    question: "How good is our data quality and completeness?",
    caption: "Run full data governance audit across missing fields, flags, and caveats.",
  },
];

function renderChatStarterCards(questions) {
  const list = questions && questions.length ? questions : CANONICAL_QUESTIONS;

  if (DOM.chatStarterGrid) {
    DOM.chatStarterGrid.replaceChildren();
    list.forEach((q) => {
      const card = el("div", "chat-starter-card");
      card.addEventListener("click", () => executeQuery(q.question));

      card.appendChild(el("div", "q-category-tag", q.category));
      card.appendChild(el("div", "q-title", q.question));
      card.appendChild(el("div", "q-caption", q.caption));

      DOM.chatStarterGrid.appendChild(card);
    });
  }

  if (DOM.chatQuickChips) {
    DOM.chatQuickChips.replaceChildren();
    list.slice(0, 6).forEach((q) => {
      const chip = el("button", "chat-quick-chip");
      chip.type = "button";
      textInto(chip, q.question);
      chip.addEventListener("click", () => executeQuery(q.question));
      DOM.chatQuickChips.appendChild(chip);
    });
  }
}

// 3. AI Conversational Analytics
async function executeQuery(question) {
  if (state.isBusy || !question || !question.trim()) return;
  state.isBusy = true;

  switchView("chat");

  if (DOM.chatStarterHero) DOM.chatStarterHero.style.display = "none";
  if (DOM.chatThread) DOM.chatThread.style.display = "flex";

  if (DOM.chatSendButton) DOM.chatSendButton.disabled = true;
  if (DOM.heroQuestionInput) DOM.heroQuestionInput.value = "";
  if (DOM.chatQuestionInput) DOM.chatQuestionInput.value = "";

  const thread = DOM.chatThread;
  if (!thread) return;

  const turn = el("div", "turn");
  const userMsg = el("div", "user-msg");
  userMsg.appendChild(el("span", null, question));
  turn.appendChild(userMsg);

  const agentMsg = el("div", "agent-msg");
  const thinking = el("div", "thinking-state");
  thinking.appendChild(el("div", "spinner"));
  thinking.appendChild(el("span", null, "Evaluating intent and computing metrics from records…"));
  agentMsg.appendChild(thinking);
  turn.appendChild(agentMsg);

  thread.appendChild(turn);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });

  try {
    const res = await fetch(`${API}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: question,
        history: state.chatHistory.slice(-4),
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `Request failed (${res.status})`);
    }

    const data = await res.json();
    agentMsg.replaceWith(renderStructuredAnswer(data));

    state.chatHistory.push({ role: "user", content: question });
    state.chatHistory.push({ role: "assistant", content: data.answer });
    state.chatHistory = state.chatHistory.slice(-8);

    saveRecentAnalysis(question, data);
  } catch (err) {
    const errorBox = el("div", "alert-banner danger");
    errorBox.appendChild(el("div", "alert-banner-detail", err.message || "Failed to complete query."));
    agentMsg.replaceWith(errorBox);
  } finally {
    state.isBusy = false;
    if (DOM.chatSendButton) DOM.chatSendButton.disabled = false;
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }
}

function renderStructuredAnswer(data) {
  const card = el("div", "agent-msg");

  if (data.plan) {
    const strip = el("div", "plan-strip");
    strip.appendChild(el("span", "plan-label", "Interpreted Intent:"));
    strip.appendChild(el("span", "plan-chip accent", data.plan.intent?.replace(/_/g, " ")));

    (data.plan.boards || []).forEach((b) => {
      strip.appendChild(el("span", "plan-chip", `${b} board`));
    });

    const f = data.plan.filters || {};
    if (f.sector) strip.appendChild(el("span", "plan-chip", `sector: ${f.sector}`));
    if (f.owner) strip.appendChild(el("span", "plan-chip", `owner: ${f.owner}`));
    if (f.account) strip.appendChild(el("span", "plan-chip", `account: ${f.account}`));

    card.appendChild(strip);
  }

  const body = el("div", "msg-body");
  body.appendChild(el("p", "answer", data.answer));

  if (data.insight) {
    body.appendChild(el("div", "insight-callout", data.insight));
  }

  if (data.metrics && data.metrics.length) {
    const mRow = el("div", "metrics-row");
    data.metrics.slice(0, 6).forEach((m) => {
      const mCard = el("div", "metric-card-inline");
      mCard.addEventListener("click", () => openProvenanceModal(m, m.label));

      const label = el("div", "m-label");
      textInto(label, m.label);
      label.appendChild(el("span", "kpi-info-trigger", "i"));
      mCard.appendChild(label);

      mCard.appendChild(el("div", "m-value", m.display));
      if (m.rows_considered > 0) {
        mCard.appendChild(el("div", "m-rows", `${m.rows_included}/${m.rows_considered} records`));
      }
      mRow.appendChild(mCard);
    });
    body.appendChild(mRow);
  }

  if (data.breakdowns && data.breakdowns.length) {
    data.breakdowns.forEach((bd) => {
      const bdNode = renderBreakdownComponent(bd);
      if (bdNode) body.appendChild(bdNode);
    });
  }

  if (data.ledger) {
    body.appendChild(renderLedgerComponent(data.ledger));
  }

  if (data.follow_ups && data.follow_ups.length) {
    const fWrap = el("div", "followups");
    data.follow_ups.forEach((q) => {
      const btn = el("button", "followup-btn", q);
      btn.addEventListener("click", () => executeQuery(q));
      fWrap.appendChild(btn);
    });
    body.appendChild(fWrap);
  }

  card.appendChild(body);
  return card;
}

function renderBreakdownComponent(bd) {
  if (!bd.rows || !bd.rows.length) return null;

  const section = el("div", "section-container");
  section.appendChild(el("h4", "section-heading", bd.title));

  if (bd.chart === "bar" && bd.columns.includes("value") && bd.rows.every((r) => r.values.value !== undefined)) {
    const values = bd.rows.map((r) => Number(r.values.value) || 0);
    const max = Math.max(...values, 1);
    const bars = el("div", "bars");

    bd.rows.slice(0, 10).forEach((r) => {
      const row = el("div", "bar-row");
      row.appendChild(el("div", "bar-name", r.label));

      const track = el("div", "bar-track");
      const fill = el("div", "bar-fill");
      fill.style.width = `${Math.max((Number(r.values.value) || 0) / max * 100, 2)}%`;
      track.appendChild(fill);
      row.appendChild(track);

      row.appendChild(el("div", "bar-value", r.display.value));
      bars.appendChild(row);
    });
    section.appendChild(bars);
  } else {
    const wrap = el("div", "table-wrap");
    const table = el("table");
    const cols = bd.columns.filter((c) => bd.rows.some((r) => r.display[c] !== undefined));

    let theadHtml = `<thead><tr><th>${escapeHtml(bd.dimension)}</th>`;
    cols.forEach((c) => { theadHtml += `<th>${escapeHtml(c.replace(/_/g, " "))}</th>`; });
    theadHtml += `</tr></thead>`;
    table.innerHTML = theadHtml;

    const tbody = el("tbody");
    bd.rows.slice(0, 12).forEach((r) => {
      const tr = el("tr");
      tr.appendChild(el("td", "name", r.label));
      cols.forEach((c) => {
        const td = el("td");
        const val = r.display[c];
        if (c === "quadrant" && val) {
          const quadClass = {
            Scale: "quad-scale",
            "Fix delivery": "quad-fix",
            Underinvested: "quad-under",
            Deprioritise: "quad-depri",
          }[val] || "quad-none";
          td.innerHTML = `<span class="quad ${quadClass}">${escapeHtml(val)}</span>`;
        } else {
          textInto(td, val !== undefined ? val : "-");
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    section.appendChild(wrap);
  }

  if (bd.note) {
    const note = el("p", "section-subtext", bd.note);
    note.style.marginTop = "6px";
    section.appendChild(note);
  }

  return section;
}

function renderLedgerComponent(ledger) {
  const details = document.createElement("details");
  details.className = "ledger-accordion";

  const summary = document.createElement("summary");
  summary.className = "ledger-summary";

  const conf = el("span", `conf conf-${ledger.confidence}`, `${ledger.confidence} confidence`);
  summary.appendChild(conf);
  textInto(summary, ` Provenance Ledger: ${ledger.rows_included} of ${ledger.rows_considered} records analyzed`);
  details.appendChild(summary);

  const body = el("div", "ledger-body");

  if (ledger.exclusions && Object.keys(ledger.exclusions).length > 0) {
    body.appendChild(el("div", "ledger-section-title", "Excluded Records"));
    const ul = el("ul", "ledger-list");
    Object.entries(ledger.exclusions).forEach(([k, v]) => {
      const li = el("li");
      li.innerHTML = `<span class="count">${v}</span> — ${escapeHtml(k)}`;
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  if (ledger.normalizations && Object.keys(ledger.normalizations).length > 0) {
    body.appendChild(el("div", "ledger-section-title", "Applied Cleaning"));
    const ul = el("ul", "ledger-list");
    Object.entries(ledger.normalizations).slice(0, 6).forEach(([k, v]) => {
      const li = el("li");
      li.innerHTML = `<span class="count">${v}</span> — ${escapeHtml(k)}`;
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  details.appendChild(body);
  return details;
}

function saveRecentAnalysis(question, data) {
  state.recentAnalyses.unshift({
    id: Date.now(),
    question,
    answer: data.answer,
    timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  });
  state.recentAnalyses = state.recentAnalyses.slice(0, 6);
  renderRecentAnalyses();
}

function renderRecentAnalyses() {
  if (!DOM.recentAnalysesGrid) return;
  const grid = DOM.recentAnalysesGrid;
  grid.replaceChildren();

  if (!state.recentAnalyses.length) {
    grid.appendChild(el("div", "empty-history-hint", "No queries executed yet in this session. Ask a question above to start."));
    return;
  }

  state.recentAnalyses.forEach((item) => {
    const card = el("div", "recent-analysis-card");
    card.addEventListener("click", () => executeQuery(item.question));

    card.appendChild(el("div", "recent-query-title", item.question));
    card.appendChild(el("div", "recent-answer-snippet", item.answer));

    const meta = el("div", "recent-meta-row");
    meta.appendChild(el("span", null, `Executed at ${item.timestamp}`));
    meta.appendChild(el("span", null, "Click to re-run →"));
    card.appendChild(meta);

    grid.appendChild(card);
  });
}

// 4. Insights
async function loadInsights() {
  try {
    const res = await fetch(`${API}/api/insights`);
    if (!res.ok) throw new Error("Insights endpoint unreachable");
    const data = await res.json();
    state.insightsData = data;

    if (DOM.insightsCoverageBadge && data.coverage) {
      DOM.insightsCoverageBadge.textContent = `Coverage: ${data.coverage.display} accounts linked (~${data.coverage.rows_included}/${data.coverage.rows_considered})`;
      DOM.insightsCoverageBadge.style.cursor = "pointer";
      DOM.insightsCoverageBadge.onclick = () => openProvenanceModal(data.coverage, "Cross-Board Coverage");
    }

    renderSectorMatrixScatter(data.sector_matrix);
    renderAccountsAtRisk(data.accounts_at_risk);
    renderOwnerPerformance(data.owner_cross);
  } catch (err) {
    console.error("Failed to load insights:", err);
  }
}

function renderSectorMatrixScatter(matrix) {
  if (!DOM.sectorMatrixContainer) return;
  const container = DOM.sectorMatrixContainer;
  container.replaceChildren();

  if (!matrix || !matrix.rows || matrix.rows.length < 2) {
    container.appendChild(el("div", "loading-shimmer-box", "Insufficient cross-board sector points to plot matrix."));
    return;
  }

  const pts = matrix.rows.filter((r) => r.values.pipeline != null && r.values.completion_rate != null);
  if (!pts.length) return;

  const W = 680, H = 380, PAD = { t: 26, r: 30, b: 50, l: 64 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;

  const xs = pts.map((p) => Number(p.values.pipeline) || 0);
  const xMax = Math.max(...xs) * 1.15 || 1;
  const sizes = pts.map((p) => Number(p.values.work_orders) || 0);
  const sMax = Math.max(...sizes, 1);

  const med = (a) => {
    const v = [...a].sort((m, n) => m - n);
    const i = Math.floor(v.length / 2);
    return v.length % 2 ? v[i] : (v[i - 1] + v[i]) / 2;
  };
  const xMed = med(xs);
  const yMed = med(pts.map((p) => Number(p.values.completion_rate) || 0));

  const X = (v) => PAD.l + (v / xMax) * iw;
  const Y = (v) => PAD.t + ih - (v / 100) * ih;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "scatter-svg");

  const mk = (tag, attrs, text) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  };

  mk("rect", { x: X(xMed), y: PAD.t, width: Math.max(X(xMax) - X(xMed), 0), height: Y(yMed) - PAD.t, class: "q-good" });
  mk("rect", { x: X(xMed), y: Y(yMed), width: Math.max(X(xMax) - X(xMed), 0), height: PAD.t + ih - Y(yMed), class: "q-bad" });

  mk("line", { x1: PAD.l, y1: Y(yMed), x2: PAD.l + iw, y2: Y(yMed), class: "q-line" });
  mk("line", { x1: X(xMed), y1: PAD.t, x2: X(xMed), y2: PAD.t + ih, class: "q-line" });

  mk("line", { x1: PAD.l, y1: PAD.t, x2: PAD.l, y2: PAD.t + ih, class: "axis" });
  mk("line", { x1: PAD.l, y1: PAD.t + ih, x2: PAD.l + iw, y2: PAD.t + ih, class: "axis" });

  [0, 50, 100].forEach((v) => {
    mk("text", { x: PAD.l - 10, y: Y(v) + 4, class: "tick", "text-anchor": "end" }, `${v}%`);
  });

  mk("text", { x: PAD.l + iw, y: PAD.t + ih + 38, class: "axis-label", "text-anchor": "end" }, "Open Pipeline Demand (INR) →");
  mk("text", { x: -(PAD.t + ih / 2), y: 16, class: "axis-label", "text-anchor": "middle", transform: "rotate(-90)" }, "Delivery Completion Rate →");

  mk("text", { x: X(xMed) + 10, y: PAD.t + 16, class: "q-label q-label-good" }, "SCALE (Strong Demand + Delivery)");
  mk("text", { x: X(xMed) + 10, y: PAD.t + ih - 10, class: "q-label q-label-bad" }, "FIX DELIVERY (High Risk)");

  pts.forEach((p) => {
    const cx = X(Number(p.values.pipeline) || 0);
    const cy = Y(Number(p.values.completion_rate) || 0);
    const r = 6 + ((Number(p.values.work_orders) || 0) / sMax) * 14;
    const isBad = p.display.quadrant === "Fix delivery";

    const dot = mk("circle", { cx, cy, r, class: isBad ? "dot dot-bad" : "dot" });
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${p.label}: ${p.display.pipeline} pipeline | ${p.display.completion_rate} completion | ${p.display.work_orders} work orders (${p.display.delayed} delayed)`;
    dot.appendChild(title);

    mk("text", { x: cx, y: cy - r - 6, class: "dot-label", "text-anchor": "middle" }, p.label);
  });

  container.appendChild(svg);
}

function renderAccountsAtRisk(accounts) {
  if (!DOM.accountsRiskBody) return;
  const body = DOM.accountsRiskBody;
  body.replaceChildren();

  if (!accounts || !accounts.rows || !accounts.rows.length) {
    body.appendChild(el("div", "loading-shimmer-box", "No accounts with active pipeline and delayed delivery."));
    return;
  }

  const tableWrap = el("div", "table-wrap");
  const table = el("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Account</th>
        <th>Open Pipeline</th>
        <th>Delayed WOs</th>
        <th>Total WOs</th>
      </tr>
    </thead>
  `;
  const tbody = el("tbody");
  accounts.rows.slice(0, 8).forEach((r) => {
    const tr = el("tr");
    tr.innerHTML = `
      <td class="name">${escapeHtml(r.label)}</td>
      <td><strong>${escapeHtml(r.display.open_pipeline || "-")}</strong></td>
      <td><span class="badge-pill badge-red">${escapeHtml(r.display.delayed || "-")}</span></td>
      <td>${escapeHtml(r.display.work_orders || "-")}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  body.appendChild(tableWrap);
}

function renderOwnerPerformance(owners) {
  if (!DOM.ownerPerformanceBody) return;
  const body = DOM.ownerPerformanceBody;
  body.replaceChildren();

  if (!owners || !owners.rows || !owners.rows.length) {
    body.appendChild(el("div", "loading-shimmer-box", "No owner comparison records available."));
    return;
  }

  const tableWrap = el("div", "table-wrap");
  const table = el("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Owner Code</th>
        <th>Open Pipeline</th>
        <th>Open Deals</th>
        <th>Work Orders</th>
        <th>Delayed</th>
      </tr>
    </thead>
  `;
  const tbody = el("tbody");
  owners.rows.slice(0, 8).forEach((r) => {
    const tr = el("tr");
    tr.innerHTML = `
      <td class="name"><code>${escapeHtml(r.label)}</code></td>
      <td>${escapeHtml(r.display.pipeline || "-")}</td>
      <td>${escapeHtml(r.display.open_deals || "-")}</td>
      <td>${escapeHtml(r.display.work_orders || "-")}</td>
      <td>${Number(r.values.delayed) > 0 ? `<span class="badge-pill badge-amber">${escapeHtml(r.display.delayed)}</span>` : "0"}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  body.appendChild(tableWrap);
}

// 5. Reports
async function loadReports() {
  // Show loading placeholders immediately
  if (DOM.reportTalkingPointsList) {
    DOM.reportTalkingPointsList.replaceChildren();
    const li = el("li", "shimmer-text");
    textInto(li, "Calculating from Monday.com…");
    DOM.reportTalkingPointsList.appendChild(li);
  }
  showViewLoading(DOM.reportRankedRisks, "Evaluating risks from board data…");
  showViewLoading(DOM.quarterlyTrendBody, "Building quarterly creation trend…");
  showViewLoading(DOM.funnelStageBody, "Calculating funnel distribution…");

  try {
    const res = await fetch(`${API}/api/reports`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.reportsData = data;

    if (DOM.reportTitleHeader) {
      DOM.reportTitleHeader.textContent = `Leadership Briefing (${data.period_label || "Current Period"})`;
    }

    if (DOM.reportTalkingPointsList) {
      DOM.reportTalkingPointsList.replaceChildren();
      const points = data.talking_points || [];
      if (!points.length) {
        DOM.reportTalkingPointsList.appendChild(el("li", null, "No talking points available for this period."));
      } else {
        points.forEach((pt) => DOM.reportTalkingPointsList.appendChild(el("li", null, pt)));
      }
    }

    if (DOM.copyTalkingPointsBtn) {
      DOM.copyTalkingPointsBtn.onclick = async () => {
        const text = (data.talking_points || []).map((p) => `• ${p}`).join("\n");
        await navigator.clipboard.writeText(text);
        const span = DOM.copyTalkingPointsBtn.querySelector("span");
        if (span) span.textContent = "Copied to Clipboard!";
        setTimeout(() => { if (span) span.textContent = "Copy Talking Points"; }, 2000);
      };
    }

    if (DOM.reportRankedRisks) {
      DOM.reportRankedRisks.replaceChildren();
      const risks = data.ranked_risks || [];
      if (!risks.length) {
        DOM.reportRankedRisks.appendChild(el("div", "loading-shimmer-box", "No material risks identified."));
      } else {
        risks.forEach((risk) => DOM.reportRankedRisks.appendChild(el("div", "risk-item-row", risk)));
      }
    }

    renderQuarterlyTrend(data.quarterly_trend);
    renderFunnelStage(data.funnel_stage);
  } catch (err) {
    console.error("Failed to load reports:", err);
    const msg = err.message || "Network error";
    showViewError(DOM.reportRankedRisks, msg, () => { state.reportsData = null; loadReports(); });
    showViewError(DOM.quarterlyTrendBody, msg, () => { state.reportsData = null; loadReports(); });
    showViewError(DOM.funnelStageBody, msg, () => { state.reportsData = null; loadReports(); });
    if (DOM.reportTalkingPointsList) {
      DOM.reportTalkingPointsList.replaceChildren();
      const li = el("li", null, `Failed to load: ${msg}. Click refresh to retry.`);
      DOM.reportTalkingPointsList.appendChild(li);
    }
  }
}

function renderQuarterlyTrend(trend) {
  if (!DOM.quarterlyTrendBody) return;
  const body = DOM.quarterlyTrendBody;
  body.replaceChildren();

  if (!trend || !trend.rows || !trend.rows.length) {
    body.appendChild(el("div", "loading-shimmer-box", "No quarterly creation data available."));
    return;
  }

  const values = trend.rows.map((r) => Number(r.values.value) || 0);
  const max = Math.max(...values, 1);
  const bars = el("div", "bars");

  trend.rows.forEach((r) => {
    const row = el("div", "bar-row");
    row.appendChild(el("div", "bar-name", r.label));

    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.max((Number(r.values.value) || 0) / max * 100, 2)}%`;
    track.appendChild(fill);
    row.appendChild(track);

    row.appendChild(el("div", "bar-value", r.display.value || "-"));
    bars.appendChild(row);
  });
  body.appendChild(bars);
}

function renderFunnelStage(funnel) {
  if (!DOM.funnelStageBody) return;
  const body = DOM.funnelStageBody;
  body.replaceChildren();

  if (!funnel || !funnel.rows || !funnel.rows.length) {
    body.appendChild(el("div", "loading-shimmer-box", "No funnel data available."));
    return;
  }

  const values = funnel.rows.map((r) => Number(r.values.deals) || 0);
  const max = Math.max(...values, 1);
  const bars = el("div", "bars");

  funnel.rows.forEach((r) => {
    const row = el("div", "bar-row");
    row.appendChild(el("div", "bar-name", r.label));

    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.max((Number(r.values.deals) || 0) / max * 100, 2)}%`;
    fill.style.background = "linear-gradient(90deg, var(--purple), #a78bfa)";
    track.appendChild(fill);
    row.appendChild(track);

    row.appendChild(el("div", "bar-value", `${r.display.deals} deals`));
    bars.appendChild(row);
  });
  body.appendChild(bars);
}

// 6. Data Quality View
async function loadDataQuality() {
  try {
    const res = await fetch(`${API}/api/data-quality`);
    if (!res.ok) throw new Error("Data quality endpoint unreachable");
    const data = await res.json();
    state.qualityData = data;

    if (DOM.qualityScoreNum) {
      DOM.qualityScoreNum.textContent = `${data.health_score || 0}%`;
    }
    const scoreBadge = document.getElementById("navQualityBadge");
    if (scoreBadge) scoreBadge.textContent = `${data.health_score || 0}%`;

    renderBoardQualityTable(DOM.qualityDealsBody, data.deals_missing, data.deals_count, "Deals");
    renderBoardQualityTable(DOM.qualityWorkOrdersBody, data.wo_missing, data.work_orders_count, "Work Orders");
    renderQualityLedgerView(DOM.qualityLedgerTableBody, data.metrics, data.caveats);
  } catch (err) {
    console.error("Failed to load data quality:", err);
  }
}

function renderBoardQualityTable(container, missingDict, totalRows, boardName) {
  if (!container) return;
  container.replaceChildren();
  if (!missingDict || !Object.keys(missingDict).length) {
    container.appendChild(el("div", "loading-shimmer-box", `No column issues found in ${boardName}.`));
    return;
  }

  const tableWrap = el("div", "table-wrap");
  const table = el("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Column Name</th>
        <th>Missing Values</th>
        <th>Completeness Rate</th>
      </tr>
    </thead>
  `;
  const tbody = el("tbody");
  Object.entries(missingDict).forEach(([col, missing]) => {
    const pct = totalRows ? ((totalRows - missing) / totalRows * 100).toFixed(0) : "0";
    const tr = el("tr");
    tr.innerHTML = `
      <td><code>${escapeHtml(col)}</code></td>
      <td><span class="count">${missing}</span> / ${totalRows} rows</td>
      <td><span class="badge-pill ${Number(pct) > 80 ? "badge-green" : Number(pct) > 50 ? "badge-amber" : "badge-red"}">${pct}% complete</span></td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  container.appendChild(tableWrap);
}

function renderQualityLedgerView(container, metrics, caveats) {
  if (!container) return;
  container.replaceChildren();

  const grid = el("div", "kpi-grid");
  (metrics || []).forEach((m) => {
    const card = el("div", "kpi-card");
    card.addEventListener("click", () => openProvenanceModal(m, m.label));

    const head = el("div", "kpi-head");
    head.appendChild(el("div", "kpi-label", m.label));
    card.appendChild(head);

    card.appendChild(el("div", "kpi-value", m.display));
    if (m.definition) card.appendChild(el("div", "kpi-sub", m.definition));
    grid.appendChild(card);
  });
  container.appendChild(grid);

  if (caveats && caveats.length) {
    const sec = el("div", "section-container");
    sec.appendChild(el("h4", "section-heading", "Structural Schema Caveats"));
    const ul = el("ul", "ledger-list");
    caveats.forEach((c) => ul.appendChild(el("li", null, c)));
    sec.appendChild(ul);
    container.appendChild(sec);
  }
}

// 7. Sources View
function renderSourcesView(boardsData) {
  if (!DOM.sourcesBoardGrid) return;
  const grid = DOM.sourcesBoardGrid;
  grid.replaceChildren();

  const dealsCard = el("div", "source-board-card");
  dealsCard.innerHTML = `
    <div class="source-board-title">
      <span>Deals Funnel Board</span>
      <span class="badge-pill badge-green">Connected</span>
    </div>
    <div class="source-meta-item"><span>Status</span><span>Active (Read-Only)</span></div>
    <div class="source-meta-item"><span>Primary Join Key</span><span><code>deal_name</code> (Account Alias)</span></div>
    <div class="source-meta-item"><span>Monetary Unit</span><span>INR (Lakh/Crore Parsed)</span></div>
    <div class="source-meta-item"><span>Sync Method</span><span>Cached / Direct GraphQL</span></div>
  `;
  grid.appendChild(dealsCard);

  const woCard = el("div", "source-board-card");
  woCard.innerHTML = `
    <div class="source-board-title">
      <span>Work Orders Board</span>
      <span class="badge-pill badge-green">Connected</span>
    </div>
    <div class="source-meta-item"><span>Status</span><span>Active (Read-Only)</span></div>
    <div class="source-meta-item"><span>Primary Join Key</span><span><code>deal_name</code> (~90% Overlap)</span></div>
    <div class="source-meta-item"><span>Date Resolution</span><span>Day-first (DD/MM/YYYY)</span></div>
    <div class="source-meta-item"><span>Sync Method</span><span>Cached / Direct GraphQL</span></div>
  `;
  grid.appendChild(woCard);
}

/* ================= INITIALIZATION ================= */

function showViewLoading(container, message) {
  if (!container) return;
  container.replaceChildren();
  const box = el("div", "loading-shimmer-box");
  const spinner = el("div", "spinner");
  spinner.style.display = "inline-block";
  spinner.style.width = "18px";
  spinner.style.height = "18px";
  spinner.style.marginRight = "10px";
  box.style.display = "flex";
  box.style.alignItems = "center";
  box.appendChild(spinner);
  textInto(box, message || "Fetching data from Monday.com…");
  container.appendChild(box);
}

function showViewError(container, errMsg, retryFn) {
  if (!container) return;
  container.replaceChildren();
  const box = el("div", "loading-shimmer-box");
  box.style.borderColor = "var(--danger)";
  box.style.color = "var(--danger)";
  textInto(box, "Error: " + (errMsg || "Failed to load data."));
  if (retryFn) {
    const btn = el("button", "alert-cta-btn");
    btn.style.marginTop = "10px";
    btn.style.display = "block";
    textInto(btn, "Retry →");
    btn.onclick = retryFn;
    box.appendChild(btn);
  }
  container.appendChild(box);
}

function initApp() {
  resolveDOM();
  initNavigation();
  initModal();

  if (DOM.heroQueryForm) {
    DOM.heroQueryForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (DOM.heroQuestionInput) executeQuery(DOM.heroQuestionInput.value);
    });
  }

  if (DOM.chatComposerForm) {
    DOM.chatComposerForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (DOM.chatQuestionInput) executeQuery(DOM.chatQuestionInput.value);
    });
  }

  if (DOM.refreshDataBtn) {
    DOM.refreshDataBtn.addEventListener("click", () => {
      // Force reload all views
      state.overviewData = null;
      state.insightsData = null;
      state.reportsData = null;
      state.qualityData = null;
      state.boardsData = null;
      loadBoardStatus();
      loadOverview();
      if (state.currentView === "insights") loadInsights();
      if (state.currentView === "reports") loadReports();
      if (state.currentView === "quality") loadDataQuality();
      if (state.currentView === "sources") loadBoardStatus();
    });
  }

  if (DOM.clearHistoryBtn) {
    DOM.clearHistoryBtn.addEventListener("click", () => {
      state.recentAnalyses = [];
      renderRecentAnalyses();
    });
  }

  // Render Chat Starter Questions immediately (no API needed)
  renderChatStarterCards(CANONICAL_QUESTIONS);

  // Load board status & overview on startup (fast)
  loadBoardStatus();
  loadOverview();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
