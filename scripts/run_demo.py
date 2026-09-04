import sqlite3
import sys
import time
import os

sys.path.insert(0, ".")

from app.db import init_schema
from app import audit
from app.agent import process_email
from app.tracker import evaluate_commitment, BoundedAction
from app.api import persist_proposed_action, record_approval, ApprovalStatus
from data.mock_emails import get_mock_emails
from data.mock_ledger import get_mock_ledger
from app.config import settings

def line(char="-", n=70):
    print(char * n)

def header(title: str):
    print()
    line("=")
    print(f"  {title}")
    line("=")

def run_pipeline():
    header("STEP 1 — Ingesting emails through Privacy-Preserving LangGraph Agent")
    ledger = get_mock_ledger()
    action_ids = []

    for email in get_mock_emails():
        commitment = process_email(email)
        proposed = evaluate_commitment(commitment, ledger)
        action_id = persist_proposed_action(proposed)
        action_ids.append(action_id)

        flag = "⚠ REVIEW" if commitment.needs_human_review else "        "
        print(f"[{flag}] {email.email_id:<9} -> {proposed.action.value:<20} "
              f"conf={commitment.confidence:.2f}  |  {proposed.reasoning[:70]}")

    return action_ids

def approve_sample(action_ids: list[int]):
    header("STEP 2 — Human approves a sample of proposed actions")
    for action_id in action_ids[:3]:
        result = record_approval(action_id, approved_by="dileep_demo", decision=ApprovalStatus.APPROVED)
        print(f"Approved action_id={action_id} | invoice={result.commitment.invoice_id} "
              f"| action={result.action.value}")

    print("\nAttempting to re-approve action_id=1 (should be rejected with a 409-equivalent error):")
    try:
        record_approval(action_ids[0], approved_by="dileep_demo", decision=ApprovalStatus.APPROVED)
    except ValueError as e:
        print(f"  Correctly blocked: {e}")

def verify_audit_trail():
    header("STEP 3 — Verifying cryptographic audit chain integrity")
    result = audit.verify_chain()
    print(f"Chain valid: {result['valid']}")
    print(f"Total events logged: {result.get('total_events', 'n/a')}")
    if not result["valid"]:
        print(f"BROKEN at event id={result['broken_at_id']}: {result['reason']}")

def tamper_demo():
    header("STEP 4 — Tamper-evidence proof (simulating a direct DB edit, bypassing the app)")
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row

    target = conn.execute("SELECT id, payload_json FROM audit_log ORDER BY id ASC LIMIT 1").fetchone()
    print(f"Directly editing audit_log row id={target['id']} via raw SQL (no app code path)...")

    tampered_payload = target["payload_json"].replace("EMAIL_INGESTED", "EMAIL_INGESTED")
    tampered_payload = tampered_payload[:-1] + ',"tampered":true}' 
    conn.execute("UPDATE audit_log SET payload_json = ? WHERE id = ?", (tampered_payload, target["id"]))
    conn.commit()
    conn.close()

    print("Re-running verify_chain() after tampering...")
    result = audit.verify_chain()
    print(f"Chain valid: {result['valid']}")
    if not result["valid"]:
        print(f"DETECTED tampering at event id={result['broken_at_id']}: {result['reason']}")
    print("\nThis proves the hash chain catches unauthorized modification even when it")
    print("bypasses the application entirely — a raw sqlite3 UPDATE was enough to trip it.")

def main():
    # Clean the database for a fresh run
    for f in ["commitment_tracker.db", "commitment_tracker.db-wal", "commitment_tracker.db-shm"]:
        if os.path.exists(f):
            os.remove(f)

    print("B2B PAYMENT COMMITMENT TRACKER — END-TO-END DEMO")
    print("Razorpay AI Buildathon — Track 03 (AI Revenue Recovery)")
    init_schema()
    audit.init_audit_schema()

    action_ids = run_pipeline()
    time.sleep(0.3)
    approve_sample(action_ids)
    time.sleep(0.3)
    verify_audit_trail()
    time.sleep(0.3)
    tamper_demo()

    header("DEMO COMPLETE")

if __name__ == "__main__":
    main()