"""Workload feature engineering, decoupled from the data source.

Reads whatever `games` + `injuries` are in MongoDB and rebuilds the labelled
`features` collection (for model training + the ACWR correlation) and the
`current_features` collection (for live risk scoring). Works identically for
simulated data and real API-Football data.
"""
from __future__ import annotations
from datetime import datetime, timedelta

import db

CHRONIC_WARMUP_MIN = 30  # weekly-equivalent minutes before ACWR is meaningful
LABEL_WINDOW_DAYS = 14

# Workload-driven (non-contact) injuries — the model's prediction target.
SOFT_TISSUE = {"Hamstring", "Calf", "Groin", "Thigh", "Muscle"}


def _clean_age(v):
    """Guard against dirty source ages (e.g. a birth year slipping through)."""
    return v if isinstance(v, (int, float)) and 15 <= v <= 45 else 25


def player_features(appearances, ref_date):
    """Rolling acute/chronic workload features from (date, minutes) tuples."""
    appts = [(d, m) for d, m, *_ in appearances if d <= ref_date]
    acute7 = sum(m for d, m in appts if (ref_date - d).days <= 6)
    chronic_total = sum(m for d, m in appts if (ref_date - d).days <= 27)
    chronic_weekly = chronic_total / 4.0
    acwr = 1.0 if chronic_weekly < CHRONIC_WARMUP_MIN else acute7 / chronic_weekly
    recent = [d for d, _ in appts if (ref_date - d).days <= 13]
    matches14 = len(recent)
    rs = sorted(recent)
    b2b = sum(1 for a, b in zip(rs, rs[1:]) if (b - a).days <= 3)
    prev = appts[-2][0] if len(appts) >= 2 else None
    last = appts[-1][0] if appts else None
    rest_days = (last - prev).days if (prev and last) else 7
    # Extra workload signals that measurably sharpen injury prediction.
    load21 = sum(m for d, m in appts if (ref_date - d).days <= 20)   # 3-week load
    acute3 = sum(m for d, m in appts if (ref_date - d).days <= 2)    # last-72h load
    ratio21 = round(load21 / (chronic_weekly * 3), 3) if chronic_weekly >= CHRONIC_WARMUP_MIN else 1.0
    return {
        "acute7": acute7,
        "chronic28": round(chronic_weekly, 1),
        "acwr": round(acwr, 3),
        "restDays": rest_days,
        "backToBack14": b2b,
        "matches14": matches14,
        "minutes7": acute7,
        "load21": load21,
        "acute3": acute3,
        "ratio21": ratio21,
        "careerGames": len(appts),   # durability / experience proxy
    }


def fatigue_index(feats: dict) -> int:
    """0–100 fatigue score from workload density and recovery.

    Purely workload-based, so European minutes feed it automatically once
    those games are ingested (they raise acute7/matches14/back-to-backs).
    """
    load = min(feats["acute7"] / 360, 1.0) * 40          # 4 full games in 7d = maxed
    congestion = min(feats["matches14"] / 5, 1.0) * 25
    b2b = min(feats["backToBack14"], 2) / 2 * 15
    rest = max(0.0, (5 - feats["restDays"]) / 5) * 20
    return int(round(load + congestion + b2b + rest))


def form_rating(appearances, ref_date, last_n: int = 4):
    """Average match rating (0–10) over the last N rated appearances."""
    rated = [r for d, _m, r in appearances if d <= ref_date and r is not None]
    if not rated:
        return None
    return round(sum(rated[-last_n:]) / len(rated[-last_n:]), 1)


INJURY_LOOKBACK_DAYS = 365
RETURN_SPIKE_DAYS = 21
NO_INJURY_SENTINEL = 400  # "healthy for a long time" — keeps the model feature numeric


def injury_history_features(episodes, ref_date):
    """Prior-injury signals as of ref_date, using only injuries that began before
    it. Previous injury is one of the strongest predictors of future injury, and
    the weeks just after returning carry the sharpest re-injury risk — so recency
    of return is the key term, alongside a proneness count."""
    prior = [e for e in episodes if e["dateInjured"] < ref_date]
    prone = sum(1 for e in prior if (ref_date - e["dateInjured"]).days <= INJURY_LOOKBACK_DAYS)
    returned = [e for e in prior if e["expectedReturn"] <= ref_date]
    days_since_return = min(((ref_date - e["expectedReturn"]).days for e in returned),
                            default=NO_INJURY_SENTINEL)
    days_since_return = min(days_since_return, NO_INJURY_SENTINEL)
    return {
        "priorInjuries": prone,
        "daysSinceReturn": days_since_return,
        "recentReturn": 1 if days_since_return <= RETURN_SPIKE_DAYS else 0,
    }


