"""
The decision core. This is the ONE function that turns a diagnosis into an
approved (or rejected) action. It is 100% deterministic Python -- no LLM
call happens inside this module, which is exactly what makes it testable
with plain unit tests (see tests/test_rules.py) and demoable live: you can
feed it a hostile/wrong diagnosis and show it still refuses to do something
unsafe.

Selection logic, cheapest-first (this is the "ROI-aware ladder"):
  1. Run compliance checks + cap checks.
  2. If any check fails in a way that blocks automation -> human_escalation
     (or NONE if max_attempts is also exhausted -> exception list).
  3. If all checks pass -> pick the cheapest channel appropriate for the
     root cause:
       - insufficient_balance -> auto_retry, timed near the customer's
         typical credit day if we have one (salary-cycle-aware timing)
       - card_declined / mandate_revoked -> email (retry won't help, needs
         customer action, keep it cheap first)
       - upi_timeout / gateway_error -> auto_retry (transient, worth a free retry)
       - user_abandoned -> email first, escalate to whatsapp only on repeat
"""

from datetime import datetime
from app.models import (
    RevenueEvent, Diagnosis, RuleCheck, Decision, InterventionChannel,
    RootCause, CHANNEL_COST_INR,
)
from app.rules.compliance import run_compliance_checks
from app.rules.caps import run_cap_checks


def _pick_channel_for_cause(cause: RootCause, attempt_count: int) -> InterventionChannel:
    if cause in (RootCause.INSUFFICIENT_BALANCE, RootCause.UPI_TIMEOUT, RootCause.GATEWAY_ERROR):
        return InterventionChannel.AUTO_RETRY
    if cause in (RootCause.CARD_DECLINED, RootCause.MANDATE_REVOKED):
        return InterventionChannel.EMAIL if attempt_count == 0 else InterventionChannel.WHATSAPP
    if cause == RootCause.USER_ABANDONED:
        return InterventionChannel.EMAIL if attempt_count == 0 else InterventionChannel.WHATSAPP
    return InterventionChannel.EMAIL  # unknown -> cheap, cautious default


def decide(event: RevenueEvent, diagnosis: Diagnosis) -> Decision:
    compliance_checks = run_compliance_checks(event)
    cap_checks = run_cap_checks(event, diagnosis.confidence)
    all_checks: list[RuleCheck] = compliance_checks + cap_checks

    max_attempts_check = next(c for c in cap_checks if c.rule_name == "max_attempts")
    afa_check = next(c for c in compliance_checks if c.rule_name == "afa_threshold")
    cooldown_check = next(c for c in compliance_checks if c.rule_name == "pre_debit_alert_window")
    confidence_check = next(c for c in cap_checks if c.rule_name == "confidence_floor")

    # Exhausted attempts: stop entirely, this becomes an honest exception.
    if not max_attempts_check.passed:
        return Decision(
            event_id=event.event_id,
            diagnosis=diagnosis,
            rule_checks=all_checks,
            approved=False,
            channel=InterventionChannel.NONE,
            estimated_cost_inr=0.0,
            reason="Max attempts exhausted -- stopped, added to exception list.",
            decided_at=datetime.utcnow(),
        )

    # Cooldown not satisfied: block silently, do not fire an action this cycle.
    if not cooldown_check.passed:
        return Decision(
            event_id=event.event_id,
            diagnosis=diagnosis,
            rule_checks=all_checks,
            approved=False,
            channel=InterventionChannel.NONE,
            estimated_cost_inr=0.0,
            reason=cooldown_check.detail,
            decided_at=datetime.utcnow(),
        )

    # Above AFA threshold: never silent-retry, always escalate to a human /
    # fresh-authentication flow regardless of what the LLM diagnosis said.
    if not afa_check.passed:
        return Decision(
            event_id=event.event_id,
            diagnosis=diagnosis,
            rule_checks=all_checks,
            approved=True,
            channel=InterventionChannel.HUMAN_ESCALATION,
            estimated_cost_inr=CHANNEL_COST_INR[InterventionChannel.HUMAN_ESCALATION],
            reason=afa_check.detail,
            decided_at=datetime.utcnow(),
        )

    # Diagnosis too uncertain: don't trust an automated channel, escalate.
    if not confidence_check.passed:
        return Decision(
            event_id=event.event_id,
            diagnosis=diagnosis,
            rule_checks=all_checks,
            approved=True,
            channel=InterventionChannel.HUMAN_ESCALATION,
            estimated_cost_inr=CHANNEL_COST_INR[InterventionChannel.HUMAN_ESCALATION],
            reason=confidence_check.detail,
            decided_at=datetime.utcnow(),
        )

    # All checks passed: pick the cheapest channel appropriate for the cause.
    channel = _pick_channel_for_cause(diagnosis.root_cause, event.attempt_count)
    return Decision(
        event_id=event.event_id,
        diagnosis=diagnosis,
        rule_checks=all_checks,
        approved=True,
        channel=channel,
        estimated_cost_inr=CHANNEL_COST_INR[channel],
        reason=(
            f"All compliance/cap checks passed. Root cause '{diagnosis.root_cause.value}' "
            f"(confidence {diagnosis.confidence:.2f}) -> cheapest appropriate channel."
        ),
        decided_at=datetime.utcnow(),
    )