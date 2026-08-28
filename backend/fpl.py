"""Fantasy Premier League integration — client + player-ID mapping.

The official FPL API is public and read-only: a manager's squad is fetchable
from just their Team ID (no login). The one hard part is entity resolution —
FPL uses its own player ids, so we build and persist a mapping from FPL ids to
our API-Football ids (the `player_map` collection). This is INFRASTRUCTURE only:
no user-facing endpoint is wired yet.

Match rate is capped by roster overlap between seasons — low (~28%) against the
frozen 2023-24 data, ~near-total once ingesting the live season the FPL API
serves. Flip it on then by adding a route that calls `squad_for_entry()`.
"""
from __future__ import annotations
import json
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

import db

FPL_BASE = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (WorkloadIQ FPL sync)"}
CACHE_DIR = Path(__file__).with_name(".fpl-cache")
BOOTSTRAP_TTL = 12 * 3600  # bootstrap-static changes slowly within a season

# FPL's abbreviated club names → the full names our data uses.
TEAM_ALIAS = {
    "Man City": "Manchester City", "Man Utd": "Manchester United",
    "Spurs": "Tottenham", "Nott'm Forest": "Nottingham Forest",
    "Coventry City": "Coventry", "Ipswich Town": "Ipswich",
}
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


class FplError(Exception):
    pass


