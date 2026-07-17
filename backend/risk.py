"""Injury-risk modelling and lineup-rotation recommendations.

A logistic-regression model is trained on the labelled feature rows (workload
features -> injured within 14 days). Predicted probabilities are combined with
interpretable sports-science rules (ACWR spikes, congestion) to tier players
and drive rotation suggestions.
"""
from __future__ import annotations
from datetime import timedelta

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import cross_val_score, GroupKFold
from sklearn.inspection import permutation_importance

import db
import features as feat

FEATURES = ["acwr", "acute7", "chronic28", "restDays", "backToBack14", "matches14", "age",
            "priorInjuries", "daysSinceReturn", "recentReturn",
            "load21", "acute3", "ratio21", "careerGames"]

# The model predicts workload-driven (soft-tissue) injuries specifically.
TARGET = "softInjuryNext14"

FORMATION = {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3}

_model = None  # cached ModelBundle


MIN_USEFUL_AUC = 0.55  # below this the learned model isn't worth shipping


class ModelBundle:
    def __init__(self, pipeline, auc, coefficients, p_moderate, p_high, base_rate,
                 model_type="logistic", note="", learned_auc=None):
        self.pipeline = pipeline
        self.auc = auc
        self.coefficients = coefficients
        self.p_moderate = p_moderate
        self.p_high = p_high
        self.base_rate = base_rate
        self.model_type = model_type    # "logistic" or "rules"
        self.note = note                # honest disclosure for the UI
        self.learned_auc = learned_auc  # CV AUC of the learned model, if trained

    def predict(self, rows):
        if self.pipeline is None:  # heuristic fallback (no trainable labels)
            return np.array([_heuristic_prob(r) for r in rows])
        X = np.array([[r[f] for f in FEATURES] for r in rows], dtype=float)
        return self.pipeline.predict_proba(X)[:, 1]


def _to_matrix(docs):
    X = np.array([[d[f] for f in FEATURES] for d in docs], dtype=float)
    y = np.array([d.get(TARGET, d.get("injuredNext14", 0)) for d in docs], dtype=int)
    groups = np.array([d["playerId"] for d in docs])
    return X, y, groups


def _heuristic_prob(r):
    """Rules-based injury probability used when ML labels are too sparse."""
    p = 0.05
    p += 0.15 * max(0.0, r["acwr"] - 1.3)
    p += 0.10 if r["restDays"] <= 3 else 0.0
    p += 0.05 * r["backToBack14"]
    p += 0.03 if r["matches14"] >= 3 else 0.0
    p += 0.012 * min(15, max(0, r["age"] - 30))  # cap so a bad age can't dominate
    if r["acwr"] < 0.8 and r["chronic28"] > 30:
        p += 0.05
    # Injury history: the weeks after returning carry the sharpest re-injury
    # risk, and repeat injuries compound it (previous injury is a leading predictor).
    dsr = r.get("daysSinceReturn", 400)
    if dsr <= 21:
        p += 0.12
    elif dsr <= 45:
        p += 0.06
    p += 0.03 * min(3, r.get("priorInjuries", 0))
    return float(min(0.9, p))


def _heuristic_bundle(docs, y, note="", learned_auc=None) -> "ModelBundle":
    """Rules-based scorer used when there aren't enough labels to train, or when
    the learned model fails to beat baseline. Scores via sports-science rules so
    the product stays sensible and degrades honestly."""
    probs = np.array([_heuristic_prob(d) for d in docs]) if docs else np.array([0.05])
    coefficients = [
        {"feature": "acwr", "weight": 0.15}, {"feature": "recentReturn", "weight": 0.12},
        {"feature": "restDays", "weight": -0.10}, {"feature": "backToBack14", "weight": 0.05},
        {"feature": "priorInjuries", "weight": 0.03}, {"feature": "matches14", "weight": 0.03},
        {"feature": "age", "weight": 0.012},
    ]
    base = float(y.mean()) if len(y) else 0.0
    return ModelBundle(None, None, coefficients,
                       float(np.quantile(probs, 0.60)), float(np.quantile(probs, 0.85)),
                       base, model_type="rules", note=note, learned_auc=learned_auc)


