"""
debug_gmail.py
Run this to diagnose why emails aren't being fetched.
It bypasses ALL keyword filtering and just pulls your last 10 unread emails raw.
"""
import pickle, base64, re
from googleapiclient.discovery import build

print("Step 1: Loading token.pickle...")
with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
print(f"  Token valid     : {creds.valid}")
print(f"  Token expired   : {creds.expired}")
print(f"  Has refresh tok : {bool(creds.refresh_token)}")
print(f"  Scopes          : {creds.scopes}")

svc = build("gmail", "v1", credentials=creds)
print("\nStep 2: Fetching last 10 UNREAD emails (no keyword filter)...")
res = svc.users().messages().list(userId="me", q="is:unread", maxResults=10).execute()
messages = res.get("messages", [])
print(f"  Found {len(messages)} unread message(s).\n")

for msg in messages:
    data = svc.users().messages().get(userId="me", id=msg["id"], format="full").execute()
    headers = {h["name"]: h["value"] for h in data["payload"]["headers"]}
    print(f"  Subject : {headers.get('Subject', '(none)')}")
    print(f"  From    : {headers.get('From', '(none)')}")
    print(f"  Date    : {headers.get('Date', '(none)')}")
    print(f"  Snippet : {data.get('snippet','')[:80]}")
    print()

print("Step 3: Now testing YOUR keyword query...")
from gmail_reader import MEETING_KEYWORDS
subject_terms = ' OR '.join([f'subject:{kw}' for kw in MEETING_KEYWORDS])
body_terms    = ' OR '.join(MEETING_KEYWORDS)
query = f'({subject_terms} OR {body_terms}) is:unread'
print(f"  Query: {query}\n")
res2 = svc.users().messages().list(userId="me", q=query, maxResults=10).execute()
messages2 = res2.get("messages", [])
print(f"  Emails matched by keyword query: {len(messages2)}")
if not messages2:
    print("\n  !! Your unread emails exist but NONE match the keyword filter.")
    print("     Add keywords from your email's subject to MEETING_KEYWORDS in gmail_reader.py")