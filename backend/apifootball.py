"""Thin API-Football (api-sports.io) client.

Handles auth, rate-limit throttling (free tier: ~10/min, ~100/day), pagination
and an on-disk response cache so re-runs don't burn the daily quota. All config
comes from backend/.env — the raw key is never hard-coded.
"""
from __future__ import annotations
import os
import sys
import json
import time
import hashlib
from collections import deque
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
API_HOST = os.environ.get("API_FOOTBALL_HOST", "v3.football.api-sports.io")
LEAGUE_ID = int(os.environ.get("LEAGUE_ID", "39"))
TARGET_SEASON = int(os.environ.get("TARGET_SEASON", "2023"))

BASE_URL = f"https://{API_HOST}"
CACHE_DIR = Path(__file__).with_name(".api-cache")

# Throttle: keep <=9 requests / 60s (leave headroom under the 10/min limit).
_MAX_PER_MIN = int(os.environ.get("REQ_PER_MIN", "9"))  # Pro plans allow far more
_request_times: deque[float] = deque()


class ApiError(Exception):
    pass


def _throttle():
    now = time.time()
    while _request_times and now - _request_times[0] > 60:
        _request_times.popleft()
    if len(_request_times) >= _MAX_PER_MIN:
        wait = 60 - (now - _request_times[0]) + 0.5
        if wait > 0:
            print(f"  …rate-limit: sleeping {wait:.0f}s")
            time.sleep(wait)
    _request_times.append(time.time())


def _cache_path(endpoint: str, params: dict) -> Path:
    key = endpoint + "?" + json.dumps(params, sort_keys=True)
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    safe = endpoint.strip("/").replace("/", "_")
    return CACHE_DIR / f"{safe}_{digest}.json"


def _request(endpoint: str, params: dict, use_cache: bool = True) -> dict:
    if not API_KEY:
        raise ApiError("API_FOOTBALL_KEY is not set in backend/.env")

    cache_file = _cache_path(endpoint, params)
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text())

    _throttle()
    resp = requests.get(
        f"{BASE_URL}/{endpoint.lstrip('/')}",
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=30,
    )
    if resp.status_code != 200:
        raise ApiError(f"{endpoint} -> HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()

    # API-Football reports logical errors in a body field, not the HTTP status.
    errors = data.get("errors")
    if errors and (isinstance(errors, dict) and errors or isinstance(errors, list) and errors):
        raise ApiError(f"{endpoint} errors: {errors}")

    if use_cache:
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(data))
    return data


def _get_all(endpoint: str, params: dict) -> list:
    """Fetch every page of a paginated endpoint and concatenate `response`.

    The first request omits `page` entirely — several endpoints (e.g. teams)
    reject an unknown `page` field — and we only paginate when the response
    reports more than one page.
    """
    data = _request(endpoint, params)
    out: list = list(data.get("response", []))
    paging = data.get("paging", {}) or {}
    total = paging.get("total", 1) or 1
    page = 1
    while page < total:
        page += 1
        data = _request(endpoint, {**params, "page": page})
        out.extend(data.get("response", []))
    return out


# --- Public methods -------------------------------------------------------

def status() -> dict:
    return _request("status", {}, use_cache=False).get("response", {})


def get_teams(league=LEAGUE_ID, season=TARGET_SEASON) -> list:
    return _get_all("teams", {"league": league, "season": season})


def get_squad(team_id: int) -> list:
    resp = _request("players/squads", {"team": team_id}).get("response", [])
    return resp[0].get("players", []) if resp else []


def get_players(league=LEAGUE_ID, season=TARGET_SEASON) -> list:
    """Every player who featured in a league-season, with birth date + nationality
    (paginated, ~50 pages). Season-accurate — unlike /players/squads (current only)."""
    return _get_all("players", {"league": league, "season": season})


def get_fixtures(league=LEAGUE_ID, season=TARGET_SEASON, status_short=None) -> list:
    params = {"league": league, "season": season}
    if status_short:
        params["status"] = status_short
    return _get_all("fixtures", params)


def get_fixture_players(fixture_id: int) -> list:
    return _request("fixtures/players", {"fixture": fixture_id}).get("response", [])


def get_injuries(league=LEAGUE_ID, season=TARGET_SEASON) -> list:
    return _get_all("injuries", {"league": league, "season": season})


def get_transfers(team_id: int) -> list:
    return _request("transfers", {"team": team_id}).get("response", [])


def get_standings(league=LEAGUE_ID, season=TARGET_SEASON) -> list:
    """Flat list of standings rows (rank, points, played, form, goalsDiff)."""
    resp = _request("standings", {"league": league, "season": season}).get("response", [])
    if not resp:
        return []
    groups = resp[0].get("league", {}).get("standings", [])
    return groups[0] if groups else []


# --- Probe ----------------------------------------------------------------

def probe():
    print(f"\n== API-Football probe ==  host={API_HOST}  league={LEAGUE_ID}  season={TARGET_SEASON}\n")
    try:
        st = status()
    except ApiError as e:
        print("  ✗ status failed:", e)
        return
    acct = st.get("account", {})
    sub = st.get("subscription", {})
    reqs = st.get("requests", {})
    print(f"  account : {acct.get('firstname', '')} {acct.get('lastname', '')} <{acct.get('email', '')}>")
    print(f"  plan    : {sub.get('plan')}  active={sub.get('active')}  ends={sub.get('end')}")
    print(f"  requests: {reqs.get('current')}/{reqs.get('limit_day')} today")
    print()

    def check(name, fn):
        try:
            rows = fn()
            print(f"  ✓ {name}: {len(rows)} rows")
            return rows
        except ApiError as e:
            print(f"  ✗ {name}: {e}")
            return []

    teams = check(f"teams (season {TARGET_SEASON})", lambda: get_teams())
    if teams:
        tid = teams[0]["team"]["id"]
        tname = teams[0]["team"]["name"]
        check(f"squad ({tname})", lambda: get_squad(tid))
    check("fixtures", lambda: get_fixtures())
    check("injuries", lambda: get_injuries())
    print("\n  Cache dir:", CACHE_DIR)
    print("  If teams/fixtures are empty, this season is likely locked on your plan —")
    print("  try an older TARGET_SEASON in backend/.env (free plans expose 2021–2023).\n")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        print("Usage: python apifootball.py --probe")