def train_model() -> ModelBundle:
    """Train the injury-risk model, honestly validated with cross-validation.

    If the learned model can't beat baseline (CV AUC < MIN_USEFUL_AUC) — common
    with real, noisy injury data over a limited window — we fall back to the
    interpretable ACWR rule set rather than ship a model worse than a coin flip.
    """
    global _model
    docs = list(db.features().find({}, {"_id": 0}))
    X, y, groups = _to_matrix(docs)

    # Need both classes (and enough positives) to fit a classifier at all.
    if len(np.unique(y)) < 2 or int(y.sum()) < 8:
        _model = _heuristic_bundle(
            docs, y, note="Too few injury labels to train a classifier — risk uses the ACWR rule set.")
        return _model

    # Gradient boosting captures the nonlinear workload↔injury interactions a
    # linear model misses. No scaling needed for trees.
    model = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_depth=4,
        l2_regularization=1.0, class_weight="balanced", random_state=42)

    # Honest estimate: GroupKFold by player, so no player appears in both train
    # and test (prevents leakage inflating the score).
    try:
        cv_auc = float(cross_val_score(
            model, X, y, cv=GroupKFold(5), groups=groups, scoring="roc_auc").mean())
    except ValueError:
        cv_auc = float("nan")

    model.fit(X, y)

    # Signed importances for the Evidence chart: permutation importance
    # (how much AUC drops when a feature is shuffled) × the sign of its
    # correlation with injury (direction). Sampled for speed.
    n = min(6000, len(y))
    idx = np.random.RandomState(0).choice(len(y), n, replace=False)
    imp = permutation_importance(model, X[idx], y[idx], n_repeats=3,
                                 scoring="roc_auc", random_state=0).importances_mean
    imp = np.clip(imp, 0, None)
    coefficients = []
    for j, f in enumerate(FEATURES):
        col = X[:, j]
        corr = np.corrcoef(col, y)[0, 1] if col.std() > 0 else 0.0
        sign = 1.0 if corr >= 0 else -1.0
        coefficients.append({"feature": f, "weight": round(float(imp[j] * sign), 3)})
    coefficients.sort(key=lambda x: abs(x["weight"]), reverse=True)

    # Gate: only ship the learned model if it beats baseline on held-out folds.
    if not (cv_auc == cv_auc) or cv_auc < MIN_USEFUL_AUC:
        _model = _heuristic_bundle(
            docs, y,
            note=(f"Learned model CV AUC {cv_auc:.2f} < {MIN_USEFUL_AUC:.2f} on this window — "
                  f"risk uses the validated ACWR rule set instead."),
            learned_auc=None if cv_auc != cv_auc else round(cv_auc, 3))
        return _model

    probs_all = model.predict_proba(X)[:, 1]
    _model = ModelBundle(model, round(cv_auc, 3), coefficients,
                         float(np.quantile(probs_all, 0.60)), float(np.quantile(probs_all, 0.85)),
                         float(y.mean()), model_type="gradient-boost")
    return _model


def get_model() -> ModelBundle:
    return _model if _model is not None else train_model()


def _tier(prob, feat, m: ModelBundle):
    """Combine model probability with interpretable domain rules."""
    reasons = []
    dsr = feat.get("daysSinceReturn", 400)
    prior = feat.get("priorInjuries", 0)
    recent_return = feat.get("recentReturn", 0) or dsr <= 21
    high_rule = (feat["acwr"] >= 1.5 or (feat["restDays"] <= 3 and feat["matches14"] >= 3)
                 or recent_return)
    mod_rule = (feat["acwr"] >= 1.3 or feat["backToBack14"] >= 1 or feat["matches14"] >= 3
                or dsr <= 45 or prior >= 3)

    if recent_return:
        reasons.append(f"Recently back from injury ({dsr}d ago) — return-to-play re-injury window")
    elif dsr <= 45:
        reasons.append(f"Returned from injury {dsr} days ago")
    if prior >= 2:
        reasons.append(f"{prior} injuries in the last year — injury-prone")
    if feat["acwr"] >= 1.5:
        reasons.append(f"ACWR spike ({feat['acwr']}) — well above the 1.3 threshold")
    elif feat["acwr"] >= 1.3:
        reasons.append(f"Elevated ACWR ({feat['acwr']})")
    elif feat["acwr"] < 0.8 and feat["chronic28"] > 30:
        reasons.append(f"Low ACWR ({feat['acwr']}) — undertraining/return-to-play zone")
    if feat["restDays"] <= 3:
        reasons.append(f"Short rest ({feat['restDays']} days since last match)")
    if feat["backToBack14"] >= 1:
        reasons.append(f"{feat['backToBack14']} back-to-back fixture(s) in last 14 days")
    if feat["matches14"] >= 3:
        reasons.append(f"High congestion ({feat['matches14']} matches in 14 days)")
    if feat["age"] >= 31:
        reasons.append(f"Age {feat['age']}")
    if not reasons:
        reasons.append("Workload within safe range")

    if prob >= m.p_high or high_rule:
        tier = "High"
    elif prob >= m.p_moderate or mod_rule:
        tier = "Moderate"
    else:
        tier = "Low"
    return tier, reasons


