"""
reply_analyzer.py
Detects when a sender replies to a conflict email and confirms a specific time slot.
Matches their reply against the free slots we offered and triggers event creation.
"""

import json
import re
import os
from dotenv import load_dotenv
load_dotenv()

import pending_store
from calendar_creator import create_event
from meeting_analyzer import call_llm


def analyze_confirmation_reply(email: dict) -> dict:
    """
    Given an incoming email, check if it's a reply confirming one of our
    suggested time slots.

    Returns:
    {
        "is_confirmation": bool,
        "confirmed_slot":  dict | None,   # one of the free_slots dicts
        "pending":         dict | None,   # the original pending meeting
    }
    """
    sender_email = _extract_email(email.get("from", ""))
    subject      = email.get("subject", "")
    body         = email.get("body", "")

    # Check if this matches any pending meeting
    pending = pending_store.find_pending(sender_email, subject)
    if not pending:
        return {"is_confirmation": False, "confirmed_slot": None, "pending": None}

    free_slots = pending.get("free_slots", [])
    if not free_slots:
        return {"is_confirmation": False, "confirmed_slot": None, "pending": pending}

    # Ask the LLM to match the reply against the offered slots
    slots_text = "\n".join(
        [f"  Slot {i+1}: {s['label']} (start: {s['start']}, end: {s['end']})"
         for i, s in enumerate(free_slots)]
    )

    prompt = f"""
We previously offered these time slots for a meeting:
{slots_text}

The person replied with this message:
\"\"\"{body[:1000]}\"\"\"

Did they confirm one of the offered slots? If yes, which slot number did they choose?
Also check if they proposed a completely different time.

Return ONLY a JSON object:
{{
  "confirmed": true or false,
  "slot_number": integer (1-based index from the list above) or null,
  "different_time_proposed": "ISO datetime string if they proposed a new time, else null"
}}
"""
    raw = call_llm(prompt, system="Return only valid JSON. No markdown, no explanation.")
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        info = json.loads(raw)
    except Exception:
        info = {"confirmed": False}

    if info.get("confirmed") and info.get("slot_number"):
        idx = info["slot_number"] - 1
        if 0 <= idx < len(free_slots):
            confirmed_slot = free_slots[idx]
            return {
                "is_confirmation": True,
                "confirmed_slot":  confirmed_slot,
                "pending":         pending,
            }

    return {"is_confirmation": False, "confirmed_slot": None, "pending": pending}


def process_confirmation_replies(emails: list[dict]) -> list[dict]:
    """
    Go through a list of emails and handle any that are confirmations
    of pending meetings. Creates calendar events for confirmed ones.

    Returns list of emails that were NOT confirmations (for normal processing).
    """
    remaining = []

    for email in emails:
        result = analyze_confirmation_reply(email)

        if result["is_confirmation"]:
            slot    = result["confirmed_slot"]
            pending = result["pending"]
            sender  = _extract_email(email.get("from", ""))

            print(f"\n{'='*60}")
            print(f"✅ Confirmation received for: {pending.get('subject')}")
            print(f"   Confirmed slot: {slot['label']}")

            # Build a result dict compatible with create_event()
            event_result = {
                "meeting_title":       pending.get("meeting_title"),
                "subject":             pending.get("subject"),
                "from":                pending.get("from"),
                "requested_attendees": pending.get("requested_attendees", []),
                "proposed_start":      slot["start"],
                "proposed_end":        slot["end"],
                "has_conflict":        False,
            }

            created = create_event(event_result, use_slot=None, dry_run=False)
            if created:
                # Remove from pending store — it's been scheduled
                pending_store.remove_pending(sender, pending.get("subject", ""))
        else:
            remaining.append(email)

    return remaining


def _extract_email(from_header: str) -> str:
    match = re.search(r'<([\w\.-]+@[\w\.-]+\.\w+)>', from_header)
    return match.group(1) if match else from_header.strip()