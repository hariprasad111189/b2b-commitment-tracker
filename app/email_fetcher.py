import imaplib
import email
import hashlib
from email.header import decode_header
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.schemas import RawEmailEvent


def _decode(value) -> str:
    if value is None:
        return ""
    decoded, encoding = decode_header(value)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(encoding or "utf-8", errors="ignore")
    return decoded


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return msg.get_payload(decode=True).decode(charset, errors="ignore")


def _extract_invoice_id(subject: str, body: str) -> Optional[str]:
    """Broadened to catch 'INV-1001', 'INV 1001', 'inv1001' — not just the exact hyphenated format."""
    import re
    combined = f"{subject} {body}"
    match = re.search(r"\bINV[\s\-]?(\d{3,6})\b", combined, re.IGNORECASE)
    return f"INV-{match.group(1)}" if match else None


def _stable_email_id(message_id_header: Optional[str], sender: str, date_header: str, subject: str) -> str:
    """Some mail clients omit Message-ID. Falls back to a stable hash of sender+date+subject
    so the same email always produces the same ID (required for duplicate-prevention to work),
    instead of an empty string that breaks tracking."""
    if message_id_header and message_id_header.strip():
        return message_id_header.strip()
    fingerprint = f"{sender}|{date_header}|{subject}".encode("utf-8")
    return "GENERATED-" + hashlib.sha256(fingerprint).hexdigest()[:24]


def fetch_unseen_emails(limit: int = 20) -> list[RawEmailEvent]:
    if not settings.imap_user or not settings.imap_app_password:
        raise ValueError("IMAP credentials not configured. Set IMAP_USER and IMAP_APP_PASSWORD in .env.")

    results: list[RawEmailEvent] = []
    conn = imaplib.IMAP4_SSL(settings.imap_host)
    try:
        conn.login(settings.imap_user, settings.imap_app_password)
        conn.select(settings.imap_folder, readonly=True)

        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return results

        message_ids = data[0].split()[-limit:]

        for msg_id in message_ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue

            msg = email.message_from_bytes(msg_data[0][1])

            subject = _decode(msg.get("Subject")) or "(no subject)"
            sender_full = _decode(msg.get("From")) or "unknown@unknown.com"
            sender_email = email.utils.parseaddr(sender_full)[1] or "unknown@unknown.com"
            sender_name = email.utils.parseaddr(sender_full)[0] or sender_email
            body = _extract_body(msg) or "(empty body)"
            date_header = msg.get("Date") or ""

            try:
                received_at = email.utils.parsedate_to_datetime(date_header)
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                received_at = datetime.now(timezone.utc)

            stable_id = _stable_email_id(msg.get("Message-ID"), sender_full, date_header, subject)
            invoice_id = _extract_invoice_id(subject, body) or "UNMATCHED"

            results.append(RawEmailEvent(
                email_id=stable_id, invoice_id=invoice_id,
                sender_name=sender_name, sender_email=sender_email, sender_phone=None,
                body=body, received_at=received_at,
                source="live"  # <-- ADD THIS LINE
            ))
    finally:
        conn.logout()

    return results