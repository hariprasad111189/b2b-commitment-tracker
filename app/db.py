import json
import sqlite3
from contextlib import contextmanager
from app.config import settings

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_schema():
    with db_session() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commitment_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                ledger_status TEXT NOT NULL,
                amount_settled REAL NOT NULL,
                amount_shortfall REAL NOT NULL,
                requires_human_approval INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                commitment_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                approved_by TEXT
            )
        """)

def init_email_tracking_schema():
    with db_session() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                email_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )
        """)

def is_already_processed(email_id: str) -> bool:
    with db_session() as conn:
        row = conn.execute("SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)).fetchone()
        return row is not None

def mark_processed(email_id: str, source: str):
    from datetime import datetime, timezone
    with db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_emails (email_id, source, processed_at) VALUES (?, ?, ?)",
            (email_id, source, datetime.now(timezone.utc).isoformat()),
        )

def clear_demo_data(*, preserve_live_processed: bool = True) -> dict:
    """Wipe commitment/demo tables so pending starts at zero.

    When preserve_live_processed=True (default), live email_ids stay marked in
    processed_emails so the background poller does not immediately re-ingest the
    same live messages on top of a fresh sample load. Live commitment rows are
    still cleared — this is only for demo reset / ingest-fresh, not the normal
    live ingest path.

    Live markers are collected from processed_emails AND from existing
    commitment_actions (non-sample email_ids / source=live) so a partially
    wiped DB still cannot re-ingest old live mail after reset.
    """
    from datetime import datetime, timezone

    with db_session() as conn:
        preserved: dict[str, str] = {}
        if preserve_live_processed:
            for row in conn.execute(
                "SELECT email_id, processed_at FROM processed_emails WHERE source = 'live'"
            ).fetchall():
                preserved[row["email_id"]] = row["processed_at"]

            # Belt-and-suspenders: if markers were already deleted but live
            # commitment rows remain, keep those Message-IDs marked processed.
            for row in conn.execute(
                "SELECT email_id, commitment_json, created_at FROM commitment_actions"
            ).fetchall():
                email_id = row["email_id"]
                if email_id.startswith("EML-"):
                    continue
                try:
                    source = json.loads(row["commitment_json"]).get("source", "live")
                except (TypeError, json.JSONDecodeError):
                    source = "live"
                if source == "live" or not email_id.startswith("EML-"):
                    preserved.setdefault(
                        email_id,
                        row["created_at"] or datetime.now(timezone.utc).isoformat(),
                    )

        deleted_actions = conn.execute("SELECT COUNT(*) FROM commitment_actions").fetchone()[0]
        conn.execute("DELETE FROM commitment_actions")
        conn.execute("DELETE FROM processed_emails")
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM draft_replies")

        now = datetime.now(timezone.utc).isoformat()
        for email_id, processed_at in preserved.items():
            conn.execute(
                "INSERT INTO processed_emails (email_id, source, processed_at) VALUES (?, 'live', ?)",
                (email_id, processed_at or now),
            )

    return {
        "cleared_actions": deleted_actions,
        "preserved_live_markers": len(preserved),
    }

def init_drafts_schema():
    with db_session() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS draft_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id INTEGER NOT NULL,
                email_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                recipient_name TEXT,
                recipient_email TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                generation_method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFTED',
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
        """)

def get_recovery_summary() -> dict:
    """Pulls from ALL actions regardless of status — this is the real business number,
    not just what's currently sitting in the pending queue."""
    with db_session() as conn:
        rows = conn.execute("SELECT action, status, amount_shortfall, commitment_json FROM commitment_actions").fetchall()

    total_exposure = 0.0
    recovered = 0.0
    at_risk = 0.0
    pending_review = 0.0

    for row in rows:
        commitment = json.loads(row["commitment_json"])
        promised = commitment.get("promised_amount") or 0.0
        total_exposure += promised

        if row["action"] == "MARK_RESOLVED" and row["status"] == "APPROVED":
            recovered += promised
        elif row["action"] == "FLAG_BROKEN_PROMISE":
            at_risk += row["amount_shortfall"]
        elif row["action"] == "ESCALATE_TO_MANAGER" and row["status"] == "PENDING":
            pending_review += row["amount_shortfall"]

    return {
        "total_exposure": total_exposure, "recovered": recovered,
        "at_risk": at_risk, "pending_review": pending_review,
        "total_items": len(rows),
    }