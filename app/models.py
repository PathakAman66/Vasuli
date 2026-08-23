"""
Shared data models for Vasuli.

Design note: these models are the contract between every layer (detection ->
diagnosis -> rules -> executor -> audit). Keeping them in one file makes it
obvious, in a panel review, exactly what data crosses each boundary.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class LossType(str, Enum):
    FAILED_MANDATE = "failed_mandate"          # UPI Autopay / subscription debit failed
    CHECKOUT_ABANDONED = "checkout_abandoned"   # payment link created, never completed


class RootCause(str, Enum):
    INSUFFICIENT_BALANCE = "insufficient_balance"
    CARD_DECLINED = "card_declined"
    UPI_TIMEOUT = "upi_timeout"
    MANDATE_REVOKED = "mandate_revoked"
    USER_ABANDONED = "user_abandoned"
    GATEWAY_ERROR = "gateway_error"
    UNKNOWN = "unknown"


class InterventionChannel(str, Enum):
    AUTO_RETRY = "auto_retry"          # cost: ~0
    EMAIL = "email"                    # cost: very low
    WHATSAPP = "whatsapp"              # cost: moderate
    HUMAN_ESCALATION = "human_escalation"  # cost: high
    NONE = "none"                      # stopped / no action taken


# Indicative per-attempt cost in INR, used by the rules engine and the
# backtest engine to compute NET recovered (gross recovered - outreach cost).
# These are illustrative placeholders, not real Razorpay/telco pricing.
CHANNEL_COST_INR = {
    InterventionChannel.AUTO_RETRY: 0.0,
    InterventionChannel.EMAIL: 0.10,
    InterventionChannel.WHATSAPP: 2.0,
    InterventionChannel.HUMAN_ESCALATION: 50.0,
    InterventionChannel.NONE: 0.0,
}


class RevenueEvent(BaseModel):
    """A single at-risk revenue event, e.g. one failed mandate charge."""
    event_id: str
    loss_type: LossType
    customer_id: str
    amount_inr: float
    gateway_error_text: str = ""          # raw, unstructured error from the gateway
    attempt_count: int = 0                # how many recovery attempts already made
    typical_credit_day_of_month: Optional[int] = None  # synthetic "salary date" signal
    created_at: datetime
    last_attempt_at: Optional[datetime] = None
    resolved: bool = False
    recovered_amount_inr: float = 0.0


class Diagnosis(BaseModel):
    """Output of the LLM parser step. Narrow by design: a label + confidence,
    nothing that touches money directly."""
    event_id: str
    root_cause: RootCause
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class RuleCheck(BaseModel):
    """One compliance/business rule evaluated against an event, kept for the
    audit trail regardless of pass/fail."""
    rule_name: str
    passed: bool
    detail: str


class Decision(BaseModel):
    """Final, rules-engine-approved decision. The LLM never produces this
    directly -- it is always constructed by app/rules/*."""
    event_id: str
    diagnosis: Diagnosis
    rule_checks: list[RuleCheck]
    approved: bool
    channel: InterventionChannel
    estimated_cost_inr: float
    reason: str
    decided_at: datetime


class ActionOutcome(BaseModel):
    """Result of actually executing a decision."""
    event_id: str
    channel: InterventionChannel
    success: bool
    recovered_amount_inr: float
    cost_inr: float
    note: str
    executed_at: datetime


class AuditRecord(BaseModel):
    """One append-only row in the audit trail. Every step of the pipeline
    writes one of these -- this is what the dashboard's explainability
    drill-down reads from."""
    id: Optional[int] = None
    event_id: str
    stage: str   # "detected" | "diagnosed" | "rule_checked" | "decided" | "executed"
    payload: str  # JSON-serialized snapshot of the relevant object above
    timestamp: datetime