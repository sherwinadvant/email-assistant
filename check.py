# test_calendar_access.py
import pickle
from googleapiclient.discovery import build

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)

svc = build("calendar", "v3", credentials=creds)

# List all calendars the assistant can see
calendars = svc.calendarList().list().execute()
for cal in calendars["items"]:
    print(cal["id"], "→", cal["summary"])# test_calendar_access.py
import pickle
from googleapiclient.discovery import build

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)

svc = build("calendar", "v3", credentials=creds)

# List all calendars the assistant can see
calendars = svc.calendarList().list().execute()
for cal in calendars["items"]:
    print(cal["id"], "→", cal["summary"])