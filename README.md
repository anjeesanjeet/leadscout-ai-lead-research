# LeadScout: AI Lead Research and Outreach Automation

An n8n and Python automation that researches companies from their public websites and news, scores how well each one fits an ideal-customer profile, and drafts a personalized outreach email from verified facts only. Results go to HubSpot and Google Sheets, and a human approves every email before it is sent.

![LeadScout results](https://raw.githubusercontent.com/anjeesanjeet/leadscout-ai-lead-research/main/outputs/thumbnail.png)

## The problem

Personalized outreach works, but researching each company takes 15 to 30 minutes. AI can do that research in seconds, but it has a well-known flaw: it invents details. A cold email that compliments a company on an award it never won does more harm than no email at all.

The real requirements:

- Research from public sources only, and respect each website's rules for automated readers.
- Never put an unverified claim about a company into an email.
- Score fit in a way a sales team can read and trust, not a black-box number.
- Fit into the tools teams already use: a spreadsheet to add leads, a CRM to track them, and a human to approve.

## What I built

LeadScout runs every company through the same pipeline:

- **Website and news research:** reads up to four public pages (home, about, careers, help) after checking robots.txt, plus recent news through Tavily search.
- **Profile extraction:** the model returns a structured profile with every fact backed by a verbatim quote from a numbered source.
- **Fact verification in code:** each quote is matched against the source text. Facts that can't be found are blocked and never reach scoring or drafting.
- **Explainable fit score:** the model answers each rubric question for the company's segment (D2C brands, B2B SaaS or agencies) and must cite verified facts. The score is computed in code, and a "yes" without evidence counts as unknown.
- **Checked drafts:** emails are written from verified facts only, then checked in code for length, banned sales phrases, placeholders and fact usage, with one automatic retry. An opt-out line is always added.
- **CRM and spreadsheet sync:** each lead goes to a local CSV, a Google Sheets tab and HubSpot (company plus a note with the score, reasons, facts and draft).
- **Human review:** a review page shows the score breakdown, every fact with its source link, and an editable draft with approve and reject buttons. LeadScout never sends email itself.

The n8n workflow ties it together: a new row in a Google Sheet triggers research, and n8n emails the reviewer a link when a draft is ready.

## How I measure it

An evaluation runs the full pipeline on 24 real companies across three segments, each labelled with its correct segment. It measures research success, segment accuracy, the share of facts verified against their sources, how many unverified facts were blocked, how often drafts pass every check, an LLM-judge score for draft quality, and cost and time per lead.

Measured results are in the evaluation report in the outputs folder.

## Architecture and stack

- **Automation:** n8n (Google Sheets trigger, HTTP request, condition, Gmail notification)
- **Backend:** Python, FastAPI
- **Models:** Claude (default Haiku 4.5) or OpenAI, with structured output through forced tool calls
- **Research:** httpx and BeautifulSoup for websites, Tavily for news, RapidFuzz for quote verification
- **Integrations:** HubSpot CRM API, Google Sheets API
- **Data:** SQLite with a full step-by-step log for every lead
- **Visuals:** results dashboard, flowcharts generated from the code and the n8n workflow file
- **Quality:** offline tests with a scripted model and a fake website

## Responsible use

Public company information only, no personal data about individuals, robots.txt respected, drafts only, and an opt-out line in every email.

## Run it yourself

Setup, the n8n, HubSpot and Google Sheets configuration, and all commands are in the [setup guide](SETUP.md).
