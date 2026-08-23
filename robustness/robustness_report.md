# Vasuli Robustness Report

7/7 adversarial cases held.

Each case below is a deliberate attempt to make the rules engine do something unsafe -- approve a silent high-value retry, ignore the cooldown, trust an overconfident wrong diagnosis, or crash on malformed input.

## [HELD] Boundary amount attack

**Attack:** Amount is exactly Rs 1 above the AFA threshold, with a maximally confident diagnosis. A naive system might treat 'just barely over' as close enough to auto-retry.

**Result:** Blocked silent retry and routed to human escalation, exactly at the boundary.

## [HELD] Overconfident wrong diagnosis

**Attack:** Diagnosis claims 99% confidence but the underlying event amount alone should still trigger compliance escalation regardless of how sure the LLM says it is.

**Result:** Confidence score was ignored where it should be -- the amount-based rule still won.

## [HELD] Replay / repeated-attack attempt

**Attack:** Simulates calling decide() again on the same event without any elapsed time, as if something tried to fire multiple retries back-to-back to bypass the notice window.

**Result:** Cooldown check blocked the immediate repeat call -- no double-fire possible.

## [HELD] Max-attempts exhaustion with high confidence

**Attack:** Even a highly confident, cheap-to-fix diagnosis must stop once attempts are exhausted -- confidence should never be able to buy extra retries.

**Result:** Attempt cap held even at maximum possible confidence -- stopped as designed.

## [HELD] Zero-confidence diagnosis

**Attack:** Diagnosis confidence is 0.0 -- the weakest possible signal an LLM (or heuristic fallback) can produce. The system must not silently guess a channel.

**Result:** Zero-confidence input was routed to a human rather than automated.

## [HELD] Empty gateway error text

**Attack:** gateway_error_text is an empty string, as would happen for a pure checkout abandonment with no gateway involved at all. The diagnosis layer (not tested here, the rules layer) must still receive *something* usable.

**Result:** Empty error text produced a valid decision object, no exception raised.

## [HELD] Extreme amount (Rs 10,00,000 mandate)

**Attack:** An unusually large recurring amount, to check the AFA threshold generalizes far beyond its Rs 15,000 boundary rather than being a narrow special case.

**Result:** Extreme amount still correctly routed to human escalation.