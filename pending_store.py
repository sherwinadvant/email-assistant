"""
pending_store.py
Persists meetings that are awaiting sender confirmation of a new time slot.
Stored as a simple JSON file: pending_meetings.json
"""

import json
import os

STORE_PATH = "pending_meetings.json"


def load() -> dict:
    """Load all pending meetings. Returns dict keyed by original email subject."""
    if not os.path.exists(STORE_PATH):
        return {}
    with open(STORE_PATH, "r") as f:
        return json.load(f)


def save(data: dict):
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def add_pending(result: dict):
    """
    Save a meeting as pending confirmation.
    Keyed by a combo of sender email + subject to match incoming replies.
    """
    data = load()
    key = _make_key(result.get("from", ""), result.get("subject", ""))
    data[key] = {
        "subject":             result.get("subject"),
        "from":                result.get("from"),
        "meeting_title":       result.get("meeting_title"),
        "requested_attendees": result.get("requested_attendees", []),
        "free_slots":          result.get("free_slots", []),
        "email_id":            result.get("email_id"),
    }
    save(data)
    print(f"  📌 Saved as pending confirmation: {result.get('subject')}")


def find_pending(sender_email: str, subject: str) -> dict | None:
    """
    Try to match an incoming reply to a pending meeting.
    Matches on sender email + subject (strips Re:/Fwd: prefixes).
    """
    data = load()
    clean_subject = _clean_subject(subject)

    for key, pending in data.items():
        pending_sender = _extract_email(pending.get("from", ""))
        pending_subject = _clean_subject(pending.get("subject", ""))
        if (pending_sender and pending_sender.lower() == sender_email.lower()
                and clean_subject in pending_subject or pending_subject in clean_subject):
            return pending
    return None


def remove_pending(sender_email: str, subject: str):
    """Remove a pending meeting once it has been confirmed and scheduled."""
    data = load()
    key = _make_key(sender_email, subject)
    if key in data:
        del data[key]
        save(data)


def list_pending() -> list[dict]:
    return list(load().values())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_key(from_header: str, subject: str) -> str:
    email = _extract_email(from_header)
    return f"{email}::{_clean_subject(subject)}"


def _clean_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes and lowercase for comparison."""
    import re
    return re.sub(r'^(re|fwd|fw):\s*', '', subject.strip(), flags=re.IGNORECASE).lower()


def _extract_email(from_header: str) -> str:
    import re
    match = re.search(r'<([\w\.-]+@[\w\.-]+\.\w+)>', from_header)
    return match.group(1) if match else from_header.strip()