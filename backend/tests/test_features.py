"""Unit tests for workload feature engineering (no DB / network needed)."""
from datetime import datetime, timedelta

import features as feat

REF = datetime(2024, 5, 15)


def _appts(*specs):
    """specs: (days_before_ref, minutes[, rating]) → sorted appearance tuples."""
    out = [(REF - timedelta(days=s[0]), s[1], s[2] if len(s) > 2 else None) for s in specs]
    return sorted(out, key=lambda t: t[0])


# --- ACWR / rolling workload -------------------------------------------------

def test_acwr_steady_load_is_about_one():
    f = feat.player_features(_appts((0, 90), (7, 90), (14, 90), (21, 90)), REF)
    assert f["acute7"] == 90            # one match in the last 7 days
    assert f["chronic28"] == 90.0       # 4×90 over 28 days, weekly-averaged
    assert 0.9 <= f["acwr"] <= 1.1


def test_acwr_spike_after_layoff():
    # returns from a long gap to two matches in a week → sharp spike
    f = feat.player_features(_appts((3, 90), (6, 90), (40, 90)), REF)
    assert f["acute7"] == 180
    assert f["acwr"] > 1.5
    assert f["matches14"] == 2


def test_low_chronic_load_neutralises_acwr():
    # below the chronic warm-up threshold, ACWR is pinned to 1.0 (not meaningful)
    f = feat.player_features(_appts((2, 20)), REF)
    assert f["acwr"] == 1.0


def test_rest_and_back_to_back():
    f = feat.player_features(_appts((0, 90), (2, 90), (9, 90)), REF)
    assert f["restDays"] == 2                 # gap between last two matches
    assert f["backToBack14"] >= 1             # 0 and 2 days apart = back-to-back


# --- fatigue -----------------------------------------------------------------

def test_fatigue_is_zero_when_idle():
    assert feat.fatigue_index({"acute7": 0, "matches14": 0, "backToBack14": 0, "restDays": 10}) == 0


def test_fatigue_maxes_under_heavy_congestion():
    f = feat.fatigue_index({"acute7": 400, "matches14": 6, "backToBack14": 3, "restDays": 0})
    assert 90 <= f <= 100


# --- form --------------------------------------------------------------------

def test_form_is_mean_of_last_four_ratings():
    appts = _appts((28, 90, 6.0), (21, 90, 7.0), (14, 90, 8.0), (7, 90, 9.0), (0, 90, 10.0))
    assert feat.form_rating(appts, REF, last_n=4) == 8.5


def test_form_is_none_without_ratings():
    assert feat.form_rating(_appts((0, 90)), REF) is None


# --- injury history (the return-to-play / proneness signals) -----------------

def test_recent_return_is_flagged():
    eps = [{"dateInjured": REF - timedelta(days=40), "expectedReturn": REF - timedelta(days=10)}]
    h = feat.injury_history_features(eps, REF)
    assert h["priorInjuries"] == 1
    assert h["daysSinceReturn"] == 10
    assert h["recentReturn"] == 1


def test_no_injury_history_uses_sentinel():
    h = feat.injury_history_features([], REF)
    assert h == {"priorInjuries": 0, "daysSinceReturn": feat.NO_INJURY_SENTINEL, "recentReturn": 0}


def test_future_injury_is_ignored():
    # an injury that only happens *after* the reference date must not leak in
    eps = [{"dateInjured": REF + timedelta(days=5), "expectedReturn": REF + timedelta(days=25)}]
    h = feat.injury_history_features(eps, REF)
    assert h["priorInjuries"] == 0
    assert h["recentReturn"] == 0


def test_long_healthy_spell_not_recent_return():
    eps = [{"dateInjured": REF - timedelta(days=300), "expectedReturn": REF - timedelta(days=280)}]
    h = feat.injury_history_features(eps, REF)
    assert h["recentReturn"] == 0
    assert h["daysSinceReturn"] == 280
