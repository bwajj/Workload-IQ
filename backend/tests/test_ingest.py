"""Unit tests for ingest mapping helpers (pure functions)."""
import ingest


# --- age (regression for the '25 for departed players' bug) ------------------

def test_valid_age_keeps_plausible_ages():
    assert ingest._valid_age(25) == 25
    assert ingest._valid_age(39) == 39


def test_valid_age_returns_none_when_unknown():
    # departed players have no current-squad age → None (so the UI shows '—'),
    # never a misleading default like 25.
    assert ingest._valid_age(None) is None


def test_valid_age_rejects_garbage():
    assert ingest._valid_age(2025) is None   # a birth year leaking in as "age"
    assert ingest._valid_age(10) is None
    assert ingest._valid_age(60) is None


# --- fixture difficulty ------------------------------------------------------

def test_difficulty_scales_with_opponent_strength():
    assert ingest._difficulty(2.4, home=True) >= 4      # title-challenger opponent
    assert ingest._difficulty(0.5, home=True) <= 2      # bottom-of-table opponent


def test_away_is_never_easier_than_home():
    assert ingest._difficulty(1.0, home=False) >= ingest._difficulty(1.0, home=True)


def test_difficulty_clamped_to_1_5():
    assert 1 <= ingest._difficulty(0.0, home=True) <= 5
    assert 1 <= ingest._difficulty(3.0, home=False) <= 5


# --- injury severity + body part ---------------------------------------------

def test_severity_bands():
    assert ingest._severity(5) == "Minor"
    assert ingest._severity(30) == "Moderate"
    assert ingest._severity(120) == "Severe"


def test_body_part_extraction():
    assert ingest._body_part("Hamstring Injury") == "Hamstring"
    assert ingest._body_part("Knee surgery") == "Knee"
    assert ingest._body_part("Knock") == "Other"


def test_position_mapping():
    assert ingest._pos("Goalkeeper") == "GK"
    assert ingest._pos("Attacker") == "FWD"
    assert ingest._pos("Unknown") == "MID"   # safe default
