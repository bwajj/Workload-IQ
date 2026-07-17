"""Unit tests for risk scoring, tiering and start-confidence (pure functions)."""
from types import SimpleNamespace

import risk

# A calm, fit, well-rested baseline player.
BASE = {"acwr": 1.0, "restDays": 7, "backToBack14": 0, "matches14": 1, "age": 25,
        "chronic28": 90, "daysSinceReturn": 400, "priorInjuries": 0, "recentReturn": 0}


# --- heuristic probability ---------------------------------------------------

def test_calm_player_is_low_risk():
    assert risk._heuristic_prob(BASE) < 0.15


def test_return_to_play_raises_risk():
    back = {**BASE, "daysSinceReturn": 5}
    assert risk._heuristic_prob(back) >= risk._heuristic_prob(BASE) + 0.1


def test_prior_injuries_compound_risk():
    prone = {**BASE, "priorInjuries": 3}
    assert risk._heuristic_prob(prone) > risk._heuristic_prob(BASE)


def test_probability_is_capped():
    worst = {**BASE, "acwr": 5, "restDays": 1, "backToBack14": 3, "matches14": 5,
             "daysSinceReturn": 3, "priorInjuries": 5, "age": 40}
    assert risk._heuristic_prob(worst) <= 0.9


# --- tiering + reasons -------------------------------------------------------

def _rules_only_model():
    # thresholds high enough that the interpretable rules, not probability, decide
    return SimpleNamespace(p_high=0.99, p_moderate=0.98)


def test_recent_return_forces_high_tier():
    feat = {**BASE, "daysSinceReturn": 5, "recentReturn": 1}
    tier, reasons = risk._tier(0.05, feat, _rules_only_model())
    assert tier == "High"
    assert any("return-to-play" in r.lower() for r in reasons)


def test_acwr_spike_forces_high_tier():
    tier, _ = risk._tier(0.05, {**BASE, "acwr": 1.6}, _rules_only_model())
    assert tier == "High"


def test_calm_player_is_low_tier_with_safe_reason():
    tier, reasons = risk._tier(0.05, BASE, _rules_only_model())
    assert tier == "Low"
    assert reasons  # never empty


# --- start confidence --------------------------------------------------------

def test_confidence_high_for_ideal_pick():
    c = risk.confidence_score({"riskScore": 5, "form": 8.0, "fatigue": 10}, difficulty=1)
    assert c >= 80
    assert risk.confidence_label(c) == "Strong start"


def test_confidence_low_for_risky_out_of_form():
    c = risk.confidence_score({"riskScore": 70, "form": 4.0, "fatigue": 90}, difficulty=5)
    assert c < 45
    assert risk.confidence_label(c) == "Bench"


def test_confidence_stays_in_range():
    hi = risk.confidence_score({"riskScore": 0, "form": 10, "fatigue": 0}, difficulty=1)
    lo = risk.confidence_score({"riskScore": 100, "form": 0, "fatigue": 100}, difficulty=5)
    assert 0 <= lo <= hi <= 100


def test_missing_form_uses_neutral_default():
    # a player with no rating shouldn't crash or score as zero form
    c = risk.confidence_score({"riskScore": 10, "form": None, "fatigue": 20}, difficulty=2)
    assert 0 <= c <= 100
