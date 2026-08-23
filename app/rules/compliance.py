"""
Compliance rules, modeled from PUBLIC RBI/NPCI reporting on the e-mandate /
UPI Autopay framework (Additional Factor of Authentication threshold and the
pre-debit notification requirement). These are illustrative, plain-language
approximations of publicly reported rules for demo purposes -- NOT a legal
compliance product, and that distinction should be stated plainly if asked.

Two rules encoded here on purpose (kept small and auditable rather than
broad, so each one can be explained in one sentence in the panel interview):

1. AFA_THRESHOLD: recurring debits above Rs 15,000 are reported to require
   full Additional Factor of Authentication (e.g. OTP) rather than a silent
   auto-retry. Vasuli will not blind-retry above this amount -- it always
   routes those to human escalation instead.

2. PRE_DEBIT_ALERT_WINDOW: e-mandate rules require advance notice before a
   retry debit. Vasuli enforces a minimum cooldown between attempts so a
   retry is never fired without that notice window having elapsed.
"""

from datetime import datetime, timedelta
from app.models import RevenueEvent, RuleCheck

AFA_THRESHOLD_INR = 15_000.0
PRE_DEBIT_ALERT_HOURS = 24


def check_afa_threshold(event: RevenueEvent) -> RuleCheck:
    if event.amount_inr > AFA_THRESHOLD_INR:
        return RuleCheck(
            rule_name="afa_threshold",
            passed=False,
            detail=(
                f"Amount Rs {event.amount_inr:,.2f} exceeds Rs {AFA_THRESHOLD_INR:,.0f} "
                "AFA threshold -- silent auto-retry not permitted, must route to "
                "human escalation / fresh authentication."
            ),
        )
    return RuleCheck(
        rule_name="afa_threshold",
        passed=True,
        detail=f"Amount Rs {event.amount_inr:,.2f} is within silent-retry threshold.",
    )


def check_pre_debit_alert_window(event: RevenueEvent) -> RuleCheck:
    if event.last_attempt_at is None:
        return RuleCheck(
            rule_name="pre_debit_alert_window",
            passed=True,
            detail="First attempt -- no prior debit, no cooldown required.",
        )
    elapsed = datetime.utcnow() - event.last_attempt_at
    required = timedelta(hours=PRE_DEBIT_ALERT_HOURS)
    if elapsed < required:
        remaining = required - elapsed
        return RuleCheck(
            rule_name="pre_debit_alert_window",
            passed=False,
            detail=(
                f"Only {elapsed.total_seconds()/3600:.1f}h since last attempt; "
                f"{PRE_DEBIT_ALERT_HOURS}h pre-debit notice window not yet elapsed "
                f"({remaining.total_seconds()/3600:.1f}h remaining)."
            ),
        )
    return RuleCheck(
        rule_name="pre_debit_alert_window",
        passed=True,
        detail=f"{elapsed.total_seconds()/3600:.1f}h since last attempt, notice window satisfied.",
    )


def run_compliance_checks(event: RevenueEvent) -> list[RuleCheck]:
    return [check_afa_threshold(event), check_pre_debit_alert_window(event)]