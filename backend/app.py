"""Flask REST API for the workload / injury-risk analytics platform."""
from __future__ import annotations
import os
from datetime import datetime, date

from flask import Flask, jsonify, request, g
from flask_cors import CORS

import db
import pipelines
import risk
import features as feat
from seed import seed
import auth

app = Flask(__name__)
CORS(app)
app.register_blueprint(auth.bp)

# Everything under /api requires a valid bearer token except these.
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register",
                "/api/public/stats", "/api/teams/meta"}


@app.before_request
def require_auth():
    path = request.path
    if not path.startswith("/api") or path in PUBLIC_PATHS or request.method == "OPTIONS":
        return None
    user = auth.verify_token(auth.token_from_request())
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    g.user = user
    return None

# Where the data comes from: "apifootball" (real) or "simulated" (demo).
DATA_SOURCE = os.environ.get("DATA_SOURCE", "simulated")


def reference_now():
    """The reference 'today' for risk scoring — driven by the loaded dataset."""
    return feat.get_reference_date()


def auc_value(model):
    """Rounded AUC, or None when unavailable (NaN or heuristic fallback)."""
    a = model.auc
    if a is None or a != a:  # None or NaN
        return None
    return round(a, 3)


# --- Serialization --------------------------------------------------------

def clean(obj):
    """Recursively convert Mongo/py values into JSON-safe primitives."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def ok(data):
    return jsonify(clean(data))


# --- Startup --------------------------------------------------------------

def ensure_ready():
    """Seed the DB on first boot and make sure the model is trained.

    Waits for MongoDB to accept connections so start order under the dev
    orchestrator (mongo/api/web launched together) doesn't matter.
    """
    import time
    for attempt in range(30):
        if db.ping():
            break
        if attempt == 0:
            print("  …waiting for MongoDB to accept connections")
        time.sleep(1)
    else:
        raise RuntimeError("MongoDB is not reachable at " + db.MONGO_URI)

    if db.players().count_documents({}) == 0:
        if DATA_SOURCE == "apifootball":
            print("  …empty database, ingesting from API-Football")
            from ingest import ingest
            ingest()
        else:
            print("  …empty database, seeding simulated data")
            seed()

    # Make sure derived feature collections exist (real-data ingest already
    # builds them; simulated seed builds them too, but recompute if missing).
    if db.features().count_documents({}) == 0 or \
            db.get_db()["current_features"].count_documents({}) == 0:
        feat.compute_features()

    auth.seed_demo_user()
    risk.train_model()


# --- Routes ---------------------------------------------------------------

@app.get("/api/health")
def health():
    reachable = db.ping()
    meta = db.get_db()["meta"].find_one({"_id": "meta"}) if reachable else None
    last = (meta or {}).get("lastRefresh")
    return ok({
        "status": "ok" if reachable else "degraded",
        "mongoConnected": reachable,
        "players": db.players().count_documents({}) if reachable else 0,
        "modelTrained": risk._model is not None,
        "dataSource": DATA_SOURCE,
        "today": reference_now().isoformat() if reachable else None,
        "lastRefresh": last.isoformat() if last else None,
    })


@app.post("/api/seed")
def reseed():
    counts = seed()
    risk.train_model()
    return ok({"seeded": counts})


@app.post("/api/ingest")
def do_ingest():
    """Pull the latest real data from API-Football, rebuild features, retrain."""
    from ingest import ingest
    counts = ingest()
    feat.compute_features()
    risk.train_model()
    return ok({"ingested": counts})


@app.get("/api/public/stats")
def public_stats():
    """Aggregate teaser numbers for the landing page — no auth required.

    Everything here is public sports data (counts + a 3-row risk teaser)."""
    if not db.ping():
        return ok({"players": 0, "teams": 0, "games": 0, "injuries": 0,
                   "europeanClubs": 0, "riskTiers": {}, "topRisk": [], "season": None})
    rows = list(db.get_db()["current_features"].find({}, {"_id": 0}))
    scored = risk.score_players(rows)
    tiers = {"High": 0, "Moderate": 0, "Low": 0}
    for s in scored:
        tiers[s["riskTier"]] += 1
    top = sorted(scored, key=lambda s: s["riskProbability"], reverse=True)[:3]
    teaser = [{k: s[k] for k in ("playerId", "playerName", "team", "riskScore", "riskTier", "acwr")}
              for s in top]
    meta = db.get_db()["meta"].find_one({"_id": "meta"}) or {}
    return ok({
        "players": db.players().count_documents({}),
        "teams": len(db.players().distinct("team")),
        "games": db.games().count_documents({}),
        "injuries": db.injuries().count_documents({}),
        "europeanClubs": db.get_db()["teams"].count_documents({"european": {"$ne": None}}),
        "riskTiers": tiers,
        "topRisk": teaser,
        "season": meta.get("season"),
    })


@app.get("/api/teams")
def teams():
    return ok(sorted(db.players().distinct("team")))


@app.get("/api/teams/meta")
def teams_meta():
    """Public team metadata (id → crest URL mapping lives client-side)."""
    docs = db.get_db()["teams"].find({}, {"_id": 1, "name": 1, "european": 1, "rank": 1})
    return ok([{"id": d["_id"], "name": d["name"], "european": d.get("european"),
                "rank": d.get("rank")} for d in docs])


@app.post("/api/fpl")
def fpl_squad():
    """Resolve a user's FPL Team ID to their squad, scored by our risk model."""
    import fpl
    body = request.get_json(silent=True) or {}
    team_id = body.get("teamId")
    if not team_id:
        return jsonify({"error": "Enter your FPL Team ID"}), 400
    try:
        squad = fpl.analyze_entry(int(team_id), body.get("gameweek"))
    except (ValueError, TypeError):
        return jsonify({"error": "Team ID must be a number"}), 400
    except fpl.FplError:
        return jsonify({"error": "Couldn't find that FPL team — check the Team ID"}), 404

    ids = [p["playerId"] for p in squad["matched"]]
    rows = list(db.get_db()["current_features"].find({"playerId": {"$in": ids}}, {"_id": 0}))
    scored = {s["playerId"]: s for s in risk.score_players(rows)}
    injured = risk.currently_injured_ids(reference_now())

    players = []
    for p in squad["matched"]:
        s = scored.get(p["playerId"])
        if not s:
            continue
        players.append({**s, "isCaptain": p["isCaptain"], "isViceCaptain": p["isViceCaptain"],
                        "onBench": p["onBench"], "price": p.get("price"),
                        "available": p["playerId"] not in injured})
    risk.tag_confidence(players, reference_now())
    players.sort(key=lambda s: (s["onBench"], -s["riskProbability"]))

    return ok({
        "managerName": squad["managerName"], "teamName": squad["teamName"],
        "gameweek": squad["gameweek"],
        "matchedCount": len(players), "pickCount": len(squad["matched"]) + len(squad["unmapped"]),
        "players": players, "unmapped": squad["unmapped"],
    })


