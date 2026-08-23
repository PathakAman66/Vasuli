"""
These tests prove the rules engine is deterministic and correctly bounded
-- notice none of them call the LLM or need an API key. That's the point:
the safety-critical logic is testable in complete isolation.
"""

from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import RevenueEvent, LossType, Diagnosis, RootCause, InterventionChannel
from app.rules.channel_selector import decide
from app.rules.compliance import AFA_THRESHOLD_INR, PRE_DEBIT_ALERT_HOURS


def make_event(**overrides) -> RevenueEvent:
    defaults = dict(
        event_id="evt_test",
        loss_type=LossType.FAILED_MANDATE,
        customer_id="cust_test",
        amount_inr=999.0,
        gateway_error_text="Insufficient Balance",
        attempt_count=0,
        typical_credit_day_of_month=1,
        created_at=datetime.utcnow(),
        last_attempt_at=None,
        resolved=False,
        recovered_amount_inr=0.0,
    )
    defaults.update(overrides)
    return RevenueEvent(**defaults)


def make_diagnosis(**overrides) -> Diagnosis:
    defaults = dict(
        event_id="evt_test",
        root_cause=RootCause.INSUFFICIENT_BALANCE,
        confidence=0.8,
        reasoning="test",
    )
    defaults.update(overrides)
    return Diagnosis(**defaults)


def test_above_afa_threshold_always_escalates_to_human():
    """No matter how confident the LLM diagnosis is, amounts above the AFA
    threshold must never be silently auto-retried."""
    event = make_event(amount_inr=AFA_THRESHOLD_INR + 1000)
    diagnosis = make_diagnosis(confidence=0.99)
    decision = decide(event, diagnosis)
    assert decision.approved is True
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION


def test_max_attempts_stops_automation():
    event = make_event(attempt_count=3)
    diagnosis = make_diagnosis()
    decision = decide(event, diagnosis)
    assert decision.approved is False
    assert decision.channel == InterventionChannel.NONE


def test_cooldown_blocks_immediate_retry():
    event = make_event(last_attempt_at=datetime.utcnow() - timedelta(hours=1))
    diagnosis = make_diagnosis()
    decision = decide(event, diagnosis)
    assert decision.approved is False
    assert "pre_debit" in decision.reason.lower() or "notice window" in decision.reason.lower()


def test_cooldown_elapsed_allows_retry():
    event = make_event(
        last_attempt_at=datetime.utcnow() - timedelta(hours=PRE_DEBIT_ALERT_HOURS + 1)
    )
    diagnosis = make_diagnosis()
    decision = decide(event, diagnosis)
    assert decision.approved is True
    assert decision.channel != InterventionChannel.NONE


def test_low_confidence_escalates_instead_of_automating():
    event = make_event()
    diagnosis = make_diagnosis(confidence=0.2)
    decision = decide(event, diagnosis)
    assert decision.approved is True
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION


def test_insufficient_balance_routes_to_cheap_auto_retry():
    event = make_event()
    diagnosis = make_diagnosis(root_cause=RootCause.INSUFFICIENT_BALANCE, confidence=0.9)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.AUTO_RETRY
    assert decision.estimated_cost_inr == 0.0


def test_card_declined_first_attempt_uses_email_not_whatsapp():
    """Cheapest-appropriate-channel-first: don't jump straight to a paid
    channel on the first attempt."""
    event = make_event(attempt_count=0, gateway_error_text="Card declined")
    diagnosis = make_diagnosis(root_cause=RootCause.CARD_DECLINED, confidence=0.9)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.EMAIL


def test_every_decision_carries_full_rule_checks_for_audit():
    event = make_event()
    diagnosis = make_diagnosis()
    decision = decide(event, diagnosis)
    rule_names = {c.rule_name for c in decision.rule_checks}
    assert {"afa_threshold", "pre_debit_alert_window", "max_attempts", "confidence_floor"} <= rule_names