const params = new URLSearchParams(location.search);
const THUMB = params.get("mode") === "thumbnail";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v) => (v === null || v === undefined ? "–" : Math.round(v * 100) + "%");
const secs = (ms) => (ms === null || ms === undefined ? "–" : (ms / 1000).toFixed(1) + " s");
const money = (v, d = 4) => (v === null || v === undefined ? "–" : "$" + Number(v).toFixed(d));
const SEG = { d2c_ecommerce: "D2C / e-commerce", b2b_saas: "B2B SaaS", agency: "Agencies" };
const GUARDS = ["Quotes verified in source", "Score computed in code", "Evidence required", "Draft checks + retry", "robots.txt respected", "Never sends email"];

if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: "base", securityLevel: "loose",
  themeVariables: { fontFamily: "Manrope, Segoe UI, sans-serif", fontSize: "14px", lineColor: "#5B6B7B", primaryColor: "#E6EEF4", primaryTextColor: "#13263A", primaryBorderColor: "#1D3D5C" },
  flowchart: { curve: "basis", htmlLabels: true } });

const cellClass = (r) => r.status === "failed" ? "fail" : r.status === "needs_review" ? "warnc" : r.drafted ? "pass" : "neutral";

function bars(el, rows, opts = {}) {
  const max = opts.max ?? Math.max(1, ...rows.map((r) => r.value));
  el.innerHTML = rows.length ? rows.map((r) => {
    const w = Math.max(2, (r.value / max) * 100);
    return `<div class="bar"><span>${esc(r.label)}</span><div class="track"><div class="fill ${r.cls || ""}" style="width:${w}%"></div></div><span class="val num">${esc(r.display)}</span></div>`;
  }).join("") : `<p class="muted small">No data yet.</p>`;
}

function strip(el, leads, grouped) {
  if (!leads || !leads.length) { el.innerHTML = grouped ? `<p class="muted small">Companies appear here after the evaluation runs.</p>` : Array.from({ length: 24 }, () => `<span class="cell"></span>`).join(""); return; }
  const cell = (r) => `<span class="cell ${cellClass(r)}" title="${esc(r.company)}: ${esc(r.status)}${r.score != null ? ", " + r.score + "/10" : ""}"></span>`;
  if (!grouped) { el.innerHTML = leads.map(cell).join(""); return; }
  const g = {};
  leads.forEach((r) => (g[r.expected_segment] ||= []).push(r));
  el.innerHTML = Object.entries(g).map(([k, list]) => `<div class="strip-row"><span>${esc(SEG[k] || k)}</span><div class="cells">${list.map(cell).join("")}</div></div>`).join("");
}

function ledger(el, items) {
  el.innerHTML = items.map((m) => `<div class="m"><div class="v ${m.cls || ""}">${m.v}</div><div class="l">${esc(m.l)}</div></div>`).join("");
}

