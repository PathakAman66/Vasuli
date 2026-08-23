"""
Generates a synthetic batch of at-risk revenue events for Vasuli to process.

Why synthetic and not scraped/real: the buildathon brief asks for a 50+
record batch of synthetic data so the match/recovery rate is reproducible
and doesn't depend on live customer data. Realism comes from two research
grounded choices baked in here:

1. The single biggest real-world cause of UPI Autopay failure is
   insufficient balance at debit time (RBI-flagged, ~20M+ mandates/month
   revoked for this reason) -- so INSUFFICIENT_BALANCE is deliberately the
   most common root cause in this dataset, not an even split.
2. Each synthetic customer gets a "typical_credit_day_of_month" (a stand-in
   for salary date) so the rules engine can retry near that window instead
   of a blind fixed interval -- this is what the salary-cycle-aware retry
   feature reasons over downstream.

Run: python data/generate_synthetic.py  -> writes data/synthetic_batch.json
"""

import json
import random
import uuid
from datetime import datetime, timedelta

random.seed(42)  # reproducible batch -- important for an "honest metrics" demo

GATEWAY_ERRORS = {
    "insufficient_balance": [
        "Transaction declined: insufficient funds in account",
        "NPCI Error: Insufficient Balance (Code: 51)",
        "UPI collect request declined by PSP - low balance",
    ],
    "card_declined": [
        "Card declined by issuing bank (Code: 05 - Do not honour)",
        "Issuer declined the transaction. Please contact your bank.",
    ],
    "upi_timeout": [
        "UPI transaction timed out - no response from PSP",
        "Request timeout: NPCI switch did not respond within SLA",
    ],
    "mandate_revoked": [
        "e-Mandate has been revoked/cancelled by the customer",
        "AutoPay mandate is no longer active",
    ],
    "gateway_error": [
        "Gateway internal error (Code: GTW-500)",
        "Unexpected error from acquiring bank",
    ],
}

# Weighted so insufficient_balance dominates, matching the real-world pattern.
ROOT_CAUSE_WEIGHTS = {
    "insufficient_balance": 0.42,
    "card_declined": 0.20,
    "upi_timeout": 0.13,
    "mandate_revoked": 0.10,
    "gateway_error": 0.10,
    "user_abandoned": 0.05,  # only relevant for checkout_abandoned events
}


def weighted_choice(weights: dict) -> str:
    keys, probs = zip(*weights.items())
    return random.choices(keys, weights=probs, k=1)[0]


def make_event(idx: int, loss_type: str) -> dict:
    customer_id = f"cust_{idx:04d}"
    amount = round(random.choice([199, 299, 499, 999, 1499, 2499, 4999, 12999, 18999]) * 1.0, 2)

    if loss_type == "checkout_abandoned":
        cause = "user_abandoned" if random.random() < 0.55 else weighted_choice(
            {k: v for k, v in ROOT_CAUSE_WEIGHTS.items() if k != "mandate_revoked"}
        )
        error_text = "" if cause == "user_abandoned" else random.choice(GATEWAY_ERRORS.get(cause, ["Unknown error"]))
    else:  # failed_mandate
        cause = weighted_choice(
            {k: v for k, v in ROOT_CAUSE_WEIGHTS.items() if k != "user_abandoned"}
        )
        error_text = random.choice(GATEWAY_ERRORS.get(cause, ["Unknown error"]))

    created_at = datetime.utcnow() - timedelta(days=random.randint(0, 10), hours=random.randint(0, 23))

    return {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "loss_type": loss_type,
        "customer_id": customer_id,
        "amount_inr": amount,
        "gateway_error_text": error_text,
        "attempt_count": 0,
        "typical_credit_day_of_month": random.choice([1, 1, 1, 5, 5, 10, 28]),  # most cluster on 1st (salary date)
        "created_at": created_at.isoformat(),
        "last_attempt_at": None,
        "resolved": False,
        "recovered_amount_inr": 0.0,
        # ground-truth label kept only for our own evaluation, never shown to the LLM
        "_true_root_cause": cause,
    }


def generate_batch(n_mandate: int = 35, n_checkout: int = 20) -> list[dict]:
    events = []
    idx = 1
    for _ in range(n_mandate):
        events.append(make_event(idx, "failed_mandate"))
        idx += 1
    for _ in range(n_checkout):
        events.append(make_event(idx, "checkout_abandoned"))
        idx += 1
    random.shuffle(events)
    return events


if __name__ == "__main__":
    batch = generate_batch()
    out_path = __file__.replace("generate_synthetic.py", "synthetic_batch.json")
    with open(out_path, "w") as f:
        json.dump(batch, f, indent=2)
    print(f"Generated {len(batch)} events -> {out_path}")
    print(f"  failed_mandate: {sum(1 for e in batch if e['loss_type']=='failed_mandate')}")
    print(f"  checkout_abandoned: {sum(1 for e in batch if e['loss_type']=='checkout_abandoned')}")
    total_value = sum(e["amount_inr"] for e in batch)
    print(f"  total at-risk value: Rs {total_value:,.2f}")