"""Command line: process a CSV of companies or a single company.

    python -m app.cli run data/demo_leads.csv            # whole file
    python -m app.cli run data/demo_leads.csv --limit 5  # first 5
    python -m app.cli add "Allbirds" allbirds.com         # one company
"""
from __future__ import annotations

import argparse
import csv
import sys

from app.config import get_settings
from app.llm import ProviderConfigError, get_provider
from app.pipeline import Pipeline


def _print(out: dict) -> None:
    score = f"{out['score']}/10" if out.get("score") is not None else "-"
    print(f"  {out['company']:<28} {str(out.get('segment') or '-'):<14} {score:>7}  {out['status']:<17} "
          f"${out['cost_usd']:.4f}  {out['duration_ms'] / 1000:.1f}s" + (f"  {out['error']}" if out.get("error") else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description="LeadScout command line")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Process a CSV with columns company, website[, segment]")
    r.add_argument("csv_path")
    r.add_argument("--limit", type=int, default=None)
    a = sub.add_parser("add", help="Process one company")
    a.add_argument("company")
    a.add_argument("website")
    args = ap.parse_args()

    settings = get_settings()
    try:
        pipeline = Pipeline(settings, get_provider(settings))
    except ProviderConfigError as exc:
        sys.exit(f"Configuration error: {exc}")

    rows = [{"company": args.company, "website": args.website}] if args.cmd == "add" else \
        list(csv.DictReader(open(args.csv_path, encoding="utf-8-sig")))[: args.limit]
    print(f"\nProcessing {len(rows)} companies with {settings.llm_provider}:{settings.model_name}\n")
    for row in rows:
        lead_id = pipeline.add_lead(row["company"], row["website"], row.get("segment"))
        _print(pipeline.process(lead_id))
    print(f"\nResults: outputs/leads.csv and the review page at {settings.public_base_url}/review")


if __name__ == "__main__":
    main()
