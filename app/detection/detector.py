"""
Detection layer. Deliberately dumb and deterministic: an event is "at risk"
if it exists in the batch and isn't resolved yet. The interesting work
(why did it fail, what should we do) happens downstream in diagnosis/rules.
Keeping detection this simple means it never needs an LLM call and never
needs a test-set precision/recall claim -- that rigor is reserved for
where it matters (Risk Manager track), not faked here.
"""

from app.models import RevenueEvent, LossType
from datetime import datetime


def load_events_from_batch(raw_events: list[dict]) -> list[RevenueEvent]:
    events = []
    for e in raw_events:
        events.append(
            RevenueEvent(
                event_id=e["event_id"],
                loss_type=LossType(e["loss_type"]),
                customer_id=e["customer_id"],
                amount_inr=e["amount_inr"],
                gateway_error_text=e.get("gateway_error_text", ""),
                attempt_count=e.get("attempt_count", 0),
                typical_credit_day_of_month=e.get("typical_credit_day_of_month"),
                created_at=datetime.fromisoformat(e["created_at"]),
                last_attempt_at=(
                    datetime.fromisoformat(e["last_attempt_at"])
                    if e.get("last_attempt_at") else None
                ),
                resolved=e.get("resolved", False),
                recovered_amount_inr=e.get("recovered_amount_inr", 0.0),
            )
        )
    return events


def flag_at_risk(events: list[RevenueEvent]) -> list[RevenueEvent]:
    """Returns only events that still need attention."""
    return [e for e in events if not e.resolved]