"""Ingest real Premier League data from API-Football into MongoDB.

Maps API-Football payloads onto the exact document shapes the rest of the app
already uses (players / games / injuries / fixtures) so nothing downstream
changes. Idempotent: re-running rebuilds the snapshot from the API cache, so
rosters and injuries stay current without duplicates.

Budget-aware: the only per-fixture call is `fixtures/players`, so we detail a
recent window of fixtures (MAX_FIXTURE_DETAIL) to stay under the free 100/day
limit. Already-cached fixtures cost no quota, so ingestion is resumable.
"""
from __future__ import annotations
import os
from collections import Counter
from datetime import timedelta

import apifootball as af
import db
import features as feat

# Seasons to ingest; the LAST is 'live' (roster/fixtures/current). Others add
# games + injuries for training + player history.
INGEST_SEASONS = [int(s) for s in
                  os.environ.get("INGEST_SEASONS", str(os.environ.get("TARGET_SEASON", "2025"))).split(",")]

MAX_FIXTURE_DETAIL = int(os.environ.get("MAX_FIXTURE_DETAIL", "60"))
UPCOMING_RESERVE = int(os.environ.get("UPCOMING_RESERVE", "10"))  # last GW = "future"
MAX_EURO_DETAIL = int(os.environ.get("MAX_EURO_DETAIL", "20"))       # per club competition
MAX_INTL_DETAIL = int(os.environ.get("MAX_INTL_DETAIL", "150"))     # international fixtures

# Club competitions PL teams appear in (API-Football league ids) — filtered to
# our clubs, same handling as league games. UEFA + domestic cups.
CLUB_COMPS = {
    2: "Champions League", 3: "Europa League", 848: "Conference League",
    45: "FA Cup", 48: "EFL Cup",
}
# International competitions our players may feature in (national-team games) —
# filtered to our player ids, so any nation is caught without a nationality map.
INTL_COMPS = {
    1: "World Cup", 4: "Euro Championship", 5: "UEFA Nations League",
    10: "Friendlies", 9: "Copa America", 6: "Africa Cup of Nations",
    32: "WC Qualification Europe", 29: "WC Qualification Africa",
    34: "WC Qualification South America", 30: "WC Qualification Asia",
}

POS_MAP = {
    "Goalkeeper": "GK", "Defender": "DEF", "Midfielder": "MID", "Attacker": "FWD",
    "G": "GK", "D": "DEF", "M": "MID", "F": "FWD",
}
FINISHED = {"FT", "AET", "PEN"}

# Injury 'reason' values that are not fitness injuries.
NON_INJURY = ("suspend", "national", "coach", "personal", "rest", "doubt", "illness",
              "card", "ban")

SEVERITY_BANDS = [("Minor", 0, 14), ("Moderate", 15, 45), ("Severe", 46, 9999)]


def _pos(v):
    return POS_MAP.get(v, "MID")


def _valid_age(v):
    """A plausible footballer age, else None (unknown) — so the UI can show '—'
    rather than a misleading default for players no longer in a squad."""
    return v if isinstance(v, int) and 15 <= v <= 45 else None


def _age_from_birth(iso, as_of):
    """Season-accurate age from a birth date, as of the reference date; None if
    unusable so the caller can fall back."""
    if not iso:
        return None
    try:
        b = _parse(iso)
    except (ValueError, TypeError):
        return None
    age = as_of.year - b.year - ((as_of.month, as_of.day) < (b.month, b.day))
    return age if 15 <= age <= 45 else None


def _severity(days):
    for name, lo, hi in SEVERITY_BANDS:
        if lo <= days <= hi:
            return name
    return "Moderate"


def _body_part(reason: str) -> str:
    r = (reason or "").lower()
    for part in ["hamstring", "knee", "ankle", "calf", "groin", "thigh", "foot",
                 "back", "shoulder", "hip", "achilles", "muscle"]:
        if part in r:
            return part.capitalize()
    return "Other"


def _rating(gstat: dict):
    """Per-match player rating (API returns it as a string, e.g. '7.3')."""
    try:
        return float(gstat.get("rating"))
    except (TypeError, ValueError):
        return None


def _difficulty(opp_ppg: float, home: bool) -> int:
    """FPL-style fixture difficulty 1–5 from opponent points-per-game + venue.

    PL PPG spans roughly 0.4 (bottom) to 2.4 (champions); away trips get a bump.
    """
    d = 1 + 2.0 * max(0.0, opp_ppg - 0.4)
    if not home:
        d += 0.4
    return int(min(5, max(1, round(d))))


