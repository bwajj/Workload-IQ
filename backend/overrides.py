"""Manual roster corrections for moves the automated feeds haven't caught.

Both data sources lag some transfers: API-Football's squad endpoint updates days
late (and can drop a player from his old club before adding him to the new one,
leaving him off the roster entirely), and even FPL can trail a completed deal.
Record confirmed-but-not-yet-in-the-feeds facts here so they survive every
re-ingest and FPL reconcile until the feeds catch up. Remove an entry once the
feeds agree — it then becomes a harmless no-op.

- CLUB_OVERRIDES: correct the club of a player already on the roster.
- ROSTER_ADDITIONS: inject a player the feeds have dropped from every squad.
Both are keyed/identified by our player id (API-Football's player id).
"""

# our playerId -> correct current club (our team-name spelling)
CLUB_OVERRIDES: dict[int, str] = {
    10135: "Arsenal",   # Bruno Guimarães — Newcastle -> Arsenal (Aug 2026, £75m)
}

# Players missing from every fetched squad — add them with the right club.
ROSTER_ADDITIONS: list[dict] = [
    {"id": 283058, "name": "Nicolas Jackson", "team": "Aston Villa", "position": "FWD"},
]


def _current_feature_row(db, pid, name, team, position):
    """Build a current_features row for an added player (no games yet -> the
    neutral defaults player_features returns for empty appearances)."""
    import features as feat
    ref = feat.get_reference_date()
    feats = feat.player_features([], ref)
    hist = feat.injury_history_features([], ref)
    return {"_id": pid, "playerId": pid, "playerName": name, "team": team,
            "position": position, "age": feat._clean_age(None), "number": None, "date": ref,
            **feats, **hist,
            "fatigue": feat.fatigue_index(feats), "form": feat.form_rating([], ref)}


def apply_overrides(db) -> dict:
    """Force overrides onto `players` and `current_features`. Returns what
    actually changed (entries already correct are skipped)."""
    changed = []

    # 1) Inject missing players.
    for a in ROSTER_ADDITIONS:
        pid = a["id"]
        existing = db.players().find_one({"_id": pid})
        db.players().update_one(
            {"_id": pid},
            {"$set": {"name": a["name"], "team": a["team"], "position": a["position"]},
             "$setOnInsert": {"age": None, "nationality": "", "number": None}},
            upsert=True)
        if db.get_db()["current_features"].find_one({"_id": pid}) is None:
            db.get_db()["current_features"].insert_one(
                _current_feature_row(db, pid, a["name"], a["team"], a["position"]))
        else:
            db.get_db()["current_features"].update_one(
                {"_id": pid}, {"$set": {"team": a["team"], "position": a["position"], "playerName": a["name"]}})
        if not existing:
            changed.append({"id": pid, "name": a["name"], "from": "(missing)", "to": a["team"]})
        elif existing.get("team") != a["team"]:
            changed.append({"id": pid, "name": a["name"], "from": existing.get("team"), "to": a["team"]})

    # 2) Correct clubs of existing players.
    for pid, team in CLUB_OVERRIDES.items():
        p = db.players().find_one({"_id": pid})
        if not p:
            continue
        if p.get("team") != team:
            changed.append({"id": pid, "name": p.get("name"), "from": p.get("team"), "to": team})
        db.players().update_one({"_id": pid}, {"$set": {"team": team}})
        db.get_db()["current_features"].update_one({"_id": pid}, {"$set": {"team": team}})

    return {"overridden": len(CLUB_OVERRIDES) + len(ROSTER_ADDITIONS), "changed": changed}
