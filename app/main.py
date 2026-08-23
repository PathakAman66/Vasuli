"""
Vasuli -- FastAPI entrypoint.

Endpoints:
  POST /api/run-batch        -> resets DB, loads data/synthetic_batch.json,
                                 runs the full pipeline for every event
  GET  /api/summary          -> aggregate numbers for the dashboard header
  GET  /api/events           -> all events with their latest status
  GET  /api/audit/{event_id} -> full audit trail for one event (explainability)
  GET  /api/exceptions       -> events that couldn't be auto-resolved
  GET  /health                -> liveness check
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db
from app.detection.detector import load_events_from_batch, flag_at_risk
from app.diagnosis.llm_parser import diagnose
from app.rules.channel_selector import decide
from app.executor.actions import execute
from app.audit import logger as audit

BATCH_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_batch.json"

app = FastAPI(title="Vasuli - Revenue Recovery Agent")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


def _run_event_through_pipeline(event) -> None:
    audit.log_detected(event.event_id, event.model_dump())

    diagnosis = diagnose(event)
    audit.log_diagnosed(event.event_id, diagnosis)

    decision = decide(event, diagnosis)
    audit.log_decided(event.event_id, decision)

    outcome = execute(decision, event.amount_inr)
    audit.log_executed(event.event_id, outcome)

    new_attempt_count = event.attempt_count + (1 if decision.channel.value != "none" else 0)
    resolved = outcome.success
    recovered = event.recovered_amount_inr + outcome.recovered_amount_inr

    db.update_event_after_attempt(
        event.event_id,
        attempt_count=new_attempt_count,
        last_attempt_at=outcome.executed_at.isoformat(),
        resolved=resolved,
        recovered_amount_inr=recovered,
    )
    db.write_outcome(outcome.model_dump())


@app.post("/api/run-batch")
def run_batch():
    if not BATCH_PATH.exists():
        raise HTTPException(404, f"No synthetic batch found at {BATCH_PATH}. Run data/generate_synthetic.py first.")

    db.reset_db()
    raw_events = json.loads(BATCH_PATH.read_text())
    for e in raw_events:
        e.pop("_true_root_cause", None)
        db.insert_event(e)

    events = load_events_from_batch(raw_events)
    at_risk = flag_at_risk(events)

    for event in at_risk:
        _run_event_through_pipeline(event)

    return summary()


@app.get("/api/summary")
def summary():
    events = db.fetch_all_events()
    outcomes = db.fetch_all_outcomes()

    total_flagged = sum(e["amount_inr"] for e in events)
    total_recovered = sum(e["recovered_amount_inr"] for e in events)
    total_cost = sum(o["cost_inr"] for o in outcomes)
    net_recovered = total_recovered - total_cost

    by_channel = {}
    for o in outcomes:
        ch = o["channel"]
        by_channel.setdefault(ch, {"attempts": 0, "successes": 0, "cost_inr": 0.0})
        by_channel[ch]["attempts"] += 1
        by_channel[ch]["successes"] += int(o["success"])
        by_channel[ch]["cost_inr"] += o["cost_inr"]

    resolved_count = sum(1 for e in events if e["resolved"])
    exception_count = sum(
        1 for e in events if not e["resolved"] and e["attempt_count"] >= 3
    )

    return {
        "total_events": len(events),
        "total_flagged_inr": round(total_flagged, 2),
        "total_gross_recovered_inr": round(total_recovered, 2),
        "total_outreach_cost_inr": round(total_cost, 2),
        "total_net_recovered_inr": round(net_recovered, 2),
        "recovery_rate_pct": round(100 * resolved_count / len(events), 1) if events else 0,
        "resolved_count": resolved_count,
        "exception_count": exception_count,
        "by_channel": by_channel,
    }


@app.get("/api/events")
def list_events():
    return db.fetch_all_events()


@app.get("/api/audit/{event_id}")
def event_audit(event_id: str):
    records = db.fetch_audit_for_event(event_id)
    if not records:
        raise HTTPException(404, "No audit records for this event_id")
    for r in records:
        r["payload"] = json.loads(r["payload"])
    return records


@app.get("/api/exceptions")
def exceptions():
    events = db.fetch_all_events()
    return [
        e for e in events
        if not e["resolved"] and e["attempt_count"] >= 3
    ]


# Serve the dashboard static files at /
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")