def _box_scores(fixture, team_name, competition, gid_start, only_teams=None,
                only_players=None, club_of=None):
    """Box-score docs for one fixture.

    only_teams  — keep only these team ids (club competitions).
    only_players — keep only these player ids (internationals: our players only).
    club_of     — {playerId: club name} to record a player's club, not the national
                  team, so roster/team grouping stays club-based for internationals.
    """
    fx = fixture["fixture"]
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    date = _parse(fx["date"])
    out = []
    gid = gid_start
    for side in af.get_fixture_players(fx["id"]):
        tid = side["team"]["id"]
        if only_teams is not None and tid not in only_teams:
            continue
        opp_id = away_id if tid == home_id else home_id
        opp_name = fixture["teams"]["away" if tid == home_id else "home"]["name"]
        for entry in side.get("players", []):
            pid = entry["player"]["id"]
            if only_players is not None and pid not in only_players:
                continue
            stat = (entry.get("statistics") or [{}])[0]
            gstat = stat.get("games", {}) or {}
            minutes = gstat.get("minutes")
            if not minutes:
                continue  # unused player — no workload
            team_label = (club_of or {}).get(pid) or team_name.get(tid, side["team"]["name"])
            out.append({
                "_id": gid,
                "playerId": pid,
                "playerName": entry["player"]["name"],
                "team": team_label,
                "position": _pos(gstat.get("position")),
                "opponent": team_name.get(opp_id, opp_name),
                "home": tid == home_id,
                "competition": competition,
                "date": date,
                "started": not gstat.get("substitute", True),
                "minutes": minutes,
                "goals": (stat.get("goals", {}) or {}).get("total") or 0,
                "assists": (stat.get("goals", {}) or {}).get("assists") or 0,
                "rating": _rating(gstat),
            })
            gid += 1
    return out, gid


def ingest():
    """Ingest one or more seasons. The last season in INGEST_SEASONS is the
    'live' one (drives roster / fixtures / current_features); earlier seasons
    add games + injuries for richer model training and player history."""
    league = af.LEAGUE_ID
    seasons = INGEST_SEASONS
    live = seasons[-1]
    print(f"\n== Ingesting Premier League seasons {seasons} (live {live}) ==")

    all_games, all_injuries = [], []
    gid, iid = 1, 1
    live_ctx = None
    for s in seasons:
        ctx = _season_data(s, gid, iid, is_live=(s == live))
        for g in ctx["games"]:
            g["season"] = s
        for inj in ctx["injuries"]:
            inj["season"] = s
        all_games += ctx["games"]
        all_injuries += ctx["injuries"]
        gid, iid = ctx["gid"], ctx["iid"]
        if s == live:
            live_ctx = ctx

    players = live_ctx["players"]
    team_docs = live_ctx["team_docs"]
    fixture_docs = live_ctx["fixture_docs"]
    reference_date = live_ctx["reference_date"]

    # Stage each collection into a temp then atomic-rename over the live one, so a
    # crash mid-persist can't leave collections empty (old data survives until swap).
    database = db.get_db()
    staged = {"players": players, "games": all_games, "injuries": all_injuries,
              "fixtures": fixture_docs, "teams": team_docs}
    for name, docs in staged.items():
        if not docs:
            continue
        tmp = database[name + "_tmp"]
        tmp.drop()
        tmp.insert_many(docs)
        tmp.rename(name, dropTarget=True)  # atomic swap
    db.ensure_indexes()

    feat.set_reference_date(reference_date, {
        "dataSource": "apifootball", "season": live, "seasons": seasons, "league": league,
    })
    print("  persisted to MongoDB.")
    return {
        "seasons": seasons, "players": len(players), "games": len(all_games),
        "injuries": len(all_injuries), "fixtures": len(fixture_docs),
        "referenceDate": reference_date.isoformat(),
    }


