from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class InvoiceRecord(BaseModel):
    """Ground-truth invoice data, independent of what the client claims in email."""
    invoice_id: str
    client_name: str
    amount_due: float = Field(gt=0)
    currency: str = "INR"
    due_date: datetime
    issued_date: datetime


class RawEmailEvent(BaseModel):
    """Raw, unprocessed inbound email. This is PRE-anonymization — never sent to an LLM as-is."""
    email_id: str
    invoice_id: str
    sender_name: str
    sender_email: EmailStr
    sender_phone: Optional[str] = None
    body: str
    received_at: datetime  # timezone-aware; this is the date-resolution anchor
    source: str = "stored"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    SETTLED = "SETTLED"


class LedgerEntry(BaseModel):
    """Deterministic bank-side truth. The tracker (Phase 4) checks commitments against this —
    never against what the LLM extracted."""
    invoice_id: str
    amount_settled: float = Field(ge=0)
    settlement_date: Optional[datetime] = None
    status: SettlementStatus


class LLMExtractionRaw(BaseModel):
    """Raw structured output from the LLM. Note: NO resolved dates here — the LLM only
    ever returns the verbatim date phrase. Date math is 100% deterministic (date_resolver.py)."""
    has_commitment: bool
    promised_amount: Optional[float] = None
    currency: Optional[str] = None
    raw_date_phrase: Optional[str] = None
    condition: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_incomplete: bool = False
    reasoning: Optional[str] = None
    claims_already_paid: bool = False


class ExtractedCommitment(BaseModel):
    email_id: str
    invoice_id: str
    has_commitment: bool
    promised_amount: Optional[float] = None
    currency: Optional[str] = None
    resolved_date: Optional[datetime] = None
    date_resolution_method: str
    date_ambiguous: bool
    raw_date_phrase: Optional[str] = None  # verbatim phrase for human review only
    condition: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_incomplete: bool = False
    needs_human_review: bool
    pii_redaction_summary: dict
    claims_already_paid: bool = False
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    source: str = "stored"


class DraftReply(BaseModel):
    id: Optional[int] = None
    action_id: int
    email_id: str
    invoice_id: str
    recipient_name: Optional[str]
    recipient_email: Optional[str]
    subject: str
    body: str
    generation_method: str  # "AI_DRAFTED" or "TEMPLATE_FALLBACK"
    status: str = "DRAFTED"  # DRAFTED, SENT
    source: str
    created_at: Optional[str] = None
    sent_at: Optional[str] = None
