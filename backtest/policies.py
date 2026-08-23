"""
Two named recovery policies, replayed offline against the same synthetic
batch so their outcomes are directly comparable. This is what produces the
"measured trade-offs, not just a working demo" evidence for the panel.

- AGGRESSIVE: retries fast and escalates to WhatsApp quickly, ignoring the
  cost ladder. Maximizes contact volume/gross recovery, at higher cost.
- COST_AWARE_LADDER: Vasuli's actual default policy (rules.channel_selector)
  -- cheapest-channel-first, respects cooldowns strictly.

Both policies still pass through the compliance rules (AFA threshold,
max attempts) unconditionally -- a policy can change *how eager* recovery
is, never whether a hard compliance rule is honoured.
"""

from datetime import datetime
from app.models import (
    RevenueEvent, Diagnosis, Decision, InterventionChannel, RootCause,
    CHANNEL_COST_INR,
)
from app.rules.compliance import run_compliance_checks
from app.rules.caps import check_max_attempts


def cost_aware_ladder_decide(event: RevenueEvent, diagnosis: Diagnosis) -> Decision:
    from app.rules.channel_selector import decide
    return decide(event, diagnosis)


def aggressive_decide(event: RevenueEvent, diagnosis: Diagnosis) -> Decision:
    compliance_checks = run_compliance_checks(event)
    max_attempts_check = check_max_attempts(event)
    all_checks = compliance_checks + [max_attempts_check]

    afa_check = next(c for c in compliance_checks if c.rule_name == "afa_threshold")

    if not max_attempts_check.passed:
        return Decision(
            event_id=event.event_id, diagnosis=diagnosis, rule_checks=all_checks,
            approved=False, channel=InterventionChannel.NONE, estimated_cost_inr=0.0,
            reason="Max attempts exhausted.", decided_at=datetime.utcnow(),
        )

    if not afa_check.passed:
        channel = InterventionChannel.HUMAN_ESCALATION
    else:
        # Aggressive: skip the cheap-first ladder, go straight to WhatsApp
        # (ignores the pre-debit cooldown rule deliberately, to illustrate
        # the trade-off -- this is intentionally the "worse" policy).
        channel = InterventionChannel.WHATSAPP if diagnosis.root_cause != RootCause.INSUFFICIENT_BALANCE \
            else InterventionChannel.AUTO_RETRY

    return Decision(
        event_id=event.event_id, diagnosis=diagnosis, rule_checks=all_checks,
        approved=True, channel=channel, estimated_cost_inr=CHANNEL_COST_INR[channel],
        reason="Aggressive policy: skips cost ladder, contacts immediately.",
        decided_at=datetime.utcnow(),
    )


POLICIES = {
    "cost_aware_ladder": cost_aware_ladder_decide,
    "aggressive": aggressive_decide,
}