@app.get("/api/overview")
def overview():
    model = risk.get_model()
    rows = list(db.get_db()["current_features"].find({}, {"_id": 0}))
    scored = risk.score_players(rows)
    injured = risk.currently_injured_ids(reference_now())

    tiers = {"High": 0, "Moderate": 0, "Low": 0}
    for s in scored:
        tiers[s["riskTier"]] += 1

    top = sorted(scored, key=lambda s: s["riskProbability"], reverse=True)[:10]

    return ok({
        "counts": {
            "players": db.players().count_documents({}),
            "games": db.games().count_documents({}),
            "injuries": db.injuries().count_documents({}),
            "activeInjuries": len(injured),
            "teams": len(db.players().distinct("team")),
        },
        "model": {
            "auc": auc_value(model),
            "baseRate": round(model.base_rate, 3),
            "coefficients": model.coefficients,
            "modelType": model.model_type,
            "note": model.note,
            "learnedAuc": model.learned_auc,
        },
        "riskTiers": tiers,
        "topRisk": top,
    })


@app.get("/api/players")
def players():
    team = request.args.get("team")
    query = {"team": team} if team and team != "All" else {}
    rows = list(db.get_db()["current_features"].find(query, {"_id": 0}))
    scored = risk.score_players(rows)
    injured = risk.currently_injured_ids(reference_now())
    import fpl
    prices = fpl.prices_by_our_id()
    for s in scored:
        s["available"] = s["playerId"] not in injured
        s["price"] = prices.get(s["playerId"])
    risk.tag_confidence(scored, reference_now())
    scored.sort(key=lambda s: s["riskProbability"], reverse=True)
    return ok(scored)


@app.get("/api/players/<int:player_id>")
def player_detail(player_id):
    player = db.players().find_one({"_id": player_id})
    if not player:
        return jsonify({"error": "Player not found"}), 404

    row = db.get_db()["current_features"].find_one({"playerId": player_id}, {"_id": 0})
    scored = risk.score_players([row]) if row else []
    timeline = list(db.games().aggregate(pipelines.player_rolling_timeline(player_id)))
    injuries = list(db.injuries().find({"playerId": player_id}).sort("dateInjured", 1))

    return ok({
        "player": player,
        "risk": scored[0] if scored else None,
        "timeline": timeline,
        "injuries": injuries,
    })


@app.get("/api/correlation")
def correlation():
    buckets = list(db.features().aggregate(pipelines.injury_rate_by_acwr_bucket()))
    body_parts = list(db.injuries().aggregate(pipelines.injuries_by_body_part()))
    model = risk.get_model()
    return ok({
        "acwrBuckets": buckets,
        "bodyParts": body_parts,
        "coefficients": model.coefficients,
        "modelAuc": auc_value(model),
    })