def _get(path: str, ttl: int = 0) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / (re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_") + ".json")
    if ttl and cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        return json.loads(cache.read_text())
    r = requests.get(f"{FPL_BASE}/{path}", headers=UA, timeout=20)
    if r.status_code != 200:
        raise FplError(f"{path} -> HTTP {r.status_code}")
    data = r.json()
    if ttl:
        cache.write_text(json.dumps(data))
    return data


def get_bootstrap() -> dict:
    return _get("bootstrap-static/", ttl=BOOTSTRAP_TTL)


def get_entry(team_id: int) -> dict:
    """A manager's basic info (name, team name) — no auth required."""
    return _get(f"entry/{team_id}/")


def get_entry_picks(team_id: int, gameweek: int) -> dict:
    """A manager's 15 picks + captain/vice for a gameweek."""
    return _get(f"entry/{team_id}/event/{gameweek}/picks/")


def _tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", " ", s.lower()).split()


def fpl_players() -> list[dict]:
    """Normalized FPL player list from bootstrap-static."""
    bs = get_bootstrap()
    team = {t["id"]: TEAM_ALIAS.get(t["name"], t["name"]) for t in bs["teams"]}
    return [{
        "fplId": e["id"],
        "name": f"{e['first_name']} {e['second_name']}".strip(),
        "webName": e["web_name"],
        "team": team[e["team"]],
        "position": POS.get(e["element_type"]),
        "price": round(e.get("now_cost", 0) / 10, 1),  # FPL price in £m
    } for e in bs["elements"]]


def build_player_map() -> dict:
    """Match FPL players to our roster and persist fplId → our id to Mongo.

    Matching is **position-guarded** (a GK never joins a MID — this is what kept
    "David Raya Martín" from colliding with "Martín Zubimendi") and runs in
    club-then-position passes so a transferred player whose FPL club disagrees
    with ours still maps by identity. A join needs an exact full-name match or at
    least two shared name tokens, so surname collisions don't produce false joins.
    """
    ours = list(db.get_db()["players"].find({}, {"_id": 1, "name": 1, "team": 1, "position": 1}))
    cand = []
    for p in ours:
        toks = _tokens(p["name"])
        cand.append({"id": p["_id"], "team": p["team"], "pos": p.get("position") or "",
                     "tokens": set(toks), "full": " ".join(toks),
                     "surname": toks[-1] if toks else ""})

    def _score(atoks, btokens):
        """Shared-token count, crediting initial↔full-name matches so an
        abbreviated roster name ('M. Lacroix') still scores against FPL's
        'Maxence Lacroix'."""
        a = set(atoks)
        sc = len(a & btokens)
        a_ini = {t for t in a if len(t) == 1} - btokens
        b_full = {t for t in btokens if len(t) > 1}
        for ini in a_ini:
            if any(t[0] == ini for t in b_full):
                sc += 1
        b_ini = {t for t in btokens if len(t) == 1} - a
        a_full = {t for t in a if len(t) > 1}
        for ini in b_ini:
            if any(t[0] == ini for t in a_full):
                sc += 1
        return sc

    def best_match(pool, ftoks, wtoks):
        """Return (our_id, how, score) or (None, None, 0) for a candidate pool."""
        full = " ".join(ftoks)
        for c in pool:                                    # exact full name wins
            if c["full"] == full:
                return c["id"], "full", 99
        scored = []
        for c in pool:
            s = max(_score(ftoks, c["tokens"]), _score(wtoks, c["tokens"]))
            if s:
                scored.append((s, c))
        if scored:
            top = max(s for s, _ in scored)
            winners = [c for s, c in scored if s == top]
            if top >= 2 and len(winners) == 1:            # ≥2 shared tokens, unique
                return winners[0]["id"], "tokens", top
        if ftoks:                                         # unique surname fallback
            hits = [c for c in pool if ftoks[-1] in c["tokens"]]
            if len(hits) == 1:
                return hits[0]["id"], "surname", 1
        if wtoks:
            hits = [c for c in pool if wtoks[-1] in c["tokens"]]
            if len(hits) == 1:
                return hits[0]["id"], "webname", 1
        return None, None, 0

    def doc_for(mid, e, how):
        return {"_id": mid, "fplId": e["fplId"], "fplWebName": e["webName"],
                "fplTeam": e["team"], "position": e["position"],
                "price": e["price"], "matchType": how}

    fpls = list(fpl_players())
    docs, seen = [], set()

    def run(pool_fn, require_strong):
        for e in fpls:
            if e["fplId"] in mapped_fpl:
                continue
            ftoks, wtoks = _tokens(e["name"]), _tokens(e["webName"])
            pool = [c for c in pool_fn(e) if c["id"] not in seen]
            mid, how, score = best_match(pool, ftoks, wtoks)
            if mid and (not require_strong or score >= 2):
                seen.add(mid); mapped_fpl.add(e["fplId"])
                docs.append(doc_for(mid, e, how))

    mapped_fpl: set = set()
    run(lambda e: [c for c in cand if c["team"] == e["team"] and c["pos"] == e["position"]], False)
    run(lambda e: [c for c in cand if c["team"] == e["team"]], True)          # club, any pos
    run(lambda e: [c for c in cand if c["pos"] == e["position"]], True)       # transfers: pos, any club

    coll = db.get_db()["player_map"]
    coll.drop()
    if docs:
        coll.insert_many(docs)
        coll.create_index("fplId")
    return {"fplConsidered": len(fpls), "mapped": len(docs),
            "ourRoster": len(ours), "ourMapped": len(seen)}


def reconcile_clubs() -> dict:
    """Align roster clubs to FPL for every mapped player, the transfer-timely
    source. API-Football's squad endpoint lags late-window moves; FPL updates
    immediately. Uses the (position-guarded, initial-aware) player_map, so even
    abbreviated roster names are covered. Manual overrides win last, for the rare
    deal FPL itself hasn't caught up on."""
    changes = []
    for m in db.get_db()["player_map"].find({}, {"_id": 1, "fplTeam": 1}):
        fteam = m.get("fplTeam")
        if not fteam:
            continue
        p = db.players().find_one({"_id": m["_id"]}, {"team": 1, "name": 1})
        if p and p.get("team") != fteam:
            changes.append({"id": m["_id"], "name": p.get("name"),
                            "from": p.get("team"), "to": fteam})
            db.players().update_one({"_id": m["_id"]}, {"$set": {"team": fteam}})
            db.get_db()["current_features"].update_one({"_id": m["_id"]}, {"$set": {"team": fteam}})

    # Manual overrides win over both API-Football and FPL (some deals lag both).
    import overrides
    ov = overrides.apply_overrides(db)
    return {"corrected": len(changes), "changes": changes, "overrides": ov}


def prices_by_our_id() -> dict:
    """{our player id → FPL price £m} from the persisted map (no network)."""
    return {d["_id"]: d.get("price") for d in db.get_db()["player_map"].find({}, {"price": 1})}


def our_id_for_fpl(fpl_id: int):
    doc = db.get_db()["player_map"].find_one({"fplId": fpl_id})
    return doc["_id"] if doc else None


def current_gameweek() -> int:
    """The live FPL gameweek (or the most recent finished one out of season)."""
    events = get_bootstrap().get("events", [])
    for e in events:
        if e.get("is_current"):
            return e["id"]
    finished = [e["id"] for e in events if e.get("finished")]
    return finished[-1] if finished else 1


def _element_index() -> dict:
    """fplId → {webName, team, position} from bootstrap."""
    return {p["fplId"]: p for p in fpl_players()}


def analyze_entry(team_id: int, gameweek: int | None = None) -> dict:
    """A manager's 15 picks resolved to our player ids, with FPL names attached
    for both matched and unmapped picks so the UI can be honest about coverage.
    """
    gw = gameweek or current_gameweek()
    entry = get_entry(team_id)
    manager = f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip()
    team_name = entry.get("name", "")
    picks = get_entry_picks(team_id, gw).get("picks", [])
    idx = _element_index()

    matched, unmapped = [], []
    for p in picks:
        el = idx.get(p["element"], {})
        base = {"fplId": p["element"], "webName": el.get("webName"), "team": el.get("team"),
                "position": el.get("position"), "price": el.get("price"),
                "isCaptain": p["is_captain"], "isViceCaptain": p["is_vice_captain"],
                "onBench": p["position"] > 11}
        our_id = our_id_for_fpl(p["element"])
        if our_id:
            matched.append({**base, "playerId": our_id})
        else:
            unmapped.append(base)
    return {"managerName": manager, "teamName": team_name, "gameweek": gw,
            "matched": matched, "unmapped": unmapped}


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        bs = get_bootstrap()
        print(f"FPL reachable · {len(bs['elements'])} players · {len(bs['teams'])} teams")
    stats = build_player_map()
    print("player_map built:", stats)
    if stats["fplConsidered"]:
        pct = 100 * stats["mapped"] // stats["fplConsidered"]
        print(f"  match rate: {stats['mapped']}/{stats['fplConsidered']} ({pct}%) "
              f"— capped by 2023-24 ↔ live-season roster overlap")
