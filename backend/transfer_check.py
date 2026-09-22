"""Daily transfer-window checker.

Keeps roster clubs current during an open transfer window. It re-syncs every
mapped player's club to FPL (the transfer-timely source) and reports what
changed, so the app follows moves without a manual poke. FPL reclassifies and
retags players fast, so the map is rebuilt first; manual overrides in
overrides.py still win last, for the rare deal even FPL hasn't caught (tell the
app about those and they persist).

Outside a transfer window it no-ops — pass --force to run anyway.

    MONGO_URI=<atlas> python transfer_check.py [--force]

Only MONGO_URI is required (FPL's API is public). Set SMTP_* + DIGEST_TO to also
receive an email digest whenever something changes.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import db as DB
import fpl

# Approximate Premier League transfer windows as ((start_month, day),
# (end_month, day)), inclusive. The end dates run ~3 weeks past deadline day
# because the data feeds keep catching up on completed moves well after the
# window formally shuts. Adjust if the league shifts the dates.
WINDOWS = [((6, 1), (9, 22)),   # summer
           ((1, 1), (2, 20))]   # winter


def window_status(today: date) -> tuple[bool, str | None]:
    for (sm, sd), (em, ed) in WINDOWS:
        if date(today.year, sm, sd) <= today <= date(today.year, em, ed):
            return True, "summer" if sm == 6 else "winter"
    return False, None


def run(force: bool = False) -> dict:
    today = date.today()
    is_open, label = window_status(today)
    print(f"[transfer-check] {today.isoformat()} — window "
          f"{'OPEN (' + label + ')' if is_open else 'closed'}")
    if not is_open and not force:
        print("[transfer-check] window closed; skipping (use --force to run anyway).")
        return {"skipped": True, "changes": []}

    mp = fpl.build_player_map()
    rc = fpl.reconcile_clubs()
    changes = rc["changes"]
    overrides_changed = rc.get("overrides", {}).get("changed", [])

    print(f"[transfer-check] map: {mp['mapped']}/{mp['ourRoster']} mapped")
    if changes:
        print(f"[transfer-check] {len(changes)} club update(s) from FPL:")
        for c in changes:
            print(f"    {c['name']}: {c['from']} -> {c['to']}")
    else:
        print("[transfer-check] no club changes from FPL.")
    if overrides_changed:
        print(f"[transfer-check] {len(overrides_changed)} manual override(s) reapplied.")

    _maybe_email(today, label, changes, overrides_changed)
    return {"skipped": False, "changes": changes, "overrides": overrides_changed}


def _maybe_email(today, label, changes, overrides_changed) -> None:
    if not os.environ.get("SMTP_HOST"):
        return
    if not (changes or overrides_changed):
        return
    to = os.environ.get("DIGEST_TO") or _address(os.environ.get("MAIL_FROM", ""))
    if not to:
        return
    try:
        import mailer
        lines = [f"• {c['name']}: {c['from']} → {c['to']}" for c in changes]
        lines += [f"• [override] {c['name']}: {c['from']} → {c['to']}" for c in overrides_changed]
        body = (f"Workload IQ transfer check — {today.isoformat()} "
                f"({label or 'off'}-window)\n\n" + "\n".join(lines) +
                "\n\nIf any club still looks wrong, it's a move neither feed has caught yet — "
                "add it to overrides.py.")
        status = mailer.send(to, "Workload IQ — roster updates", body)
        print(f"[transfer-check] digest emailed to {to} ({status}).")
    except Exception as e:  # never fail the job over the email
        print(f"[transfer-check] email skipped: {e}")


def _address(mail_from: str) -> str:
    # "Name <addr@x>" -> "addr@x"
    if "<" in mail_from and ">" in mail_from:
        return mail_from.split("<", 1)[1].split(">", 1)[0].strip()
    return mail_from.strip()


if __name__ == "__main__":
    run(force="--force" in sys.argv)
