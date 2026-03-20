"""
main.py
Entry point for the Gmail Calendar Assistant.

Usage:
    python main.py              # run once, ask before sending
    python main.py --send       # run once, send automatically
    python main.py --dry-run    # run once, print only
    python main.py --watch      # continuous polling loop (recommended)
    python main.py --serve      # web dashboard (port 5050)
"""

import sys
import time
import os
import argparse
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

print("[ENV CHECK] NVIDIA_API_KEY set:", bool(os.environ.get("NVIDIA_API_KEY")))
print("[ENV CHECK] .env loaded from:", os.path.abspath(".env"))

# ── Import gmail_reader ───────────────────────────────────────────────────────
try:
    from gmail_reader import fetch_meeting_emails, get_gmail_service
except ImportError:
    def fetch_meeting_emails(max_results=10):
        print("[WARN] gmail_reader.py not found.")
        return []
    def get_gmail_service():
        raise FileNotFoundError("gmail_reader.py not found.")

from meeting_analyzer import process_all_emails
from email_sender import send_all_replies
from calendar_creator import create_all_events

# How often to poll Gmail in watch mode (seconds)
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))


# ── Mark emails as read ───────────────────────────────────────────────────────

def mark_as_read(email_ids: list[str]):
    """Remove the UNREAD label so processed emails are never picked up again."""
    if not email_ids:
        return
    try:
        service, _ = get_gmail_service()
        for email_id in email_ids:
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        print(f"  ✓ Marked {len(email_ids)} email(s) as read.")
    except Exception as e:
        print(f"  ! Could not mark emails as read: {e}")


# ── Confirmation reply handling ───────────────────────────────────────────────

def _extract_email(from_header: str) -> str:
    import re
    match = re.search(r'<([\w\.-]+@[\w\.-]+\.\w+)>', from_header)
    return match.group(1) if match else from_header.strip()


