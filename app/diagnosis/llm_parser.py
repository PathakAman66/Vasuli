"""
Diagnosis layer -- the ONLY place in Vasuli that calls an LLM.

Design decision (be ready to defend this in the panel interview):
Claude's job here is narrow on purpose: turn an unstructured gateway error
string into a structured root_cause label + confidence score. That's it.
It never decides retry counts, never picks a channel, never touches money.

Why here and not elsewhere: gateway error text is genuinely unstructured
free text ("NPCI Error: Insufficient Balance (Code: 51)" vs "Card declined
by issuing bank (Code: 05 - Do not honour)") -- a job classification models
are good at and hardcoded string-matching is brittle for. Everything
downstream of this (is a retry allowed, which channel, what it costs) is
handled by deterministic Python in app/rules/, specifically so an LLM
mistake here can produce a *wrong label*, never a *wrong money action*.

If ANTHROPIC_API_KEY is not set, falls back to a keyword heuristic so the
rest of the pipeline (and the demo) still runs end-to-end without a live key.
"""

import json
import os
from app.models import Diagnosis, RevenueEvent, RootCause

_client = None


def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        _client = Anthropic(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are a narrow classification component inside a payments \
recovery pipeline. Your ONLY job: read a raw payment gateway error string and \
classify its root cause. You do not make retry, channel, or compliance decisions \
-- a separate deterministic rules engine does that. Respond with strict JSON only, \
no prose, matching this schema:
{"root_cause": "<one of: insufficient_balance, card_declined, upi_timeout, \
mandate_revoked, user_abandoned, gateway_error, unknown>", \
"confidence": <float 0-1>, "reasoning": "<one short sentence>"}"""


def _heuristic_fallback(error_text: str) -> Diagnosis:
    """No-API-key fallback: simple keyword rules. Lower confidence than the
    LLM path on purpose, so the rules engine treats it more conservatively."""
    text = (error_text or "").lower()
    if not text:
        cause, conf = RootCause.USER_ABANDONED, 0.6
    elif "insufficient" in text or "balance" in text or "code: 51" in text:
        cause, conf = RootCause.INSUFFICIENT_BALANCE, 0.55
    elif "declined" in text or "code: 05" in text:
        cause, conf = RootCause.CARD_DECLINED, 0.55
    elif "timeout" in text or "timed out" in text:
        cause, conf = RootCause.UPI_TIMEOUT, 0.55
    elif "mandate" in text or "revoked" in text:
        cause, conf = RootCause.MANDATE_REVOKED, 0.55
    else:
        cause, conf = RootCause.GATEWAY_ERROR, 0.4
    return Diagnosis(
        event_id="",  # filled by caller
        root_cause=cause,
        confidence=conf,
        reasoning="heuristic fallback (no ANTHROPIC_API_KEY set)",
    )


def diagnose(event: RevenueEvent) -> Diagnosis:
    client = _get_client()
    if client is None:
        d = _heuristic_fallback(event.gateway_error_text)
        d.event_id = event.event_id
        return d

    try:
        resp = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"loss_type: {event.loss_type.value}\n"
                    f"gateway_error_text: {event.gateway_error_text!r}\n"
                    f"amount_inr: {event.amount_inr}\n"
                    f"attempt_count: {event.attempt_count}"
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        return Diagnosis(
            event_id=event.event_id,
            root_cause=RootCause(parsed["root_cause"]),
            confidence=float(parsed["confidence"]),
            reasoning=parsed["reasoning"],
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any LLM/parse
        # failure must degrade gracefully, never crash the pipeline or block money.
        d = _heuristic_fallback(event.gateway_error_text)
        d.event_id = event.event_id
        d.reasoning = f"LLM call/parse failed ({exc.__class__.__name__}), used heuristic fallback"
        d.confidence = min(d.confidence, 0.4)
        return d