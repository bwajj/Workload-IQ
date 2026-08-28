"""Manual club corrections for transfers the automated sources haven't caught.

Both data sources lag some moves: API-Football's squad endpoint updates days
late, and even FPL can trail a completed deal. When a transfer is confirmed in
reality but not yet in the feeds, record it here (keyed by our player id) so it
survives every re-ingest and FPL reconcile until the feeds catch up. Remove an
entry once the sources agree — it then becomes a harmless no-op.
"""

# our playerId -> correct current club (our team-name spelling)
CLUB_OVERRIDES: dict[int, str] = {
    10135: "Arsenal",   # Bruno Guimarães — Newcastle -> Arsenal (Aug 2026, £75m)
}


def apply_overrides(db) -> dict:
    """Force CLUB_OVERRIDES onto `players` and `current_features`. Returns what
    actually changed (entries already correct are skipped)."""
    changed = []
    for pid, team in CLUB_OVERRIDES.items():
        p = db.players().find_one({"_id": pid})
        if not p:
            continue
        if p.get("team") != team:
            changed.append({"id": pid, "name": p.get("name"), "from": p.get("team"), "to": team})
        db.players().update_one({"_id": pid}, {"$set": {"team": team}})
        db.get_db()["current_features"].update_one({"_id": pid}, {"$set": {"team": team}})
    return {"overridden": len(CLUB_OVERRIDES), "changed": changed}
