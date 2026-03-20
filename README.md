#  Gmail Calendar AI Assistant

An AI-powered email assistant that monitors your Gmail inbox, detects meeting requests, checks Google Calendar for conflicts, suggests free slots, drafts replies, and automatically creates calendar events — all hands-free.

Built with Python, NVIDIA NIM (LLaMA 3.1), and the Google APIs.

---

##  Features

- **Meeting detection** — reads unread emails and identifies scheduling requests using an LLM
- **Attendee resolution** — figures out whose calendar time is being requested from the email body, not just the headers
- **Conflict checking** — queries Google Calendar for all attendees simultaneously using the Freebusy API
- **Free slot suggestion** — finds up to 5 open windows across all attendees' working hours
- **AI reply drafting** — writes a professional reply confirming the meeting or proposing alternatives
- **Sends the reply** — dispatches the drafted email via Gmail API
- **Pending confirmation tracking** — when a conflict is found, saves the meeting as pending and waits for the sender to confirm a slot
- **Calendar event creation** — creates the Google Calendar event with all attendees once a slot is confirmed
- **Continuous watch mode** — polls Gmail every N seconds and handles everything automatically
- **Marks emails as read** — prevents reprocessing the same email on subsequent runs

---

##  Project Structure

```
email-assistant/
├── gmail_reader.py       # Fetches unread meeting emails from Gmail
├── meeting_analyzer.py   # AI brain — intent detection, attendee resolution, conflict checking
├── email_sender.py       # Sends drafted replies via Gmail API
├── calendar_creator.py   # Creates Google Calendar events
├── reply_analyzer.py     # Detects when a sender confirms a slot from our reply
├── pending_store.py      # Persists meetings awaiting sender confirmation (JSON)
├── auth_setup.py         # One-time OAuth2 setup — run this first
├── main.py               # Orchestrator — wires everything together
├── dashboard.html        # Web UI (used by --serve mode)
├── .env                  # Your secrets — never commit this
├── .gitignore
└── requirements.txt
```

---

##  Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/email-assistant.git
cd email-assistant
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Google Cloud credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project
3. Enable the **Gmail API** and **Google Calendar API**
4. Go to **APIs & Services → OAuth consent screen** → External → add your email as a test user
5. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
6. Application type: **Desktop app**
7. Download the JSON and rename it to `credentials.json`
8. Place `credentials.json` in the project folder

### 4. Create your `.env` file

```env
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx
MY_EMAIL=ai.assistant@gmail.com
LOCAL_TZ=Asia/Kolkata
POLL_INTERVAL=30
```