def score_players(rows):
    """Attach risk probability, tier and reasons to a list of current-feature rows."""
    m = get_model()
    if not rows:
        return []
    probs = m.predict(rows)
    scored = []
    for r, p in zip(rows, probs):
        tier, reasons = _tier(float(p), r, m)
        scored.append({
            "playerId": r["playerId"],
            "playerName": r["playerName"],
            "team": r["team"],
            "position": r["position"],
            "age": r["age"],
            "number": r.get("number"),
            "riskProbability": round(float(p), 3),
            "riskScore": int(round(float(p) * 100)),
            "riskTier": tier,
            "reasons": reasons,
            "acwr": r["acwr"],
            "acute7": r["acute7"],
            "chronic28": r["chronic28"],
            "restDays": r["restDays"],
            "backToBack14": r["backToBack14"],
            "matches14": r["matches14"],
            "fatigue": r.get("fatigue"),
            "form": r.get("form"),
            "priorInjuries": r.get("priorInjuries", 0),
            "daysSinceReturn": r.get("daysSinceReturn"),
        })
    return scored


# How much each factor pulls the "start confidence" score (must sum to 1).
CONFIDENCE_WEIGHTS = {"availability": 0.35, "form": 0.25, "fixture": 0.25, "freshness": 0.15}


def confidence_components(s, difficulty):
    """The four 0–100 sub-scores behind start confidence (higher = better)."""
    return {
        "availability": 100 - s["riskScore"],                       # low injury risk
        "form": (s["form"] * 10) if s.get("form") is not None else 60,  # recent rating
        "fixture": (6 - (difficulty or 3)) * 20,                    # easy opponent
        "freshness": 100 - (s.get("fatigue") or 0),                 # not fatigued
    }


def confidence_score(s, difficulty):
    """0–100 'start confidence': how confident to start/captain this player this
    gameweek, balancing injury risk and fatigue against form and fixture — the
    risk-vs-reward tradeoff in one number."""
    comp = confidence_components(s, difficulty)
    score = sum(CONFIDENCE_WEIGHTS[k] * comp[k] for k in CONFIDENCE_WEIGHTS)
    return int(round(max(0, min(100, score))))


def confidence_label(score):
    if score >= 75:
        return "Strong start"
    if score >= 60:
        return "Solid"
    if score >= 45:
        return "Toss-up"
    return "Bench"


def confidence_driver(s, difficulty):
    """One-line rationale: the weakest sub-score if it's a real drag, else the
    strongest. Powers the plain-English 'why' on picks."""
    comp = confidence_components(s, difficulty)
    labels = {"availability": "injury risk", "form": "poor form",
              "fixture": "tough fixture", "freshness": "fatigue"}
    strengths = {"availability": "low injury risk", "form": "in form",
                 "fixture": "soft fixture", "freshness": "well rested"}
    worst = min(comp, key=comp.get)
    if comp[worst] < 50:
        return f"held back by {labels[worst]}"
    best = max(comp, key=comp.get)
    return strengths[best]


def attach_confidence(scored: dict, difficulty, injured: set):
    """Tag each scored player with start confidence for the gameweek in place."""
    for pid, s in scored.items():
        if pid in injured:
            s["confidence"], s["confidenceLabel"] = 0, "Out"
        else:
            s["confidence"] = confidence_score(s, difficulty)
            s["confidenceLabel"] = confidence_label(s["confidence"])
            s["confidenceDriver"] = confidence_driver(s, difficulty)


