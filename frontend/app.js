/* Skylark Business Intelligence - client
 *
 * Deliberately dependency-free. The interesting property: metric values are
 * rendered from the `metrics` array returned by the analytics engine, never
 * parsed out of the model's prose. The wording and the numbers travel on
 * separate paths, so wording can never corrupt a figure.
 */

const API = "";
const conversation = document.getElementById("conversation");
const welcome = document.getElementById("welcome");
const form = document.getElementById("composerForm");
const input = document.getElementById("questionInput");
const sendButton = document.getElementById("sendButton");
const boardStatus = document.getElementById("boardStatus");

let history = [];
let busy = false;

/* ---------------------------------------------------------------- utils */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** All board-derived strings go through here. Board content is untrusted
 *  input, so it is inserted as text nodes and never as HTML. */
function textInto(parent, value) {
  parent.appendChild(document.createTextNode(value == null ? "" : String(value)));
  return parent;
}

function scrollToEnd() {
  requestAnimationFrame(() =>
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" })
  );
}

function freshness(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

/* -------------------------------------------------------- board status */

async function loadBoardStatus() {
  try {
    const res = await fetch(`${API}/api/boards`);
    const data = await res.json();
    boardStatus.replaceChildren();

    if (!data.monday_configured) {
      const chip = el("span", "chip chip-error");
      chip.appendChild(el("span", "dot"));
      textInto(chip, "Monday.com not configured");
      boardStatus.appendChild(chip);
      return;
    }

    (data.boards || []).forEach((board) => {
      const chip = el("span", board.error ? "chip chip-error" : "chip");
      chip.appendChild(el("span", "dot"));
      const label = board.error
        ? `${board.name}: unavailable`
        : `${board.name} · ${board.item_count} items · ${freshness(board.age_seconds)}`;
      textInto(chip, label);
      if (board.error) chip.title = board.error;
      boardStatus.appendChild(chip);
    });

    if (!data.llm_configured) {
      const chip = el("span", "chip chip-muted");
      textInto(chip, `${data.llm_provider} key missing · template answers`);
      boardStatus.appendChild(chip);
    }
  } catch {
    boardStatus.replaceChildren();
    const chip = el("span", "chip chip-error");
    chip.appendChild(el("span", "dot"));
    textInto(chip, "backend unreachable");
    boardStatus.appendChild(chip);
  }
}

/* ------------------------------------------------------------ renderers */

function renderPlanStrip(plan) {
  if (!plan) return null;
  const strip = el("div", "plan-strip");
  strip.appendChild(el("span", "plan-label", "Interpreted as"));

  const intentChip = el("span", "plan-chip accent");
  textInto(intentChip, plan.intent.replace(/_/g, " "));
  strip.appendChild(intentChip);

  (plan.boards || []).forEach((b) => {
    const chip = el("span", "plan-chip");
    textInto(chip, b.replace(/_/g, " "));
    strip.appendChild(chip);
  });

  const f = plan.filters || {};
  const filterBits = [];
  if (f.sector) filterBits.push(`sector: ${f.sector}`);
  if (f.owner) filterBits.push(`owner: ${f.owner}`);
  if (f.account) filterBits.push(`account: ${f.account}`);
  if (f.date_range && f.date_range.preset)
    filterBits.push(f.date_range.preset.replace(/_/g, " "));
  filterBits.forEach((bit) => {
    const chip = el("span", "plan-chip");
    textInto(chip, bit);
    strip.appendChild(chip);
  });

  return strip;
}

function renderMetrics(metrics) {
  const shown = (metrics || []).slice(0, 6);
  if (!shown.length) return null;
  const grid = el("div", "metrics");

  shown.forEach((m) => {
    const card = el("div", "metric");

    const label = el("div", "metric-label");
    textInto(label, m.label);
    if (m.definition || m.formula) label.appendChild(el("span", "info", "i"));
    card.appendChild(label);

    const value = el(
      "div",
      m.value === null ? "metric-value unavailable" : "metric-value"
    );
    textInto(value, m.display);
    card.appendChild(value);

    if (m.rows_considered > 0) {
      const rows = el("div", "metric-rows");
      textInto(rows, `${m.rows_included}/${m.rows_considered} records`);
      card.appendChild(rows);
    }

    if (m.definition || m.formula) {
      const tip = el("div", "tip");
      if (m.definition) textInto(tip, m.definition);
      if (m.formula) {
        tip.appendChild(document.createElement("br"));
        const code = el("code");
        textInto(code, m.formula);
        tip.appendChild(code);
      }
      card.appendChild(tip);
    }
    grid.appendChild(card);
  });
  return grid;
}

const QUADRANT_CLASS = {
  Scale: "quad-scale",
  "Fix delivery": "quad-fix",
  Underinvested: "quad-under",
  "Deprioritise": "quad-depri",
};


/* The cross-board showpiece: pipeline (x) against delivery health (y).
 * Hand-rolled SVG -- a charting library would be 40kb for one chart, and this
 * needs to be readable in both themes without a runtime dependency. */
function renderScatter(bd) {
  const pts = bd.rows.filter(
    (r) => r.values.pipeline != null && r.values.completion_rate != null
  );
  const unplotted = bd.rows.filter(
    (r) => r.values.pipeline == null || r.values.completion_rate == null
  );
  if (pts.length < 2) return null;

  const W = 560, H = 340, PAD = { t: 22, r: 22, b: 46, l: 58 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;

  const xs = pts.map((p) => p.values.pipeline);
  const xMax = Math.max(...xs) * 1.12 || 1;
  const sizes = pts.map((p) => p.values.work_orders || 0);
  const sMax = Math.max(...sizes, 1);

  // Quadrant lines sit at the median of each axis, matching how the backend
  // assigns quadrant labels.
  const med = (a) => {
    const v = [...a].sort((m, n) => m - n);
    const i = Math.floor(v.length / 2);
    return v.length % 2 ? v[i] : (v[i - 1] + v[i]) / 2;
  };
  const xMed = med(xs);
  const yMed = med(pts.map((p) => p.values.completion_rate));

  const X = (v) => PAD.l + (v / xMax) * iw;
  const Y = (v) => PAD.t + ih - (v / 100) * ih;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "scatter");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", bd.title);

  const mk = (tag, attrs, text) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text !== undefined) n.textContent = text;
    svg.appendChild(n);
    return n;
  };

  // quadrant shading: the "fix delivery" corner is the one that matters
  mk("rect", { x: X(xMed), y: PAD.t, width: Math.max(X(xMax) - X(xMed), 0),
               height: Y(yMed) - PAD.t, class: "q-good" });
  mk("rect", { x: X(xMed), y: Y(yMed), width: Math.max(X(xMax) - X(xMed), 0),
               height: PAD.t + ih - Y(yMed), class: "q-bad" });

  mk("line", { x1: PAD.l, y1: Y(yMed), x2: PAD.l + iw, y2: Y(yMed), class: "q-line" });
  mk("line", { x1: X(xMed), y1: PAD.t, x2: X(xMed), y2: PAD.t + ih, class: "q-line" });

  mk("line", { x1: PAD.l, y1: PAD.t, x2: PAD.l, y2: PAD.t + ih, class: "axis" });
  mk("line", { x1: PAD.l, y1: PAD.t + ih, x2: PAD.l + iw, y2: PAD.t + ih, class: "axis" });

  [0, 50, 100].forEach((v) => {
    mk("text", { x: PAD.l - 8, y: Y(v) + 4, class: "tick", "text-anchor": "end" }, v + "%");
  });

  mk("text", { x: PAD.l + iw, y: PAD.t + ih + 34, class: "axis-label",
               "text-anchor": "end" }, "Open pipeline →");
  mk("text", { x: -(PAD.t + ih / 2), y: 15, class: "axis-label",
               "text-anchor": "middle", transform: "rotate(-90)" }, "Delivery completion →");

  mk("text", { x: X(xMed) + 8, y: PAD.t + 14, class: "q-label q-label-good" }, "SCALE");
  mk("text", { x: X(xMed) + 8, y: PAD.t + ih - 8, class: "q-label q-label-bad" }, "FIX DELIVERY");

  pts.forEach((p) => {
    const cx = X(p.values.pipeline), cy = Y(p.values.completion_rate);
    const r = 5 + ((p.values.work_orders || 0) / sMax) * 13;
    const bad = p.display.quadrant === "Fix delivery";
    const dot = mk("circle", { cx, cy, r, class: bad ? "dot dot-bad" : "dot" });
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent =
      `${p.label}: ${p.display.pipeline} pipeline, ` +
      `${p.display.completion_rate} completion, ` +
      `${p.display.work_orders} work orders (${p.display.delayed} delayed)`;
    dot.appendChild(title);
    mk("text", { x: cx, y: cy - r - 6, class: "dot-label", "text-anchor": "middle" }, p.label);
  });

  const wrap = el("div", "chart-wrap");
  wrap.appendChild(svg);
  if (unplotted.length) {
    const note = el(
      "p", "table-note",
      `Not plotted (no delivery history): ${unplotted.map((u) => u.label).join(", ")}.`
    );
    wrap.appendChild(note);
  }
  return wrap;
}

