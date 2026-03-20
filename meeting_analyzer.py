"""
meeting_analyzer.py
AI-powered layer that sits on top of gmail_reader.py
Determines WHOSE calendar time is being requested, checks for conflicts,
and suggests resolutions.
"""
from dotenv import load_dotenv
import os

load_dotenv()
print("[ENV CHECK] NVIDIA_API_KEY set:", bool(os.environ.get("NVIDIA_API_KEY")))
print("[ENV CHECK] .env loaded from:", os.path.abspath(".env"))
#import os
import re
import json
from datetime import datetime, timedelta
from dateutil import parser as date_parser
import pytz
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import pickle

# ─── CONFIG ──────────────────────────────────────────────────────────────────

# Your team's known members: map name fragments / email patterns to their
# primary calendar email.  Add every person whose calendar you manage here.
SLOT_SEARCH_DAYS = 7   # how far ahead to search
WORK_START_HOUR  = 9   # 9 AM
WORK_END_HOUR    = 18  # 6 PM
TEAM_MEMBERS = {
     "sherwin":   "sherwin.advant@gmail.com",
     "sanskar":     "sanskar3bhosale@gmail.com",
     "sharma":  "rahul.sharma@company.com",
}

# The primary user (owner of the OAuth token / the person running this script)
MY_EMAIL = os.environ.get("MY_EMAIL", "me@example.com")

# Timezone for all calendar operations
LOCAL_TZ = pytz.timezone(os.environ.get("LOCAL_TZ", "Asia/Kolkata"))

# How many days ahead to search for free slots
SLOT_SEARCH_DAYS = 7

# Working hours (24h)
WORK_START_HOUR = 9
WORK_END_HOUR   = 18

# ─── NVIDIA / OPENAI-COMPATIBLE LLM CALL ─────────────────────────────────────

def call_llm(prompt: str, system: str = "") -> str:
    """
    Call NVIDIA NIM (or any OpenAI-compatible endpoint).
    Set NVIDIA_API_KEY and optionally NVIDIA_BASE_URL in your environment.
    Falls back to a simple heuristic if the key is missing.
    """
    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    model    = os.environ.get("LLM_MODEL", "meta/llama-3.1-70b-instruct")

    if not api_key:
        # Graceful degradation: return empty JSON so callers handle it
        return "{}"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1024,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "{}"


# ─── CALENDAR SERVICE ─────────────────────────────────────────────────────────

def get_calendar_service():
    """Return an authenticated Google Calendar service using stored token."""
    token_path = "token.pickle"
    if not os.path.exists(token_path):
        raise FileNotFoundError("token.pickle not found. Run gmail_reader.py first to authenticate.")
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    return build("calendar", "v3", credentials=creds)


# ─── STEP 1 : IDENTIFY WHOSE TIME IS REQUESTED ───────────────────────────────

def identify_requested_attendees(email: dict) -> list[str]:
    """
    Core problem you asked to solve.
    Returns a list of calendar emails whose time is being requested.

    Strategy (layered):
      1. Ask the LLM to extract person references from the body.
      2. Match those references against TEAM_MEMBERS.
      3. Fall back to To/Cc headers if nothing matched in the body.
      4. Always include MY_EMAIL as a fallback of last resort.
    """
    body    = email.get("body", "")
    subject = email.get("subject", "")
    to      = email.get("to", "")
    cc      = email.get("cc", "")

    # --- Layer 1: LLM extraction ---
    llm_prompt = f"""
You are a scheduling assistant. Given the email below, list the names or email addresses
of the people whose calendar time is being requested (i.e. the people who are supposed
to ATTEND the proposed meeting, not the sender).

Return ONLY a JSON array of strings, e.g. ["Alice Smith", "bob@acme.com"].
If you cannot determine anyone, return [].

Subject: {subject}
Body:
{body[:2000]}
"""
    raw = call_llm(llm_prompt, system="Return only valid JSON. No markdown, no explanation.")
    # Parse LLM JSON
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        mentions = json.loads(raw) if raw.startswith("[") else []
    except Exception:
        mentions = []

    resolved = set()

    # --- Layer 2: Match LLM mentions against known team members ---
    for mention in mentions:
        mention_lower = mention.lower()
        # Exact email match
        if "@" in mention and mention.lower() in [v.lower() for v in TEAM_MEMBERS.values()]:
            resolved.add(mention.lower())
            continue
        # Name fragment match
        for name_key, cal_email in TEAM_MEMBERS.items():
            if name_key in mention_lower or mention_lower in name_key:
                resolved.add(cal_email)

    # --- Layer 3: Fall back to To / Cc headers ---
    if not resolved:
        all_header_emails = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", to + " " + cc)
        for em in all_header_emails:
            if em.lower() != email.get("from", "").lower():
                # Check if this email belongs to a known team member
                if em.lower() in [v.lower() for v in TEAM_MEMBERS.values()]:
                    resolved.add(em.lower())

    # --- Layer 4: Last resort — assume MY_EMAIL ---
    if not resolved:
        resolved.add(MY_EMAIL)

    return list(resolved)


