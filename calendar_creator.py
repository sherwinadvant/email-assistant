"""
calendar_creator.py
Creates Google Calendar events for confirmed meetings.
Called after the reply email is sent successfully.
"""

import os
import pickle
from googleapiclient.discovery import build
from dateutil import parser as date_parser
import pytz

LOCAL_TZ = pytz.timezone(os.environ.get("LOCAL_TZ", "Asia/Kolkata"))
MY_EMAIL  = os.environ.get("MY_EMAIL", "me@example.com")


def get_calendar_service():
    token_path = "token.pickle"
    if not os.path.exists(token_path):
        raise FileNotFoundError("token.pickle not found.")
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    return build("calendar", "v3", credentials=creds)


def create_event(result: dict, use_slot: dict = None, dry_run: bool = False) -> dict | None:
    """
    Creates a Google Calendar event for a confirmed meeting.

    Args:
        result    : processed email result dict from meeting_analyzer
        use_slot  : if provided, use this free slot instead of the originally proposed time
                    (pass one of the dicts from result["free_slots"])
        dry_run   : if True, prints the event but does NOT create it

    Returns:
        The created event dict from Google Calendar API, or None on failure
    """
    # ── Determine start/end times ─────────────────────────────
    if use_slot:
        start_iso = use_slot["start"]
        end_iso   = use_slot["end"]
    else:
        start_iso = result.get("proposed_start")
        end_iso   = result.get("proposed_end")

    if not start_iso or not end_iso:
        print("  ! Cannot create event — no confirmed time available.")
        return None

    # Parse and ensure timezone awareness
    start_dt = date_parser.parse(start_iso)
    end_dt   = date_parser.parse(end_iso)
    if start_dt.tzinfo is None:
        start_dt = LOCAL_TZ.localize(start_dt)
    if end_dt.tzinfo is None:
        end_dt = LOCAL_TZ.localize(end_dt)

    # ── Build attendee list ───────────────────────────────────
    attendees = [
        {"email": email}
        for email in result.get("requested_attendees", [])
        if email.lower() != MY_EMAIL.lower()  # Google adds the organiser automatically
    ]

    # Also invite the original sender if not already in attendees
    sender_email = _extract_email(result.get("from", ""))
    if sender_email and sender_email not in [a["email"] for a in attendees]:
        attendees.append({"email": sender_email})

    # ── Build event payload ───────────────────────────────────
    event = {
        "summary": result.get("meeting_title", "Meeting"),
        "description": (
            f"Scheduled automatically by AI Email Assistant.\n\n"
            f"Original email subject: {result.get('subject', '')}\n"
            f"From: {result.get('from', '')}"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": str(LOCAL_TZ),
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": str(LOCAL_TZ),
        },
        "attendees": attendees,
        # Send email invites to all attendees
        "guestsCanModifyEvent": False,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email",  "minutes": 60},
                {"method": "popup",  "minutes": 15},
            ],
        },
    }

    if dry_run:
        print(f"\n{'─'*60}")
        print(f"[DRY RUN] Would create calendar event:")
        print(f"  Title     : {event['summary']}")
        print(f"  Start     : {start_dt.strftime('%A, %d %b %Y · %I:%M %p')}")
        print(f"  End       : {end_dt.strftime('%A, %d %b %Y · %I:%M %p')}")
        print(f"  Attendees : {[a['email'] for a in attendees]}")
        print(f"{'─'*60}")
        return event

    try:
        svc = get_calendar_service()
        created = svc.events().insert(
            calendarId="primary",
            body=event,
            sendUpdates="all",   # sends Google Calendar invites to all attendees
        ).execute()

        print(f"  ✓ Calendar event created: {created.get('summary')}")
        print(f"    📅 {start_dt.strftime('%A, %d %b %Y · %I:%M %p')} → {end_dt.strftime('%I:%M %p')}")
        print(f"    🔗 {created.get('htmlLink')}")
        return created

    except Exception as e:
        print(f"  ✗ Failed to create calendar event: {e}")
        return None


def create_all_events(results: list[dict], dry_run: bool = False) -> None:
    """
    Creates calendar events only for meetings with NO conflict
    (confirmed at the originally proposed time).

    Meetings WITH conflicts are saved to pending_store and will be
    scheduled only when the sender replies confirming a slot.

    Args:
        results : list of dicts from meeting_analyzer.process_all_emails()
        dry_run : if True, prints events but does NOT create them
    """
    import pending_store

    created = 0
    pending = 0
    skipped = 0

    for r in results:
        if not r.get("is_meeting_request"):
            skipped += 1
            continue

        print(f"\nProcessing event for: {r.get('subject')}")

        if r.get("has_conflict"):
            # Don't create event yet — wait for sender to confirm a slot
            pending_store.add_pending(r)
            pending += 1
            print(f"  ⏳ Conflict detected — waiting for sender to confirm a slot.")
        else:
            # No conflict — create event at the proposed time right away
            event = create_event(r, use_slot=None, dry_run=dry_run)
            if event:
                created += 1
            else:
                skipped += 1

    mode = "dry run" if dry_run else "created"
    print(f"\n✓ Done — {created} event(s) {mode}, {pending} pending confirmation, {skipped} skipped.")


def _extract_email(from_header: str) -> str | None:
    """Extract email address from 'Name <email>' format."""
    import re
    match = re.search(r'<([\w\.-]+@[\w\.-]+\.\w+)>', from_header)
    return match.group(1) if match else from_header.strip() or None