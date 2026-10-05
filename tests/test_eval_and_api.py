import copy

from fastapi.testclient import TestClient

import eval.run_eval as ev
from app.fetch import Fetcher
from app.flowchart import n8n_mermaid, pipeline_mermaid, trace_mermaid
from app.metrics import dashboard_payload
from app.pipeline import Pipeline
from tests.conftest import GOOD_DRAFT, PROFILE, SCORE, SITE, FakeClient, ScriptedProvider


def test_summary_math():
    rs = [
        {"status": "ready_for_review", "segment_correct": True, "facts": 4, "verified": 3, "drafted": True,
         "draft_first_pass": True, "draft_final_pass": True, "judge": {"score": 4}, "cost_usd": 0.01, "duration_ms": 1000,
         "expected_segment": "d2c_ecommerce", "score": 7.0},
        {"status": "failed", "segment_correct": False, "facts": 0, "verified": 0, "drafted": False,
         "draft_first_pass": False, "draft_final_pass": False, "judge": None, "cost_usd": 0.0, "duration_ms": 500,
         "expected_segment": "agency", "score": None},
    ]
    s = ev.summarize(rs)
    assert s["research_success_rate"] == 0.5 and s["segment_accuracy"] == 1.0 and s["grounding_rate"] == 0.75
    assert s["unverified_facts_blocked"] == 1 and s["judge_avg"] == 4 and s["cost_per_lead_usd"] == 0.005
    assert "LeadScout evaluation report" in ev.render_report({"summary": s, "meta": {
        "provider": "x", "model": "y", "companies": 2, "tavily": False, "run_at": "now"},
        "by_segment": ev.by_segment(rs), "leads": [r | {"company": "c", "segment": "s"} for r in rs]})


def test_flowcharts_and_dashboard(settings):
    p = Pipeline(settings, ScriptedProvider([copy.deepcopy(PROFILE), SCORE, GOOD_DRAFT]),
                 fetcher=Fetcher(settings, client=FakeClient(SITE)), search_fn=lambda q: [])
    lid = p.add_lead("Kettle & Co", "kettleandco.example")
    p.process(lid)
    assert "FIT{" in pipeline_mermaid(settings) and "verify_facts" in pipeline_mermaid(settings)
    n8n = n8n_mermaid()
    assert "googleSheetsTrigger" in n8n and "-- true -->" in n8n
    trace = trace_mermaid(settings, lid)
    assert "draft_email" in trace and "ready_for_review" in trace
    d = dashboard_payload(settings)
    assert d["live"]["processed"] == 1 and d["live"]["grounding_rate"] == 0.75 and d["eval"] is None


def test_api_requires_key_for_automation(monkeypatch, settings):
    import app.main as m
    monkeypatch.setattr(m, "settings", settings)
    settings.api_key = "secret"
    c = TestClient(m.app)
    assert c.post("/api/leads/run", json={"company": "X", "website": "x.com"}).status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/flowchart?view=n8n").json()["mermaid"].startswith("flowchart")


def test_target_and_control_metrics():
    base = {"segment_correct": True, "facts": 1, "verified": 1, "draft_first_pass": True, "draft_final_pass": True,
            "judge": None, "cost_usd": 0.0, "duration_ms": 1, "expected_segment": "agency", "score": 5.0}
    rs = [base | {"status": "ready_for_review", "drafted": True, "expected_size": "small_mid", "capped": False},
          base | {"status": "not_a_fit", "drafted": False, "expected_size": "small_mid", "capped": True},
          base | {"status": "not_a_fit", "drafted": False, "expected_size": "large", "capped": True}]
    s = ev.summarize(rs)
    assert s["target_draft_rate"] == 0.5 and s["large_filtered_rate"] == 1.0 and s["targets_wrongly_capped"] == 1