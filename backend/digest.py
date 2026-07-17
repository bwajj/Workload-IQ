"""Weekly gameweek digest email — captain shortlist + injury risks.

Reuses the picks engine (`risk.gameweek_picks`) to compose an HTML/text email,
sent via the existing mailer. On the frozen 2023-24 data a literal weekly cadence
is moot, so sending is on-demand (a button in the app); on a live season this same
`build_digest` is what a weekly cron would render.
"""
from __future__ import annotations
import os

import risk
import mailer

APP_URL = os.environ.get("APP_URL", "http://localhost:5173")

INK = "#141417"
MUTED = "#6f6f78"
LINE = "#e7e7e4"
LOW, MOD, HIGH = "#0e7a43", "#b45309", "#d1242f"


def _conf_color(score):
    return LOW if score >= 60 else MOD if score >= 45 else HIGH


def build_digest(gameweek=None) -> dict | None:
    picks = risk.gameweek_picks(gameweek)
    if not picks:
        return None
    gw = picks["gameweek"]
    captains = picks["captainPicks"][:6]
    risks = picks["avoid"][:6]

    subject = f"Workload IQ · Gameweek {gw} — captain picks & injury risks"

    # --- plain text ---
    lines = [f"Workload IQ — Gameweek {gw}", "", "CAPTAIN SHORTLIST"]
    for i, p in enumerate(captains, 1):
        venue = "v" if p["home"] else "@"
        lines.append(f"  {i}. {p['playerName']} ({p['team']}, {p['position']}) — "
                     f"confidence {p['confidence']} · {venue} {p['opponent']} "
                     f"({p['difficulty']}/5) · form {p.get('form')}")
    lines += ["", "SIT / INJURY RISKS"]
    for p in risks:
        lines.append(f"  - {p['playerName']} ({p['team']}, {p['position']}) — "
                     f"{p['riskScore']}% · {p['reasons'][0]}")
    lines += ["", f"Open the planner: {APP_URL}/picks"]
    text = "\n".join(lines)

    # --- html ---
    cap_rows = ""
    for i, p in enumerate(captains, 1):
        venue = "v" if p["home"] else "@"
        cap_rows += f"""
        <tr>
          <td style="padding:8px 6px;color:{MUTED};font-size:13px;">{i}</td>
          <td style="padding:8px 6px;font-weight:600;color:{INK};">{p['playerName']}
            <span style="color:{MUTED};font-weight:400;font-size:12px;"> · {p['team']} · {p['position']}</span></td>
          <td style="padding:8px 6px;color:{MUTED};font-size:13px;">{venue} {p['opponent']} ({p['difficulty']}/5)</td>
          <td style="padding:8px 6px;text-align:right;font-weight:700;color:{_conf_color(p['confidence'])};">{p['confidence']}</td>
        </tr>"""

    risk_rows = ""
    for p in risks:
        risk_rows += f"""
        <tr>
          <td style="padding:8px 6px;font-weight:600;color:{INK};">{p['playerName']}
            <span style="color:{MUTED};font-weight:400;font-size:12px;"> · {p['team']}</span>
            <div style="color:{MUTED};font-size:12px;font-weight:400;">{p['reasons'][0]}</div></td>
          <td style="padding:8px 6px;text-align:right;font-weight:700;color:{HIGH};">{p['riskScore']}%</td>
        </tr>"""

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;color:{INK};">
  <div style="font-weight:800;font-size:18px;letter-spacing:-0.02em;">
    <span style="display:inline-block;width:9px;height:9px;background:{LOW};border-radius:3px;margin-right:6px;"></span>Workload IQ</div>
  <div style="color:{MUTED};font-size:13px;margin:2px 0 20px;">Gameweek {gw} · captain picks & injury risks</div>

  <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};border-bottom:2px solid {INK};padding-bottom:6px;">Captain shortlist</div>
  <table style="width:100%;border-collapse:collapse;font-size:14px;">{cap_rows}</table>

  <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};border-bottom:2px solid {INK};padding-bottom:6px;margin-top:26px;">Sit / injury risks</div>
  <table style="width:100%;border-collapse:collapse;font-size:14px;">{risk_rows}</table>

  <a href="{APP_URL}/picks" style="display:inline-block;margin-top:24px;background:{INK};color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:600;font-size:14px;">Open the planner →</a>
  <div style="color:{MUTED};font-size:11px;margin-top:20px;border-top:1px solid {LINE};padding-top:12px;">
    Injury risk blends workload (ACWR, rest, congestion) with injury history. Confidence adds form &amp; fixture difficulty.</div>
</div>"""

    return {"subject": subject, "text": text, "html": html, "gameweek": gw,
            "captains": len(captains), "risks": len(risks)}


def send_digest(to: str, gameweek=None) -> dict | None:
    d = build_digest(gameweek)
    if not d:
        return None
    status = mailer.send(to, d["subject"], d["text"], d["html"])
    return {"gameweek": d["gameweek"], "to": to, "mailStatus": status,
            "captains": d["captains"], "risks": d["risks"]}
