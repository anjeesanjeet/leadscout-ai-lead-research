"""Orchestrates one lead end to end and records every step (used for metrics and the trace flowchart)."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from app import research
from app.config import Settings
from app.db import connect, events_for, facts_for, get_lead, log_event, now_iso, update_lead
from app.fetch import Fetcher, normalize_website, tavily_search
from app.llm import BaseProvider
from app.sinks import sync_lead

# The pipeline's steps, in order. The architecture flowchart is generated from this list.
STEPS = [
    ("fetch_website", "Read public website pages", "robots.txt respected; max pages capped"),
    ("search_news", "Search recent news (Tavily)", "public sources only"),
    ("extract_profile", "Extract profile + quoted facts", "structured output via forced tool call"),
    ("verify_facts", "Verify every quote against its source", "unverified facts are dropped"),
    ("score_fit", "Score fit against the segment rubric", "score computed in code; 'yes' needs evidence"),
    ("draft_email", "Draft outreach from verified facts", "length, banned phrases, placeholders checked; 1 retry"),
    ("sync", "Sync to CSV, Google Sheets, HubSpot", "never sends email; human approves"),
]


class Step:
    def __init__(self):
        self.cost = 0.0
        self.status = "ok"
        self.detail = ""


class Pipeline:
    def __init__(self, settings: Settings, provider: BaseProvider, fetcher: Fetcher | None = None,
                 search_fn=None, db_path: Path | str | None = None):
        self.settings, self.provider = settings, provider
        self.fetcher = fetcher or Fetcher(settings)
        self.search_fn = search_fn or (lambda q: tavily_search(settings, q))
        self.db_path = Path(db_path or settings.db_path)

    # ---------------------------------------------------------------- leads

    def add_lead(self, company: str, website: str, segment_hint: str | None = None) -> int:
        _, domain = normalize_website(website)
        conn = connect(self.db_path)
        try:
            row = conn.execute("SELECT id FROM leads WHERE domain = ?", (domain,)).fetchone()
            if row:
                return row["id"]
            ts = now_iso()
            cur = conn.execute(
                "INSERT INTO leads (company, website, domain, segment_hint, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (company.strip(), website.strip(), domain, segment_hint, ts, ts))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @contextmanager
    def _step(self, conn, lead_id: int, name: str, totals: dict):
        st, t0 = Step(), time.perf_counter()
        try:
            yield st
        except Exception as exc:
            st.status, st.detail = "failed", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000
            totals["cost"] += st.cost
            log_event(conn, lead_id, name, st.status, st.detail, ms, st.cost)

    # ---------------------------------------------------------------- run

    def process(self, lead_id: int) -> dict:
        conn = connect(self.db_path)
        t_start, totals = time.perf_counter(), {"cost": 0.0}
        try:
            lead = get_lead(conn, lead_id)
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            for table in ("sources", "facts", "events"):
                conn.execute(f"DELETE FROM {table} WHERE lead_id = ?", (lead_id,))
            update_lead(conn, lead_id, status="researching", error=None, score=None, score_breakdown=None,
                        draft_subject=None, draft_body=None, draft_checks=None, draft_attempts=0)
            try:
                status = self._run(conn, lead, totals)
                error = None
            except Exception as exc:
                status, error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
            update_lead(conn, lead_id, status=status, error=error, cost_usd=round(totals["cost"], 6),
                        duration_ms=round((time.perf_counter() - t_start) * 1000, 1))
            with self._step(conn, lead_id, "sync", totals) as st:
                result = sync_lead(self.settings, conn, lead_id)
                st.detail = ", ".join(f"{k}: {v}" for k, v in result.items() if not k.startswith("hubspot_"))
                if any(str(v).startswith("error") for v in result.values()):
                    st.status = "warning"
            update_lead(conn, lead_id, sync_status=result)
            return self.summary(conn, lead_id)
        finally:
            conn.close()

    def _run(self, conn, lead: dict, totals: dict) -> str:
        lid, s = lead["id"], self.settings

        with self._step(conn, lid, "fetch_website", totals) as st:
            pages, err = self.fetcher.research(lead["website"])
            st.detail = f"{len(pages)} pages" + (f" ({err})" if err else "")
            if not pages:
                st.status = "warning"

        with self._step(conn, lid, "search_news", totals) as st:
            results = self.search_fn(f"{lead['company']} company news")
            if s.tavily_api_key:
                st.cost = s.tavily_price_per_search
                st.detail = f"{len(results)} results"
            else:
                st.status, st.detail = "skipped", "TAVILY_API_KEY not set"

        sources = pages + results
        if not sources:
            raise RuntimeError("No public sources could be read for this company")
        conn.executemany("INSERT INTO sources (lead_id, idx, kind, url, title, text) VALUES (?,?,?,?,?,?)",
                         [(lid, i, x["kind"], x["url"], x.get("title"), x["text"]) for i, x in enumerate(sources, 1)])
        conn.commit()

        with self._step(conn, lid, "extract_profile", totals) as st:
            res = research.extract_profile(self.provider, lead["company"], lead["website"], sources)
            st.cost = res.cost_usd
            profile = res.data
            if not profile.get("facts"):
                raise RuntimeError("Model returned no facts")
            st.detail = f"segment {profile.get('segment')}, {len(profile['facts'])} facts"

        with self._step(conn, lid, "verify_facts", totals) as st:
            facts = research.verify_facts(profile.get("facts", []), sources, s.grounding_min_score)
            conn.executemany(
                "INSERT INTO facts (lead_id, fact_id, claim, quote, source_idx, source_url, verified, match_score) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(lid, f["fact_id"], f["claim"], f["quote"], f["source_idx"], f["source_url"], int(f["verified"]),
                  f["match_score"]) for f in facts])
            conn.commit()
            n_ok = sum(f["verified"] for f in facts)
            st.detail = f"{n_ok} of {len(facts)} verified"
            if n_ok < len(facts):
                st.status = "warning"

        profile["size_signal"], profile["size_reason"] = research.classify_size(profile)
        profile_store = {k: v for k, v in profile.items() if k != "facts"}
        segment = profile.get("segment", "other")
        update_lead(conn, lid, profile=profile_store, segment=segment)
        icp = s.icp()
        segments = icp["segments"]

        if segment not in segments:
            with self._step(conn, lid, "score_fit", totals) as st:
                st.status, st.detail = "skipped", f"segment '{segment}' is outside the target segments"
            update_lead(conn, lid, score=0.0, score_breakdown={"score": 0.0, "criteria": [], "note": st.detail})
            return "not_a_fit"

        with self._step(conn, lid, "score_fit", totals) as st:
            res, score = research.score_fit(self.provider, profile, facts, segments[segment],
                                            icp.get("capped_max_score"))
            st.cost = res.cost_usd
            st.detail = f"{score['score']}/10" + (f" (capped from {score['uncapped_score']}: large company)"
                                                   if score.get("capped") else "")
        update_lead(conn, lid, score=score["score"], score_breakdown=score)
        if score["score"] < s.fit_threshold:
            return "not_a_fit"

        sender = s.sender()
        feedback, checks, draft, attempts = None, [], {}, 0
        for attempts in (1, 2):
            with self._step(conn, lid, "draft_email", totals) as st:
                res = research.draft_email(self.provider, profile, facts, score, sender, feedback)
                st.cost = res.cost_usd
                draft = res.data
                checks = research.check_draft(draft, facts, lead["company"])
                failed = [c for c in checks if not c["passed"]]
                st.detail = f"attempt {attempts}: " + ("all checks passed" if not failed else
                                                        "failed " + ", ".join(c["name"] for c in failed))
                if failed:
                    st.status = "warning"
            if not failed:
                break
            feedback = "; ".join(f"{c['name']} ({c['detail']})" for c in failed)
        update_lead(conn, lid, draft_subject=draft.get("subject", ""),
                    draft_body=research.finalize_body(draft.get("body", ""), sender),
                    draft_checks={"checks": checks, "facts_used": draft.get("facts_used", [])},
                    draft_attempts=attempts)
        return "ready_for_review" if all(c["passed"] for c in checks) else "needs_review"

    # ---------------------------------------------------------------- review

    def decide(self, lead_id: int, decision: str, subject: str | None = None, body: str | None = None) -> dict:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        conn = connect(self.db_path)
        try:
            fields = {"status": "approved" if decision == "approve" else "rejected", "decided_at": now_iso()}
            if subject is not None:
                fields["draft_subject"] = subject
            if body is not None:
                fields["draft_body"] = body
            update_lead(conn, lead_id, **fields)
            log_event(conn, lead_id, "human_review", "ok", f"{decision}d by reviewer")
            update_lead(conn, lead_id, sync_status=sync_lead(self.settings, conn, lead_id))
            return self.summary(conn, lead_id)
        finally:
            conn.close()

    @staticmethod
    def summary(conn, lead_id: int) -> dict:
        lead = get_lead(conn, lead_id)
        facts = facts_for(conn, lead_id)
        lead["facts"] = facts
        lead["events"] = events_for(conn, lead_id)
        lead["sources"] = [dict(r) for r in conn.execute(
            "SELECT idx, kind, url, title FROM sources WHERE lead_id = ? ORDER BY idx", (lead_id,))]
        lead["grounding_rate"] = round(sum(f["verified"] for f in facts) / len(facts), 3) if facts else None
        return lead


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)