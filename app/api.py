import smtplib
from email.mime.text import MIMEText
import json
from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.db import (
    db_session, init_schema, init_email_tracking_schema,
    is_already_processed, mark_processed, init_drafts_schema,
    get_recovery_summary, clear_demo_data,
)
from app.poller import ingestion_lock
from app.schemas import ExtractedCommitment
from app.tracker import ProposedAction, BoundedAction, evaluate_commitment
from app import audit
from app.config import settings
from app.email_fetcher import fetch_unseen_emails
from app.reply_drafter import draft_reply, DRAFT_ELIGIBLE_ACTIONS
from data.mock_ledger import get_mock_ledger

app = FastAPI(title="B2B Payment Commitment Tracker", version="0.1.0")

import traceback
from fastapi.responses import JSONResponse
from fastapi import Request

@app.exception_handler(Exception)
async def catch_all_errors(request: Request, exc: Exception):
    traceback.print_exc()  # full traceback still prints in your uvicorn terminal
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {str(exc)}"},
    )

class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class StoredAction(ProposedAction):
    id: int
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None

class ApprovalRequest(BaseModel):
    approved_by: str
    decision: ApprovalStatus

@app.on_event("startup")
def on_startup():
    init_schema()
    audit.init_audit_schema()
    init_email_tracking_schema()
    init_drafts_schema()
    from app.poller import start_background_poller
    start_background_poller()

def _row_to_stored_action(row) -> StoredAction:
    commitment_data = json.loads(row["commitment_json"])
    return StoredAction(
        id=row["id"], commitment=ExtractedCommitment(**commitment_data),
        action=BoundedAction(row["action"]), reasoning=row["reasoning"],
        ledger_status=row["ledger_status"], amount_settled=row["amount_settled"],
        amount_shortfall=row["amount_shortfall"],
        requires_human_approval=bool(row["requires_human_approval"]),
        status=ApprovalStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        approved_at=datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None,
        approved_by=row["approved_by"],
    )

def persist_proposed_action(proposed: ProposedAction) -> int:
    with db_session() as conn:
        cursor = conn.execute(
            """INSERT INTO commitment_actions
               (email_id, invoice_id, action, reasoning, ledger_status, amount_settled,
                amount_shortfall, requires_human_approval, status, commitment_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposed.commitment.email_id, proposed.commitment.invoice_id, proposed.action.value,
             proposed.reasoning, proposed.ledger_status, proposed.amount_settled,
             proposed.amount_shortfall, int(proposed.requires_human_approval),
             ApprovalStatus.PENDING.value, proposed.commitment.model_dump_json(),
             datetime.now(timezone.utc).isoformat()),
        )
        action_id = cursor.lastrowid

    audit.log_event("ACTION_PROPOSED", {
        "action_id": action_id, "email_id": proposed.commitment.email_id,
        "invoice_id": proposed.commitment.invoice_id, "action": proposed.action.value,
        "reasoning": proposed.reasoning, "amount_shortfall": proposed.amount_shortfall,
    })
    return action_id

def _maybe_draft_reply(action_id: int):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM commitment_actions WHERE id = ?", (action_id,)).fetchone()
    
    if row is None:
        return
        
    action_enum = BoundedAction(row["action"])
    if action_enum not in DRAFT_ELIGIBLE_ACTIONS:
        return
        
    stored = _row_to_stored_action(row)
    proposed = ProposedAction(
        commitment=stored.commitment, action=stored.action, reasoning=stored.reasoning,
        ledger_status=stored.ledger_status, amount_settled=stored.amount_settled,
        amount_shortfall=stored.amount_shortfall, requires_human_approval=stored.requires_human_approval,
    )
    
    subject, body, method = draft_reply(proposed)
    
    with db_session() as conn:
        conn.execute(
            """INSERT INTO draft_replies
               (action_id, email_id, invoice_id, recipient_name, recipient_email, subject, body,
                generation_method, status, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFTED', ?, ?)""",
            (action_id, stored.commitment.email_id, stored.commitment.invoice_id,
             stored.commitment.sender_name, stored.commitment.sender_email, subject, body,
             method, stored.commitment.source, datetime.now(timezone.utc).isoformat()),
        )
    audit.log_event("REPLY_DRAFTED", {
        "action_id": action_id, "invoice_id": stored.commitment.invoice_id, "method": method,
    })

def record_approval(action_id: int, approved_by: str, decision: ApprovalStatus) -> StoredAction:
    if decision == ApprovalStatus.PENDING:
        raise ValueError("decision must be APPROVED or REJECTED.")
    with db_session() as conn:
        row = conn.execute("SELECT * FROM commitment_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise LookupError(f"No action found with id={action_id}")
        if row["status"] != ApprovalStatus.PENDING.value:
            raise ValueError(f"Action {action_id} already resolved with status={row['status']}.")

        conn.execute(
            "UPDATE commitment_actions SET status = ?, approved_at = ?, approved_by = ? WHERE id = ?",
            (decision.value, datetime.now(timezone.utc).isoformat(), approved_by, action_id),
        )
        updated = conn.execute("SELECT * FROM commitment_actions WHERE id = ?", (action_id,)).fetchone()

    audit.log_event("ACTION_APPROVED" if decision == ApprovalStatus.APPROVED else "ACTION_REJECTED", {
        "action_id": action_id, "approved_by": approved_by, "decision": decision.value,
    })
    
    if decision == ApprovalStatus.APPROVED:
        _maybe_draft_reply(action_id)
        
    return _row_to_stored_action(updated)

@app.get("/api/v1/commitments/pending", response_model=list[StoredAction])
def get_pending_commitments():
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM commitment_actions WHERE status = ? ORDER BY created_at ASC",
            (ApprovalStatus.PENDING.value,),
        ).fetchall()
    return [_row_to_stored_action(r) for r in rows]

@app.post("/api/v1/commitments/{action_id}/approve", response_model=StoredAction)
def approve_commitment_action(action_id: int, request: ApprovalRequest):
    try:
        return record_approval(action_id, request.approved_by, request.decision)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

def _ingest_emails(emails: list, source: str) -> dict:
    from app.agent import process_email

    new_emails = [e for e in emails if not is_already_processed(e.email_id)]
    if not new_emails:
        return {"ingested": 0, "skipped_duplicates": len(emails), "action_ids": [], "failed": []}

    ledger = get_mock_ledger()
    inserted_ids = []
    failed = []

    for email in new_emails:
        try:
            commitment = process_email(email)
            proposed = evaluate_commitment(commitment, ledger)
            inserted_ids.append(persist_proposed_action(proposed))
            mark_processed(email.email_id, source)
        except Exception as e:
            failed.append({"email_id": email.email_id, "error": f"{type(e).__name__}: {str(e)}"})

    return {
        "ingested": len(inserted_ids),
        "skipped_duplicates": len(emails) - len(new_emails),
        "action_ids": inserted_ids,
        "failed": failed,
    }

@app.post("/api/v1/commitments/ingest")
def ingest_stored_emails():
    from data.mock_emails import get_mock_emails
    return _ingest_emails(get_mock_emails(), source="stored")

@app.post("/api/v1/commitments/ingest-fresh")
def ingest_fresh_sample_emails():
    """Wipe demo state (keeping live processed markers), then ingest exactly
    the 5 sample emails. Holds ingestion_lock so the live poller cannot race."""
    from data.mock_emails import get_mock_emails

    with ingestion_lock:
        clear_demo_data(preserve_live_processed=True)
        return _ingest_emails(get_mock_emails(), source="stored")

@app.post("/api/v1/commitments/ingest-live")
def ingest_live_emails():
    with ingestion_lock:
        try:
            emails = fetch_unseen_emails()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _ingest_emails(emails, source="live")

@app.get("/api/v1/live/status")
def live_status():
    return {
        "email_mode": settings.email_mode,
        "imap_configured": bool(settings.imap_user and settings.imap_app_password),
        "poll_interval_seconds": settings.poll_interval_seconds,
    }

@app.get("/api/v1/audit/chain")
def get_audit_chain():
    return audit.get_full_chain()

@app.get("/api/v1/audit/verify")
def verify_audit_chain():
    return audit.verify_chain()

@app.post("/api/v1/dev/reset-demo-data")
def reset_demo_data():
    """Clear all commitment/demo rows. Preserves live processed_emails markers
    so the background poller will not re-ingest previously seen live mail."""
    with ingestion_lock:
        result = clear_demo_data(preserve_live_processed=True)
        with db_session() as conn:
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM commitment_actions WHERE status = ?",
                (ApprovalStatus.PENDING.value,),
            ).fetchone()[0]
            live_markers = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE source = 'live'"
            ).fetchone()[0]
    return {
        "status": "Demo data cleared.",
        "pending_count": pending_count,
        "cleared_actions": result["cleared_actions"],
        "preserved_live_markers": result["preserved_live_markers"],
        "live_markers_remaining": live_markers,
    }