function latencyChart(el, values) {
  if (!values.length) { el.innerHTML = `<p class="muted small" style="margin-top:14px">No data yet.</p>`; return; }
  const maxS = Math.max(...values) / 1000, binW = maxS <= 20 ? 5 : 10, nBins = Math.max(4, Math.ceil(maxS / binW));
  const counts = Array(nBins).fill(0);
  values.forEach((ms) => counts[Math.min(nBins - 1, Math.floor(ms / 1000 / binW))]++);
  const W = 560, H = 210, pad = 30, bw = (W - pad * 2) / nBins, top = Math.max(...counts);
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Histogram of time per lead" style="width:100%;margin-top:12px">${counts.map((c, i) => {
    const h = (c / top) * (H - 60);
    return `<rect x="${pad + i * bw + 3}" y="${H - 30 - h}" width="${bw - 6}" height="${h}" rx="4" fill="#1D3D5C"></rect>
      ${c ? `<text x="${pad + i * bw + bw / 2}" y="${H - 36 - h}" text-anchor="middle" font-size="12" fill="#5B6B7B">${c}</text>` : ""}
      <text x="${pad + i * bw + bw / 2}" y="${H - 12}" text-anchor="middle" font-size="12" fill="#5B6B7B">${i * binW}s</text>`;
  }).join("")}<line x1="${pad}" x2="${W - pad}" y1="${H - 30}" y2="${H - 30}" stroke="#D5DEE6"></line></svg>`;
}

async function renderFlow(view) {
  const box = $("flow");
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === view)));
  box.innerHTML = `<p class="muted small">Drawing…</p>`;
  try {
    const data = await (await fetch(`/api/flowchart?view=${view}`)).json();
    if (!data.mermaid) { box.innerHTML = `<p class="muted small">No leads processed yet.</p>`; return; }
    box.innerHTML = (await mermaid.render("m" + Date.now(), data.mermaid)).svg;
  } catch (e) { box.innerHTML = `<p class="chip bad">Could not draw the flowchart (${esc(e.message || e)}).</p>`; }
}

function segRows(ev, big) {
  return (ev?.by_segment || []).map((g) => ({ label: SEG[g.segment] || g.segment, value: g.avg_score || 0,
    display: g.avg_score != null ? (big ? g.avg_score.toFixed(1) : g.avg_score + "/10") : "–", cls: (g.avg_score || 0) >= 6 ? "full" : "" }));
}

function renderDashboard(d) {
  const ev = d.eval, s = ev?.summary, live = d.live;
  $("app").hidden = false;
  $("banner").hidden = !!ev;
  $("subtitle").textContent = `Results: ${ev ? ev.meta.provider + " / " + ev.meta.model : d.provider + " / " + d.model}`;
  $("heroRate").textContent = s ? pct(s.grounding_rate) : "–";
  $("heroSub").textContent = s ? `${s.facts_verified} of ${s.facts_total} facts confirmed; ${s.unverified_facts_blocked} unverified facts blocked` : "Run the evaluation to measure";
  strip($("strip"), ev?.leads, true);
  ledger($("ledger"), [
    { v: s ? `${s.researched}/${s.companies}` : "–", l: "Companies researched" },
    { v: s ? pct(s.segment_accuracy) : "–", l: "Segment classified correctly" },
    ...(s && s.target_draft_rate != null ? [{ v: pct(s.target_draft_rate), l: `Realistic targets drafted (${s.targets})` },
      { v: pct(s.large_filtered_rate), l: `Large companies filtered (${s.large_controls})` }] : []),
    { v: s ? pct(s.draft_first_pass_rate) : "–", l: "Drafts passing checks first time" },
    { v: s ? pct(s.draft_final_pass_rate) : "–", l: "Drafts passing after one retry", cls: s && s.draft_final_pass_rate === 1 ? "good" : "" },
    { v: s ? money(s.cost_per_lead_usd, 3) : "–", l: "Cost per lead" },
    { v: s ? secs(s.duration_p95_ms) : "–", l: "p95 time per lead" },
    ...(s && s.judge_avg ? [{ v: s.judge_avg + " / 5", l: "Draft quality (LLM judge)" }] : []),
  ]);
  bars($("segBars"), segRows(ev), { max: 10 });
  latencyChart($("latency"), (ev?.leads || []).map((r) => r.duration_ms));
  $("runMeta").textContent = ev ? `${ev.meta.companies} companies, run ${ev.meta.run_at.replace("T", " ").slice(0, 16)} UTC, news search ${ev.meta.tavily ? "on" : "off"}` : "";
  $("table").innerHTML = ev ? `<thead><tr><th>Company</th><th>Segment</th><th>Fit</th><th>Outcome</th><th>Facts verified</th><th>Judge</th><th>Time</th><th>Cost</th></tr></thead>
    <tbody>${ev.leads.map((r) => `<tr><td>${esc(r.company)}</td>
      <td>${esc(SEG[r.segment] || r.segment || "–")}${r.segment_correct ? "" : ` <span class="chip bad">expected ${esc(SEG[r.expected_segment] || r.expected_segment)}</span>`}</td>
      <td class="num">${r.score ?? "–"}</td><td><span class="chip ${r.status === "failed" ? "bad" : r.drafted ? "ok" : ""}">${esc(r.status.replace(/_/g, " "))}</span></td>
      <td class="num">${r.verified}/${r.facts}</td><td class="num">${r.judge?.score ?? "–"}</td>
      <td class="num">${secs(r.duration_ms)}</td><td class="num">${money(r.cost_usd)}</td></tr>`).join("")}</tbody>`
    : `<tbody><tr><td class="muted">No evaluation results yet.</td></tr></tbody>`;
  ledger($("liveLedger"), [
    { v: live.processed, l: "Leads processed" },
    { v: pct(live.fit_rate), l: "Fit for outreach" },
    { v: pct(live.grounding_rate), l: "Facts verified" },
    { v: pct(live.draft_first_pass_rate), l: "Drafts passing first time" },
    { v: money(live.cost_per_lead_usd, 3), l: "Cost per lead" },
    { v: secs(live.duration_avg_ms), l: "Average time per lead" },
  ]);
  bars($("statusBars"), Object.entries(live.status_counts).map(([k, v]) => ({ label: k.replace(/_/g, " "), value: v, display: v })));
  $("integrations").innerHTML = Object.entries(d.integrations).map(([k, on]) =>
    `<div class="bar"><span>${esc(k.replace("_", " "))}</span><span class="chip ${on ? "ok" : ""}" style="justify-self:start">${on ? "connected" : "not configured"}</span><span></span></div>`).join("");
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => renderFlow(t.dataset.view)));
  return renderFlow("pipeline");
}

function renderThumbnail(d) {
  document.body.classList.add("thumb-mode");
  $("thumb").hidden = false;
  const ev = d.eval, s = ev?.summary;
  $("tModel").innerHTML = ev ? `Evaluated on ${ev.meta.companies} real companies<br>${esc(ev.meta.model)}` : esc(d.model);
  $("tRate").textContent = s ? pct(s.grounding_rate) : "–";
  if (s) $("tCaption").textContent = `of extracted facts verified against their source (${s.facts_verified}/${s.facts_total})`;
  $("tKpis").innerHTML = [
    { v: s ? `${s.researched}/${s.companies}` : "–", l: "companies researched" },
    { v: s ? pct(s.segment_accuracy) : "–", l: "segments classified correctly" },
    { v: s ? money(s.cost_per_lead_usd, 3) : "–", l: "cost per lead" },
    { v: s ? secs(s.duration_avg_ms) : "–", l: "average time per lead" },
  ].map((m) => `<div><div class="v">${m.v}</div><div class="l">${m.l}</div></div>`).join("");
  const rows = segRows(ev, true);
  if (rows.length) bars($("tBars"), rows, { max: 10 });
  else $("tBars").innerHTML = Object.values(SEG).map((c) => `<div class="bar"><span>${c}</span><div class="track"></div><span class="val">–</span></div>`).join("");
  strip($("tStrip"), ev?.leads, false);
  const L = ev?.leads || [];
  const outcome = [["Draft ready", L.filter((r) => cellClass(r) === "pass").length, "full"],
    ["Needs a look", L.filter((r) => cellClass(r) === "warnc").length, "low"],
    ["Not a fit", L.filter((r) => cellClass(r) === "neutral").length, "neutral"],
    ["Failed", L.filter((r) => cellClass(r) === "fail").length, "bad"]];
  bars($("tOutcome"), outcome.map(([label, n, cls]) => ({ label, value: n, display: ev ? n : "–", cls })), { max: Math.max(1, L.length) });
  $("tGuards").innerHTML = GUARDS.map((g) => `<li>${esc(g)}</li>`).join("");
  $("tFlow").innerHTML = [["Google Sheets + n8n", "New lead trigger", ""], ["Website + news", "Public sources only", ""],
    ["AI research", esc(ev ? ev.meta.model : d.model), "core"], ["Verify + score", "Facts checked in code", ""], ["HubSpot + Sheets", "Human approves", ""]]
    .map(([k, sub, cls]) => `<div class="t-step ${cls}"><div class="t-k">${k}</div><div class="t-d">${sub}</div></div>`).join("");
  $("tWatermark").hidden = !!ev;
}

(async () => {
  try {
    const d = await (await fetch("/api/dashboard")).json();
    if (THUMB) renderThumbnail(d); else await renderDashboard(d);
  } catch (e) {
    document.body.innerHTML = `<p style="padding:40px">Could not load dashboard data: ${esc(e.message)}. Is the server running?</p>`;
  } finally { await document.fonts?.ready; window.__ready = true; }
})();