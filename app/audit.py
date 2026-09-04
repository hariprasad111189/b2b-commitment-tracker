import hashlib
import json
from datetime import datetime, timezone
from app.db import db_session

GENESIS_HASH = "0" * 64

def canonicalize(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

def hash_raw_content(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

def compute_hash(event_type: str, payload_canonical: str, prev_hash: str, created_at: str) -> str:
    material = f"{event_type}|{payload_canonical}|{prev_hash}|{created_at}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

def init_audit_schema():
    with db_session() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                chain_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

def _get_last_hash(conn) -> str:
    row = conn.execute("SELECT chain_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return row["chain_hash"] if row else GENESIS_HASH

def log_event(event_type: str, payload: dict) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    canonical = canonicalize(payload)

    with db_session() as conn:
        prev_hash = _get_last_hash(conn)
        chain_hash = compute_hash(event_type, canonical, prev_hash, created_at)
        cursor = conn.execute(
            """INSERT INTO audit_log (event_type, payload_json, prev_hash, chain_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, canonical, prev_hash, chain_hash, created_at),
        )
        return {
            "id": cursor.lastrowid, "event_type": event_type,
            "prev_hash": prev_hash, "chain_hash": chain_hash, "created_at": created_at,
        }

def get_full_chain() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]

def verify_chain() -> dict:
    chain = get_full_chain()
    expected_prev = GENESIS_HASH

    for row in chain:
        recomputed = compute_hash(row["event_type"], row["payload_json"], row["prev_hash"], row["created_at"])
        if row["prev_hash"] != expected_prev:
            return {"valid": False, "broken_at_id": row["id"],
                     "reason": f"prev_hash mismatch: expected {expected_prev}, found {row['prev_hash']}"}
        if recomputed != row["chain_hash"]:
            return {"valid": False, "broken_at_id": row["id"],
                     "reason": "stored chain_hash does not match recomputed hash."}
        expected_prev = row["chain_hash"]

    return {"valid": True, "broken_at_id": None, "reason": None, "total_events": len(chain)}

def tamper_first_record() -> int | None:
    from app.db import db_session
    with db_session() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS tamper_backup (row_id INTEGER PRIMARY KEY, original_payload TEXT)")
        target = conn.execute("SELECT id, payload_json FROM audit_log ORDER BY id ASC LIMIT 1").fetchone()
        if target is None: return None
        
        conn.execute("INSERT OR REPLACE INTO tamper_backup (row_id, original_payload) VALUES (?, ?)", (target["id"], target["payload_json"]))
        tampered = target["payload_json"][:-1] + ',"tampered":true}'
        conn.execute("UPDATE audit_log SET payload_json = ? WHERE id = ?", (tampered, target["id"]))
        return target["id"]

def restore_tampered_record() -> bool:
    from app.db import db_session
    with db_session() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS tamper_backup (row_id INTEGER PRIMARY KEY, original_payload TEXT)")
        row = conn.execute("SELECT row_id, original_payload FROM tamper_backup ORDER BY row_id DESC LIMIT 1").fetchone()
        if row is None: return False
        
        conn.execute("UPDATE audit_log SET payload_json = ? WHERE id = ?", (row["original_payload"], row["row_id"]))
        conn.execute("DELETE FROM tamper_backup WHERE row_id = ?", (row["row_id"],))
        return True