import math

import pandas as pd
import pytest

from evaluation.score_title_odds import (
    MIN_PROBABILITY,
    calibration_slope,
    champion_score,
    finals_score,
)


def test_champion_score_reports_probability_rank_and_log_loss():
    teams = pd.DataFrame({"team_id": [1, 2, 3], "championship_pct": [0.6, 0.3, 0.1]})

    probability, rank, loss = champion_score(teams, 2)

    assert (probability, rank) == (0.3, 2)
    assert loss == pytest.approx(-math.log(0.3))


def test_a_champion_given_zero_odds_has_a_large_but_finite_log_loss():
    teams = pd.DataFrame({"team_id": [1, 2], "championship_pct": [1.0, 0.0]})

    _, rank, loss = champion_score(teams, 2)

    assert rank == 2
    assert loss == pytest.approx(-math.log(MIN_PROBABILITY))


def test_finals_score_finds_the_pairing_in_either_order():
    matchups = pd.DataFrame({
        "team_a_id": [1, 1, 2], "team_b_id": [2, 3, 3], "matchup_pct": [0.5, 0.3, 0.2],
    })

    assert finals_score(matchups, 3, 1) == (0.3, 2)
    assert finals_score(matchups, 4, 1) == (0.0, None)


def test_calibration_slope_detects_projections_that_are_too_cautious():
    actual = pd.Series(range(5, 30))
    cautious = 17 + (actual - 17) * 0.5

    assert calibration_slope(cautious, actual) == pytest.approx(2.0)
    assert calibration_slope(actual, actual) == pytest.approx(1.0)
