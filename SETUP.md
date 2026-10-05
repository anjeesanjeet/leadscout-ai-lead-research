# LeadScout: setup and technical guide

Back to the [project overview](README.md).

## Quick start

Requires Python 3.10+. Commands are for Windows PowerShell; on macOS/Linux use `source .venv/bin/activate` and `cp`.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then add ANTHROPIC_API_KEY (and TAVILY_API_KEY if you have one)
python -m pytest -q           # 13 tests, no API key needed
python -m app.main            # open http://127.0.0.1:8100
```

On the review page, enter a company and website (e.g. Allbirds, allbirds.com) and click **Research and draft**.

## Command line

```powershell
python -m app.cli add "Allbirds" allbirds.com
python -m app.cli run data/demo_leads.csv --limit 5
```

Results land in the database, `outputs/leads.csv`, and any configured sinks.

## Evaluate

```powershell
python -m eval.run_eval --judge
```

Runs all 24 companies in `data/demo_leads.csv` on an isolated database (never touches Google Sheets or HubSpot)
and writes `outputs/eval_results.json` and `outputs/eval_report.md`.

| Metric | Meaning |
|---|---|
| Research success | Companies with at least one readable public source |
| Segment accuracy | Model's segment vs the labelled segment |
| Facts verified | Share of extracted facts whose quote was found in the source |
| Unverified facts blocked | Facts dropped before scoring and drafting |
| Draft pass rates | Drafts passing every code check, first time and after one retry |
| Judge score | LLM review of each draft for specificity, accuracy and tone (1-5) |
| Cost and time per lead | Model tokens plus news search, wall-clock time |

Live websites change, so results vary slightly between runs. Some sites block automated readers; those leads
fall back to news search results, or fail cleanly if nothing is readable.

## Export portfolio assets

```powershell
python -m playwright install chromium     # once
python -m scripts.export_assets
```

Creates `outputs/thumbnail.png` (1600 x 1200), `dashboard_full.png`, `review_page.png`,
`flowchart_pipeline.png`, `flowchart_n8n.png`, `flowchart_trace.png` and `docs/architecture.md`.

## Google Sheets (optional)

1. In Google Cloud Console, create a project, enable the **Google Sheets API**, create a **service account** and download its JSON key into the project folder.
2. Create a spreadsheet with a tab named **Inbox** with columns `company`, `website`, `segment`.
3. Share the spreadsheet with the service account's email (Editor).
4. In `.env`: `GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json` and `GOOGLE_SHEET_ID=<id from the sheet URL>`.

LeadScout writes one row per lead to a **Leads** tab (created automatically) and updates it on approval.

## HubSpot (optional)

1. In HubSpot: Settings, Integrations, **Private Apps**, create an app with the scopes `crm.objects.companies.read` and `crm.objects.companies.write`. If a sync later reports a missing scope for notes, add the scope named in the error message.
2. Put the access token in `.env` as `HUBSPOT_TOKEN`.

Each lead creates or updates a company by domain and attaches a note with the score, reasons, verified facts and draft.

## n8n automation (optional)

1. Install Node.js 20+ and start n8n: `npx n8n` (opens http://localhost:5678).
2. Set `LEADSCOUT_API_KEY` in `.env` and restart LeadScout.
3. In n8n: **Import from file**, choose `n8n/leadscout_workflow.json`.
4. Open each node: connect your Google Sheets and Gmail credentials, set your sheet id, your email address, and the same API key in the HTTP Request header.
5. Activate the workflow. Adding a row to the **Inbox** tab now researches the company and emails you a review link when a draft is ready.

The workflow calls `POST /api/leads/run`. If n8n runs in Docker, replace `127.0.0.1` with `host.docker.internal`.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | /api/leads | Research a company (review page) |
| POST | /api/leads/run | Same, for automation; requires `X-API-Key` when set |
| GET | /api/leads, /api/leads/{id} | List leads, full detail |
| POST | /api/leads/{id}/rerun | Research again |
| POST | /api/leads/{id}/decision | Approve or reject, with optional edits |
| GET | /api/dashboard, /api/flowchart | Dashboard data, Mermaid diagrams |

Interactive docs at `/docs`.

## Project structure

```
app/
  config.py      settings from .env
  db.py          SQLite: leads, sources, facts, step events
  fetch.py       polite website reader (robots.txt) + Tavily news search
  llm.py         Claude / OpenAI structured output via forced tool calls
  research.py    profile extraction, quote verification, fit scoring, drafting + checks
  pipeline.py    orchestration, step logging, review decisions
  sinks.py       CSV, Google Sheets, HubSpot
  metrics.py     dashboard data
  flowchart.py   generated Mermaid diagrams
  main.py        FastAPI app
  cli.py         command line
config/          icp.json (segment rubrics), sender.json (your offer and signature)
data/            demo_leads.csv (24 labelled companies)
eval/            run_eval.py
n8n/             leadscout_workflow.json
static/          review, dashboard and flowchart pages
scripts/         export_assets.py
tests/           offline tests with a scripted model and fake website
```

## Customising

- **Your offer:** edit `config/sender.json` (offer, proof points, call to action, signature, opt-out line).
- **Ideal customers:** edit `config/icp.json`. Each segment has weighted criteria; add a segment by adding an entry and its id to `SEGMENTS` in `app/research.py`.
- **Threshold:** `FIT_THRESHOLD` in `.env` decides which leads get a draft.

## Responsible use

LeadScout reads only public company websites and news, respects robots.txt, stores no personal data about
individuals, and never sends email. Every draft includes an opt-out line. Check the anti-spam rules that apply to
you (for example CAN-SPAM in the US, GDPR/PECR in the EU and UK) before sending outreach.