def _split_confirmation_replies(emails: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Check each email against pending_store.
    Returns (remaining_new_emails, list_of_confirmed_email_ids).
    Confirmed ones get their calendar event created immediately.
    """
    from reply_analyzer import analyze_confirmation_reply
    from calendar_creator import create_event
    import pending_store

    remaining    = []
    confirmed_ids = []

    for email in emails:
        result = analyze_confirmation_reply(email)

        if result["is_confirmation"]:
            slot    = result["confirmed_slot"]
            pending = result["pending"]
            sender  = _extract_email(email.get("from", ""))

            print(f"\n{'='*60}")
            print(f"✅ Slot confirmed by {sender}: {slot['label']}")
            print(f"   Meeting: {pending.get('meeting_title')}")

            # Build the result dict create_event() expects
            event_result = {
                "meeting_title":       pending.get("meeting_title"),
                "subject":             pending.get("subject"),
                "from":                pending.get("from"),
                "requested_attendees": pending.get("requested_attendees", []),
                "proposed_start":      slot["start"],
                "proposed_end":        slot["end"],
                "has_conflict":        False,
            }
            create_event(event_result, use_slot=None, dry_run=False)
            pending_store.remove_pending(sender, pending.get("subject", ""))
            confirmed_ids.append(email["id"])
        else:
            remaining.append(email)

    return remaining, confirmed_ids


# ── Single processing cycle ───────────────────────────────────────────────────

def run_cycle(auto_send=False, dry_run=False) -> bool:
    """
    One full cycle: fetch → confirmations → analyze → reply → events → mark read.
    Returns True if any emails were found.
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking Gmail…")
    emails = fetch_meeting_emails(max_results=15)

    if not emails:
        print("  No unread meeting emails.")
        return False

    print(f"  Found {len(emails)} email(s).\n")

    # ── Step 1: Confirmation replies ─────────────────────────────────────────
    remaining, confirmed_ids = _split_confirmation_replies(emails)
    if confirmed_ids:
        mark_as_read(confirmed_ids)   # ← mark confirmed replies as read

    if not remaining:
        return True

    # ── Step 2: Analyze new meeting requests ─────────────────────────────────
    results = process_all_emails(remaining)
    processed_ids = [r.get("email_id") for r in results if r.get("email_id")]

    for r in results:
        print(f"\n{'═'*60}")
        print(f"📧  {r['subject']}")
        if not r.get("is_meeting_request"):
            print(f"    ↳ Not a meeting request — skipped.")
            continue
        print(f"    From            : {r.get('from')}")
        print(f"    Meeting title   : {r.get('meeting_title')}")
        print(f"    Proposed time   : {r.get('proposed_start')} → {r.get('proposed_end')}")
        print(f"    Attendees needed: {', '.join(r.get('requested_attendees', []))}")
        print(f"    Conflicts       : {'YES ⚠️' if r.get('has_conflict') else 'None ✅'}")
        if r.get("free_slots"):
            print("    Free slots      :")
            for s in r["free_slots"]:
                print(f"      • {s['label']}")
        if r.get("suggested_reply"):
            print(f"\n    ── Suggested reply ──────────────────────────────────")
            for line in r["suggested_reply"].split("\n"):
                print(f"    {line}")

    meeting_results = [r for r in results if r.get("is_meeting_request")]
    if not meeting_results:
        mark_as_read(processed_ids)   # ← mark non-meeting emails as read too
        return True

    print(f"\n{'═'*60}")

    # ── Step 3: Send replies + create events ─────────────────────────────────
    if dry_run:
        send_all_replies(results, dry_run=True)
        create_all_events(results, dry_run=True)

    elif auto_send:
        send_all_replies(results, dry_run=False)
        create_all_events(results, dry_run=False)
        mark_as_read(processed_ids)   # ← mark as read after sending

    else:
        # Interactive mode
        print(f"\n📨  Send {len(meeting_results)} drafted reply email(s)? [y/N]: ", end="", flush=True)
        if input().strip().lower() == "y":
            send_all_replies(results, dry_run=False)

        print(f"\n📅  Create calendar event(s) for these meetings? [y/N]: ", end="", flush=True)
        if input().strip().lower() == "y":
            create_all_events(results, dry_run=False)

        mark_as_read(processed_ids)   # ← always mark as read once user has seen them

    return True


# ── Watch mode ────────────────────────────────────────────────────────────────

def run_watch():
    """
    Poll Gmail every POLL_INTERVAL seconds automatically.
    Handles both new meeting requests AND confirmation replies.
    Press Ctrl+C to stop.
    """
    print(f"👀  Watch mode — polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.\n")
    while True:
        try:
            run_cycle(auto_send=True)
            print(f"\n  ⏱  Next check in {POLL_INTERVAL}s…")
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n\nStopped.")
            break
        except Exception as e:
            print(f"\n[ERROR] {e} — retrying in {POLL_INTERVAL}s…")
            time.sleep(POLL_INTERVAL)


# ── Web dashboard ─────────────────────────────────────────────────────────────

def run_dashboard():
    try:
        from flask import Flask, jsonify, render_template_string
    except ImportError:
        print("Flask not installed. Run: pip install flask")
        sys.exit(1)

    app = Flask(__name__)
    DASHBOARD_HTML = (open("dashboard.html").read()
                      if os.path.exists("dashboard.html")
                      else "<h1>dashboard.html not found</h1>")

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/process")
    def api_process():
        emails = fetch_meeting_emails(max_results=15)
        results = process_all_emails(emails)
        return jsonify(results)

    print("Starting dashboard at http://localhost:5050")
    app.run(port=5050, debug=False)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gmail Calendar Assistant")
    parser.add_argument("--serve",   action="store_true", help="Web dashboard")
    parser.add_argument("--send",    action="store_true", help="Auto-send without asking")
    parser.add_argument("--dry-run", action="store_true", help="Print only, do not send")
    parser.add_argument("--watch",   action="store_true", help="Continuous polling loop")
    args = parser.parse_args()

    if args.serve:
        run_dashboard()
    elif args.watch:
        run_watch()
    else:
        run_cycle(auto_send=args.send, dry_run=args.dry_run)