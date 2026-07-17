"""Transactional mail with a graceful dev fallback.

If SMTP_* is configured in backend/.env, mail is sent for real. Without
credentials, each message is written to backend/outbox/ as a .eml file and
logged, so the flow is inspectable locally — no silent black hole.

.env keys: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, MAIL_FROM, APP_URL
"""
from __future__ import annotations
import os
import re
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Workload IQ <no-reply@workloadiq.local>")
APP_URL = os.environ.get("APP_URL", "http://localhost:5173")

OUTBOX = Path(__file__).with_name("outbox")


def send(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Send a message. Returns 'smtp' (delivered) or 'outbox' (dev fallback)."""
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if SMTP_HOST:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return "smtp"

    OUTBOX.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", to.lower()).strip("-")
    path = OUTBOX / f"{int(time.time())}-{slug}.eml"
    path.write_bytes(bytes(msg))
    print(f"  ✉  no SMTP configured — wrote {path.name} to backend/outbox/")
    return "outbox"


def send_welcome(email: str, name: str) -> str:
    first = (name or "there").split()[0]
    subject = "Welcome to Workload IQ — your account is ready"
    text = f"""Hi {first},

Your Workload IQ account ({email}) has been created.

What's inside:
  - Today      every Premier League player, ranked by 14-day injury risk
  - Selection  a drag-and-drop lineup sandbox with fixture difficulty,
               fatigue and form — rotatable across gameweeks
  - Evidence   the methodology, plus a backtest of predictions against
               the injuries that actually happened

Sign in: {APP_URL}

— Workload IQ
"""
    html = f"""\
<div style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:520px;margin:0 auto;color:#141417">
  <p style="font-size:15px"><strong style="color:#0e7a43">●</strong> <strong>Workload IQ</strong></p>
  <h2 style="margin:18px 0 6px">You're in, {first}.</h2>
  <p>Your account (<strong>{email}</strong>) has been created.</p>
  <ul style="line-height:1.7;padding-left:18px">
    <li><strong>Today</strong> — every Premier League player, ranked by 14-day injury risk</li>
    <li><strong>Selection</strong> — a drag-and-drop lineup sandbox with fixture difficulty, fatigue &amp; form</li>
    <li><strong>Evidence</strong> — the methodology, backtested against the injuries that actually happened</li>
  </ul>
  <p style="margin:22px 0">
    <a href="{APP_URL}" style="background:#141417;color:#ffffff;text-decoration:none;
       padding:10px 22px;border-radius:8px;font-weight:600">Sign in</a>
  </p>
  <p style="color:#6f6f78;font-size:12.5px">Workload IQ — injury-risk analytics for the Premier League.</p>
</div>
"""
    return send(email, subject, text, html)
