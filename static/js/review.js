const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const STATUS = {
  ready_for_review: ["Ready for review", "ok"], needs_review: ["Needs a look", "warn"], approved: ["Approved", "ok"],
  rejected: ["Rejected", "bad"], not_a_fit: ["Not a fit", ""], failed: ["Failed", "bad"], researching: ["Researching", "warn"], new: ["New", ""],
};
const FILTERS = [["all", "All"], ["ready_for_review", "Ready"], ["needs_review", "Needs a look"], ["approved", "Approved"], ["not_a_fit", "Not a fit"]];
let leads = [], filter = "all", current = new URLSearchParams(location.search).get("lead");

const chip = (status) => { const [t, c] = STATUS[status] || [status, ""]; return `<span class="chip ${c}">${esc(t)}</span>`; };

async function loadList() {
  leads = await (await fetch("/api/leads")).json();
  renderFilters();
  renderList();
}

function renderFilters() {
  $("filters").innerHTML = FILTERS.map(([k, label]) => {
    const n = k === "all" ? leads.length : leads.filter((l) => l.status === k).length;
    return `<button type="button" data-f="${k}" aria-pressed="${filter === k}">${label} ${n}</button>`;
  }).join("");
  $("filters").querySelectorAll("button").forEach((b) => b.onclick = () => { filter = b.dataset.f; renderFilters(); renderList(); });
}

function renderList() {
  const items = leads.filter((l) => filter === "all" || l.status === filter);
  $("list").innerHTML = items.length ? items.map((l) => `
    <div class="item" data-id="${l.id}" aria-current="${String(l.id) === String(current)}" tabindex="0">
      <div><div class="co">${esc(l.company)}</div><div class="muted" style="font-size:13px">${esc(l.segment || l.website)}</div><div style="margin-top:4px">${chip(l.status)}</div></div>
      <div class="score num">${l.score ?? "–"}</div>
    </div>`).join("") : `<p class="muted" style="padding:20px">No leads here yet.</p>`;
  $("list").querySelectorAll(".item").forEach((el) => {
    el.onclick = () => open(el.dataset.id);
    el.onkeydown = (e) => { if (e.key === "Enter") open(el.dataset.id); };
  });
}

async function open(id) {
  current = id;
  history.replaceState(null, "", `/review?lead=${id}`);
  renderList();
  const r = await fetch(`/api/leads/${id}`);
  if (!r.ok) { $("detail").innerHTML = `<div class="empty">Lead not found.</div>`; return; }
  renderDetail(await r.json());
}