# ─── STEP 2 : DETECT MEETING REQUEST & EXTRACT PROPOSED TIME ─────────────────

def analyze_meeting_intent(email: dict) -> dict:
    """
    Returns a dict:
    {
        "is_meeting_request": bool,
        "proposed_start":     ISO datetime str or None,
        "proposed_end":       ISO datetime str or None,
        "duration_minutes":   int or None,
        "meeting_title":      str,
        "requested_attendees": [emails],
        "raw_time_mention":   str   # what the sender actually wrote
    }
    """
    body    = email.get("body", "")
    subject = email.get("subject", "")

    now         = datetime.now(LOCAL_TZ)
    today_str   = now.strftime("%A, %d %B %Y")   # e.g. "Friday, 21 March 2026"
    now_iso     = now.isoformat()

    llm_prompt = f"""
Analyze this email and extract meeting/scheduling information.

TODAY is {today_str} (ISO: {now_iso}).
You MUST resolve ALL relative date references (like "tomorrow", "this Friday",
"next Monday", "in 2 days") into exact calendar dates using today's date above.

Return a JSON object with these exact keys:
{{
  "is_meeting_request": true or false,
  "raw_time_mention": "the exact time/date phrase the sender wrote, or null",
  "proposed_start_iso": "ISO 8601 datetime with timezone offset, e.g. 2026-03-22T17:00:00+05:30 — NEVER null if any time is mentioned",
  "proposed_end_iso": "ISO 8601 datetime if explicitly mentioned, else null",
  "duration_minutes": integer if mentioned (e.g. '1 hour' = 60), else 60,
  "meeting_title": "short title for the event"
}}

Timezone is Asia/Kolkata (+05:30) unless the email says otherwise.

Subject: {subject}
Body:
{body[:2000]}
"""
    raw = call_llm(llm_prompt, system="Return only valid JSON. No markdown, no explanation.")
    print(f"  [DEBUG] LLM raw response: {repr(raw)}")
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        info = json.loads(raw)
        print(f"  [DEBUG] Parsed info: {info}")
    except Exception as e:
        print(f"  [DEBUG] JSON parse error: {e}")
        info = {"is_meeting_request": False}
    # Resolve attendees
    info["requested_attendees"] = identify_requested_attendees(email)

    # Parse ISO strings to aware datetimes
    for key in ("proposed_start_iso", "proposed_end_iso"):
        val = info.get(key)
        if val:
            try:
                dt = date_parser.parse(val)
                if dt.tzinfo is None:
                    dt = LOCAL_TZ.localize(dt)
                info[key] = dt.isoformat()
            except Exception:
                info[key] = None

    return info


# ─── STEP 3 : CHECK CALENDAR FOR CONFLICTS ───────────────────────────────────