@app.get("/api/v1/live/test-connection")
def test_live_connection():
    try:
        emails = fetch_unseen_emails(limit=1)
        return {"success": True, "message": "Connected to your inbox successfully."}
    except Exception as e:
        return {"success": False, "message": f"{type(e).__name__}: {str(e)}"}

@app.post("/api/v1/audit/tamper-demo")
def tamper_demo_endpoint():
    row_id = audit.tamper_first_record()
    if row_id is None:
        raise HTTPException(status_code=400, detail="No records exist yet.")
    return {"tampered_row": row_id}

@app.post("/api/v1/audit/restore-demo")
def restore_demo_endpoint():
    restored = audit.restore_tampered_record()
    return {"restored": restored}

@app.get("/api/v1/drafts/pending")
def get_pending_drafts():
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM draft_replies WHERE status = 'DRAFTED' ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/v1/drafts/{draft_id}/send")
def send_draft(draft_id: int):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM draft_replies WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Draft not found.")
        if row["status"] == "SENT":
            raise HTTPException(status_code=409, detail="Already sent.")
            
    if not settings.smtp_host or not settings.smtp_user:
        raise HTTPException(status_code=400, detail="Email sending isn't configured. Use Copy instead, or add SMTP settings to .env.")
        
    if not row["recipient_email"] or "@" not in row["recipient_email"]:
        raise HTTPException(status_code=400, detail="No valid recipient email address on file for this draft.")
        
    try:
        msg = MIMEText(row["body"])
        msg["Subject"] = row["subject"]
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
        msg["To"] = row["recipient_email"]
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sending failed: {str(e)}")
        
    with db_session() as conn:
        conn.execute("UPDATE draft_replies SET status = 'SENT', sent_at = ? WHERE id = ?",
                     (datetime.now(timezone.utc).isoformat(), draft_id))
                     
    audit.log_event("REPLY_SENT", {"draft_id": draft_id, "recipient": row["recipient_email"]})
    return {"status": "sent"}

@app.get("/api/v1/recovery/summary")
def recovery_summary():
    return get_recovery_summary()
