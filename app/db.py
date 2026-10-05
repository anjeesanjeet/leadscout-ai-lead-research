"""SQLite storage for leads, sources, verified facts and the per-step event log."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company         TEXT NOT NULL,
    website         TEXT NOT NULL,
    domain          TEXT NOT NULL UNIQUE,
    segment_hint    TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    segment         TEXT,
    profile         TEXT,
    score           REAL,
    score_breakdown TEXT,
    draft_subject   TEXT,
    draft_body      TEXT,
    draft_checks    TEXT,
    draft_attempts  INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    duration_ms     REAL NOT NULL DEFAULT 0,
    error           TEXT,
    sync_status     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    decided_at      TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id   INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    idx       INTEGER NOT NULL,
    kind      TEXT NOT NULL,
    url       TEXT NOT NULL,
    title     TEXT,
    text      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    fact_id     TEXT NOT NULL,
    claim       TEXT NOT NULL,
    quote       TEXT NOT NULL,
    source_idx  INTEGER,
    source_url  TEXT,
    verified    INTEGER NOT NULL DEFAULT 0,
    match_score REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    step        TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    duration_ms REAL NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sources_lead ON sources(lead_id);
CREATE INDEX IF NOT EXISTS idx_facts_lead ON facts(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
"""

JSON_COLS = ("profile", "score_breakdown", "draft_checks", "sync_status")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path | str) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def lead_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in JSON_COLS:
        if d.get(col):
            d[col] = json.loads(d[col])
    return d


def get_lead(conn: sqlite3.Connection, lead_id: int) -> dict | None:
    return lead_to_dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())


def update_lead(conn: sqlite3.Connection, lead_id: int, **fields) -> None:
    for col in JSON_COLS:
        if col in fields and fields[col] is not None and not isinstance(fields[col], str):
            fields[col] = json.dumps(fields[col], ensure_ascii=False)
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE leads SET {cols} WHERE id = ?", (*fields.values(), lead_id))
    conn.commit()


def log_event(conn: sqlite3.Connection, lead_id: int, step: str, status: str, detail: str = "",
              duration_ms: float = 0.0, cost_usd: float = 0.0) -> None:
    conn.execute(
        "INSERT INTO events (lead_id, ts, step, status, detail, duration_ms, cost_usd) VALUES (?,?,?,?,?,?,?)",
        (lead_id, now_iso(), step, status, detail[:500], round(duration_ms, 1), round(cost_usd, 6)),
    )
    conn.commit()


def facts_for(conn: sqlite3.Connection, lead_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM facts WHERE lead_id = ? ORDER BY id", (lead_id,))]


def events_for(conn: sqlite3.Connection, lead_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM events WHERE lead_id = ? ORDER BY id", (lead_id,))]
