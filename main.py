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

        elif email.get("is_reply"):
            # This Re: email was checked by reply_analyzer and is NOT a slot
            # confirmation. It could be a casual reply ("Thanks!"), an agenda
            # question, or anything else. We do NOT pass it to meeting_analyzer
            # — it is never a new meeting request. Just mark it as read and
            # move on so it doesn't reappear on every Refresh.
            print(f"  ↳ Non-confirmation reply — marking as read and skipping: {email.get('subject')}")
            confirmed_ids.append(email["id"])   # reuse confirmed_ids — both get marked read

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
        from flask import Flask, jsonify, send_file, Response
    except ImportError:
        print("Flask not installed. Run: pip install flask")
        sys.exit(1)

    app = Flask(__name__)

    @app.route("/")
    def index():
        # Serve the file directly each request — never stale, no Jinja conflicts
        if os.path.exists("dashboard.html"):
            return send_file(os.path.abspath("dashboard.html"))
        return Response("<h1>dashboard.html not found</h1>", mimetype="text/html")

    # In-memory state shared across requests within this server session
    dashboard_state = {
        "last_results": [],
        "last_refresh": None,
        "activity":     [],
    }

    def _log(msg: str, kind: str = "info"):
        dashboard_state["activity"].insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg":  msg,
            "kind": kind,
        })
        dashboard_state["activity"] = dashboard_state["activity"][:50]

    @app.route("/api/status")
    def api_status():
        """Lightweight poll — returns cached results and activity feed, no side effects."""
        return jsonify({
            "results":      dashboard_state["last_results"],
            "activity":     dashboard_state["activity"],
            "last_refresh": dashboard_state["last_refresh"],
        })

    @app.route("/api/refresh")
    def api_refresh():
        """
        Fast Gmail fetch — no LLM, no send, no calendar.
        Returns raw email list for the sidebar immediately.
        Fetches unread meeting emails from the last 7 days.
        """
        try:
            from gmail_reader import get_gmail_service, MEETING_KEYWORDS, decode_body
            import re as _re
            svc, _ = get_gmail_service()

            subject_terms = ' OR '.join([f'subject:{kw}' for kw in MEETING_KEYWORDS])
            body_terms    = ' OR '.join(MEETING_KEYWORDS)
            query = f'({subject_terms} OR {body_terms}) is:unread newer_than:7d'

            res      = svc.users().messages().list(userId='me', q=query, maxResults=20).execute()
            messages = res.get('messages', [])

            emails = []
            for msg in messages:
                md      = svc.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                headers = {h['name']: h['value'] for h in md['payload']['headers']}
                emails.append({
                    'id':      msg['id'],
                    'subject': headers.get('Subject', 'No Subject'),
                    'from':    headers.get('From', 'Unknown'),
                    'date':    headers.get('Date', ''),
                    'snippet': md.get('snippet', '')[:120],
                    'unread':  True,
                    # Placeholder flags — Preview will fill these in properly
                    'is_meeting_request': True,
                    'has_conflict': False,
                })

            dashboard_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
            _log(f"Gmail refreshed — {len(emails)} unread meeting email(s) found.", "info")
            return jsonify({"status": "ok" if emails else "no_emails", "results": emails})

        except Exception as e:
            _log(f"Refresh error: {e}", "error")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/sync")
    def api_sync():
        """
        Fetch emails from Gmail (unread AND recently read) and return raw
        metadata for the sidebar — no LLM analysis, no send, no calendar.
        This is just a fast Gmail refresh so the user can see what's there.
        """
        from gmail_reader import fetch_meeting_emails as _fetch

        # Also pull in emails that were already read (last 2 days) so the
        # dashboard isn't blank after a --send run marks everything as read.
        try:
            svc, _ = __import__('gmail_reader').get_gmail_service()
            from gmail_reader import MEETING_KEYWORDS, decode_body, extract_emails_from_text
            import base64 as _b64

            subject_terms = ' OR '.join([f'subject:{kw}' for kw in MEETING_KEYWORDS])
            body_terms    = ' OR '.join(MEETING_KEYWORDS)
            # No is:unread filter here — show everything recent
            query = f'({subject_terms} OR {body_terms}) newer_than:3d'

            res = svc.users().messages().list(userId='me', q=query, maxResults=20).execute()
            messages = res.get('messages', [])

            emails = []
            for msg in messages:
                md = svc.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                headers = {h['name']: h['value'] for h in md['payload']['headers']}
                body    = decode_body(md['payload'])
                labels  = md.get('labelIds', [])
                emails.append({
                    'id':       msg['id'],
                    'subject':  headers.get('Subject', 'No Subject'),
                    'from':     headers.get('From', 'Unknown'),
                    'date':     headers.get('Date', ''),
                    'snippet':  md.get('snippet', '')[:120],
                    'unread':   'UNREAD' in labels,
                    'is_meeting_request': True,   # lightweight — just show it; Preview will analyse
                })
        except Exception as e:
            _log(f'Sync error: {e}', 'error')
            return jsonify({'status': 'error', 'message': str(e)}), 500

        if not emails:
            _log('Sync: no meeting emails found in the last 3 days.', 'info')
            dashboard_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
            return jsonify({'status': 'no_emails', 'results': []})

        _log(f'Sync: found {len(emails)} email(s) — click Preview to analyse.', 'info')
        dashboard_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
        # Store raw emails so Preview can act on them without re-fetching
        dashboard_state["synced_emails"] = emails
        return jsonify({'status': 'ok', 'results': emails})

    @app.route("/api/preview")
    def api_preview():
        """
        Fetch + analyse emails. Does NOT send or schedule anything.
        Looks at unread emails first; if none found, also checks emails
        read in the last 3 days so the dashboard works after a --send run.
        """
        emails = fetch_meeting_emails(max_results=15)

        if not emails:
            # Fallback: also check recently-read meeting emails (last 3 days)
            try:
                svc, _ = __import__('gmail_reader').get_gmail_service()
                from gmail_reader import MEETING_KEYWORDS, decode_body, extract_emails_from_text
                subject_terms = ' OR '.join([f'subject:{kw}' for kw in MEETING_KEYWORDS])
                body_terms    = ' OR '.join(MEETING_KEYWORDS)
                query = f'({subject_terms} OR {body_terms}) newer_than:3d'
                res = svc.users().messages().list(userId='me', q=query, maxResults=15).execute()
                raw_msgs = res.get('messages', [])
                for msg in raw_msgs:
                    md      = svc.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                    headers = {h['name']: h['value'] for h in md['payload']['headers']}
                    body    = decode_body(md['payload'])
                    all_text = body + headers.get('From','') + headers.get('To','') + headers.get('Cc','')
                    import re as _re
                    mentioned = list(set(_re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', all_text)))
                    emails.append({
                        'id':               msg['id'],
                        'from':             headers.get('From','Unknown'),
                        'to':               headers.get('To',''),
                        'cc':               headers.get('Cc',''),
                        'subject':          headers.get('Subject','No Subject'),
                        'date':             headers.get('Date',''),
                        'snippet':          md.get('snippet',''),
                        'body':             body[:3000],
                        'mentioned_emails': mentioned,
                    })
            except Exception as e:
                _log(f"Preview fetch error: {e}", "error")

        if not emails:
            _log("No meeting emails found (unread or recent).", "info")
            dashboard_state["last_results"] = []
            dashboard_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
            return jsonify({"status": "no_emails", "results": []})

        _log(f"Fetched {len(emails)} email(s) — analysing…", "info")

        remaining, confirmed_ids = _split_confirmation_replies(emails)
        if confirmed_ids:
            mark_as_read(confirmed_ids)
            _log(f"Auto-confirmed {len(confirmed_ids)} slot reply(s).", "success")

        results = process_all_emails(remaining)
        meeting_count  = sum(1 for r in results if r.get("is_meeting_request"))
        conflict_count = sum(1 for r in results if r.get("has_conflict"))
        _log(
            f"Preview ready — {meeting_count} meeting(s), {conflict_count} conflict(s). "
            "Review below, then click Send & Schedule.",
            "success" if not conflict_count else "warn",
        )

        dashboard_state["last_results"] = results
        dashboard_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
        return jsonify({"status": "ok", "results": results})

    @app.route("/api/process")
    def api_process():
        """Send replies + create events for the last previewed batch."""
        results = dashboard_state.get("last_results", [])
        if not results:
            return jsonify({"status": "error", "message": "Run Preview first."}), 400

        meeting_results = [r for r in results if r.get("is_meeting_request")]
        if not meeting_results:
            return jsonify({"status": "no_meetings", "message": "No meeting requests to act on."})

        _log(f"Sending {len(meeting_results)} reply(s)…", "info")
        send_all_replies(results, dry_run=False)
        _log("Replies sent.", "success")

        _log("Creating calendar events…", "info")
        create_all_events(results, dry_run=False)
        _log("Calendar events created.", "success")

        processed_ids = [r.get("email_id") for r in results if r.get("email_id")]
        mark_as_read(processed_ids)

        # Clear cache so the same batch can't be accidentally sent twice
        dashboard_state["last_results"] = []

        return jsonify({"status": "ok", "sent": len(meeting_results)})

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