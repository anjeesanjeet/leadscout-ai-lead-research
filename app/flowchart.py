"""Automated flowcharts (Mermaid), generated from the code, the n8n workflow file and the run logs:

  * pipeline - built from the pipeline's STEPS list
  * n8n      - parsed from n8n/leadscout_workflow.json (nodes + connections)
  * trace    - the recorded steps of one real lead, read from the database

Usage:  python -m app.flowchart          (writes docs/architecture.md)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import ROOT_DIR, Settings, get_settings
from app.db import connect, events_for, get_lead
from app.pipeline import STEPS

N8N_FILE = ROOT_DIR / "n8n" / "leadscout_workflow.json"

CLASSDEFS = """
    classDef io fill:#E6EEF4,stroke:#1D3D5C,color:#1D3D5C
    classDef ai fill:#1D3D5C,stroke:#1D3D5C,color:#FFFFFF
    classDef code fill:#FFFFFF,stroke:#1D3D5C,color:#1D3D5C
    classDef store fill:#FDF1DC,stroke:#C98A12,color:#5A3E08
    classDef human fill:#FBE3DD,stroke:#B5452F,color:#6E2213
    classDef ok fill:#E3F1EA,stroke:#2E7D5B,color:#174A33
    classDef warn fill:#FDF1DC,stroke:#C98A12,color:#5A3E08
    classDef bad fill:#FBE3DD,stroke:#B5452F,color:#6E2213
    classDef skip fill:#F4F6F8,stroke:#D5DEE6,color:#5B6B7B"""

AI_STEPS = {"extract_profile", "score_fit", "draft_email"}


def _safe(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace('"', "'").replace("<", "(").replace(">", ")").replace("#", "no. ").replace("`", "'")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def pipeline_mermaid(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    lines = ["flowchart TD",
             '    IN(["New lead: Google Sheets via n8n, review page or CLI"])']
    prev = "IN"
    for sid, label, guard in STEPS:
        if sid == "sync":
            continue
        lines.append(f'    {sid}["{_safe(label)}<br/><small>{_safe(guard, 80)}</small>"]')
        if sid == "draft_email":
            lines.append(f'    FIT{{"Fit score ≥ {settings.fit_threshold:g}?"}}')
            lines.append(f"    {prev} --> FIT")
            lines.append("    FIT -- yes --> draft_email")
            lines.append('    FIT -- no --> NF["Not a fit: no draft, no extra cost"]')
            lines.append("    NF --> sync")
        else:
            lines.append(f"    {prev} --> {sid}")
        prev = sid
    sync = next(s for s in STEPS if s[0] == "sync")
    lines += [
        f'    sync["{_safe(sync[1])}<br/><small>{_safe(sync[2], 80)}</small>"]',
        "    draft_email --> sync",
        '    CSV[("leads.csv")]', '    GS[("Google Sheets: Leads tab")]', '    HS[("HubSpot: company + note")]',
        '    REV["Human review: approve, edit or reject"]',
        "    sync --> CSV", "    sync --> GS", "    sync --> HS", "    sync --> REV",
        CLASSDEFS,
        "    class IN,NF io",
        "    class " + ",".join(s for s in AI_STEPS) + " ai",
        "    class " + ",".join(s[0] for s in STEPS if s[0] not in AI_STEPS) + ",FIT code",
        "    class CSV,GS,HS store",
        "    class REV human",
    ]
    return "\n".join(lines)


def n8n_mermaid(path: Path = N8N_FILE) -> str | None:
    if not path.exists():
        return None
    wf = json.loads(path.read_text(encoding="utf-8"))
    ids = {n["name"]: f"N{i}" for i, n in enumerate(wf.get("nodes", []))}
    lines = ["flowchart LR"]
    classes: dict[str, list[str]] = {"io": [], "code": [], "human": [], "skip": []}
    for n in wf.get("nodes", []):
        kind = n["type"].split(".")[-1]
        nid = ids[n["name"]]
        lines.append(f'    {nid}["{_safe(n["name"])}<br/><small>n8n: {_safe(kind, 40)}</small>"]')
        cls = ("io" if "Trigger" in kind or kind == "webhook" else "human" if kind in ("gmail", "slack")
               else "skip" if kind == "noOp" else "code")
        classes[cls].append(nid)
    for src, conn in wf.get("connections", {}).items():
        outputs = conn.get("main", [])
        is_if = next((n for n in wf["nodes"] if n["name"] == src), {}).get("type", "").endswith(".if")
        for out_idx, targets in enumerate(outputs):
            for t in targets or []:
                label = (" -- true --> " if out_idx == 0 else " -- false --> ") if is_if else " --> "
                lines.append(f"    {ids[src]}{label}{ids[t['node']]}")
    lines.append(CLASSDEFS)
    lines += [f"    class {','.join(v)} {k}" for k, v in classes.items() if v]
    return "\n".join(lines)


def trace_mermaid(settings: Settings, lead_id: int) -> str | None:
    conn = connect(settings.db_path)
    try:
        lead = get_lead(conn, lead_id)
        events = events_for(conn, lead_id)
    finally:
        conn.close()
    if not lead or not events:
        return None
    lines = ["flowchart TD", f'    L(["{_safe(lead["company"])}<br/><small>{_safe(lead["website"], 50)}</small>"])']
    prev, classes = "L", {"ok": [], "warn": [], "bad": [], "skip": []}
    for i, e in enumerate(events, 1):
        nid = f"E{i}"
        secs = f"{e['duration_ms'] / 1000:.1f}s"
        lines.append(f'    {nid}["{e["step"]}<br/><small>{_safe(e["detail"], 60)}, {secs}</small>"]')
        lines.append(f"    {prev} --> {nid}")
        classes[{"ok": "ok", "warning": "warn", "failed": "bad", "skipped": "skip"}.get(e["status"], "skip")].append(nid)
        prev = nid
    score = f"{lead['score']}/10" if lead["score"] is not None else "no score"
    lines += [f'    R(["Result: {_safe(lead["status"])} ({score})"])', f"    {prev} --> R", CLASSDEFS, "    class L,R io"]
    lines += [f"    class {','.join(v)} {k}" for k, v in classes.items() if v]
    return "\n".join(lines)


def latest_lead_id(settings: Settings) -> int | None:
    conn = connect(settings.db_path)
    try:
        row = conn.execute("SELECT id FROM leads WHERE status NOT IN ('new','researching') "
                           "ORDER BY (draft_body IS NOT NULL) DESC, updated_at DESC LIMIT 1").fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def write_docs(settings: Settings | None = None, path: Path | None = None) -> Path:
    settings = settings or get_settings()
    path = path or ROOT_DIR / "docs" / "architecture.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["# LeadScout architecture", "",
            "Generated by `python -m app.flowchart` from the pipeline code and the n8n workflow file.", "",
            "## Research pipeline", "", "```mermaid", pipeline_mermaid(settings), "```", "",
            "## n8n workflow", "", "```mermaid", n8n_mermaid() or "flowchart LR\n    A[No workflow file]", "```", ""]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(f"Wrote {write_docs()}")
