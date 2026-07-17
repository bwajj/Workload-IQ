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
    """Fuzzy-match FPL players to our roster by team + name; persist to Mongo.

    Matching is deliberately conservative (unique-candidate only) to avoid false
    joins between players who share a surname on the same club.
    """
    ours = list(db.get_db()["players"].find({}, {"_id": 1, "name": 1, "team": 1}))
    our_teams = {p["team"] for p in ours}
    by_team: dict[str, list] = defaultdict(list)
    for p in ours:
        toks = _tokens(p["name"])
        by_team[p["team"]].append({"id": p["_id"], "tokens": set(toks), "full": " ".join(toks)})

    def match(team, full_toks, web):
        cands = by_team.get(team, [])
        full = " ".join(full_toks)
        for c in cands:                                  # 1) exact full name
            if c["full"] == full:
                return c["id"], "full"
        if full_toks:                                     # 2) unique surname
            hits = [c for c in cands if full_toks[-1] in c["tokens"]]
            if len(hits) == 1:
                return hits[0]["id"], "surname"
        wt = _tokens(web)                                 # 3) unique web-name token
        if wt:
            hits = [c for c in cands if wt[-1] in c["tokens"]]
            if len(hits) == 1:
                return hits[0]["id"], "webname"
        return None, None

    docs, seen = [], set()
    considered = 0
    for e in fpl_players():
        if e["team"] not in our_teams:
            continue  # club not in our data this season (e.g. promoted sides)
        considered += 1
        mid, how = match(e["team"], _tokens(e["name"]), e["webName"])
        if mid and mid not in seen:
            seen.add(mid)
            docs.append({"_id": mid, "fplId": e["fplId"], "fplWebName": e["webName"],
                         "fplTeam": e["team"], "position": e["position"],
                         "price": e["price"], "matchType": how})

    coll = db.get_db()["player_map"]
    coll.drop()
    if docs:
        coll.insert_many(docs)
        coll.create_index("fplId")
    return {"fplConsidered": considered, "mapped": len(docs),
            "ourRoster": len(ours), "ourMapped": len(seen)}


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