/* Talking points are the deliverable of a leadership briefing, so they get a
 * copy button rather than a table row. */
function renderTalkingPoints(bd) {
  const section = el("div", "section");
  const head = el("div", "tp-head");
  head.appendChild(el("h3", "section-title", bd.title));
  const btn = el("button", "copy-btn", "Copy");
  btn.addEventListener("click", async () => {
    const text = bd.rows.map((r) => "• " + r.label).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Press Ctrl+C";
    }
    setTimeout(() => (btn.textContent = "Copy"), 1800);
  });
  head.appendChild(btn);
  section.appendChild(head);

  const list = el("ul", "talking-points");
  bd.rows.forEach((r) => {
    const li = el("li");
    textInto(li, r.label);
    list.appendChild(li);
  });
  section.appendChild(list);
  if (bd.note) section.appendChild(el("p", "table-note", bd.note));
  return section;
}

function renderBreakdown(bd) {
  if (!bd.rows || !bd.rows.length) return null;
  if (bd.key === "talking_points") return renderTalkingPoints(bd);

  if (bd.chart === "scatter") {
    const chart = renderScatter(bd);
    if (chart) {
      const section = el("div", "section");
      section.appendChild(el("h3", "section-title", bd.title));
      section.appendChild(chart);
      if (bd.note) section.appendChild(el("p", "table-note", bd.note));
      return section;
    }
  }

  const section = el("div", "section");
  section.appendChild(el("h3", "section-title", bd.title));

  const numericCols = bd.columns.filter((c) =>
    bd.rows.some((r) => r.display[c] !== undefined)
  );

  // A horizontal bar reads faster than a table for a single ranked measure.
  const isSimpleBar =
    bd.chart === "bar" &&
    numericCols.includes("value") &&
    bd.rows.every((r) => r.values.value !== undefined);

  if (isSimpleBar) {
    const values = bd.rows.map((r) => Number(r.values.value) || 0);
    const max = Math.max(...values, 1);
    const bars = el("div", "bars");
    bd.rows.slice(0, 9).forEach((r) => {
      const row = el("div", "bar-row");
      const name = el("div", "bar-name");
      textInto(name, r.label);
      name.title = r.label;
      row.appendChild(name);

      const track = el("div", "bar-track");
      const fill = el("div", "bar-fill");
      fill.style.width = `${Math.max((Number(r.values.value) || 0) / max * 100, 1.5)}%`;
      track.appendChild(fill);
      row.appendChild(track);

      const val = el("div", "bar-value");
      textInto(val, r.display.value);
      row.appendChild(val);
      bars.appendChild(row);
    });
    section.appendChild(bars);
  } else {
    const wrap = el("div", "table-wrap");
    const table = el("table");

    const thead = el("thead");
    const headRow = el("tr");
    headRow.appendChild(el("th", null, bd.dimension));
    numericCols.forEach((c) =>
      headRow.appendChild(el("th", null, c.replace(/_/g, " ")))
    );
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = el("tbody");
    bd.rows.slice(0, 10).forEach((r) => {
      const tr = el("tr");
      const nameCell = el("td", "name");
      textInto(nameCell, r.label);
      tr.appendChild(nameCell);

      numericCols.forEach((c) => {
        const td = el("td");
        const raw = r.display[c];
        if (c === "quadrant" && raw) {
          const badge = el("span", `quad ${QUADRANT_CLASS[raw] || "quad-none"}`);
          textInto(badge, raw);
          td.appendChild(badge);
        } else {
          textInto(td, raw !== undefined ? raw : "-");
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    section.appendChild(wrap);
  }

  if (bd.note) section.appendChild(el("p", "table-note", bd.note));
  return section;
}

function renderLedger(ledger) {
  if (!ledger) return null;
  const details = document.createElement("details");
  details.className = "ledger";

  const summary = document.createElement("summary");
  summary.className = "ledger-summary";
  const conf = el("span", `conf conf-${ledger.confidence}`);
  textInto(conf, `${ledger.confidence} confidence`);
  summary.appendChild(conf);
  textInto(
    summary,
    ` ${ledger.rows_included} of ${ledger.rows_considered} records used`
  );
  details.appendChild(summary);

  const body = el("div", "ledger-body");

  if (ledger.notes && ledger.notes.length) {
    body.appendChild(el("h4", null, "Summary"));
    const ul = el("ul", "ledger-list");
    ledger.notes.forEach((n) => {
      const li = el("li");
      textInto(li, n);
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  const exclusions = Object.entries(ledger.exclusions || {});
  if (exclusions.length) {
    body.appendChild(el("h4", null, "Records excluded"));
    const ul = el("ul", "ledger-list");
    exclusions.forEach(([reason, count]) => {
      const li = el("li");
      const c = el("span", "count", String(count));
      li.appendChild(c);
      textInto(li, ` — ${reason}`);
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  const norms = Object.entries(ledger.normalizations || {});
  if (norms.length) {
    body.appendChild(el("h4", null, "Cleaning applied"));
    const ul = el("ul", "ledger-list");
    norms.slice(0, 10).forEach(([what, count]) => {
      const li = el("li");
      const c = el("span", "count", String(count));
      li.appendChild(c);
      textInto(li, ` — ${what}`);
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  if (ledger.warnings && ledger.warnings.length) {
    body.appendChild(el("h4", null, "Warnings"));
    const ul = el("ul", "ledger-list");
    ledger.warnings.forEach((w) => {
      const li = el("li");
      textInto(li, w);
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  details.appendChild(body);
  return details;
}

function renderResponse(data) {
  const card = el("div", "agent-msg");

  const strip = renderPlanStrip(data.plan);
  if (strip) card.appendChild(strip);

  const body = el("div", "msg-body");

  const answer = el("p", "answer");
  textInto(answer, data.answer);
  body.appendChild(answer);

  if (data.assumptions && data.assumptions.length) {
    const note = el("div", "assumption-note");
    const b = el("b", null, "Assumed: ");
    note.appendChild(b);
    textInto(note, data.assumptions.join(" "));
    body.appendChild(note);
  }

  const metrics = renderMetrics(data.metrics);
  if (metrics) body.appendChild(metrics);

  if (data.insight) {
    const section = el("div", "section");
    section.appendChild(el("h3", "section-title", "Insight"));
    const insight = el("div", "insight");
    textInto(insight, data.insight);
    section.appendChild(insight);
    body.appendChild(section);
  }

  (data.breakdowns || []).forEach((bd) => {
    const node = renderBreakdown(bd);
    if (node) body.appendChild(node);
  });

  if (data.risks && data.risks.length) {
    const section = el("div", "section");
    section.appendChild(el("h3", "section-title", "Risks & caveats"));
    const ul = el("ul", "risks");
    data.risks.slice(0, 7).forEach((r) => {
      const li = el("li");
      textInto(li, r);
      ul.appendChild(li);
    });
    section.appendChild(ul);
    body.appendChild(section);
  }

  const ledger = renderLedger(data.ledger);
  if (ledger) body.appendChild(ledger);

  if (data.degraded && data.degraded_reason) {
    const note = el("div", "degraded");
    textInto(note, data.degraded_reason);
    body.appendChild(note);
  }

  if (data.follow_ups && data.follow_ups.length) {
    const wrap = el("div", "followups");
    data.follow_ups.forEach((q) => {
      const btn = el("button", "followup");
      textInto(btn, q);
      btn.addEventListener("click", () => ask(q));
      wrap.appendChild(btn);
    });
    body.appendChild(wrap);
  }

  card.appendChild(body);
  return card;
}

/* ----------------------------------------------------------------- flow */

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true;
  sendButton.disabled = true;
  input.value = "";
  if (welcome) welcome.remove();

  const turn = el("div", "turn");
  const userMsg = el("div", "user-msg");
  const bubble = el("span");
  textInto(bubble, question);
  userMsg.appendChild(bubble);
  turn.appendChild(userMsg);

  const pending = el("div", "agent-msg");
  const thinking = el("div", "thinking");
  thinking.appendChild(el("div", "spinner"));
  textInto(thinking, "Querying Monday.com and computing metrics…");
  pending.appendChild(thinking);
  turn.appendChild(pending);

  conversation.appendChild(turn);
  scrollToEnd();

  try {
    const res = await fetch(`${API}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history: history.slice(-4) }),
    });

    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `Request failed (${res.status})`);
    }

    const data = await res.json();
    pending.replaceWith(renderResponse(data));

    history.push({ role: "user", content: question });
    history.push({ role: "assistant", content: data.answer });
    history = history.slice(-6);
  } catch (err) {
    const error = el("div", "error-msg");
    textInto(error, err.message || "Something went wrong. Please try again.");
    pending.replaceWith(error);
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
    scrollToEnd();
    loadBoardStatus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  ask(input.value);
});

document.querySelectorAll(".suggestion").forEach((btn) => {
  btn.addEventListener("click", () => ask(btn.dataset.q));
});

loadBoardStatus();
input.focus();
