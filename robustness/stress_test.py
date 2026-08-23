"""
Adversarial stress test for Vasuli's rules engine.

This does NOT test the happy path -- tests/test_rules.py already does that.
This file exists to answer one question a panel is very likely to ask:
"what happens when something tries to break this?"

Each case below is a deliberate attempt to make the rules engine do
something unsafe: approve a silent high-value retry, ignore the cooldown,
trust an overconfident-but-wrong diagnosis, or crash on malformed input.
The report at the bottom is generated fresh every run -- nothing here is
cherry-picked, and a failing case would show up as FAILED in the report,
not get quietly dropped.

Run: python robustness/stress_test.py
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import RevenueEvent, LossType, Diagnosis, RootCause, InterventionChannel
from app.rules.channel_selector import decide

REPORT_PATH = Path(__file__).resolve().parent / "robustness_report.md"


def make_event(**overrides) -> RevenueEvent:
    defaults = dict(
        event_id="evt_adversarial",
        loss_type=LossType.FAILED_MANDATE,
        customer_id="cust_adversarial",
        amount_inr=999.0,
        gateway_error_text="test",
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
        event_id="evt_adversarial", root_cause=RootCause.INSUFFICIENT_BALANCE,
        confidence=0.8, reasoning="adversarial test",
    )
    defaults.update(overrides)
    return Diagnosis(**defaults)


CASES = []


def case(name, description):
    def wrapper(fn):
        CASES.append((name, description, fn))
        return fn
    return wrapper


@case(
    "Boundary amount attack",
    "Amount is exactly Rs 1 above the AFA threshold, with a maximally confident diagnosis. "
    "A naive system might treat 'just barely over' as close enough to auto-retry.",
)
def boundary_amount_attack():
    event = make_event(amount_inr=15_000.01)
    diagnosis = make_diagnosis(confidence=0.99)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION, (
        f"Expected human escalation above AFA threshold, got {decision.channel}"
    )
    return "Blocked silent retry and routed to human escalation, exactly at the boundary."


@case(
    "Overconfident wrong diagnosis",
    "Diagnosis claims 99% confidence but the underlying event amount alone should still "
    "trigger compliance escalation regardless of how sure the LLM says it is.",
)
def overconfident_wrong_diagnosis():
    event = make_event(amount_inr=50_000.0)
    diagnosis = make_diagnosis(confidence=0.99, root_cause=RootCause.INSUFFICIENT_BALANCE)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION, (
        "High confidence must not override the AFA threshold."
    )
    return "Confidence score was ignored where it should be -- the amount-based rule still won."


@case(
    "Replay / repeated-attack attempt",
    "Simulates calling decide() again on the same event without any elapsed time, as if "
    "something tried to fire multiple retries back-to-back to bypass the notice window.",
)
def replay_attack():
    event = make_event(last_attempt_at=datetime.utcnow())  # just attempted, right now
    diagnosis = make_diagnosis()
    decision = decide(event, diagnosis)
    assert decision.approved is False, "A same-instant repeat call must be blocked by the cooldown."
    assert decision.channel == InterventionChannel.NONE
    return "Cooldown check blocked the immediate repeat call -- no double-fire possible."


@case(
    "Max-attempts exhaustion with high confidence",
    "Even a highly confident, cheap-to-fix diagnosis must stop once attempts are exhausted -- "
    "confidence should never be able to buy extra retries.",
)
def max_attempts_cannot_be_bought():
    event = make_event(attempt_count=3)
    diagnosis = make_diagnosis(confidence=1.0)
    decision = decide(event, diagnosis)
    assert decision.approved is False
    assert decision.channel == InterventionChannel.NONE
    return "Attempt cap held even at maximum possible confidence -- stopped as designed."


@case(
    "Zero-confidence diagnosis",
    "Diagnosis confidence is 0.0 -- the weakest possible signal an LLM (or heuristic "
    "fallback) can produce. The system must not silently guess a channel.",
)
def zero_confidence_diagnosis():
    event = make_event()
    diagnosis = make_diagnosis(confidence=0.0)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION
    return "Zero-confidence input was routed to a human rather than automated."


@case(
    "Empty gateway error text",
    "gateway_error_text is an empty string, as would happen for a pure checkout "
    "abandonment with no gateway involved at all. The diagnosis layer (not tested here, "
    "the rules layer) must still receive *something* usable.",
)
def empty_error_text_does_not_crash_rules():
    event = make_event(gateway_error_text="", loss_type=LossType.CHECKOUT_ABANDONED)
    diagnosis = make_diagnosis(root_cause=RootCause.USER_ABANDONED, confidence=0.7)
    decision = decide(event, diagnosis)  # should not raise
    assert decision is not None
    return "Empty error text produced a valid decision object, no exception raised."


@case(
    "Extreme amount (Rs 10,00,000 mandate)",
    "An unusually large recurring amount, to check the AFA threshold generalizes far "
    "beyond its Rs 15,000 boundary rather than being a narrow special case.",
)
def extreme_amount():
    event = make_event(amount_inr=1_000_000.0)
    diagnosis = make_diagnosis(confidence=0.95)
    decision = decide(event, diagnosis)
    assert decision.channel == InterventionChannel.HUMAN_ESCALATION
    return "Extreme amount still correctly routed to human escalation."


def main():
    results = []
    for name, description, fn in CASES:
        try:
            outcome = fn()
            results.append((name, description, True, outcome))
        except AssertionError as e:
            results.append((name, description, False, str(e)))
        except Exception as e:  # noqa: BLE001 - a crash IS a failure worth reporting
            results.append((name, description, False, f"Unhandled exception: {e!r}"))

    passed = sum(1 for r in results if r[2])
    total = len(results)

    lines = [
        "# Vasuli Robustness Report\n",
        f"{passed}/{total} adversarial cases held.\n",
        "Each case below is a deliberate attempt to make the rules engine do something "
        "unsafe -- approve a silent high-value retry, ignore the cooldown, trust an "
        "overconfident wrong diagnosis, or crash on malformed input.\n",
    ]
    for name, description, ok, detail in results:
        status = "HELD" if ok else "FAILED"
        lines.append(f"## [{status}] {name}\n")
        lines.append(f"**Attack:** {description}\n")
        lines.append(f"**Result:** {detail}\n")

    REPORT_PATH.write_text("\n".join(lines))
    print(f"Robustness test complete: {passed}/{total} held -> {REPORT_PATH}")
    for name, _, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")

    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()