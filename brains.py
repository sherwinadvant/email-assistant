import anthropic, json
from dotenv import load_dotenv
import os
load_dotenv()
print("Key loaded:", os.getenv('ANTHROPIC_API_KEY'))
client = anthropic.Anthropic()

def analyze_email(subject, body, sender):
    prompt = f"""You are an executive assistant. Analyze this email.

From: {sender}
Subject: {subject}s
Body: {body}

Reply ONLY with valid JSON in exactly this format:
{{
  "is_scheduling_request": true or false,
  "participants": ["email1@x.com", "email2@x.com"],
  "preferred_dates": ["2024-12-20", "2024-12-21"],
  "duration_minutes": 30,
  "notes": "any special requests"
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = message.content[0].text
    return json.loads(response_text)   # converts Claude's reply to a Python dict
result = analyze_email(
    subject="Meeting next week?",
    sender="alice@example.com",
    body="Hi, can we find 30 mins sometime Mon-Wed next week? Bob should join too."
)
print(result['is_scheduling_request'])  # True
print(result['participants'])           # ['alice@example.com', 'bob@example.com']
print(result['duration_minutes'])       # 30
def generate_reply(participants, chosen_slot):
    prompt = f"""Write a short, professional email confirming a meeting.
Meeting time: {chosen_slot}
Participants: {', '.join(participants)}
Sign off as: AI Assistant

Keep it under 80 words. Just the email body, no subject line."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text