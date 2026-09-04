from datetime import datetime, timezone
from typing import Optional
from enum import Enum
from pydantic import BaseModel
from app.schemas import ExtractedCommitment, LedgerEntry, SettlementStatus
from app.config import settings

AMOUNT_TOLERANCE = 1.0

class BoundedAction(str, Enum):
    MARK_RESOLVED = "MARK_RESOLVED"
    FLAG_BROKEN_PROMISE = "FLAG_BROKEN_PROMISE"
    PAUSE_DUNNING = "PAUSE_DUNNING"
    ESCALATE_TO_MANAGER = "ESCALATE_TO_MANAGER"
    DRAFT_REMINDER = "DRAFT_REMINDER"
    NO_ACTION = "NO_ACTION"

class ProposedAction(BaseModel):
    commitment: ExtractedCommitment
    action: BoundedAction
    reasoning: str
    ledger_status: str
    amount_settled: float
    amount_shortfall: float
    requires_human_approval: bool

def _find_ledger_entry(invoice_id: str, ledger: list[LedgerEntry]) -> Optional[LedgerEntry]:
    return next((e for e in ledger if e.invoice_id == invoice_id), None)

def _format_review_reasons(reasons: list[str]) -> str:
    if len(reasons) == 1:
        return f"Needs review because {reasons[0]}"
    bullets = "\n".join(f"• {r}" for r in reasons)
    return f"Needs review because:\n{bullets}"

def _human_review_reasons(
    commitment: ExtractedCommitment,
    ledger_entry: Optional[LedgerEntry] = None,
) -> list[str]:
    """Build only the reasons that actually triggered human review for this invoice."""
    reasons: list[str] = []
    phrase = (commitment.raw_date_phrase or "").strip()

    if commitment.claims_already_paid and ledger_entry is not None:
        if ledger_entry.status == SettlementStatus.SETTLED:
            reasons.append(
                "the customer says the invoice was already paid, and the payment ledger "
                "confirms it is settled."
            )
        else:
            reasons.append(
                "the customer says the invoice was already paid, but the payment ledger still "
                "shows the invoice as pending. The system detected a contradiction and requires "
                "human verification."
            )

    if commitment.date_ambiguous and phrase:
        reasons.append(
            f"the customer wrote '{phrase}'. The system cannot safely determine "
            f"the exact calendar date from this phrase, so human confirmation is required."
        )
    elif commitment.date_ambiguous:
        reasons.append(
            "the payment date phrase in the email is ambiguous and could mean more than "
            "one calendar date, so human confirmation is required."
        )

    if commitment.confidence < settings.confidence_threshold:
        reasons.append(
            "the AI confidence for the extracted payment commitment is below the safety threshold."
        )

    if commitment.extraction_incomplete:
        if commitment.promised_amount is None and not phrase and commitment.resolved_date is None:
            reasons.append(
                "the customer email does not contain a clear payment amount or payment date."
            )
        else:
            if commitment.promised_amount is None:
                reasons.append(
                    "the customer email does not contain a clear payment amount."
                )
            if not phrase and commitment.resolved_date is None:
                reasons.append(
                    "the customer email does not contain a clear payment date."
                )
            if phrase and commitment.resolved_date is None and not commitment.date_ambiguous:
                reasons.append(
                    f"the customer wrote '{phrase}', but the system could not turn that into "
                    f"an exact calendar date."
                )
            if commitment.promised_amount is not None and (phrase or commitment.resolved_date is not None):
                if not any("does not contain a clear payment" in r for r in reasons):
                    reasons.append(
                        "the extraction was marked incomplete, so the system will not "
                        "auto-approve this commitment."
                    )

    if (
        commitment.has_commitment
        and commitment.resolved_date is None
        and not commitment.date_ambiguous
        and not any("payment date" in r for r in reasons)
        and not any("calendar date" in r for r in reasons)
    ):
        if phrase:
            reasons.append(
                f"the customer wrote '{phrase}', but no exact payment date could be resolved."
            )
        else:
            reasons.append(
                "the customer email does not contain a clear payment date."
            )

    seen: set[str] = set()
    unique: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique

