"""Authentication: users in MongoDB, hashed passwords, signed bearer tokens.

Uses werkzeug (password hashing) and itsdangerous (signed tokens) — both ship
with Flask, so no new dependencies. The signing secret persists in a gitignored
file so sessions survive server restarts.
"""
from __future__ import annotations
import os
import re
import secrets
from pathlib import Path

from flask import Blueprint, request, jsonify, g
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

import db
import mailer

TOKEN_MAX_AGE = 30 * 24 * 3600  # 30 days
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEMO_EMAIL = "demo@workloadiq.app"
DEMO_PASSWORD = "matchday2024"


def _secret() -> str:
    env = os.environ.get("AUTH_SECRET")
    if env:
        return env
    f = Path(__file__).with_name(".auth-secret")
    if f.exists():
        return f.read_text().strip()
    s = secrets.token_hex(32)
    f.write_text(s)
    return s


_serializer = URLSafeTimedSerializer(_secret(), salt="wiq-auth")


def issue_token(email: str) -> str:
    return _serializer.dumps(email)


def verify_token(token: str):
    """Return {email, name} for a valid, unexpired token, else None."""
    if not token:
        return None
    try:
        email = _serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.users().find_one({"_id": email})
    if not user:
        return None
    return {"email": user["_id"], "name": user.get("name", ""),
            "fplTeamId": user.get("fplTeamId")}


def token_from_request() -> str:
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else ""


def seed_demo_user():
    """Create the demo account on first boot (idempotent)."""
    if db.users().count_documents({"_id": DEMO_EMAIL}) == 0:
        db.users().insert_one({
            "_id": DEMO_EMAIL,
            "name": "Demo Analyst",
            "password": generate_password_hash(DEMO_PASSWORD),
        })


bp = Blueprint("auth", __name__)


def _session_payload(email: str, name: str):
    return {"token": issue_token(email), "user": {"email": email, "name": name}}


@bp.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    user = db.users().find_one({"_id": email})
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Incorrect email or password"}), 401
    return jsonify(_session_payload(email, user.get("name", "")))


@bp.post("/api/auth/register")
def register():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if not name:
        name = email.split("@")[0].title()
    if db.users().find_one({"_id": email}):
        return jsonify({"error": "An account with that email already exists"}), 409
    db.users().insert_one({
        "_id": email,
        "name": name,
        "password": generate_password_hash(password),
    })
    # Confirmation email — must never block account creation.
    mail_status = "failed"
    try:
        mail_status = mailer.send_welcome(email, name)
    except Exception as e:  # noqa: BLE001 — log and move on
        print(f"  ! welcome mail to {email} failed: {e}")
    payload = _session_payload(email, name)
    payload["mailStatus"] = mail_status
    return jsonify(payload), 201


@bp.get("/api/auth/me")
def me():
    # The before_request guard already validated the token and set g.user.
    return jsonify(g.user)


@bp.post("/api/auth/fpl-team")
def save_fpl_team():
    """Persist (or clear) the signed-in user's FPL Team ID."""
    body = request.get_json(silent=True) or {}
    raw = str(body.get("teamId", "")).strip()
    team_id = raw if raw.isdigit() else None
    db.users().update_one({"_id": g.user["email"]}, {"$set": {"fplTeamId": team_id}})
    return jsonify({"fplTeamId": team_id})
