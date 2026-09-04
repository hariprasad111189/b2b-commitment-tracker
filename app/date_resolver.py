import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from dateutil import parser as dateutil_parser

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

@dataclass
class DateResolution:
    resolved_date: Optional[datetime]
    method: str
    ambiguous: bool
    notes: str

def resolve_relative_date(phrase: Optional[str], anchor: datetime) -> DateResolution:
    """Anchor = the email's received_at timestamp. All math is plain Python."""
    if not phrase or not phrase.strip():
        return DateResolution(None, "NO_PHRASE", False, "No date phrase was extracted.")
    p = phrase.strip().lower()

    # "in N days"
    m = re.search(r"in\s+(\d+)\s+day", p)
    if m:
        n = int(m.group(1))
        return DateResolution(anchor + timedelta(days=n), "RELATIVE_DAYS", False, f"Anchor + {n} day(s).")

    # "end of month" / "end of the month"
    if "end of month" in p or "end of the month" in p:
        next_month = anchor.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)
        return DateResolution(last_day, "END_OF_MONTH", False, "Resolved to the last calendar day of anchor's month.")

    # "next <weekday>"
    m = re.search(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", p)
    if m:
        target = _WEEKDAYS[m.group(1)]
        days_ahead = (target - anchor.weekday() + 7) % 7
        days_ahead = days_ahead if days_ahead != 0 else 7
        resolved = anchor + timedelta(days=days_ahead)
        return DateResolution(
            resolved, "NEXT_WEEKDAY", True,
            f"Resolved 'next {m.group(1)}' to nearest future occurrence ({resolved.date()}). Flagged for human confirmation."
        )

    # Absolute date parsing
    try:
        parsed = dateutil_parser.parse(phrase, default=anchor, fuzzy=True)
        return DateResolution(parsed, "ABSOLUTE_PARSED", False, "Parsed as an absolute date string.")
    except (ValueError, OverflowError):
        return DateResolution(None, "UNRESOLVED", True, f"Could not resolve phrase: '{phrase}'.")