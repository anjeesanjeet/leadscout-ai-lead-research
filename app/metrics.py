"""Dashboard data: evaluation results plus live pipeline metrics from the database."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.config import Settings
from app.db import connect, lead_to_dict
from app.pipeline import STEPS


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    k = (len(vals) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def live_metrics(settings: Settings, db_path: Path | None = None) -> dict:
    conn = connect(db_path or settings.db_path)
    try:
        leads = [lead_to_dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY updated_at DESC")]
        facts = conn.execute("SELECT lead_id, verified FROM facts").fetchall()
        drafts = conn.execute("SELECT lead_id, status FROM events WHERE step = 'draft_email' ORDER BY id").fetchall()
    finally:
        conn.close()
    done = [l for l in leads if l["status"] not in ("new", "researching")]
    processed = [l for l in done if l["status"] != "failed"]
    fit = [l for l in processed if l["status"] in ("ready_for_review", "needs_review", "approved", "rejected")]
    first_draft: dict[int, str] = {}
    for d in drafts:
        first_draft.setdefault(d["lead_id"], d["status"])
    durations = [l["duration_ms"] for l in done if l["duration_ms"]]
    costs = [l["cost_usd"] for l in done]
    bins = Counter()
    for l in processed:
        if l["score"] is not None:
            bins[min(4, int(l["score"] // 2))] += 1
    return {
        "leads": len(leads),
        "processed": len(done),
        "status_counts": dict(Counter(l["status"] for l in leads)),
        "segment_counts": dict(Counter(l["segment"] or "unknown" for l in processed)),
        "fit_rate": round(len(fit) / len(processed), 3) if processed else None,
        "grounding_rate": round(sum(f["verified"] for f in facts) / len(facts), 3) if facts else None,
        "facts_total": len(facts),
        "draft_first_pass_rate": round(sum(1 for s in first_draft.values() if s == "ok") / len(first_draft), 3) if first_draft else None,
        "cost_per_lead_usd": round(sum(costs) / len(costs), 5) if costs else None,
        "total_cost_usd": round(sum(costs), 4),
        "duration_avg_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "duration_p95_ms": percentile(durations, 95),
        "score_bins": [bins.get(i, 0) for i in range(5)],
        "recent": [{"id": l["id"], "company": l["company"], "segment": l["segment"], "score": l["score"],
                    "status": l["status"], "cost_usd": l["cost_usd"], "duration_ms": l["duration_ms"]} for l in leads[:12]],
    }


def dashboard_payload(settings: Settings) -> dict:
    return {
        "provider": settings.llm_provider, "model": settings.model_name,
        "fit_threshold": settings.fit_threshold,
        "steps": [{"id": s[0], "label": s[1], "guard": s[2]} for s in STEPS],
        "integrations": {
            "tavily": bool(settings.tavily_api_key),
            "google_sheets": bool(settings.google_service_account_file and settings.google_sheet_id),
            "hubspot": bool(settings.hubspot_token),
        },
        "eval": load_json(settings.eval_results_path),
        "live": live_metrics(settings),
    }
