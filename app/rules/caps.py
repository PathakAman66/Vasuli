"""
Bounded-behaviour caps -- the "stopping rules" the buildathon brief asks for
explicitly. These exist so the agent cannot retry or contact a customer
indefinitely, regardless of what the LLM diagnosis suggests.
"""

from app.models import RevenueEvent, RuleCheck

MAX_ATTEMPTS = 3
MIN_CONFIDENCE_FOR_AUTO_ACTION = 0.5


def check_max_attempts(event: RevenueEvent) -> RuleCheck:
    if event.attempt_count >= MAX_ATTEMPTS:
        return RuleCheck(
            rule_name="max_attempts",
            passed=False,
            detail=(
                f"{event.attempt_count}/{MAX_ATTEMPTS} attempts already made -- "
                "stopping automated recovery, moving to exception list."
            ),
        )
    return RuleCheck(
        rule_name="max_attempts",
        passed=True,
        detail=f"{event.attempt_count}/{MAX_ATTEMPTS} attempts used.",
    )


def check_confidence_floor(confidence: float) -> RuleCheck:
    if confidence < MIN_CONFIDENCE_FOR_AUTO_ACTION:
        return RuleCheck(
            rule_name="confidence_floor",
            passed=False,
            detail=(
                f"Diagnosis confidence {confidence:.2f} below "
                f"{MIN_CONFIDENCE_FOR_AUTO_ACTION} floor -- too uncertain for an "
                "automated channel, routing to human escalation instead."
            ),
        )
    return RuleCheck(
        rule_name="confidence_floor",
        passed=True,
        detail=f"Diagnosis confidence {confidence:.2f} meets the floor for automated action.",
    )


def run_cap_checks(event: RevenueEvent, confidence: float) -> list[RuleCheck]:
    return [check_max_attempts(event), check_confidence_floor(confidence)]