def check_conflicts(calendar_email: str, start_iso: str, end_iso: str) -> list[dict]:
    """
    Returns list of conflicting events for calendar_email between start and end.
    Only your own calendar (MY_EMAIL) is readable via OAuth.
    Other attendees' calendars return 404 unless they've shared with you.
    """
    try:
        svc = get_calendar_service()
    except FileNotFoundError as e:
        print(f"[Calendar] {e}")
        return []

    # Map to 'primary' if this is the authenticated user's own email
    cal_id = "primary" if calendar_email.lower() == MY_EMAIL.lower() else calendar_email

    try:
        events_result = svc.events().list(
            calendarId=cal_id,
            timeMin=start_iso,
            timeMax=end_iso,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return events_result.get("items", [])
    except Exception as e:
        # 404 means we don't have access to this person's calendar — skip silently
        if "404" in str(e):
            print(f"  ℹ [{calendar_email}] Calendar not shared with you — skipping conflict check for them")
        else:
            print(f"[Calendar] Could not fetch events for {calendar_email}: {e}")
        return []


# ─── STEP 4 : FIND FREE SLOTS ─────────────────────────────────────────────────

def find_free_slots(attendees: list[str], duration_minutes: int, after_iso: str) -> list[dict]:
    """
    Returns up to 5 free time slots where ALL attendees are available.
    """
    try:
        svc = get_calendar_service()
    except FileNotFoundError:
        return []

    search_start = date_parser.parse(after_iso)
    if search_start.tzinfo is None:
        search_start = LOCAL_TZ.localize(search_start)
    search_end = search_start + timedelta(days=SLOT_SEARCH_DAYS)

    try:
        body = {
            "timeMin": search_start.isoformat(),
            "timeMax": search_end.isoformat(),
            "timeZone": str(LOCAL_TZ),
            # Use 'primary' for own calendar, actual email for shared ones
            "items": [
                {"id": "primary" if a.lower() == MY_EMAIL.lower() else a}
                for a in attendees
            ],
        }
        freebusy = svc.freebusy().query(body=body).execute()
    except Exception as e:
        print(f"[Calendar] Freebusy error: {e}")
        return []

    # Collect all busy intervals
    busy_intervals = []
    for cal_id, cal_info in freebusy.get("calendars", {}).items():
        for period in cal_info.get("busy", []):
            busy_intervals.append((
                date_parser.parse(period["start"]),
                date_parser.parse(period["end"]),
            ))
    busy_intervals.sort(key=lambda x: x[0])

    # Walk through working hours day by day looking for free windows
    free_slots = []
    cursor = search_start.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
    duration = timedelta(minutes=duration_minutes)

    while cursor < search_end and len(free_slots) < 5:
        # Skip weekends
        if cursor.weekday() >= 5:
            cursor += timedelta(days=1)
            cursor = cursor.replace(hour=WORK_START_HOUR, minute=0, second=0)
            continue

        slot_end = cursor + duration
        if cursor.hour >= WORK_END_HOUR:
            cursor += timedelta(days=1)
            cursor = cursor.replace(hour=WORK_START_HOUR, minute=0, second=0)
            continue

        conflict = False
        for b_start, b_end in busy_intervals:
            if cursor < b_end and slot_end > b_start:
                conflict = True
                cursor = b_end  # jump past the busy block
                break

        if not conflict:
            free_slots.append({
                "start": cursor.isoformat(),
                "end":   slot_end.isoformat(),
                "label": cursor.strftime("%A, %d %b %Y · %I:%M %p"),
            })
            cursor += duration + timedelta(minutes=15)  # 15-min gap between suggestions

    return free_slots


# ─── STEP 5 : DRAFT REPLY ─────────────────────────────────────────────────────

def draft_reply(email: dict, analysis: dict, conflicts: list, free_slots: list) -> str:
    """
    Ask the LLM to draft a polite reply email.
    """
    slots_text = "\n".join(
        [f"  • {s['label']}" for s in free_slots]
    ) or "  (No free slots found in the next 7 working days)"

    conflict_text = "\n".join(
        [f"  • {e.get('summary','Unnamed event')} @ {e.get('start',{}).get('dateTime','?')}"
         for e in conflicts[:3]]
    ) or "  None"

    prompt = f"""
Draft a professional, concise reply to this email.

Original email from: {email.get('from')}
Subject: {email.get('subject')}
Their message snippet: {email.get('snippet')}

Situation:
- Requested meeting time: {analysis.get('raw_time_mention') or analysis.get('proposed_start_iso') or 'unspecified'}
- Conflicts on the calendar: {conflict_text}
- Available alternative slots:
{slots_text}

If there are conflicts, politely apologize and propose the alternative slots.
If there are no conflicts, confirm the meeting.
Sign off as an AI scheduling assistant.
Keep the reply under 150 words.
"""
    return call_llm(prompt, system="You are a professional scheduling assistant. Write only the email body, no subject line.")


# ─── MAIN ORCHESTRATOR ────────────────────────────────────────────────────────

def process_email(email: dict) -> dict:
    """
    Full pipeline for a single parsed email dict (as returned by gmail_reader.py).
    Returns a rich result dict ready to be displayed or acted upon.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {email.get('subject','(no subject)')}")

    # Step 1 & 2: Identify meeting intent + who is requested
    analysis = analyze_meeting_intent(email)

    if not analysis.get("is_meeting_request"):
        return {
            "email_id":          email.get("id"),
            "subject":           email.get("subject"),
            "is_meeting_request": False,
            "message":           "Not a meeting request — skipped.",
        }

    print(f"  ✓ Meeting detected: {analysis.get('meeting_title')}")
    print(f"  ✓ Requested attendees: {analysis.get('requested_attendees')}")
    print(f"  ✓ Proposed time: {analysis.get('proposed_start_iso')} → {analysis.get('proposed_end_iso')}")

    # Step 3: Check conflicts for each requested attendee
    start_iso = analysis.get("proposed_start_iso")
    end_iso   = analysis.get("proposed_end_iso")
    duration  = analysis.get("duration_minutes") or 60

    # Always infer end time if missing
    if start_iso and not end_iso:
        start_dt = date_parser.parse(start_iso)
        end_iso  = (start_dt + timedelta(minutes=duration)).isoformat()
        print(f"  ℹ End time inferred: +{duration} min → {end_iso}")

    all_conflicts = []
    if start_iso and end_iso:
        for attendee in analysis["requested_attendees"]:
            conflicts = check_conflicts(attendee, start_iso, end_iso)
            all_conflicts.extend(conflicts)
            if conflicts:
                print(f"  ✗ Conflict for {attendee}: {[c.get('summary') for c in conflicts]}")
            else:
                print(f"  ✓ No conflicts for {attendee}")
    else:
        print("  ! Could not determine exact proposed time — skipping conflict check")

    # Step 4: Find free slots if there are conflicts (or no time was proposed)
    duration = analysis.get("duration_minutes") or 60
    free_slots = []
    if all_conflicts or not start_iso:
        after = start_iso or datetime.now(LOCAL_TZ).isoformat()
        free_slots = find_free_slots(analysis["requested_attendees"], duration, after)
        print(f"  ✓ Found {len(free_slots)} free slot(s)")

    # Step 5: Draft reply
    reply = draft_reply(email, analysis, all_conflicts, free_slots)

    return {
        "email_id":            email.get("id"),
        "subject":             email.get("subject"),
        "from":                email.get("from"),
        "is_meeting_request":  True,
        "meeting_title":       analysis.get("meeting_title"),
        "proposed_start":      start_iso,
        "proposed_end":        end_iso,
        "requested_attendees": analysis["requested_attendees"],
        "conflicts":           all_conflicts,
        "free_slots":          free_slots,
        "has_conflict":        bool(all_conflicts),
        "suggested_reply":     reply,
        "analysis":            analysis,
    }


def process_all_emails(emails: list[dict]) -> list[dict]:
    """Process a list of parsed emails and return results."""
    return [process_email(e) for e in emails]