def _season_data(season, gid, iid, is_live):
    """Build one season's games + injuries (+ live-only roster/fixtures/teams).
    Reads its own team map since relegated/promoted clubs differ by season."""
    league = af.LEAGUE_ID
    print(f"\n-- season {season} {'(live)' if is_live else '(history)'} --")
    teams = af.get_teams(league, season)
    team_name = {t["team"]["id"]: t["team"]["name"] for t in teams}

    # Ages/shirt numbers + season-accurate bios only for the live season (roster).
    squad_info, player_bio = {}, {}
    if is_live:
        for t in teams:
            for pl in af.get_squad(t["team"]["id"]):
                squad_info[pl["id"]] = {"age": pl.get("age"), "number": pl.get("number")}
        try:
            for pl in af.get_players(league, season):
                p = pl.get("player", {})
                player_bio[p.get("id")] = {"birth": (p.get("birth") or {}).get("date"),
                                           "nationality": p.get("nationality") or ""}
        except af.ApiError as e:
            print(f"  ! player bios unavailable ({e})")

    fixtures = af.get_fixtures(league, season)
    finished = sorted(
        [f for f in fixtures if f["fixture"]["status"]["short"] in FINISHED],
        key=lambda f: f["fixture"]["date"],
    )
    if is_live and UPCOMING_RESERVE:
        detail = finished[:-UPCOMING_RESERVE][-MAX_FIXTURE_DETAIL:]
    else:
        detail = finished[-MAX_FIXTURE_DETAIL:]
    reference_date = _parse(detail[-1]["fixture"]["date"]) if detail else \
        _parse(finished[-1]["fixture"]["date"])
    window_start = _parse(detail[0]["fixture"]["date"]) if detail else reference_date

    # League games
    games = []
    for i, f in enumerate(detail, 1):
        rows, gid = _box_scores(f, team_name, "Premier League", gid)
        games.extend(rows)
        if i % 60 == 0:
            print(f"    …{i}/{len(detail)} league fixtures")

    in_window = lambda f: (f["fixture"]["status"]["short"] in FINISHED and
                           window_start <= _parse(f["fixture"]["date"]) <= reference_date)
    pl_ids = set(team_name)
    UEFA = {2, 3, 848}
    club_of = {}
    for g in games:
        club_of.setdefault(g["playerId"], g["team"])
    our_player_ids = set(club_of)

    # Club competitions (European + domestic cups) — filtered to our clubs.
    european: dict[int, str] = {}
    club_detail = []
    for lg, comp in CLUB_COMPS.items():
        try:
            cfx = af.get_fixtures(lg, season)
        except af.ApiError:
            continue
        for f in cfx:
            involved = {f["teams"]["home"]["id"], f["teams"]["away"]["id"]} & pl_ids
            if not involved:
                continue
            if lg in UEFA:
                for tid in involved:
                    european[tid] = comp
            if in_window(f):
                club_detail.append((f, comp))
    club_detail.sort(key=lambda fc: fc[0]["fixture"]["date"])
    for f, comp in club_detail:
        rows, gid = _box_scores(f, team_name, comp, gid, only_teams=pl_ids)
        games.extend(rows)

    # International games — filtered to our players by id; comps straddle years.
    intl_detail, seen_fx = [], set()
    for lg, comp in INTL_COMPS.items():
        for yr in (season - 1, season, season + 1):
            try:
                ifx = af.get_fixtures(lg, yr)
            except af.ApiError:
                continue
            for f in ifx:
                fid = f["fixture"]["id"]
                if fid not in seen_fx and in_window(f):
                    seen_fx.add(fid)
                    intl_detail.append((f, comp))
    intl_detail.sort(key=lambda fc: fc[0]["fixture"]["date"])
    for f, comp in intl_detail[-MAX_INTL_DETAIL:]:
        rows, gid = _box_scores(f, team_name, comp, gid,
                                only_players=our_player_ids, club_of=club_of)
        games.extend(rows)
    print(f"    games: {len(games)} (league + cups/euro + internationals)")

    raw = af.get_injuries(league, season)
    injuries, iid = _build_injury_episodes(raw, team_name, reference_date, iid)
    print(f"    injury episodes: {len(injuries)}")

    players, team_docs, fixture_docs = [], [], []
    if is_live:
        # Standings → team strength / fixture difficulty.
        strength: dict[str, dict] = {}
        for row in af.get_standings(league, season):
            t = row["team"]
            played = (row.get("all", {}) or {}).get("played") or 1
            doc = {
                "_id": t["id"], "name": team_name.get(t["id"], t["name"]),
                "rank": row.get("rank"), "points": row.get("points"), "played": played,
                "ppg": round((row.get("points") or 0) / played, 2),
                "form": row.get("form"), "goalsDiff": row.get("goalsDiff"),
                "european": european.get(t["id"]),
            }
            team_docs.append(doc)
            strength[doc["name"]] = doc

        # Roster from the live season's participants. A player's club is their
        # LATEST league game's team, so mid-season transfers show the new club
        # (list order + internationals labelled with the old club would mislead).
        roster = {}
        for g in games:
            e = roster.setdefault(g["playerId"], {
                "name": g["playerName"], "team": g["team"], "positions": [], "team_date": None})
            e["positions"].append(g["position"])
            if g["competition"] == "Premier League" and (e["team_date"] is None or g["date"] >= e["team_date"]):
                e["team"] = g["team"]
                e["team_date"] = g["date"]
        for pid, e in roster.items():
            sq = squad_info.get(pid, {})
            bio = player_bio.get(pid, {})
            age = _age_from_birth(bio.get("birth"), reference_date) or _valid_age(sq.get("age"))
            players.append({
                "_id": pid, "name": e["name"], "team": e["team"],
                "position": Counter(e["positions"]).most_common(1)[0][0],
                "age": age, "nationality": bio.get("nationality", ""), "number": sq.get("number"),
            })
        known = sum(1 for p in players if p["age"] is not None)
        print(f"    roster: {len(players)} ({known} with age)")

        # Fixture docs for gameweek planner.
        def _round_no(f):
            r = (f.get("league", {}) or {}).get("round", "")
            try:
                return int(str(r).rsplit("-", 1)[1].strip())
            except (ValueError, IndexError):
                return None
        fxid = 1
        for f in fixtures:
            rnd = _round_no(f)
            if rnd is None:
                continue
            for side, home in (("home", True), ("away", False)):
                tid = f["teams"][side]["id"]
                opp_id = f["teams"]["away" if home else "home"]["id"]
                opp = team_name.get(opp_id, f["teams"]["away" if home else "home"]["name"])
                opp_meta = strength.get(opp, {})
                fixture_docs.append({
                    "_id": fxid, "team": team_name.get(tid, ""), "opponent": opp,
                    "home": home, "competition": "Premier League",
                    "date": _parse(f["fixture"]["date"]), "round": rnd,
                    "difficulty": _difficulty(opp_meta.get("ppg", 1.3), home),
                    "opponentRank": opp_meta.get("rank"),
                })
                fxid += 1

    return {"games": games, "injuries": injuries, "gid": gid, "iid": iid,
            "reference_date": reference_date, "players": players,
            "team_docs": team_docs, "fixture_docs": fixture_docs}