def selectable_gameweeks():
    """Rounds usable in the planner/backtest: >=3 weeks of detailed match
    history behind them. `backtestable` marks rounds with fixtures still to
    come afterwards — i.e. an observable injury window."""
    first_game = db.games().find_one(sort=[("date", 1)])
    if not first_game:
        return []
    cutoff = first_game["date"] + timedelta(days=21)
    last = db.fixtures().find_one({"round": {"$exists": True, "$ne": None}},
                                  sort=[("date", -1)])
    if not last:
        return []
    rows = db.fixtures().aggregate([
        {"$match": {"round": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$round", "start": {"$min": "$date"}}},
        {"$match": {"start": {"$gte": cutoff}}},
        {"$sort": {"start": 1}},
    ])
    return [{"round": r["_id"], "start": r["start"],
             "backtestable": r["start"] < last["date"]} for r in rows]


def tag_confidence(players, today):
    """Attach start confidence in place, using each player's team next fixture."""
    diffs = {}
    for f in db.fixtures().find({"date": {"$gt": today}}).sort("date", 1):
        diffs.setdefault(f["team"], f.get("difficulty"))
    for s in players:
        d = diffs.get(s["team"], 3)
        s["confidence"] = confidence_score(s, d)
        s["confidenceLabel"] = confidence_label(s["confidence"])
        s["confidenceDriver"] = confidence_driver(s, d)
    return players


def gameweek_picks(gameweek=None):
    """League-wide start/captain shortlist for a gameweek.

    Scores every regular player as of the eve of the round using their own team's
    fixture difficulty, then surfaces the highest-confidence picks and the players
    to sit (injury risks). The engine behind captain/transfer decisions.
    """
    gws = selectable_gameweeks()
    if not gws:
        return None
    if gameweek is None or gameweek not in {g["round"] for g in gws}:
        gameweek = gws[-1]["round"]

    first_fixture = db.fixtures().find_one({"round": gameweek}, sort=[("date", 1)])
    if not first_fixture:
        return None
    as_of = first_fixture["date"] - timedelta(days=1)
    fixtures = {f["team"]: f for f in db.fixtures().find({"round": gameweek})}

    scored = score_players(feat.compute_all_features(as_of))
    injured = currently_injured_ids(as_of)

    picks = []
    for s in scored:
        fx = fixtures.get(s["team"])
        # Only rank fit regulars whose team actually plays this round — chronic
        # load filters out fringe players who got a one-off cameo.
        if (s["playerId"] in injured or fx is None or s.get("form") is None
                or s["matches14"] < 1 or s["chronic28"] < 45):
            continue
        diff = fx.get("difficulty")
        entry = {**s,
                 "confidence": confidence_score(s, diff),
                 "confidenceLabel": confidence_label(confidence_score(s, diff)),
                 "confidenceDriver": confidence_driver(s, diff),
                 "opponent": fx["opponent"], "home": fx["home"], "difficulty": diff}
        picks.append(entry)

    best = sorted(picks, key=lambda x: (-x["confidence"], -(x["form"] or 0)))[:12]
    avoid = sorted([p for p in picks if p["riskTier"] == "High"],
                   key=lambda x: -x["riskScore"])[:10]

    return {
        "gameweek": gameweek,
        "asOf": as_of.isoformat(),
        "ranked": len(picks),
        "captainPicks": best,
        "avoid": avoid,
    }


def _gameweek_observations(gameweek, window_days):
    """Per-player (prediction, outcome) pairs for one past gameweek.

    Scores every fit player as of the eve of the round using only prior data,
    then labels each with whether an injury actually followed in the window.
    Returns (context, observations) or None.
    """
    testable = [g for g in selectable_gameweeks() if g["backtestable"]]
    if not testable:
        return None
    if gameweek is None or gameweek not in {g["round"] for g in testable}:
        gameweek = testable[-1]["round"]

    fixture = db.fixtures().find_one({"round": gameweek}, sort=[("date", 1)])
    if not fixture:
        return None
    as_of = fixture["date"] - timedelta(days=1)
    window_end = as_of + timedelta(days=window_days)
    last_fixture = db.fixtures().find_one(sort=[("date", -1)])["date"]
    truncated = window_end > last_fixture  # injuries only surface via missed fixtures

    scored = score_players(feat.compute_all_features(as_of))
    already_out = currently_injured_ids(as_of)
    candidates = [s for s in scored if s["playerId"] not in already_out]

    # First new injury per player inside the window.
    new_injuries = {}
    for inj in db.injuries().find({}):
        if as_of < inj["dateInjured"] <= window_end:
            prev = new_injuries.get(inj["playerId"])
            if prev is None or inj["dateInjured"] < prev["dateInjured"]:
                new_injuries[inj["playerId"]] = inj

    obs = [{
        "player": s,
        "prob": s["riskProbability"],
        "riskScore": s["riskScore"],
        "tier": s["riskTier"],
        "injured": s["playerId"] in new_injuries,
        "injury": new_injuries.get(s["playerId"]),
    } for s in candidates]

    ctx = {"gameweek": gameweek, "asOf": as_of, "windowEnd": window_end,
           "windowDays": window_days, "truncated": truncated}
    return ctx, obs


def _tier_stats(obs):
    stats = []
    for tier in ["High", "Moderate", "Low"]:
        group = [o for o in obs if o["tier"] == tier]
        hit = [o for o in group if o["injured"]]
        stats.append({"tier": tier, "players": len(group), "injured": len(hit),
                      "rate": round(len(hit) / len(group), 3) if group else 0.0})
    return stats


def _lift(tier_stats):
    high = next(t for t in tier_stats if t["tier"] == "High")
    low = next(t for t in tier_stats if t["tier"] == "Low")
    return round(high["rate"] / low["rate"], 1) \
        if low["rate"] > 0 and high["players"] > 0 else None


def backtest_gameweek(gameweek=None, window_days=14):
    """Predictions vs. reality for a single past gameweek."""
    res = _gameweek_observations(gameweek, window_days)
    if res is None:
        return None
    ctx, obs = res
    tier_stats = _tier_stats(obs)

    injured_list = []
    for o in obs:
        if not o["injured"]:
            continue
        s, inj = o["player"], o["injury"]
        injured_list.append({
            "playerId": s["playerId"], "playerName": s["playerName"],
            "team": s["team"], "position": s["position"],
            "riskScore": s["riskScore"], "riskTier": s["riskTier"],
            "form": s.get("form"), "fatigue": s.get("fatigue"),
            "injuryType": inj.get("type"),
            "dateInjured": inj["dateInjured"].isoformat(),
            "daysOut": inj.get("daysOut"),
            "flagged": s["riskTier"] != "Low",
        })
    injured_list.sort(key=lambda x: -x["riskScore"])
    flagged = sum(1 for x in injured_list if x["flagged"])

    return {
        "gameweek": ctx["gameweek"],
        "asOf": ctx["asOf"].isoformat(),
        "windowDays": ctx["windowDays"],
        "windowEnd": ctx["windowEnd"].isoformat(),
        "truncated": ctx["truncated"],
        "candidates": len(obs),
        "tierStats": tier_stats,
        "injured": injured_list,
        "summary": {
            "totalInjured": len(injured_list),
            "flagged": flagged,
            "flaggedPct": round(flagged / len(injured_list), 2) if injured_list else None,
            "lift": _lift(tier_stats),
        },
    }


# Calibration bins over predicted risk score (%).
_CALIB_BINS = [(0, 10), (10, 20), (20, 35), (35, 101)]


def backtest_summary(window_days=14):
    """Pool predictions across every backtestable gameweek and evaluate the
    scores as a classifier: out-of-sample AUC, calibration, tier lift and
    precision/recall. This is the honest, aggregate report card."""
    gws = [g for g in selectable_gameweeks() if g["backtestable"]]
    all_obs, used = [], []
    for g in gws:
        res = _gameweek_observations(g["round"], window_days)
        if res is None:
            continue
        all_obs.extend(res[1])
        used.append(g["round"])
    if not all_obs:
        return None

    labels = [1 if o["injured"] else 0 for o in all_obs]
    probs = [o["prob"] for o in all_obs]
    positives = sum(labels)

    auc = brier = None
    if 0 < positives < len(labels):
        from sklearn.metrics import roc_auc_score, brier_score_loss
        auc = round(float(roc_auc_score(labels, probs)), 3)
        brier = round(float(brier_score_loss(labels, probs)), 4)

    calibration = []
    for lo, hi in _CALIB_BINS:
        grp = [o for o in all_obs if lo <= o["riskScore"] < hi]
        if not grp:
            continue
        calibration.append({
            "label": f"{lo}%+" if hi > 100 else f"{lo}–{hi}%",
            "n": len(grp),
            "predicted": round(sum(o["riskScore"] for o in grp) / len(grp), 1),
            "actual": round(100 * sum(1 for o in grp if o["injured"]) / len(grp), 1),
        })

    tier_stats = _tier_stats(all_obs)
    flagged = [o for o in all_obs if o["tier"] != "Low"]
    tp = sum(1 for o in flagged if o["injured"])

    return {
        "gameweeks": used,
        "windowDays": window_days,
        "observations": len(all_obs),
        "injuries": positives,
        "auc": auc,
        "brier": brier,
        "lift": _lift(tier_stats),
        "tierStats": tier_stats,
        "calibration": calibration,
        "precision": round(tp / len(flagged), 3) if flagged else None,
        "recall": round(tp / positives, 3) if positives else None,
        "flaggedPlayers": len(flagged),
    }


def simulate_workload(player_id, extra_matches):
    """'What-if' scoring: add hypothetical upcoming matches to a player's real
    workload and recompute ACWR / fatigue / risk. Reuses the live model and the
    exact feature math, so the projection is consistent with the rest of the app.
    """
    player = db.players().find_one({"_id": player_id})
    if not player:
        return None
    ref = feat.get_reference_date()
    appts = sorted(
        [(g["date"], g["minutes"], g.get("rating"))
         for g in db.games().find({"playerId": player_id}) if g.get("minutes")],
        key=lambda t: t[0])
    age = feat._clean_age(player.get("age"))
    episodes = list(db.injuries().find({"playerId": player_id}))

    def score_at(appearances, as_of):
        f = feat.player_features(appearances, as_of)
        hist = feat.injury_history_features(episodes, as_of)
        row = {"playerId": player_id, "playerName": player["name"],
               "team": player["team"], "position": player["position"],
               "age": age, "number": player.get("number"), **f, **hist,
               "fatigue": feat.fatigue_index(f)}
        return score_players([row])[0]

    baseline = score_at(appts, ref)

    # Process hypothetical matches chronologically, scoring the player on the
    # EVE of each one — the risk he'd carry *into* that match. The endpoint
    # alone is misleading: a spiked player "normalises" by surviving games,
    # but the decision that matters is whether to play him through the peak.
    cleaned = []
    for m in (extra_matches or []):
        try:
            days = max(0, int(m.get("daysFromNow", 0)))
            mins = int(m.get("minutes", 0))
        except (TypeError, ValueError):
            continue
        if mins > 0:
            cleaned.append((days, mins))
    cleaned.sort()

    sim = list(appts)
    path = []
    last = ref
    for i, (days, mins) in enumerate(cleaned, 1):
        when = ref + timedelta(days=days)
        entering = score_at(sim, when - timedelta(hours=12))
        path.append({
            "match": i,
            "daysFromNow": days,
            "minutes": mins,
            "riskScore": entering["riskScore"],
            "riskTier": entering["riskTier"],
            "acwr": entering["acwr"],
            "fatigue": entering["fatigue"],
        })
        sim.append((when, mins, None))
        sim.sort(key=lambda t: t[0])
        last = max(last, when)
    projected = score_at(sim, last)
    # Peak exposure anywhere in the scenario: entering any simulated match, or
    # the load carried out of it into whatever comes next.
    peak = max([p["riskScore"] for p in path] + [projected["riskScore"]]) \
        if path else baseline["riskScore"]

    return {
        "player": {"id": player_id, "name": player["name"],
                   "position": player["position"], "team": player["team"]},
        "referenceDate": ref.isoformat(),
        "baseline": baseline,
        "path": path,
        "peakRisk": peak,
        "projected": projected,
    }


def currently_injured_ids(today):
    """Player ids with an injury episode spanning `today` (any status — the
    stored status is relative to the reference date, but gameweek rotation
    asks about arbitrary dates)."""
    ids = set()
    for inj in db.injuries().find({}):
        if inj["dateInjured"] <= today <= inj["expectedReturn"]:
            ids.add(inj["playerId"])
    return ids


def rotation_plan(team, today, gameweek=None):
    """Recommend a lineup for a team's fixture, resting high-risk players.

    With `gameweek`, the plan is computed for that round: features, fatigue,
    form and availability are all evaluated as of the eve of the fixture.
    """
    fixture = None
    if gameweek is not None:
        fixture = db.fixtures().find_one({"team": team, "round": gameweek})
    if fixture is None:
        fixture = db.fixtures().find_one(
            {"team": team, "date": {"$gt": today}}, sort=[("date", 1)])
    if fixture is None:  # end of the stored window — use the last fixture
        fixture = db.fixtures().find_one({"team": team}, sort=[("date", -1)])
    gameweek = fixture.get("round") if fixture else gameweek

    as_of = fixture["date"] - timedelta(days=1) if fixture else today
    rows = feat.compute_team_features(team, as_of)
    scored = {s["playerId"]: s for s in score_players(rows)}

    injured = currently_injured_ids(as_of)
    injury_docs = {}
    for i in db.injuries().find({"team": team}):
        if i["dateInjured"] <= as_of <= i["expectedReturn"]:
            injury_docs[i["playerId"]] = i

    attach_confidence(scored, fixture.get("difficulty") if fixture else 3, injured)

    available, unavailable = [], []
    for pid, s in scored.items():
        if pid in injured:
            inj = injury_docs.get(pid, {})
            s = {**s, "injuryType": inj.get("type"),
                 "expectedReturn": inj.get("expectedReturn").isoformat()
                 if inj.get("expectedReturn") else None}
            unavailable.append(s)
        else:
            available.append(s)

    # Build recommended XI: lowest-risk available players per position.
    recommended, rested = [], []
    by_pos = {}
    for s in available:
        by_pos.setdefault(s["position"], []).append(s)
    for pos, players in by_pos.items():
        players.sort(key=lambda s: s["riskProbability"])

    for pos, need in FORMATION.items():
        pool = sorted(by_pos.get(pos, []), key=lambda s: s["riskProbability"])
        chosen = pool[:need]
        recommended.extend(chosen)
        # High-risk players who are NOT chosen are actively rested.
        for s in pool[need:]:
            if s["riskTier"] == "High":
                rested.append(s)

    # Any High-risk player who *would* have started but is high-risk: flag.
    for s in recommended:
        if s["riskTier"] == "High":
            s["startWarning"] = "High risk but no lower-risk cover at this position"

    recommended.sort(key=lambda s: (["GK", "DEF", "MID", "FWD"].index(s["position"]),
                                     s["riskProbability"]))
    rested.sort(key=lambda s: -s["riskProbability"])
    unavailable.sort(key=lambda s: -s["riskProbability"])

    team_meta = db.get_db()["teams"].find_one({"name": team}) or {}

    # Full squad snapshot (for the lineup sandbox's bench).
    squad = []
    for pid, s in scored.items():
        entry = {**s, "available": pid not in injured}
        if pid in injury_docs:
            entry["injuryType"] = injury_docs[pid].get("type")
        squad.append(entry)
    squad.sort(key=lambda s: -s["riskProbability"])

    return {
        "team": team,
        "european": team_meta.get("european"),
        "teamRank": team_meta.get("rank"),
        "gameweek": gameweek,
        "asOf": as_of.isoformat(),
        "fixture": {
            "opponent": fixture["opponent"],
            "home": fixture["home"],
            "date": fixture["date"].isoformat(),
            "competition": fixture["competition"],
            "difficulty": fixture.get("difficulty"),
            "opponentRank": fixture.get("opponentRank"),
        } if fixture else None,
        "recommendedXI": recommended,
        "restRecommendations": rested,
        "unavailable": unavailable,
        "squad": squad,
        "squadRiskAvg": round(
            sum(s["riskProbability"] for s in scored.values()) / len(scored), 3)
        if scored else 0,
    }
