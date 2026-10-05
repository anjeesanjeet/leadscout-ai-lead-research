"""Evaluation: runs the full pipeline on a labelled list of real companies and measures quality and cost.

Usage:
    python -m eval.run_eval                 # all companies in data/demo_leads.csv
    python -m eval.run_eval --limit 6       # quick check
    python -m eval.run_eval --judge         # add an LLM-judge score for each email draft

Uses its own database (outputs/eval_work) and never writes to Google Sheets or HubSpot.
Writes outputs/eval_results.json (dashboard + thumbnail) and outputs/eval_report.md (case study).
Note: results depend on live websites, which change over time.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone

from app.config import ROOT_DIR, get_settings
from app.llm import BaseProvider, ProviderConfigError, get_provider
from app.metrics import percentile
from app.pipeline import Pipeline

LEADS = ROOT_DIR / "data" / "demo_leads.csv"

JUDGE_SCHEMA = {"type": "object", "properties": {
    "score": {"type": "integer", "minimum": 1, "maximum": 5},
    "reason": {"type": "string"}}, "required": ["score", "reason"]}
JUDGE_SYSTEM = """You review B2B cold emails before they are sent. You get the sender's offer, the verified facts
about the recipient company, and the draft. Score 1-5:
5 = specific to this company, every claim supported by the facts, a clear and relevant link to the offer, concise and respectful;
4 = good with a minor issue; 3 = generic or slightly off; 2 = weak relevance or a doubtful claim; 1 = inaccurate, pushy or spammy."""


def judge(provider: BaseProvider, sender: dict, lead: dict) -> dict:
    facts = "\n".join(f"- {f['claim']}" for f in lead["facts"] if f["verified"])
    user = (f"Sender offer: {sender['offer']}\n\nVerified facts about {lead['company']}:\n{facts}\n\n"
            f"Draft subject: {lead['draft_subject']}\n\n{lead['draft_body']}")
    try:
        res = provider.structured(JUDGE_SYSTEM, user, "submit_review", JUDGE_SCHEMA, max_tokens=300)
        return {"score": int(res.data.get("score", 0)) or None, "reason": str(res.data.get("reason", ""))[:300],
                "cost_usd": res.cost_usd}
    except Exception as exc:
        return {"score": None, "reason": f"judge error: {type(exc).__name__}", "cost_usd": 0.0}


def run(provider_name: str | None, limit: int | None, use_judge: bool) -> dict:
    base = get_settings()
    provider = get_provider(base, provider_name)
    work = base.outputs_dir / "eval_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    s = copy.copy(base)
    s.db_path, s.outputs_dir = work / "eval.db", work          # isolated database and CSV
    s.hubspot_token = s.google_service_account_file = s.google_sheet_id = ""   # never touch real sinks
    pipeline = Pipeline(s, provider)
    rows = list(csv.DictReader(open(LEADS, encoding="utf-8-sig")))[:limit]
    sender = s.sender()

    print(f"\nEvaluating {len(rows)} companies with {provider.name}:{provider.model}\n")
    results = []
    for i, row in enumerate(rows, 1):
        out = pipeline.process(pipeline.add_lead(row["company"], row["website"]))
        drafts = [e for e in out["events"] if e["step"] == "draft_email"]
        checks = (out.get("draft_checks") or {}).get("checks", [])
        verified = sum(f["verified"] for f in out["facts"])
        rec = {
            "company": row["company"], "website": row["website"], "expected_segment": row["segment"],
            "expected_size": row.get("size") or "small_mid", "capped": bool((out.get("score_breakdown") or {}).get("capped")),
            "segment": out.get("segment"), "segment_correct": out.get("segment") == row["segment"],
            "status": out["status"], "score": out.get("score"), "facts": len(out["facts"]), "verified": verified,
            "drafted": bool(drafts), "draft_first_pass": bool(drafts) and drafts[0]["status"] == "ok",
            "draft_final_pass": bool(checks) and all(c["passed"] for c in checks),
            "cost_usd": out["cost_usd"], "duration_ms": out["duration_ms"], "error": out.get("error"),
            "draft_subject": out.get("draft_subject"), "judge": None,
        }
        if use_judge and out.get("draft_body"):
            rec["judge"] = judge(provider, sender, out)
        results.append(rec)
        j = f"  judge {rec['judge']['score']}/5" if rec["judge"] and rec["judge"]["score"] else ""
        print(f"  [{i:>2}/{len(rows)}] {row['company']:<24} {str(rec['segment']):<14} "
              f"{'ok ' if rec['segment_correct'] else 'MISS'} {str(rec['score'] or '-'):>4}/10 "
              f"{rec['status']:<17} facts {verified}/{rec['facts']}  ${rec['cost_usd']:.4f}{j}"
              + (f"  {rec['error']}" if rec["error"] else ""))

    payload = {
        "meta": {"provider": provider.name, "model": provider.model, "companies": len(results), "judge": use_judge,
                 "fit_threshold": s.fit_threshold, "tavily": bool(s.tavily_api_key),
                 "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()},
        "summary": summarize(results),
        "by_segment": by_segment(results),
        "leads": results,
    }
    base.outputs_dir.mkdir(parents=True, exist_ok=True)
    base.eval_results_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (base.outputs_dir / "eval_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def summarize(rs: list[dict]) -> dict:
    ok = [r for r in rs if r["status"] != "failed"]
    drafted = [r for r in ok if r["drafted"]]
    judged = [r["judge"]["score"] for r in rs if r["judge"] and r["judge"].get("score")]
    durations = [r["duration_ms"] for r in rs]
    facts, verified = sum(r["facts"] for r in ok), sum(r["verified"] for r in ok)
    targets = [r for r in ok if r.get("expected_size", "small_mid") != "large"]
    controls = [r for r in ok if r.get("expected_size") == "large"]
    return {
        "companies": len(rs),
        "researched": len(ok),
        "targets": len(targets), "large_controls": len(controls),
        "target_draft_rate": _rate(sum(r["drafted"] for r in targets), len(targets)),
        "large_filtered_rate": _rate(sum(not r["drafted"] for r in controls), len(controls)),
        "targets_wrongly_capped": sum(1 for r in targets if r.get("capped")),
        "research_success_rate": _rate(len(ok), len(rs)),
        "segment_accuracy": _rate(sum(r["segment_correct"] for r in ok), len(ok)),
        "facts_total": facts, "facts_verified": verified,
        "grounding_rate": _rate(verified, facts),
        "unverified_facts_blocked": facts - verified,
        "avg_verified_facts": round(verified / len(ok), 1) if ok else None,
        "fit_rate": _rate(len(drafted), len(ok)),
        "drafts": len(drafted),
        "draft_first_pass_rate": _rate(sum(r["draft_first_pass"] for r in drafted), len(drafted)),
        "draft_final_pass_rate": _rate(sum(r["draft_final_pass"] for r in drafted), len(drafted)),
        "judge_avg": round(sum(judged) / len(judged), 2) if judged else None,
        "cost_per_lead_usd": round(sum(r["cost_usd"] for r in rs) / len(rs), 5) if rs else None,
        "total_cost_usd": round(sum(r["cost_usd"] for r in rs), 4),
        "duration_avg_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "duration_p95_ms": percentile(durations, 95),
    }


def by_segment(rs: list[dict]) -> list[dict]:
    groups: dict[str, list] = defaultdict(list)
    for r in rs:
        groups[r["expected_segment"]].append(r)
    out = []
    for seg, items in groups.items():
        ok = [r for r in items if r["status"] != "failed"]
        scores = [r["score"] for r in ok if r["score"] is not None]
        out.append({"segment": seg, "companies": len(items),
                    "segment_accuracy": _rate(sum(r["segment_correct"] for r in ok), len(ok)),
                    "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
                    "drafted": sum(r["drafted"] for r in ok)})
    return out


def render_report(p: dict) -> str:
    s, m = p["summary"], p["meta"]
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    lines = [
        "# LeadScout evaluation report", "",
        f"Model: `{m['provider']}:{m['model']}`  |  Companies: {m['companies']}  |  News search: "
        f"{'on' if m['tavily'] else 'off'}  |  Run: {m['run_at']}", "",
        "| Metric | Result |", "|---|---|",
        f"| Companies researched | {s['researched']}/{s['companies']} ({pct(s['research_success_rate'])}) |",
        f"| Segment accuracy | {pct(s['segment_accuracy'])} |",
        f"| Facts verified against sources | {s['facts_verified']}/{s['facts_total']} ({pct(s['grounding_rate'])}) |",
        f"| Unverified facts blocked | {s['unverified_facts_blocked']} |",
        f"| Fit for outreach (drafted) | {s['drafts']} ({pct(s['fit_rate'])}) |",
        f"| Realistic targets drafted | {pct(s['target_draft_rate'])} of {s['targets']} |",
        f"| Large controls filtered out | {pct(s['large_filtered_rate'])} of {s['large_controls']} |",
        f"| Targets wrongly capped as large | {s['targets_wrongly_capped']} |",
        f"| Drafts passing checks first time / after retry | {pct(s['draft_first_pass_rate'])} / {pct(s['draft_final_pass_rate'])} |",
        f"| Cost per lead | ${s['cost_per_lead_usd']:.4f} |",
        f"| Time per lead, avg / p95 | {s['duration_avg_ms']/1000:.1f}s / {s['duration_p95_ms']/1000:.1f}s |",
    ]
    if s.get("judge_avg"):
        lines.append(f"| Draft quality (LLM judge, 1-5) | {s['judge_avg']} |")
    lines += ["", "## By segment", "", "| Segment | Companies | Segment accuracy | Avg fit score | Drafted |",
              "|---|---|---|---|---|"]
    lines += [f"| {g['segment']} | {g['companies']} | {pct(g['segment_accuracy'])} | {g['avg_score']} | {g['drafted']} |"
              for g in p["by_segment"]]
    lines += ["", "## Per company", "", "| Company | Segment | Expected size | Score | Status | Facts verified | Judge |",
              "|---|---|---|---|---|---|---|"]
    for r in p["leads"]:
        seg = r["segment"] if r["segment_correct"] else f"{r['segment']} (expected {r['expected_segment']})"
        jd = r["judge"]["score"] if r["judge"] and r["judge"].get("score") else ""
        cap = " (capped)" if r.get("capped") else ""
        lines.append(f"| {r['company']} | {seg} | {r.get('expected_size', '')} | "
                     f"{r['score'] if r['score'] is not None else ''}{cap} | {r['status']} | "
                     f"{r['verified']}/{r['facts']} | {jd} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate LeadScout on real companies.")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    try:
        p = run(args.provider, args.limit, args.judge)
    except ProviderConfigError as exc:
        sys.exit(f"Configuration error: {exc}")
    s = p["summary"]
    print(f"\nResearched {s['researched']}/{s['companies']} | segment accuracy {s['segment_accuracy']} | "
          f"facts verified {s['grounding_rate']} | ${s['cost_per_lead_usd']:.4f}/lead")
    print("Saved outputs/eval_results.json and outputs/eval_report.md")


if __name__ == "__main__":
    main()