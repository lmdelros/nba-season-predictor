import numpy as np
import pandas as pd
import pytest

from evaluation.evaluate_win_model import pregame_win_pct
from features.build_features import compute_team_game_features

FEATURE_COLUMNS = [
    "rolling_win_pct_l10", "rolling_off_rating", "rolling_def_rating", "rest_days",
    "is_back_to_back", "h2h_win_pct_season", "season_win_pct_home", "season_win_pct_away",
]


def _games(n_days=60, seed=0):
    """A synthetic season: 6 teams, three games on most days, with rest gaps of 1-3 days."""
    rng = np.random.default_rng(seed)
    rows, game_id, day = [], 1, pd.Timestamp("2024-10-22")
    for _ in range(n_days):
        teams = rng.permutation(6)
        for home, away in zip(teams[0::2], teams[1::2]):
            rows.append({
                "game_id": game_id, "season": "2024-25", "game_date": day,
                "home_team_id": int(home), "away_team_id": int(away),
                "home_score": int(rng.integers(90, 130)), "away_score": int(rng.integers(90, 130)),
            })
            game_id += 1
        day += pd.Timedelta(days=int(rng.integers(1, 4)))
    games = pd.DataFrame(rows)
    # Ties are impossible in the NBA; break them so every game has a winner.
    ties = games["home_score"] == games["away_score"]
    games.loc[ties, "home_score"] += 1
    return games


def _team_games(games):
    """Same shape as load_team_games(): one row per team per game."""
    home = games.rename(columns={
        "home_team_id": "team_id", "away_team_id": "opp_id",
        "home_score": "points_for", "away_score": "points_against",
    }).assign(is_home=True)
    away = games.rename(columns={
        "away_team_id": "team_id", "home_team_id": "opp_id",
        "away_score": "points_for", "home_score": "points_against",
    }).assign(is_home=False)
    return pd.concat([home, away], ignore_index=True)


def _box(team_games, seed=1):
    """Same shape as load_team_box_totals(): per-team box totals for each game."""
    rng = np.random.default_rng(seed)
    n = len(team_games)
    return pd.DataFrame({
        "game_id": team_games["game_id"], "team_id": team_games["team_id"],
        "fga": rng.integers(80, 95, n), "fta": rng.integers(15, 30, n),
        "oreb": rng.integers(5, 15, n), "tov": rng.integers(10, 18, n),
    })


def _rescore_from(games, box, cutoff, seed=99):
    """Copies of games and box with every result on or after cutoff replaced at random."""
    rng = np.random.default_rng(seed)
    games, box = games.copy(), box.copy()
    future = games["game_date"] >= cutoff
    games.loc[future, "home_score"] = rng.integers(60, 160, future.sum())
    games.loc[future, "away_score"] = games.loc[future, "home_score"] + rng.choice([-25, 25])
    future_ids = games.loc[future, "game_id"]
    box_future = box["game_id"].isin(future_ids)
    box.loc[box_future, "fga"] = rng.integers(60, 120, box_future.sum())
    box.loc[box_future, "tov"] = rng.integers(0, 30, box_future.sum())
    return games, box


def _features(games, box):
    df = compute_team_game_features(_team_games(games), box)
    return df.set_index(["game_id", "team_id"]).sort_index()[FEATURE_COLUMNS]


@pytest.mark.parametrize("cutoff_day", [5, 30, 55])
def test_features_ignore_results_on_or_after_game_date(cutoff_day):
    games = _games()
    box = _box(_team_games(games))
    cutoff = games["game_date"].drop_duplicates().iloc[cutoff_day]
    changed_games, changed_box = _rescore_from(games, box, cutoff)

    original = _features(games, box)
    changed = _features(changed_games, changed_box)

    # Games ON the cutoff date are included on purpose: their own result changed,
    # so this also fails if a game's features use that game's own outcome.
    known = games.loc[games["game_date"] <= cutoff, "game_id"]
    pd.testing.assert_frame_equal(
        original[original.index.get_level_values("game_id").isin(known)],
        changed[changed.index.get_level_values("game_id").isin(known)],
    )
    # Sanity check that the rescoring changed something, so the test can't pass vacuously.
    assert not original.equals(changed)


def test_features_match_hand_computed_values():
    # Team 1 vs. team 2 three times: home win, away loss, then a home win after 3 days off.
    games = pd.DataFrame({
        "game_id": [1, 2, 3], "season": "2024-25",
        "game_date": pd.to_datetime(["2024-10-22", "2024-10-23", "2024-10-26"]),
        "home_team_id": [1, 2, 1], "away_team_id": [2, 1, 2],
        "home_score": [110, 120, 105], "away_score": [100, 95, 99],
    })
    box = _box(_team_games(games))
    team1 = _features(games, box).xs(1, level="team_id")

    assert team1["rolling_win_pct_l10"].tolist()[1:] == [1.0, 0.5]
    assert pd.isna(team1["rolling_win_pct_l10"].iloc[0])
    assert team1["rest_days"].tolist()[1:] == [1, 3]
    assert team1["is_back_to_back"].tolist()[1:] == [True, False]
    assert team1["h2h_win_pct_season"].tolist()[1:] == [1.0, 0.5]
    assert pd.isna(team1["season_win_pct_home"].iloc[0])
    assert team1["season_win_pct_home"].tolist()[1:] == [1.0, 1.0]
    assert team1["season_win_pct_away"].tolist()[2] == 0.0


def test_pregame_win_pct_ignores_results_on_or_after_game_date():
    games = _games()
    cutoff = games["game_date"].drop_duplicates().iloc[30]
    changed_games, _ = _rescore_from(games, _box(_team_games(games)), cutoff)

    known = games.loc[games["game_date"] <= cutoff, "game_id"]
    original = pregame_win_pct(games).loc[known]
    changed = pregame_win_pct(changed_games).loc[known]
    pd.testing.assert_frame_equal(original, changed)
    assert not pregame_win_pct(games).equals(pregame_win_pct(changed_games))
