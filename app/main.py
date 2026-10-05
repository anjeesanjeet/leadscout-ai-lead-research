"""FastAPI service: lead API (used by n8n and the review page), dashboard and flowchart APIs, pages.

Run:  python -m app.main     then open http://127.0.0.1:8100
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT_DIR, get_settings
from app.db import connect
from app.flowchart import latest_lead_id, n8n_mermaid, pipeline_mermaid, trace_mermaid
from app.llm import ProviderConfigError, get_provider
from app.metrics import dashboard_payload
from app.pipeline import Pipeline

STATIC = ROOT_DIR / "static"
settings = get_settings()
app = FastAPI(title="LeadScout: AI lead research and outreach", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline(settings, get_provider(settings))


def _review_url(lead_id: int) -> str:
    return f"{settings.public_base_url}/review?lead={lead_id}"


# ------------------------------------------------------------------ pages

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/review")


for _page in ("review", "dashboard", "flowchart"):
    def _make(name=_page):
        def page():
            return FileResponse(STATIC / f"{name}.html")
        return page
    app.get(f"/{_page}", include_in_schema=False)(_make())


# ------------------------------------------------------------------ API

class LeadIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    website: str = Field(min_length=3, max_length=300)
    segment_hint: str | None = None


class DecisionIn(BaseModel):
    decision: str
    subject: str | None = None
    body: str | None = None


def _run(lead: LeadIn) -> dict:
    try:
        pipeline = get_pipeline()
    except ProviderConfigError as exc:
        raise HTTPException(400, str(exc))
    lead_id = pipeline.add_lead(lead.company, lead.website, lead.segment_hint)
    out = pipeline.process(lead_id)
    out["review_url"] = _review_url(lead_id)
    return out


@app.post("/api/leads")
def create_and_process(lead: LeadIn):
    """Used by the review page."""
    return _run(lead)


@app.post("/api/leads/run")
def run_for_automation(lead: LeadIn, x_api_key: str | None = Header(default=None)):
    """Used by n8n. Requires X-API-Key when LEADSCOUT_API_KEY is set."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "Invalid or missing X-API-Key")
    out = _run(lead)
    # keep the payload small for automation tools
    keep = ("id", "company", "website", "segment", "status", "score", "draft_subject", "draft_body",
            "grounding_rate", "cost_usd", "review_url", "error")
    return {k: out.get(k) for k in keep}


@app.get("/api/leads")
def list_leads():
    conn = connect(settings.db_path)
    try:
        rows = conn.execute("SELECT id, company, website, segment, status, score, cost_usd, updated_at "
                            "FROM leads ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/leads/{lead_id}")
def get_one(lead_id: int):
    conn = connect(settings.db_path)
    try:
        if not conn.execute("SELECT 1 FROM leads WHERE id = ?", (lead_id,)).fetchone():
            raise HTTPException(404, "Lead not found")
        return Pipeline.summary(conn, lead_id) | {"review_url": _review_url(lead_id)}
    finally:
        conn.close()


@app.post("/api/leads/{lead_id}/rerun")
def rerun(lead_id: int):
    try:
        return get_pipeline().process(lead_id)
    except ProviderConfigError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/leads/{lead_id}/decision")
def decide(lead_id: int, body: DecisionIn):
    try:
        pipeline = get_pipeline()
    except ProviderConfigError:
        pipeline = Pipeline.__new__(Pipeline)          # decisions need no model
        pipeline.settings, pipeline.db_path = settings, settings.db_path
    try:
        return pipeline.decide(lead_id, body.decision, body.subject, body.body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/dashboard")
def dashboard():
    return dashboard_payload(settings)


@app.get("/api/flowchart")
def flowchart(view: str = "pipeline", lead_id: int | None = None):
    if view == "pipeline":
        return {"view": view, "mermaid": pipeline_mermaid(settings)}
    if view == "n8n":
        return {"view": view, "mermaid": n8n_mermaid()}
    if view == "trace":
        lid = lead_id or latest_lead_id(settings)
        return {"view": view, "lead_id": lid, "mermaid": trace_mermaid(settings, lid) if lid else None}
    raise HTTPException(400, "view must be pipeline, n8n or trace")


@app.get("/api/health")
def health():
    return {"status": "ok", "provider": settings.llm_provider, "model": settings.model_name}


@app.exception_handler(ProviderConfigError)
def _provider_error(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
