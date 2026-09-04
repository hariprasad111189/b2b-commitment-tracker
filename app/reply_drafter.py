import json
from datetime import datetime, timezone

from groq import Groq
from app.config import settings
from app.tracker import ProposedAction, BoundedAction

_client = Groq(api_key=settings.groq_api_key)

# Only these actions get a customer-facing draft. ESCALATE_TO_MANAGER never does —
# a contradiction or low-confidence case needs a human decision BEFORE any reply goes out,
# not an auto-drafted one that might accidentally confirm something unverified.
DRAFT_ELIGIBLE_ACTIONS = {
    BoundedAction.MARK_RESOLVED, BoundedAction.PAUSE_DUNNING,
    BoundedAction.FLAG_BROKEN_PROMISE, BoundedAction.DRAFT_REMINDER,
}

SYSTEM_PROMPT = """You draft short, professional business email replies for a collections team.
You will be given EXACT fact strings (amounts, dates) that have already been calculated and
formatted correctly. You must use these fact strings VERBATIM, character for character, exactly
as given. Do not recalculate, reformat, round, or invent any monetary figure or date not provided
to you. Do not add any number that wasn't given to you.

Write 60-120 words, courteous and professional, appropriate to the situation described.
Return ONLY JSON: {"subject": "...", "body": "..."}"""


def _template_fallback(proposed: ProposedAction) -> tuple[str, str]:
    """Deterministic, zero-LLM fallback — used if the AI draft fails validation.
    Guarantees a reply is always available even if generation is unreliable."""
    c = proposed.commitment
    amount = f"₹{c.promised_amount:,.2f}" if c.promised_amount else "the outstanding amount"
    date_str = c.resolved_date.strftime("%d %B %Y") if c.resolved_date else "the agreed date"

    if proposed.action == BoundedAction.MARK_RESOLVED:
        subject = f"Payment Received - Invoice {c.invoice_id}"
        body = (f"Dear {c.sender_name or 'Sir/Madam'},\n\nThank you — our records confirm receipt of "
                f"{amount} against Invoice {c.invoice_id}. This matter is now closed on our end.\n\n"
                f"Regards,\nAccounts Receivable")
    elif proposed.action == BoundedAction.PAUSE_DUNNING:
        subject = f"Payment Plan Confirmed - Invoice {c.invoice_id}"
        body = (f"Dear {c.sender_name or 'Sir/Madam'},\n\nThank you for confirming payment of {amount} "
                f"by {date_str} for Invoice {c.invoice_id}. We will pause reminders until that date.\n\n"
                f"Regards,\nAccounts Receivable")
    elif proposed.action == BoundedAction.FLAG_BROKEN_PROMISE:
        subject = f"Follow-Up Required - Invoice {c.invoice_id}"
        body = (f"Dear {c.sender_name or 'Sir/Madam'},\n\nWe note that the payment of {amount} committed "
                f"for {date_str} against Invoice {c.invoice_id} has not yet been received. Please provide "
                f"an updated payment timeline at your earliest convenience.\n\nRegards,\nAccounts Receivable")
    else:
        subject = f"Regarding Invoice {c.invoice_id}"
        body = (f"Dear {c.sender_name or 'Sir/Madam'},\n\nThis is a follow-up regarding Invoice "
                f"{c.invoice_id}. Please reach out at your convenience to discuss.\n\nRegards,\nAccounts Receivable")

    return subject, body


def _facts_present(body: str, facts: list[str]) -> bool:
    return all(fact in body for fact in facts if fact)


def draft_reply(proposed: ProposedAction) -> tuple[str, str, str]:
    """Returns (subject, body, generation_method). Falls back to a deterministic template
    if the AI-generated draft doesn't contain the exact required figures verbatim —
    this is the same zero-hallucination discipline as the rest of the system."""
    c = proposed.commitment
    amount_str = f"₹{c.promised_amount:,.2f}" if c.promised_amount else None
    date_str = c.resolved_date.strftime("%d %B %Y") if c.resolved_date else None
    required_facts = [f for f in [amount_str, date_str, c.invoice_id] if f]

    facts_description = (
        f"Invoice ID: {c.invoice_id}\n"
        f"Situation: {proposed.action.value}\n"
        f"Exact amount (use verbatim if relevant): {amount_str or 'not applicable'}\n"
        f"Exact date (use verbatim if relevant): {date_str or 'not applicable'}\n"
        f"Context: {proposed.reasoning}"
    )

    try:
        response = _client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": facts_description},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        subject, body = parsed["subject"], parsed["body"]

        if _facts_present(body, required_facts):
            return subject, body, "AI_DRAFTED"
    except Exception:
        pass

    subject, body = _template_fallback(proposed)
    return subject, body, "TEMPLATE_FALLBACK"