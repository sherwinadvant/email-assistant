"""
email_sender.py
Sends AI-drafted reply emails via Gmail API.
"""

import os
import pickle
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build


def get_gmail_service():
    token_path = "token.pickle"
    if not os.path.exists(token_path):
        raise FileNotFoundError("token.pickle not found.")
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    return build("gmail", "v1", credentials=creds)


def send_reply(original_email: dict, reply_body: str, dry_run: bool = False) -> bool:
    """
    Sends a reply to the original email's sender.

    Args:
        original_email : parsed email dict from gmail_reader.py
        reply_body     : the AI-drafted reply text
        dry_run        : if True, prints the email but does NOT send it

    Returns:
        True if sent (or dry_run), False on error
    """
    # Extract reply-to address — sender of the original email
    from_header = original_email.get("from", "")
    # Parse "Name <email@domain.com>" format
    import re
    match = re.search(r'<([\w\.-]+@[\w\.-]+\.\w+)>', from_header)
    to_address = match.group(1) if match else from_header.strip()

    subject = original_email.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    # Build the MIME message
    msg = MIMEMultipart("alternative")
    msg["To"]      = to_address
    msg["Subject"] = subject

    # Plain text part
    msg.attach(MIMEText(reply_body, "plain"))

    # Thread it as a reply if we have the message ID
    msg_id = original_email.get("id")
    if msg_id:
        msg["In-Reply-To"]  = msg_id
        msg["References"]   = msg_id

    if dry_run:
        print(f"\n{'─'*60}")
        print(f"[DRY RUN] Would send email:")
        print(f"  To      : {to_address}")
        print(f"  Subject : {subject}")
        print(f"  Body    :\n{reply_body}")
        print(f"{'─'*60}")
        return True

    try:
        svc = get_gmail_service()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent_msg = svc.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()
        print(f"  ✓ Reply sent to {to_address}  [Gmail message id: {sent_msg.get('id')}]")
        return True
    except Exception as e:
        print(f"  ✗ Failed to send reply to {to_address}: {e}")
        print(f"    → Check that token.pickle has the 'gmail.send' scope.")
        return False


def send_all_replies(results: list[dict], dry_run: bool = False) -> None:
    """
    Send replies for all processed emails that are meeting requests.

    Args:
        results : list of dicts returned by meeting_analyzer.process_all_emails()
        dry_run : if True, prints emails but does NOT send them
    """
    sent = 0
    skipped = 0

    for r in results:
        if not r.get("is_meeting_request"):
            skipped += 1
            continue
        if not r.get("suggested_reply"):
            print(f"  ! No reply drafted for: {r.get('subject')} — skipping")
            skipped += 1
            continue

        # Reconstruct minimal original_email dict needed for send_reply
        original_email = {
            "id":      r.get("email_id"),
            "from":    r.get("from"),
            "subject": r.get("subject"),
        }

        print(f"\nSending reply for: {r.get('subject')}")
        success = send_reply(original_email, r["suggested_reply"], dry_run=dry_run)
        if success:
            sent += 1
        else:
            skipped += 1

    mode = "dry run" if dry_run else "sent"
    print(f"\n✓ Done — {sent} email(s) {mode}, {skipped} skipped.")