import copy

from app.fetch import Fetcher, candidate_links, html_to_text, normalize_website
from app.pipeline import Pipeline
from app.research import check_draft, compute_score, verify_facts
from tests.conftest import (BAD_DRAFT, GOOD_DRAFT, HOME_HTML, PROFILE, SCORE, SITE, FakeClient, ScriptedProvider)


def fetcher(settings):
    return Fetcher(settings, client=FakeClient(SITE))


def test_normalize_and_links():
    assert normalize_website("www.KettleAndCo.example/") == ("https://www.KettleAndCo.example", "kettleandco.example")
    links = candidate_links(HOME_HTML, "https://kettleandco.example", "kettleandco.example")
    assert links == ["https://kettleandco.example/about", "https://kettleandco.example/pages/faq"]
    title, text = html_to_text(HOME_HTML)
    assert "Kettle & Co" in title and "var x" not in text and "200 products" in text


def test_fetcher_reads_pages(settings):
    pages, err = fetcher(settings).research("kettleandco.example")
    assert err is None and len(pages) == 3


def test_grounding_rejects_invented_quote(settings):
    pages, _ = fetcher(settings).research("kettleandco.example")
    facts = verify_facts(PROFILE["facts"], pages)
    assert [f["verified"] for f in facts] == [True, True, True, False]


def test_score_requires_verified_evidence():
    from app.config import Settings
    seg = Settings().icp()["segments"]["d2c_ecommerce"]
    verified = [{"fact_id": "F1"}, {"fact_id": "F2"}, {"fact_id": "F3"}]
    out = compute_score(SCORE["criteria"], seg, verified)
    by = {c["id"]: c for c in out["criteria"]}
    assert by["growth"]["answer"] == "unknown" and by["growth"]["downgraded"]   # F4 was not verified
    assert by["size_fit"]["answer"] == "unknown"                                 # no evidence cited
    assert out["score"] == 7.0                                                   # (3+2+2)/10


def test_draft_checks():
    facts = [{"fact_id": "F1", "verified": True}, {"fact_id": "F2", "verified": True}, {"fact_id": "F4", "verified": False}]
    assert all(c["passed"] for c in check_draft(GOOD_DRAFT, facts, "Kettle & Co"))
    failed = {c["name"] for c in check_draft(BAD_DRAFT, facts, "Kettle & Co") if not c["passed"]}
    assert {"Uses a verified fact", "No banned phrases", "No placeholders", "Length 60-130 words"} <= failed


def test_end_to_end_with_retry(settings):
    provider = ScriptedProvider([copy.deepcopy(PROFILE), SCORE, BAD_DRAFT, GOOD_DRAFT])
    p = Pipeline(settings, provider, fetcher=fetcher(settings), search_fn=lambda q: [])
    lid = p.add_lead("Kettle & Co", "kettleandco.example")
    assert p.add_lead("Kettle and Co", "https://www.kettleandco.example") == lid   # dedupe by domain
    out = p.process(lid)
    assert out["status"] == "ready_for_review" and out["score"] == 7.0 and out["draft_attempts"] == 2
    assert out["grounding_rate"] == 0.75 and "won't follow up" in out["draft_body"]
    assert "failed these checks" in provider.prompts[-1][1]      # retry received feedback
    steps = [e["step"] for e in out["events"]]
    assert steps == ["fetch_website", "search_news", "extract_profile", "verify_facts", "score_fit",
                     "draft_email", "draft_email", "sync"]
    assert out["sync_status"]["csv"] == "ok" and settings.leads_csv_path.exists()
    assert out["cost_usd"] > 0


def test_low_score_is_not_a_fit_and_skips_draft(settings):
    low = {"criteria": [{"id": "sells_online", "answer": "no", "fact_ids": [], "reason": "x"}]}
    provider = ScriptedProvider([copy.deepcopy(PROFILE), low])
    p = Pipeline(settings, provider, fetcher=fetcher(settings), search_fn=lambda q: [])
    out = p.process(p.add_lead("Kettle & Co", "kettleandco.example"))
    assert out["status"] == "not_a_fit" and out["draft_body"] is None and not provider.results