| Variable | Description |
|---|---|
| `NVIDIA_API_KEY` | Your NVIDIA NIM API key — get one free at [build.nvidia.com](https://build.nvidia.com) |
| `MY_EMAIL` | The Gmail address the assistant runs as (the one whose `credentials.json` you're using) |
| `LOCAL_TZ` | Your timezone — used for date parsing and calendar queries |
| `POLL_INTERVAL` | How often (seconds) to check Gmail in watch mode. Default: 30 |

### 5. Add your team members

In `meeting_analyzer.py`, fill in the `TEAM_MEMBERS` dict with everyone whose calendar the assistant should check:

```python
TEAM_MEMBERS = {
    "alice":   "alice@company.com",
    "bob":     "bob@company.com",
    "sherwin": "sherwin.advant@gmail.com",
    "sanskar": "sanskar3bhosale@gmail.com",
}
```

Name fragments are matched case-insensitively against the email body, so `"sherwin"` will match *"can Sherwin join?"*.

### 6. Share calendars with the assistant account

For the assistant to check a colleague's calendar for conflicts, they need to share their Google Calendar:

1. They open [calendar.google.com](https://calendar.google.com)
2. Hover over their calendar → **three dots → Settings and sharing**
3. Under **Share with specific people** → add `MY_EMAIL`
4. Permission: **See all event details**
5. The assistant account accepts the invite from its Gmail inbox

### 7. Authenticate (run once)

```bash
python auth_setup.py
```

A browser window will open. Log in as the assistant's Gmail account and grant all permissions. This generates `token.pickle` — you won't need to do this again.

Verify the output shows all scopes:
```
✓ token.pickle saved with scopes:
   • https://www.googleapis.com/auth/gmail.readonly
   • https://www.googleapis.com/auth/gmail.send
   • https://www.googleapis.com/auth/gmail.modify
   • https://www.googleapis.com/auth/calendar
   • https://www.googleapis.com/auth/calendar.events
✓ Gmail connected  → ai.assistant@gmail.com
✓ Calendar connected → ai.assistant@gmail.com, Holidays in India, colleague@gmail.com
```

---

##  Usage

### Run once (interactive)
```bash
python main.py
```
Processes all unread meeting emails once, then asks whether to send replies and create calendar events.

### Run once (automatic)
```bash
python main.py --send
```
Processes and sends everything without asking.

### Dry run (preview only)
```bash
python main.py --dry-run
```
Prints the analysis, drafted replies, and events that *would* be created — without actually sending or creating anything.

### Watch mode (recommended for daily use)
```bash
python main.py --watch
```
Stays running and polls Gmail every `POLL_INTERVAL` seconds. Handles new meeting requests and confirmation replies automatically. Press `Ctrl+C` to stop.

### Web dashboard
```bash
python main.py --serve
```
Opens a local web dashboard at [http://localhost:5050](http://localhost:5050) showing all processed emails, detected conflicts, free slots, and drafted replies.

---

##  How It Works

```
Unread Gmail
     │
     ▼
Is this a confirmation reply to a pending meeting?
     ├─ YES → extract confirmed slot → create calendar event → mark as read
     └─ NO  ↓
            ▼
     Detect meeting intent (LLM)
            │
            ▼
     Identify whose time is requested
     (LLM body analysis → TEAM_MEMBERS match → To/Cc fallback)
            │
            ▼
     Check Google Calendar for conflicts (Freebusy API)
            │
     ┌──────┴──────┐
   No conflict   Conflict
     │               │
     ▼               ▼
  Draft confirm   Find 5 free slots
  reply           Draft reply with alternatives
     │               │
     └──────┬─────────┘
            ▼
     Send reply via Gmail API
            │
     ┌──────┴──────┐
   No conflict   Conflict
     │               │
     ▼               ▼
  Create event   Save to pending_meetings.json
  immediately    Wait for sender to reply
                        │
                        ▼ (next poll cycle)
                 Sender confirms slot
                        │
                        ▼
                 Create calendar event
                 Remove from pending
                        │
                        ▼
                 Mark email as read
```

---

##  Configuration Reference

All configuration lives in `meeting_analyzer.py` (top section) and `.env`:

| Setting | Location | Default | Description |
|---|---|---|---|
| `TEAM_MEMBERS` | `meeting_analyzer.py` | `{}` | Name → email map for attendee resolution |
| `MY_EMAIL` | `.env` | — | The assistant's own Gmail address |
| `LOCAL_TZ` | `.env` | `Asia/Kolkata` | Timezone for all date operations |
| `POLL_INTERVAL` | `.env` | `30` | Seconds between Gmail checks in watch mode |
| `SLOT_SEARCH_DAYS` | `meeting_analyzer.py` | `7` | How many days ahead to search for free slots |
| `WORK_START_HOUR` | `meeting_analyzer.py` | `9` | Start of working day (24h) |
| `WORK_END_HOUR` | `meeting_analyzer.py` | `18` | End of working day (24h) |

---

## Security Notes

- **Never commit** `credentials.json`, `token.pickle`, or `.env` — all are in `.gitignore`
- The assistant only reads emails matching meeting-related keywords — it does not access your full inbox
- Calendar access is read-only for shared calendars; write access is only to the assistant's own `primary` calendar
- OAuth tokens are stored locally in `token.pickle` and never leave your machine

---

##  Requirements

- Python 3.10+
- A Google Cloud project with Gmail and Calendar APIs enabled
- An NVIDIA NIM API key (free tier available)
- Google accounts for the assistant and any team members whose calendars are checked

---

## Contributing

Pull requests welcome. If you add support for new features (e.g. Outlook, auto-reschedule existing events, Slack notifications), please open an issue first to discuss.

---

##  License

MIT