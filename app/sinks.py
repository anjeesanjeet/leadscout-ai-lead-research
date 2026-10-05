"""Where results go: a local CSV (always), Google Sheets and HubSpot (each enabled by its credentials)."""
from __future__ import annotations

import csv
import html
import time

import httpx

from app.config import Settings
from app.db import facts_for, get_lead, lead_to_dict

FIELDS = ["lead_id", "company", "website", "segment", "status", "fit_score", "why_they_fit", "verified_facts",
          "draft_subject", "draft_body", "cost_usd", "updated_at"]


def lead_row(lead: dict, facts: list[dict]) -> list:
    crit = (lead.get("score_breakdown") or {}).get("criteria", [])
    why = "; ".join(c["reason"] for c in crit if c["answer"] in ("yes", "partial"))
    vf = " | ".join(f["claim"] for f in facts if f["verified"])
    return [lead["id"], lead["company"], lead["website"], lead.get("segment") or "", lead["status"],
            lead.get("score") if lead.get("score") is not None else "", why, vf,
            lead.get("draft_subject") or "", lead.get("draft_body") or "", round(lead.get("cost_usd") or 0, 4),
            lead["updated_at"]]


def export_csv(settings: Settings, conn) -> None:
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    rows = [lead_to_dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY id")]
    with open(settings.leads_csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for lead in rows:
            w.writerow(lead_row(lead, facts_for(conn, lead["id"])))


class GoogleSheetsSink:
    """Upserts one row per lead into the 'Leads' worksheet (service-account auth)."""

    def __init__(self, settings: Settings):
        import gspread
        gc = gspread.service_account(filename=settings.google_service_account_file)
        sheet = gc.open_by_key(settings.google_sheet_id)
        try:
            self.ws = sheet.worksheet("Leads")
        except gspread.WorksheetNotFound:
            self.ws = sheet.add_worksheet(title="Leads", rows=1000, cols=len(FIELDS))
        if self.ws.row_values(1) != FIELDS:
            self.ws.update(values=[FIELDS], range_name="A1")

    def upsert(self, row: list) -> None:
        ids = self.ws.col_values(1)
        values = [["" if v is None else v for v in row]]
        if str(row[0]) in ids:
            self.ws.update(values=values, range_name=f"A{ids.index(str(row[0])) + 1}")
        else:
            self.ws.append_row(values[0], value_input_option="RAW")


class HubSpotSink:
    """Creates/updates the company by domain and attaches the research + draft as a note."""
    BASE = "https://api.hubapi.com"
    NOTE_TO_COMPANY = 190  # HubSpot-defined association type id

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20, headers={
            "Authorization": f"Bearer {settings.hubspot_token}", "Content-Type": "application/json"})

    def _company_id(self, lead: dict) -> str:
        r = self.client.post(f"{self.BASE}/crm/v3/objects/companies/search", json={
            "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": lead["domain"]}]}],
            "properties": ["domain"], "limit": 1})
        r.raise_for_status()
        props = {"name": lead["company"], "domain": lead["domain"],
                 "description": ((lead.get("profile") or {}).get("one_liner") or "")[:500]}
        results = r.json().get("results", [])
        if results:
            cid = results[0]["id"]
            self.client.patch(f"{self.BASE}/crm/v3/objects/companies/{cid}", json={"properties": props}).raise_for_status()
            return cid
        r = self.client.post(f"{self.BASE}/crm/v3/objects/companies", json={"properties": props})
        r.raise_for_status()
        return r.json()["id"]

    @staticmethod
    def note_html(lead: dict, facts: list[dict]) -> str:
        e = html.escape
        crit = (lead.get("score_breakdown") or {}).get("criteria", [])
        parts = [f"<p><strong>LeadScout fit score: {lead.get('score', 0)}/10</strong> ({e(lead['status'])})</p>",
                 f"<p>{e((lead.get('profile') or {}).get('one_liner', ''))}</p><p><strong>Why they fit</strong></p><ul>"]
        parts += [f"<li>{e(c['question'])} <em>{c['answer']}</em>: {e(c['reason'])}</li>" for c in crit]
        parts.append("</ul><p><strong>Verified facts</strong></p><ul>")
        parts += [f"<li>{e(f['claim'])} (<a href=\"{e(f['source_url'] or '')}\">source</a>)</li>" for f in facts if f["verified"]]
        parts.append("</ul>")
        if lead.get("draft_body"):
            body = e(lead["draft_body"]).replace("\n", "<br>")
            parts.append(f"<p><strong>Draft: {e(lead.get('draft_subject') or '')}</strong></p><p>{body}</p>")
        return "".join(parts)

    def upsert(self, lead: dict, facts: list[dict], previous: dict | None) -> dict:
        cid = self._company_id(lead)
        props = {"hs_timestamp": str(int(time.time() * 1000)), "hs_note_body": self.note_html(lead, facts)}
        note_id = (previous or {}).get("hubspot_note_id")
        if note_id:
            r = self.client.patch(f"{self.BASE}/crm/v3/objects/notes/{note_id}", json={"properties": props})
            if r.status_code == 404:
                note_id = None
            else:
                r.raise_for_status()
        if not note_id:
            r = self.client.post(f"{self.BASE}/crm/v3/objects/notes", json={"properties": props, "associations": [
                {"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                                "associationTypeId": self.NOTE_TO_COMPANY}]}]})
            r.raise_for_status()
            note_id = r.json()["id"]
        return {"hubspot_company_id": cid, "hubspot_note_id": note_id}


def sync_lead(settings: Settings, conn, lead_id: int) -> dict:
    lead, facts = get_lead(conn, lead_id), facts_for(conn, lead_id)
    previous = lead.get("sync_status") or {}
    status: dict = {k: v for k, v in previous.items() if k.startswith("hubspot_")}
    try:
        export_csv(settings, conn)
        status["csv"] = "ok"
    except OSError as exc:
        status["csv"] = f"error: {exc}"
    if settings.google_service_account_file and settings.google_sheet_id:
        try:
            GoogleSheetsSink(settings).upsert(lead_row(lead, facts))
            status["google_sheets"] = "ok"
        except Exception as exc:  # never fail the pipeline on a sink
            status["google_sheets"] = f"error: {type(exc).__name__}: {str(exc)[:150]}"
    else:
        status["google_sheets"] = "not configured"
    if settings.hubspot_token:
        try:
            status.update(HubSpotSink(settings).upsert(lead, facts, previous))
            status["hubspot"] = "ok"
        except Exception as exc:
            status["hubspot"] = f"error: {type(exc).__name__}: {str(exc)[:150]}"
    else:
        status["hubspot"] = "not configured"
    return status