def test_other_segment_skips_scoring(settings):
    prof = copy.deepcopy(PROFILE) | {"segment": "other"}
    p = Pipeline(settings, ScriptedProvider([prof]), fetcher=fetcher(settings), search_fn=lambda q: [])
    assert p.process(p.add_lead("Kettle & Co", "kettleandco.example"))["status"] == "not_a_fit"


def test_no_sources_fails_cleanly(settings):
    p = Pipeline(settings, ScriptedProvider([]), fetcher=Fetcher(settings, client=FakeClient({})), search_fn=lambda q: [])
    out = p.process(p.add_lead("Ghost", "ghost.example"))
    assert out["status"] == "failed" and "No public sources" in out["error"]


def test_decide_and_resync(settings):
    provider = ScriptedProvider([copy.deepcopy(PROFILE), SCORE, GOOD_DRAFT])
    p = Pipeline(settings, provider, fetcher=fetcher(settings), search_fn=lambda q: [])
    lid = p.add_lead("Kettle & Co", "kettleandco.example")
    p.process(lid)
    out = p.decide(lid, "approve", body="Edited body")
    assert out["status"] == "approved" and out["draft_body"] == "Edited body" and out["decided_at"]


def test_banned_phrase_allowed_when_it_comes_from_a_verified_fact():
    facts = [{"fact_id": "F1", "verified": True, "claim": "Shoes are made from 100% merino wool", "quote": "100% merino wool"}]
    draft = dict(GOOD_DRAFT, facts_used=["F1"], body=GOOD_DRAFT["body"].replace("With over 200 products", "With 100% merino wool shoes"))
    by = {c["name"]: c for c in check_draft(draft, facts, "Kettle & Co")}
    assert by["No banned phrases"]["passed"]
    hype = dict(draft, body=draft["body"] + " We guarantee results.")
    assert not {c["name"]: c for c in check_draft(hype, facts, "Kettle & Co")}["No banned phrases"]["passed"]


def test_large_company_is_capped():
    from app.config import Settings
    seg = Settings().icp()["segments"]["d2c_ecommerce"]
    verified = [{"fact_id": "F1"}, {"fact_id": "F2"}, {"fact_id": "F3"}]
    out = compute_score(SCORE["criteria"], seg, verified, "large", 5, size_reason="2,275 employees")
    assert out["score"] == 5.0 and out["uncapped_score"] == 7.0 and out["capped"] and "2,275" in out["note"]
    assert compute_score(SCORE["criteria"], seg, verified, "mid", 5)["score"] == 7.0
    assert compute_score(SCORE["criteria"], seg, verified, "mid", 5, sells_ai=True)["capped"]


def test_fact_stuffing_fails_check():
    facts = [{"fact_id": f"F{i}", "verified": True, "claim": "", "quote": ""} for i in range(1, 4)]
    by = {c["name"]: c for c in check_draft(dict(GOOD_DRAFT, facts_used=["F1", "F2", "F3"]), facts, "Kettle & Co")}
    assert not by["At most 2 facts"]["passed"]


def test_classify_size_in_code():
    from app.research import classify_size
    assert classify_size({"employees": 300, "annual_revenue_usd": 66_000_000})[0] == "mid"     # 550 crore INR
    assert classify_size({"employees": 700})[0] == "mid"
    assert classify_size({"employees": 2275})[0] == "large"
    assert classify_size({"annual_revenue_usd": 500_000_000})[0] == "large"
    assert classify_size({"valuation_usd": 5e9}) == ("large", "$5.0B valuation")
    assert classify_size({"publicly_listed": True})[0] == "large"
    assert classify_size({"employees": 25})[0] == "small"
    assert classify_size({})[0] == "unknown"