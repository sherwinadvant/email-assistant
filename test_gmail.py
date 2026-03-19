"""
test_gmail.py
Run this standalone to test if Gmail authentication and email fetching works.
"""

from gmail_reader import fetch_meeting_emails

print(" Authenticating with Gmail...")
print("   (A browser window will open on first run — log in and grant access)\n")

emails = fetch_meeting_emails(max_results=2)

if not emails:
    print("!!  No meeting-related emails found, or authentication failed.")
else:
    print(f" Successfully fetched {len(emails)} email(s):\n")
    for i, email in enumerate(emails, 1):
        print(f"{'='*60}")
        print(f"[{i}] From    : {email['from']}")
        print(f"    To      : {email['to']}")
        print(f"    Subject : {email['subject']}")
        print(f"    Date    : {email['date']}")
        print(f"    Snippet : {email['snippet'][:100]}...")
        print(f"    Emails found in thread: {email['mentioned_emails']}")
        print(f"    Body preview:\n")
        print(email['body'][:300])
        print()
