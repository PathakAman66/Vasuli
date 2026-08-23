"""
Minimal SQLite persistence layer. Deliberately not an ORM -- for a project
this size, raw SQL keeps the audit trail's schema honest and inspectable
(you can literally `sqlite3 vasuli.db` and read it during the panel demo).
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("DATABASE_PATH", "./vasuli.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    loss_type TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    amount_inr REAL NOT NULL,
    gateway_error_text TEXT,
    attempt_count INTEGER DEFAULT 0,
    typical_credit_day_of_month INTEGER,
    created_at TEXT NOT NULL,
    last_attempt_at TEXT,
    resolved INTEGER DEFAULT 0,
    recovered_amount_inr REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    payload TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    event_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    success INTEGER NOT NULL,
    recovered_amount_inr REAL NOT NULL,
    cost_inr REAL NOT NULL,
    note TEXT,
    executed_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def reset_db():
    """Wipe and recreate -- used before a fresh batch run/demo."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def insert_event(event: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO events
            (event_id, loss_type, customer_id, amount_inr, gateway_error_text,
             attempt_count, typical_credit_day_of_month, created_at,
             last_attempt_at, resolved, recovered_amount_inr)
            VALUES (:event_id, :loss_type, :customer_id, :amount_inr, :gateway_error_text,
             :attempt_count, :typical_credit_day_of_month, :created_at,
             :last_attempt_at, :resolved, :recovered_amount_inr)""",
            event,
        )


def update_event_after_attempt(event_id: str, attempt_count: int, last_attempt_at: str,
                                resolved: bool, recovered_amount_inr: float):
    with get_conn() as conn:
        conn.execute(
            """UPDATE events SET attempt_count = ?, last_attempt_at = ?,
               resolved = ?, recovered_amount_inr = ? WHERE event_id = ?""",
            (attempt_count, last_attempt_at, int(resolved), recovered_amount_inr, event_id),
        )


def write_audit(event_id: str, stage: str, payload: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (event_id, stage, payload, timestamp) VALUES (?, ?, ?, ?)",
            (event_id, stage, json.dumps(payload, default=str), datetime.utcnow().isoformat()),
        )


def write_outcome(outcome: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO outcomes (event_id, channel, success, recovered_amount_inr,
               cost_inr, note, executed_at) VALUES
               (:event_id, :channel, :success, :recovered_amount_inr, :cost_inr, :note, :executed_at)""",
            outcome,
        )


def fetch_all_events() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


def fetch_audit_for_event(event_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE event_id = ? ORDER BY id", (event_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_all_audit() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def fetch_all_outcomes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM outcomes ORDER BY executed_at").fetchall()
        return [dict(r) for r in rows]