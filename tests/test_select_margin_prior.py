import pandas as pd
import pytest

from evaluation.select_margin_prior import previous_season, with_prior
from models.train_win_probability import (
    MARGIN_PRIOR_WEIGHT,
    SHRUNK_MARGIN_COLUMNS,
    add_shrunk_margins,
)


def _games():
    return pd.DataFrame({
        "season": ["2023-24", "2023-24"],
        "home_team_id": [1, 2], "away_team_id": [2, 1],
        "home_season_avg_margin": [6.0, None], "away_season_avg_margin": [-3.0, None],
        "home_games_played": [5, 0], "away_games_played": [15, 0],
    })


# Previous-season margins: team 1 was +8, team 2 was -4 in 2022-23.
MARGINS = {("2022-23", 1): 8.0, ("2022-23", 2): -4.0}


def test_previous_season():
    assert previous_season("2023-24") == "2022-23"
    assert previous_season("2000-01") == "1999-00"


def test_the_chosen_weight_matches_the_production_shrinkage():
    games = _games()
    # Production reads last season's margin from the team_game_form view.
    with_columns = games.assign(**{
        f"{side}_prior_season_margin": [
            MARGINS.get(("2022-23", team)) for team in games[f"{side}_team_id"]
        ]
        for side in ("home", "away")
    })

    expected = add_shrunk_margins(with_columns)[SHRUNK_MARGIN_COLUMNS]
    actual = with_prior(games, MARGIN_PRIOR_WEIGHT, MARGINS)[SHRUNK_MARGIN_COLUMNS]

    pd.testing.assert_frame_equal(actual, expected)


def test_margin_is_pulled_toward_a_share_of_last_seasons_margin():
    result = with_prior(_games(), 0.5, MARGINS)

    # Home team 1: 5 games at +6, prior 0.5 * 8 = 4: (5 * 6 + 10 * 4) / 15.
    assert result.loc[0, "home_season_avg_margin_shrunk"] == pytest.approx(70 / 15)
    # Away team 2: 15 games at -3, prior 0.5 * -4 = -2: (15 * -3 + 10 * -2) / 25.
    assert result.loc[0, "away_season_avg_margin_shrunk"] == pytest.approx(-65 / 25)
    # Before a team's first game, its margin is the prior alone.
    assert result.loc[1, "home_season_avg_margin_shrunk"] == pytest.approx(-2.0)
    assert result.loc[1, "away_season_avg_margin_shrunk"] == pytest.approx(4.0)


def test_a_team_without_a_previous_season_starts_from_zero():
    games = _games().assign(season="2022-23")  # 2021-22 is not in MARGINS

    result = with_prior(games, 1.0, MARGINS)

    assert result.loc[1, "home_season_avg_margin_shrunk"] == 0.0
