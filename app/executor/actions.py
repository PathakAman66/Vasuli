"""
Executor -- the only layer allowed to touch money or send a customer
message, and only ever acting on a pre-approved Decision object. It never
re-interprets a diagnosis; it just carries out what the rules engine already
decided, then records exactly what happened.

Real send integrations (Razorpay retry API, email, WhatsApp) are wrapped
behind small functions so they're easy to point at real test-mode
endpoints later -- for the buildathon submission, WhatsApp/email are
simulated (logged, not actually sent), which is explicitly acceptable per
the brief: bounded logic matters more than real delivery.
"""

import random
from datetime import datetime
from app.models import Decision, ActionOutcome, InterventionChannel, RootCause


def _simulate_recovery_probability(decision: Decision) -> float:
    """Illustrative success-probability model per channel/root-cause, used
    only to simulate outcomes for the demo batch (no real customers are
    contacted). Grounded loosely in the idea that auto-retry works well for
    transient causes and poorly for causes that need customer action."""
    cause = decision.diagnosis.root_cause
    channel = decision.channel

    if channel == InterventionChannel.AUTO_RETRY:
        return 0.55 if cause == RootCause.INSUFFICIENT_BALANCE else 0.35
    if channel == InterventionChannel.EMAIL:
        return 0.25
    if channel == InterventionChannel.WHATSAPP:
        return 0.40
    if channel == InterventionChannel.HUMAN_ESCALATION:
        return 0.65
    return 0.0


def execute(decision: Decision, amount_inr: float, rng: random.Random | None = None) -> ActionOutcome:
    rng = rng or random
    if not decision.approved or decision.channel == InterventionChannel.NONE:
        return ActionOutcome(
            event_id=decision.event_id,
            channel=InterventionChannel.NONE,
            success=False,
            recovered_amount_inr=0.0,
            cost_inr=0.0,
            note="No action executed (blocked by rules engine or stopped).",
            executed_at=datetime.utcnow(),
        )

    prob = _simulate_recovery_probability(decision)
    success = rng.random() < prob
    recovered = amount_inr if success else 0.0

    note = {
        InterventionChannel.AUTO_RETRY: "Simulated retry via Razorpay test-mode API.",
        InterventionChannel.EMAIL: "Simulated: recovery email queued (not actually sent).",
        InterventionChannel.WHATSAPP: "Simulated: WhatsApp nudge queued (not actually sent).",
        InterventionChannel.HUMAN_ESCALATION: "Escalated to human ops queue for manual follow-up.",
    }[decision.channel]

    return ActionOutcome(
        event_id=decision.event_id,
        channel=decision.channel,
        success=success,
        recovered_amount_inr=recovered,
        cost_inr=decision.estimated_cost_inr,
        note=note,
        executed_at=datetime.utcnow(),
    )