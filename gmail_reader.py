"""
gmail_reader.py
Connects to Gmail API and fetches meeting-related emails.
"""

import os
import base64
import re
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

MEETING_KEYWORDS = [
    'meeting', 'schedule', 'reschedule', 'postpone', 'prepone',
    'call', 'sync', 'standup', 'interview', 'appointment',
    'availability', 'invite', 'calendar', 'zoom'
]

def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None
    token_path = 'token.pickle'

    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError(
                    " credentials.json not found!\n"
                    "   Please download it from Google Cloud Console:\n"
                    "   1. Go to console.cloud.google.com\n"
                    "   2. Create a project → Enable Gmail + Calendar APIs\n"
                    "   3. Create OAuth 2.0 credentials → Download as credentials.json\n"
                    "   4. Place it in the same folder as this script."
                )
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    return build('gmail', 'v1', credentials=creds), creds

def decode_body(payload):
    """Decode email body from base64."""
    if 'body' in payload and payload['body'].get('data'):
        data = payload['body']['data']
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                data = part['body'].get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return ""

def extract_emails_from_text(text):
    """Extract email addresses from text."""
    return re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)

def fetch_meeting_emails(max_results=10):
    """
    Fetch recent emails related to meetings from Gmail.
    Returns list of parsed email dicts.
    """
    try:
        service, _ = get_gmail_service()#Unpacking the get_gmail_service (Basically to log into gmail we do this), Gm API and credentials
    except FileNotFoundError as e:
        print(e)
        return []

    query = ' OR '.join([f'subject:{kw}' for kw in MEETING_KEYWORDS])
    query += ' is:unread'

    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=max_results
    ).execute()

    messages = results.get('messages', [])
    parsed_emails = []

    for msg in messages:
        msg_data = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='full'
        ).execute()

        headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
        body = decode_body(msg_data['payload'])

        # Extract all email addresses mentioned
        all_text = body + headers.get('From', '') + headers.get('To', '') + headers.get('Cc', '')
        mentioned_emails = list(set(extract_emails_from_text(all_text)))

        from_header = headers.get('From', 'Unknown')
        subject     = headers.get('Subject', 'No Subject')

        # Skip emails sent FROM our own assistant account — these are our
        # own outgoing replies that Gmail placed back in the inbox.
        my_email = os.environ.get('MY_EMAIL', '').lower()
        sender_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
        sender_email = sender_match.group(0).lower() if sender_match else ''
        if my_email and sender_email == my_email:
            print(f"  [gmail_reader] Skipping own outgoing reply: {subject}")
            continue

        # Tag Re: emails so the pipeline routes them to reply_analyzer,
        # not meeting_analyzer — a Re: from a sender is a slot confirmation,
        # never a fresh meeting request.
        is_reply = bool(re.match(r'^re:\s*', subject.strip(), re.IGNORECASE))

        parsed_emails.append({
            'id': msg['id'],
            'from': from_header,
            'to': headers.get('To', ''),
            'cc': headers.get('Cc', ''),
            'subject': subject,
            'date': headers.get('Date', ''),
            'snippet': msg_data.get('snippet', ''),
            'body': body[:3000],
            'mentioned_emails': mentioned_emails,
            'is_reply': is_reply,
        })

    return parsed_emails