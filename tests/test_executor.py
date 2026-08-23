import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Decision, Diagnosis, RootCause, InterventionChannel
from app.executor.actions import execute


def make_decision(**overrides) -> Decision:
    diagnosis = Diagnosis(
        event_id="evt_test", root_cause=RootCause.INSUFFICIENT_BALANCE,
        confidence=0.8, reasoning="test",
    )
    defaults = dict(
        event_id="evt_test", diagnosis=diagnosis, rule_checks=[],
        approved=True, channel=InterventionChannel.AUTO_RETRY,
        estimated_cost_inr=0.0, reason="test", decided_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return Decision(**defaults)


def test_unapproved_decision_never_executes():
    decision = make_decision(approved=False, channel=InterventionChannel.NONE)
    outcome = execute(decision, amount_inr=999.0, rng=random.Random(1))
    assert outcome.success is False
    assert outcome.recovered_amount_inr == 0.0
    assert outcome.channel == InterventionChannel.NONE


def test_approved_decision_can_recover_full_amount_on_success():
    decision = make_decision(approved=True, channel=InterventionChannel.AUTO_RETRY)
    rng = random.Random(0)  # deterministic seed picked to land on a success
    outcome = execute(decision, amount_inr=500.0, rng=rng)
    if outcome.success:
        assert outcome.recovered_amount_inr == 500.0
    else:
        assert outcome.recovered_amount_inr == 0.0


def test_outcome_never_recovers_more_than_the_event_amount():
    decision = make_decision()
    for seed in range(20):
        outcome = execute(decision, amount_inr=1234.0, rng=random.Random(seed))
        assert outcome.recovered_amount_inr in (0.0, 1234.0)