def compute_features(reference_date: datetime | None = None):
    """Rebuild `features` and `current_features` from games + injuries in Mongo."""
    players = list(db.players().find({}))
    games = list(db.games().find({}))
    injuries = list(db.injuries().find({}))

    if reference_date is None:
        reference_date = max((g["date"] for g in games), default=datetime.utcnow())

    # Appearances per player (sorted by date), carrying the match rating.
    appearances: dict[int, list] = {}
    for g in games:
        if g.get("minutes"):
            appearances.setdefault(g["playerId"], []).append(
                (g["date"], g["minutes"], g.get("rating")))
    for pid in appearances:
        appearances[pid].sort(key=lambda t: t[0])

    # Injury onset dates per player (for labelling) + full episodes (for history).
    # Soft-tissue onsets are the model's target — workload predicts muscle strains,
    # not impact injuries — while all onsets drive the descriptive charts.
    onsets: dict[int, list] = {}
    soft_onsets: dict[int, list] = {}
    episodes_by_player: dict[int, list] = {}
    for inj in injuries:
        onsets.setdefault(inj["playerId"], []).append(inj["dateInjured"])
        if inj.get("bodyPart") in SOFT_TISSUE:
            soft_onsets.setdefault(inj["playerId"], []).append(inj["dateInjured"])
        episodes_by_player.setdefault(inj["playerId"], []).append(inj)

    pmeta = {p["_id"]: p for p in players}

    # --- Labelled feature rows: one per appearance -------------------------
    feature_rows = []
    fid = 1
    for pid, appts in appearances.items():
        meta = pmeta.get(pid, {})
        age = _clean_age(meta.get("age"))
        eps = episodes_by_player.get(pid, [])
        for ref_date, _m, _r in appts:
            feats = player_features(appts, ref_date)
            hist = injury_history_features(eps, ref_date)
            hi = ref_date + timedelta(days=LABEL_WINDOW_DAYS)
            injured_next = int(any(ref_date < di <= hi for di in onsets.get(pid, [])))
            soft_next = int(any(ref_date < di <= hi for di in soft_onsets.get(pid, [])))
            feature_rows.append({
                "_id": fid,
                "playerId": pid,
                "playerName": meta.get("name", ""),
                "team": meta.get("team", ""),
                "position": meta.get("position", ""),
                "age": age,
                "date": ref_date,
                **feats,
                **hist,
                "injuredNext14": injured_next,
                "softInjuryNext14": soft_next,
            })
            fid += 1

    # --- Current features: one per player, as of reference_date ------------
    current_rows = []
    for p in players:
        appts = appearances.get(p["_id"], [])
        feats = player_features(appts, reference_date)
        hist = injury_history_features(episodes_by_player.get(p["_id"], []), reference_date)
        current_rows.append({
            "_id": p["_id"],
            "playerId": p["_id"],
            "playerName": p["name"],
            "team": p["team"],
            "position": p["position"],
            "age": _clean_age(p.get("age")),
            "number": p.get("number"),
            "date": reference_date,
            **feats,
            **hist,
            "fatigue": fatigue_index(feats),
            "form": form_rating(appts, reference_date),
        })

    database = db.get_db()
    database["features"].drop()
    database["current_features"].drop()
    if feature_rows:
        db.features().insert_many(feature_rows)
    if current_rows:
        database["current_features"].insert_many(current_rows)

    set_reference_date(reference_date)
    return {
        "features": len(feature_rows),
        "current_features": len(current_rows),
        "referenceDate": reference_date.isoformat(),
    }


def compute_team_features(team: str, as_of: datetime) -> list[dict]:
    """Current-feature-shaped rows for one team's squad, as of an arbitrary date."""
    return _rows_as_of(list(db.players().find({"team": team})), as_of)


def compute_all_features(as_of: datetime) -> list[dict]:
    """Current-feature-shaped rows for every player, as of an arbitrary date.

    Powers the backtest: score the whole league as of the eve of a past
    gameweek, then compare with the injuries that actually followed.
    """
    return _rows_as_of(list(db.players().find({})), as_of)


def _rows_as_of(players: list[dict], as_of: datetime) -> list[dict]:
    """Risk/fatigue/form feature rows recomputed from games before `as_of`."""
    ids = [p["_id"] for p in players]
    games = db.games().find({"playerId": {"$in": ids}})

    appearances: dict[int, list] = {}
    for g in games:
        if g.get("minutes"):
            appearances.setdefault(g["playerId"], []).append(
                (g["date"], g["minutes"], g.get("rating")))
    for pid in appearances:
        appearances[pid].sort(key=lambda t: t[0])

    episodes_by_player: dict[int, list] = {}
    for inj in db.injuries().find({"playerId": {"$in": ids}}):
        episodes_by_player.setdefault(inj["playerId"], []).append(inj)

    rows = []
    for p in players:
        appts = appearances.get(p["_id"], [])
        feats = player_features(appts, as_of)
        hist = injury_history_features(episodes_by_player.get(p["_id"], []), as_of)
        rows.append({
            "playerId": p["_id"],
            "playerName": p["name"],
            "team": p["team"],
            "position": p["position"],
            "age": _clean_age(p.get("age")),
            "number": p.get("number"),
            "date": as_of,
            **feats,
            **hist,
            "fatigue": fatigue_index(feats),
            "form": form_rating(appts, as_of),
        })
    return rows


def set_reference_date(reference_date: datetime, extra: dict | None = None):
    doc = {"_id": "meta", "referenceDate": reference_date}
    if extra:
        doc.update(extra)
    db.get_db()["meta"].update_one({"_id": "meta"}, {"$set": doc}, upsert=True)


def get_reference_date() -> datetime:
    """Reference 'now' for risk scoring; falls back to latest game date."""
    meta = db.get_db()["meta"].find_one({"_id": "meta"})
    if meta and meta.get("referenceDate"):
        return meta["referenceDate"]
    latest = db.games().find_one(sort=[("date", -1)])
    return latest["date"] if latest else datetime.utcnow()