@app.get("/api/transfers")
def transfers():
    """Replacement suggestions for a player: same position, similar-or-lower
    price, available, ranked by start confidence."""
    import fpl
    out_id = request.args.get("playerId", type=int)
    if out_id is None:
        return jsonify({"error": "playerId required"}), 400
    exclude = {int(x) for x in request.args.get("exclude", "").split(",") if x.strip().isdigit()}
    exclude.add(out_id)

    rows = list(db.get_db()["current_features"].find({}, {"_id": 0}))
    scored = {s["playerId"]: s for s in risk.score_players(rows)}
    out = scored.get(out_id)
    if not out:
        return jsonify({"error": "Player not found"}), 404

    injured = risk.currently_injured_ids(reference_now())
    prices = fpl.prices_by_our_id()
    for s in scored.values():
        s["available"] = s["playerId"] not in injured
        s["price"] = prices.get(s["playerId"])
    risk.tag_confidence(list(scored.values()), reference_now())

    out_price = prices.get(out_id)
    cap = (out_price + 0.5) if out_price is not None else None
    cands = [s for s in scored.values()
             if s["position"] == out["position"] and s["playerId"] not in exclude
             and s["available"] and s["matches14"] >= 1
             and (cap is None or (s.get("price") is not None and s["price"] <= cap))]
    cands.sort(key=lambda s: -(s.get("confidence") or 0))
    return ok({"out": {**out, "price": out_price}, "suggestions": cands[:3]})


@app.get("/api/fixture-ticker")
def fixture_ticker():
    """20 teams × next N gameweeks of fixture difficulty (FPL-style ticker)."""
    n = request.args.get("n", default=6, type=int)
    from_round = request.args.get("fromRound", type=int)
    rounds = sorted(db.fixtures().distinct("round"))
    if not rounds:
        return ok({"rounds": [], "teams": []})
    start = from_round if from_round in rounds else rounds[0]
    window = [r for r in rounds if r >= start][:n]

    by_team: dict[str, list] = {}
    for f in db.fixtures().find({"round": {"$in": window}}):
        by_team.setdefault(f["team"], []).append({
            "round": f["round"], "opponent": f["opponent"],
            "home": f["home"], "difficulty": f.get("difficulty"),
        })
    teams = []
    for team, fx in by_team.items():
        fx.sort(key=lambda x: x["round"])
        diffs = [x["difficulty"] for x in fx if x["difficulty"] is not None]
        teams.append({"team": team, "fixtures": fx,
                      "avgDifficulty": round(sum(diffs) / len(diffs), 2) if diffs else None})
    teams.sort(key=lambda t: t["avgDifficulty"] if t["avgDifficulty"] is not None else 99)
    return ok({"rounds": window, "teams": teams})


@app.get("/api/team-load")
def team_load():
    return ok(list(db.games().aggregate(pipelines.team_load_ranking())))


@app.get("/api/workload-summary")
def workload_summary():
    team = request.args.get("team")
    pipeline = pipelines.player_workload_summary()
    if team and team != "All":
        pipeline = [{"$match": {"team": team}}] + pipeline
    return ok(list(db.games().aggregate(pipeline)))


@app.get("/api/rotation/<team>")
def rotation(team):
    gw = request.args.get("gameweek", type=int)
    return ok(risk.rotation_plan(team, reference_now(), gameweek=gw))


@app.get("/api/gameweeks")
def gameweeks():
    """Rounds selectable in the planner/backtest — only those with enough
    workload history behind them (>=3 weeks of detailed games)."""
    return ok(risk.selectable_gameweeks())


@app.post("/api/digest/send")
def send_digest():
    """Email the signed-in user the gameweek digest (captain picks + injury risks)."""
    import digest
    body = request.get_json(silent=True) or {}
    gw = body.get("gameweek")
    result = digest.send_digest(g.user["email"], gw)
    if result is None:
        return jsonify({"error": "No pickable gameweeks in this dataset"}), 404
    return ok(result)


@app.get("/api/picks")
def picks():
    """Captain shortlist + players to sit for a gameweek."""
    gw = request.args.get("gameweek", type=int)
    result = risk.gameweek_picks(gw)
    if result is None:
        return jsonify({"error": "No pickable gameweeks in this dataset"}), 404
    return ok(result)


@app.get("/api/backtest")
def backtest():
    """Predictions vs reality for a past gameweek."""
    gw = request.args.get("gameweek", type=int)
    result = risk.backtest_gameweek(gw)
    if result is None:
        return jsonify({"error": "No backtestable gameweeks in this dataset"}), 404
    return ok(result)


@app.get("/api/backtest/summary")
def backtest_summary():
    """Aggregate evaluation pooled across all backtestable gameweeks."""
    result = risk.backtest_summary()
    if result is None:
        return jsonify({"error": "No backtestable gameweeks in this dataset"}), 404
    return ok(result)


@app.post("/api/players/<int:player_id>/simulate")
def simulate(player_id):
    """Recompute a player's risk after hypothetical upcoming matches."""
    body = request.get_json(silent=True) or {}
    result = risk.simulate_workload(player_id, body.get("extraMatches", []))
    if result is None:
        return jsonify({"error": "Player not found"}), 404
    return ok(result)


@app.get("/api/injuries")
def injuries():
    team = request.args.get("team")
    query = {"team": team} if team and team != "All" else {}
    docs = list(db.injuries().find(query).sort("dateInjured", -1))
    return ok(docs)


if __name__ == "__main__":
    ensure_ready()
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", 5001)))
    print(f"\n  🩺  Injury-risk API on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