def evaluate_commitment(
    commitment: ExtractedCommitment,
    ledger: list[LedgerEntry],
    as_of: Optional[datetime] = None,
) -> ProposedAction:
    as_of = as_of or datetime.now(timezone.utc)
    ledger_entry = _find_ledger_entry(commitment.invoice_id, ledger)
    
    if ledger_entry is None:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.ESCALATE_TO_MANAGER,
            reasoning=(
                f"Needs review because no payment ledger entry was found for invoice "
                f"{commitment.invoice_id}. The system cannot verify settlement without ledger data."
            ),
            ledger_status="NOT_FOUND", amount_settled=0.0,
            amount_shortfall=commitment.promised_amount or 0.0, requires_human_approval=True,
        )

    # Same decision order as before — only the explanation text is clearer.
    if commitment.needs_human_review or commitment.extraction_incomplete:
        reasons = _human_review_reasons(commitment, ledger_entry)
        if not reasons:
            reasons = [
                "this item was flagged for human confirmation before any collection action is taken."
            ]
        return ProposedAction(
            commitment=commitment,
            action=BoundedAction.ESCALATE_TO_MANAGER,
            reasoning=_format_review_reasons(reasons),
            ledger_status=ledger_entry.status.value,
            amount_settled=ledger_entry.amount_settled,
            amount_shortfall=max((commitment.promised_amount or 0.0) - ledger_entry.amount_settled, 0.0),
            requires_human_approval=True,
        )

    if commitment.claims_already_paid:
        if ledger_entry.status == SettlementStatus.SETTLED:
            return ProposedAction(
                commitment=commitment, action=BoundedAction.MARK_RESOLVED,
                reasoning=(
                    "Needs review because the customer says the invoice was already paid, "
                    "and the payment ledger confirms it is settled. Please confirm before closing."
                ),
                ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
                amount_shortfall=0.0, requires_human_approval=True,
            )
        return ProposedAction(
            commitment=commitment, action=BoundedAction.ESCALATE_TO_MANAGER,
            reasoning=(
                "Needs review because the customer says the invoice was already paid, but the "
                "payment ledger still shows the invoice as pending. The system detected a "
                "contradiction and requires human verification."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=0.0, requires_human_approval=True,
        )

    if not commitment.has_commitment:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.NO_ACTION,
            reasoning=(
                "Needs review because the customer email does not contain a clear payment "
                "commitment. No specific amount or payment date was promised, so the system "
                "will not take an automated collection action."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=0.0, requires_human_approval=False,
        )

    promised_amount = commitment.promised_amount or 0.0
    shortfall = max(promised_amount - ledger_entry.amount_settled, 0.0)

    if shortfall <= AMOUNT_TOLERANCE:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.MARK_RESOLVED,
            reasoning=(
                f"The ledger shows ₹{ledger_entry.amount_settled:,.2f} settled, which matches "
                f"the promised amount of ₹{promised_amount:,.2f}. Please confirm before marking resolved."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=0.0, requires_human_approval=True,
        )

    if commitment.resolved_date is None:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.ESCALATE_TO_MANAGER,
            reasoning=(
                "Needs review because a payment commitment was found, but the customer email "
                "does not contain a clear payment date."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=shortfall, requires_human_approval=True,
        )

    promise_due = commitment.resolved_date
    if promise_due.tzinfo is None:
        promise_due = promise_due.replace(tzinfo=timezone.utc)
    
    if as_of < promise_due:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.PAUSE_DUNNING,
            reasoning=(
                f"The customer committed to pay ₹{promised_amount:,.2f} by {promise_due.date()}. "
                f"That date has not arrived yet, so reminders should be paused until then."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=shortfall, requires_human_approval=True,
        )

    if ledger_entry.amount_settled > 0:
        return ProposedAction(
            commitment=commitment, action=BoundedAction.FLAG_BROKEN_PROMISE,
            reasoning=(
                f"The customer promised ₹{promised_amount:,.2f} by {promise_due.date()}, but only "
                f"₹{ledger_entry.amount_settled:,.2f} has been received. Shortfall: ₹{shortfall:,.2f}."
            ),
            ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
            amount_shortfall=shortfall, requires_human_approval=True,
        )

    return ProposedAction(
        commitment=commitment, action=BoundedAction.FLAG_BROKEN_PROMISE,
        reasoning=(
            f"The customer promised ₹{promised_amount:,.2f} by {promise_due.date()}, but the ledger "
            f"shows no payment received yet."
        ),
        ledger_status=ledger_entry.status.value, amount_settled=ledger_entry.amount_settled,
        amount_shortfall=shortfall, requires_human_approval=True,
    )
