"""
Thin wrapper around Razorpay's official Python SDK, scoped to TEST MODE only.
Used to demonstrate real API integration (creating a payment link that
mirrors a checkout_abandoned event, or fetching a subscription's status) --
the actual recovery DECISION logic never lives here, only the API calls.

If RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET aren't set, every method degrades
to returning a clearly-marked mock response so the rest of the app keeps
working without live keys (e.g. for local dev / grading without secrets).
"""

import os


def _get_client():
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        return None
    import razorpay
    return razorpay.Client(auth=(key_id, key_secret))


def create_test_payment_link(amount_inr: float, description: str, customer_id: str) -> dict:
    """Creates a real Razorpay TEST MODE payment link, or a mock dict if no
    keys are configured."""
    client = _get_client()
    if client is None:
        return {
            "mock": True,
            "note": "No RAZORPAY_KEY_ID/SECRET set -- returning a mock response.",
            "amount_inr": amount_inr,
            "description": description,
            "customer_id": customer_id,
        }
    link = client.payment_link.create({
        "amount": int(amount_inr * 100),  # paise
        "currency": "INR",
        "description": description,
        "notes": {"customer_id": customer_id, "source": "vasuli_recovery_agent"},
    })
    return link


def fetch_payment_status(payment_id: str) -> dict:
    client = _get_client()
    if client is None:
        return {"mock": True, "note": "No RAZORPAY_KEY_ID/SECRET set.", "payment_id": payment_id}
    return client.payment.fetch(payment_id)