def _build_injury_episodes(raw, team_name, reference_date, iid=1):
    """Collapse per-fixture unavailability rows into injury episodes.
    Returns (episodes, next_iid) so ids stay unique across seasons."""
    # Group missed-fixture dates per (player, reason), excluding non-injuries.
    groups: dict[tuple, dict] = {}
    for row in raw:
        player = row.get("player", {})
        reason = (player.get("reason") or "").strip()
        if not reason or any(k in reason.lower() for k in NON_INJURY):
            continue
        pid = player.get("id")
        fx = row.get("fixture", {})
        date = _parse(fx.get("date")) if fx.get("date") else None
        if pid is None or date is None:
            continue
        key = (pid, reason)
        g = groups.setdefault(key, {
            "playerId": pid, "playerName": player.get("name", ""),
            "team": (row.get("team", {}) or {}).get("name", ""),
            "reason": reason, "dates": [],
        })
        g["dates"].append(date)

    episodes = []
    for g in groups.values():
        dates = sorted(g["dates"])
        # Split into episodes when there's a >30-day gap between missed games.
        segment = [dates[0]]
        for d in dates[1:]:
            if (d - segment[-1]).days > 30:
                episodes.append(_episode(iid, g, segment, team_name, reference_date))
                iid += 1
                segment = [d]
            else:
                segment.append(d)
        episodes.append(_episode(iid, g, segment, team_name, reference_date))
        iid += 1
    return episodes, iid


def _episode(iid, g, segment, team_name, reference_date):
    date_injured = segment[0] - timedelta(days=2)
    expected_return = segment[-1] + timedelta(days=5)
    days_out = max(1, (expected_return - date_injured).days)
    status = "Active" if date_injured <= reference_date <= expected_return else "Recovered"
    return {
        "_id": iid,
        "playerId": g["playerId"],
        "playerName": g["playerName"],
        "team": g["team"],
        "position": "",
        "type": g["reason"],
        "bodyPart": _body_part(g["reason"]),
        "severity": _severity(days_out),
        "mechanism": "Match",
        "dateInjured": date_injured,
        "daysOut": days_out,
        "expectedReturn": expected_return,
        "status": status,
        "acwrAtOnset": 0.0,
        "notes": f"{g['reason']} — missed {len(segment)} fixture(s).",
    }


def _parse(iso: str):
    from dateutil import parser
    dt = parser.isoparse(iso)
    return dt.replace(tzinfo=None)  # store naive UTC to match the rest of the app


if __name__ == "__main__":
    counts = ingest()
    print("\nIngest complete:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("\nBuilding features…")
    print(feat.compute_features())