function renderDetail(l) {
  const p = l.profile || {}, sb = l.score_breakdown || {}, checks = (l.draft_checks || {}).checks || [];
  const factById = Object.fromEntries((l.facts || []).map((f) => [f.fact_id, f]));
  const crit = (sb.criteria || []).map((c) => `
    <div class="crit"><span class="chip ${c.answer === "yes" ? "ok" : c.answer === "partial" ? "warn" : ""}">${esc(c.answer)}</span>
      <div><div>${esc(c.question)}</div><div class="muted" style="font-size:13.5px">${esc(c.reason)}${c.downgraded ? " (downgraded: no verified evidence)" : ""}</div>
      ${c.fact_ids.length ? `<div class="muted" style="font-size:12.5px">Evidence: ${c.fact_ids.map((x) => esc(factById[x]?.claim || x)).join("; ")}</div>` : ""}</div>
      <span class="num muted">${c.points}/${c.weight}</span></div>`).join("") || `<p class="muted">${esc(sb.note || "Not scored.")}</p>`;
  const facts = (l.facts || []).map((f) => `
    <div class="fact ${f.verified ? "" : "blocked"}"><span class="chip ${f.verified ? "ok" : "bad"}">${f.verified ? "verified" : "blocked"}</span>
      <div><div class="claim">${esc(f.claim)}</div><q>${esc(f.quote)}</q>
      <div style="font-size:12.5px">${f.source_url ? `<a href="${esc(f.source_url)}" target="_blank" rel="noopener">source</a>` : ""} <span class="muted">match ${f.match_score}%</span></div></div></div>`).join("");
  const draft = l.draft_body != null ? `
    <div class="section"><h2>Outreach draft</h2>
      <div class="checks">${checks.map((c) => `<span class="chip ${c.passed ? "ok" : "bad"}" title="${esc(c.detail)}">${esc(c.name)}</span>`).join("")}</div>
      <label class="f" for="subj">Subject</label><input class="subject" id="subj" value="${esc(l.draft_subject)}">
      <label class="f" for="body">Body</label><textarea id="body">${esc(l.draft_body)}</textarea>
      <div class="actions">
        <button type="button" id="approve">Approve</button>
        <button type="button" class="reject" id="reject">Reject</button>
        <button type="button" class="ghost" id="copy">Copy email</button>
      </div>
      <p class="muted" style="font-size:13px;margin-top:8px">LeadScout never sends email. Approving marks the lead and syncs it; you send it yourself.</p>
    </div>` : "";
  const trace = (l.events || []).map((e) => `
    <span class="chip ${e.status === "ok" ? "ok" : e.status === "failed" ? "bad" : e.status === "warning" ? "warn" : ""}">${esc(e.status)}</span>
    <span><b>${esc(e.step)}</b> <span class="muted">${esc(e.detail)}</span></span>
    <span class="num muted">${(e.duration_ms / 1000).toFixed(1)}s</span><span class="num muted">$${e.cost_usd.toFixed(4)}</span>`).join("");
  const sync = l.sync_status ? Object.entries(l.sync_status).filter(([k]) => !k.startsWith("hubspot_"))
    .map(([k, v]) => `<span class="chip ${v === "ok" ? "ok" : String(v).startsWith("error") ? "bad" : ""}" title="${esc(v)}">${esc(k.replace("_", " "))}: ${esc(String(v).slice(0, 30))}</span>`).join(" ") : "";

  $("detail").innerHTML = `
    <div class="head">
      <div><h1>${esc(l.company)}</h1>
        <p class="muted"><a href="https://${esc(l.domain)}" target="_blank" rel="noopener">${esc(l.domain)}</a>, ${esc(p.location || "")}</p>
        <p style="margin-top:8px;max-width:640px">${esc(p.one_liner || "")}</p>
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">${chip(l.status)} <span class="chip">${esc(l.segment || "unknown segment")}</span> ${sync}</div>
        ${l.error ? `<p class="chip bad" style="margin-top:8px">${esc(l.error)}</p>` : ""}
      </div>
      <div><div class="bigscore num">${l.score ?? "–"}<span style="font-size:22px;color:var(--slate)">/10</span></div>
        <p class="muted num" style="text-align:right">fit score, ${l.grounding_rate != null ? Math.round(l.grounding_rate * 100) + "% facts verified" : ""}</p>
        <div style="text-align:right;margin-top:8px"><button type="button" class="ghost" id="rerun">Research again</button></div></div>
    </div>
    ${draft}
    <div class="section"><h2>Why this score</h2>${sb.capped ? `<p class="chip warn" style="margin-bottom:10px;white-space:normal">${esc(sb.note)}</p>` : ""}${crit}</div>
    <div class="section"><h2>Facts found</h2><p class="muted" style="font-size:13.5px;margin-bottom:8px">Each quote was checked against its source. Blocked facts are never used in scoring or drafts.</p>${facts || '<p class="muted">No facts.</p>'}</div>
    <div class="section"><h2>Pipeline steps</h2><div class="trace">${trace}</div>
      <p class="muted num" style="margin-top:10px;font-size:13.5px">Total ${(l.duration_ms / 1000).toFixed(1)}s, $${(l.cost_usd || 0).toFixed(4)}. <a href="/flowchart?view=trace&lead=${l.id}">See as flowchart</a></p></div>`;

  const decide = async (decision) => {
    const body = { decision, subject: $("subj").value, body: $("body").value };
    const r = await fetch(`/api/leads/${l.id}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) { await loadList(); renderDetail(await r.json()); } else alert((await r.json()).detail || "Failed");
  };
  if ($("approve")) {
    $("approve").onclick = () => decide("approve");
    $("reject").onclick = () => decide("reject");
    $("copy").onclick = async () => { await navigator.clipboard.writeText(`Subject: ${$("subj").value}\n\n${$("body").value}`); $("copy").textContent = "Copied"; };
  }
  $("rerun").onclick = async () => {
    $("rerun").disabled = true; $("rerun").textContent = "Researching…";
    const r = await fetch(`/api/leads/${l.id}/rerun`, { method: "POST" });
    const data = await r.json();
    if (!r.ok) { alert(data.detail || "Failed"); $("rerun").disabled = false; $("rerun").textContent = "Research again"; return; }
    await loadList(); open(l.id);
  };
}

$("addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("runBtn").disabled = true; $("busy").hidden = false;
  try {
    const r = await fetch("/api/leads", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company: $("company").value, website: $("website").value }) });
    const data = await r.json();
    if (!r.ok) { alert(data.detail || "Request failed"); return; }
    $("company").value = ""; $("website").value = "";
    await loadList(); open(data.id);
  } catch { alert("Can't reach the server. Is `python -m app.main` running?"); }
  finally { $("runBtn").disabled = false; $("busy").hidden = true; }
});

loadList().then(() => { if (current) open(current); });