"""
auth_setup.py
Run this ONCE to generate token.pickle with the correct Gmail + Calendar scopes.
Place credentials.json in the same folder, then run:
    python auth_setup.py
"""

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send', 
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
]

def main():
    creds = None
    token_path = 'token.pickle'

    # If a token exists, check if it covers all needed scopes
    if os.path.exists(token_path):
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
        if creds and creds.valid:
            missing = [s for s in SCOPES if s not in (creds.scopes or [])]
            if missing:
                print(f"⚠ Existing token is missing scopes: {missing}")
                print("  Deleting token.pickle and re-authenticating...")
                os.remove(token_path)
                creds = None
        elif creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())

    # Fresh auth flow
    if not creds or not creds.valid:
        if not os.path.exists('credentials.json'):
            print("✗ credentials.json not found in current directory.")
            print("  Download it from Google Cloud Console → APIs & Services → Credentials")
            return

        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)

        with open(token_path, 'wb') as f:
            pickle.dump(creds, f)
        print(f"✓ token.pickle saved with scopes:")
        for s in creds.scopes or []:
            print(f"   • {s}")

    # Quick sanity checks
    print("\nRunning sanity checks...")

    try:
        gmail = build('gmail', 'v1', credentials=creds)
        profile = gmail.users().getProfile(userId='me').execute()
        print(f"✓ Gmail connected  → {profile['emailAddress']}")
    except Exception as e:
        print(f"✗ Gmail check failed: {e}")

    try:
        cal = build('calendar', 'v3', credentials=creds)
        calendars = cal.calendarList().list().execute()
        names = [c['summary'] for c in calendars.get('items', [])[:3]]
        print(f"✓ Calendar connected → {', '.join(names)}")
    except Exception as e:
        print(f"✗ Calendar check failed: {e}")

    print("\nAll done! You can now run:  python main.py")

if __name__ == '__main__':
    main()