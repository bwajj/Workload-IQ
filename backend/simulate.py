"""Deterministic simulation of a Premier League half-season.

Produces heterogeneous box-score documents (per player, per match) and injury
reports. Crucially, injuries are *caused* by workload in the model below
(acute:chronic spikes, fixture congestion, low rest, age), so the correlations
the platform later surfaces — and the ML model it trains — reflect a genuine
signal rather than noise.
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta

SEASON_START = datetime(2026, 1, 5)
SEASON_END = datetime(2026, 7, 5)
TODAY = datetime(2026, 7, 8)  # reference "now" for current risk

TEAMS = [
    "Arsenal", "Manchester City", "Liverpool", "Chelsea",
    "Manchester United", "Tottenham Hotspur", "Newcastle United", "Aston Villa",
]

FIRST_NAMES = [
    "James", "Oliver", "Harry", "Jack", "Leo", "Noah", "Lucas", "Mason", "Ethan",
    "Diego", "Marco", "Luka", "Kai", "Youssef", "Mateo", "Andre", "Bruno", "Rafael",
    "Kenji", "Omar", "Nikola", "Sven", "Pierre", "Thiago", "Sergio", "Viktor",
]
LAST_NAMES = [
    "Bennett", "Clarke", "Foster", "Hughes", "Reid", "Walsh", "Doyle", "Marsh",
    "Costa", "Silva", "Moreno", "Kovac", "Larsson", "Novak", "Fischer", "Dubois",
    "Rossi", "Ferrari", "Yilmaz", "Haddad", "Andersen", "Petrov", "Mensah", "Okafor",
    "Tanaka", "Nakamura", "Vidal", "Sanchez", "Muller", "Bianchi",
]

POSITION_PLAN = ["GK", "GK", "GK",
                 "DEF", "DEF", "DEF", "DEF", "DEF", "DEF", "DEF",
                 "MID", "MID", "MID", "MID", "MID", "MID",
                 "FWD", "FWD", "FWD", "FWD"]  # 20 players / squad

NATIONALITIES = ["England", "Spain", "France", "Brazil", "Portugal", "Germany",
                 "Netherlands", "Argentina", "Italy", "Japan", "Sweden", "Senegal"]

SEVERITY_BANDS = [  # (severity, weight, min_days, max_days)
    ("Minor", 0.50, 5, 14),
    ("Moderate", 0.35, 15, 45),
    ("Severe", 0.15, 46, 180),
]

INJURY_TYPES = {
    "Hamstring": ["Hamstring strain (grade 1)", "Hamstring strain (grade 2)", "Hamstring tear"],
    "Calf": ["Calf strain", "Calf tightness"],
    "Knee": ["Knee ligament (ACL)", "Knee cartilage", "MCL sprain"],
    "Ankle": ["Ankle sprain", "Ankle ligament damage"],
    "Groin": ["Groin/adductor strain"],
    "Thigh": ["Thigh strain", "Quadriceps strain"],
    "Foot": ["Metatarsal fracture", "Foot contusion"],
    "Back": ["Lower back spasm"],
}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def simulate():
    rng = random.Random(42)

    players = []
    pid = 1
    for team in TEAMS:
        used = set()
        for i, pos in enumerate(POSITION_PLAN):
            # Unique-ish name per player.
            while True:
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                if name not in used:
                    used.add(name)
                    break
            # First ~13 listed players are "regulars" (start most games).
            regular = i in (0, 3, 4, 5, 6, 10, 11, 12, 16, 17, 18, 13, 7)
            players.append({
                "_id": pid,
                "name": name,
                "team": team,
                "position": pos,
                "age": rng.randint(18, 35),
                "nationality": rng.choice(NATIONALITIES),
                "number": i + 1,
                "regular": regular,
            })
            pid += 1

    by_team = {t: [p for p in players if p["team"] == t] for t in TEAMS}

    # Per-player mutable state during the simulation.
    state = {p["_id"]: {"appearances": [], "injured_until": None, "ever_injured": False}
             for p in players}

    games = []
    injuries = []
    gid = 1
    iid = 1

    # Build a global, chronologically-ordered match list across all teams so
    # injuries accrue in real time.
    team_matches = []  # (date, team)
    for team in TEAMS:
        d = SEASON_START + timedelta(days=rng.randint(0, 3))
        while d <= SEASON_END:
            team_matches.append((d, team))
            gap = rng.choices([3, 4, 7, 7, 8, 10], weights=[3, 3, 6, 6, 3, 2])[0]
            d = d + timedelta(days=gap)
    team_matches.sort(key=lambda x: x[0])

    def features_for(player_id, ref_date):
        appts = [(dt, m) for dt, m in state[player_id]["appearances"] if dt <= ref_date]
        acute7 = sum(m for dt, m in appts if (ref_date - dt).days <= 6)
        chronic_total = sum(m for dt, m in appts if (ref_date - dt).days <= 27)
        chronic_weekly = chronic_total / 4.0
        if chronic_weekly < 30:  # warm-up period, ratio not yet meaningful
            acwr = 1.0
        else:
            acwr = acute7 / chronic_weekly
        recent = [dt for dt, _ in appts if (ref_date - dt).days <= 13]
        matches14 = len(recent)
        recent_sorted = sorted(recent)
        b2b = sum(1 for a, b in zip(recent_sorted, recent_sorted[1:]) if (b - a).days <= 3)
        prev = appts[-2][0] if len(appts) >= 2 else None
        last = appts[-1][0] if appts else None
        rest_days = (last - prev).days if (prev and last) else 7
        return {
            "acute7": acute7,
            "chronic28": round(chronic_weekly, 1),
            "acwr": round(acwr, 3),
            "restDays": rest_days,
            "backToBack14": b2b,
            "matches14": matches14,
            "minutes7": acute7,
        }

    for match_date, team in team_matches:
        squad = by_team[team]
        available = [p for p in squad
                     if state[p["_id"]]["injured_until"] is None
                     or state[p["_id"]]["injured_until"] <= match_date]
        opponent = rng.choice([t for t in TEAMS if t != team])
        home = rng.random() < 0.5
        competition = "Premier League" if rng.random() < 0.8 else "Cup"

        def pick(pos, n, pool):
            cands = [p for p in pool if p["position"] == pos]
            cands.sort(key=lambda p: (not p["regular"], rng.random()))
            return cands[:n]

        starters = (pick("GK", 1, available) + pick("DEF", 4, available)
                    + pick("MID", 3, available) + pick("FWD", 3, available))
        starter_ids = {p["_id"] for p in starters}
        bench = [p for p in available if p["_id"] not in starter_ids]
        subs = rng.sample(bench, min(3, len(bench))) if bench else []

        for p in starters:
            minutes = 90 if rng.random() < 0.7 else rng.randint(60, 89)
            _record_game(games, gid, p, team, opponent, home, competition,
                         match_date, True, minutes, rng)
            gid += 1
            state[p["_id"]]["appearances"].append((match_date, minutes))
        for p in subs:
            minutes = rng.randint(8, 30)
            _record_game(games, gid, p, team, opponent, home, competition,
                         match_date, False, minutes, rng)
            gid += 1
            state[p["_id"]]["appearances"].append((match_date, minutes))

        # Evaluate injury onset for everyone who featured.
        for p in starters + subs:
            st = state[p["_id"]]
            feats = features_for(p["_id"], match_date)
            prob = (0.010
                    + 0.060 * max(0, feats["acwr"] - 1.3)
                    + 0.00035 * max(0, feats["acute7"] - 200)
                    + (0.020 if feats["restDays"] <= 3 else 0)
                    + 0.010 * feats["backToBack14"]
                    + 0.0015 * max(0, p["age"] - 30)
                    + (0.030 if st["ever_injured"] else 0))
            prob = _clamp(prob, 0.0, 0.5)
            if rng.random() < prob:
                sev = rng.choices([b[0] for b in SEVERITY_BANDS],
                                  weights=[b[1] for b in SEVERITY_BANDS])[0]
                band = next(b for b in SEVERITY_BANDS if b[0] == sev)
                days_out = rng.randint(band[2], band[3])
                date_injured = match_date + timedelta(days=rng.randint(0, 2))
                expected_return = date_injured + timedelta(days=days_out)
                body = rng.choice(list(INJURY_TYPES.keys()))
                inj_type = rng.choice(INJURY_TYPES[body])
                status = "Recovered" if expected_return <= TODAY else "Active"
                injuries.append({
                    "_id": iid,
                    "playerId": p["_id"],
                    "playerName": p["name"],
                    "team": team,
                    "position": p["position"],
                    "type": inj_type,
                    "bodyPart": body,
                    "severity": sev,
                    "mechanism": "Match" if competition != "Training" else "Training",
                    "dateInjured": date_injured,
                    "daysOut": days_out,
                    "expectedReturn": expected_return,
                    "status": status,
                    "acwrAtOnset": feats["acwr"],
                    "notes": f"Sustained vs {opponent}. ACWR {feats['acwr']} at onset.",
                })
                iid += 1
                st["injured_until"] = expected_return
                st["ever_injured"] = True

    # --- Labelled feature rows (one per appearance) for ML + correlation ----
    injury_by_player = {}
    for inj in injuries:
        injury_by_player.setdefault(inj["playerId"], []).append(inj["dateInjured"])

    features = []
    fid = 1
    pmap = {p["_id"]: p for p in players}
    for p in players:
        appts = sorted(state[p["_id"]]["appearances"])
        for ref_date, _m in appts:
            state[p["_id"]]["appearances"] = appts  # ensure full history visible
            feats = features_for(p["_id"], ref_date)
            injured_next14 = 0
            for di in injury_by_player.get(p["_id"], []):
                if ref_date < di <= ref_date + timedelta(days=14):
                    injured_next14 = 1
                    break
            features.append({
                "_id": fid,
                "playerId": p["_id"],
                "playerName": p["name"],
                "team": p["team"],
                "position": p["position"],
                "age": p["age"],
                "date": ref_date,
                **feats,
                "injuredNext14": injured_next14,
            })
            fid += 1

    # --- Current features (as of TODAY) for live risk scoring ---------------
    current_features = []
    for p in players:
        feats = features_for(p["_id"], TODAY)
        current_features.append({
            "_id": p["_id"],
            "playerId": p["_id"],
            "playerName": p["name"],
            "team": p["team"],
            "position": p["position"],
            "age": p["age"],
            "number": p["number"],
            "date": TODAY,
            **feats,
        })

    # --- Upcoming fixtures for the rotation planner -------------------------
    fixtures = []
    fx = 1
    for team in TEAMS:
        d = TODAY + timedelta(days=rng.randint(2, 4))
        for _ in range(3):
            fixtures.append({
                "_id": fx,
                "team": team,
                "opponent": rng.choice([t for t in TEAMS if t != team]),
                "home": rng.random() < 0.5,
                "competition": "Premier League",
                "date": d,
            })
            fx += 1
            d = d + timedelta(days=rng.choice([3, 4, 7]))

    # Strip the internal "regular" flag from stored player docs.
    for p in players:
        p.pop("regular", None)

    return {
        "players": players,
        "games": games,
        "injuries": injuries,
        "features": features,
        "current_features": current_features,
        "fixtures": fixtures,
    }


def _record_game(games, gid, p, team, opponent, home, competition, date, started, minutes, rng):
    games.append({
        "_id": gid,
        "playerId": p["_id"],
        "playerName": p["name"],
        "team": team,
        "position": p["position"],
        "opponent": opponent,
        "home": home,
        "competition": competition,
        "date": date,
        "started": started,
        "minutes": minutes,
        "goals": rng.choices([0, 1, 2], weights=[85, 12, 3])[0] if p["position"] in ("MID", "FWD") else 0,
        "assists": rng.choices([0, 1], weights=[88, 12])[0],
        "distanceKm": round(minutes * 0.115 + rng.uniform(-0.5, 0.5), 2),
        "sprints": int(minutes * rng.uniform(0.25, 0.4)),
    })


if __name__ == "__main__":
    data = simulate()
    for k, v in data.items():
        print(f"{k}: {len(v)}")
