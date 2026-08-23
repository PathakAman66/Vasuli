"""
Thin audit-trail wrapper. Every pipeline stage calls one of these so the
dashboard's explainability drill-down can reconstruct, for any event, the
full chain: detected -> diagnosed -> rule_checked -> decided -> executed.
Nothing about this module is clever on purpose -- an audit trail's only job
is to be complete and boring.
"""

from app import db


def log_detected(event_id: str, payload: dict):
    db.write_audit(event_id, "detected", payload)


def log_diagnosed(event_id: str, diagnosis) -> None:
    db.write_audit(event_id, "diagnosed", diagnosis.model_dump())


def log_decided(event_id: str, decision) -> None:
    db.write_audit(event_id, "decided", decision.model_dump())


def log_executed(event_id: str, outcome) -> None:
    db.write_audit(event_id, "executed", outcome.model_dump())