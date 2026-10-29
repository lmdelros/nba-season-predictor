import pandas as pd

from features.build_features import compute_team_game_features
from models.train_win_probability import (
    FEATURE_COLUMNS,
    MARGIN_COLUMNS,
    ORIGINAL_FEATURE_COLUMNS,
)
from simulation.monte_carlo import (
    SNAPSHOT_COLUMNS,
    cutoff_snapshot,
    freeze_remaining_features,
    head_to_head_before,
    predict_remaining,
)
from tests.test_build_features import _box, _games, _rescore_from, _team_games


def _season_inputs(games, box):
    """predict_remaining()'s two inputs, built from a synthetic season the same way
    load_training_data() and load_team_features() build them from the database."""
    features = compute_team_game_features(_team_games(games), box)
    # Mirrors the team_game_form view in db/views.sql (rows are already in time order
    # per team): average margin over the team's earlier games this season.
    margin = features["points_for"] - features["points_against"]
    features["season_avg_margin"] = margin.groupby(
        [features["season"], features["team_id"]]
    ).transform(lambda s: s.shift(1).expanding().mean())
    team_features = features[["team_id", "game_date", *SNAPSHOT_COLUMNS]]

    sides = {
        "home": features[features["is_home"]].set_index("game_id"),
        "away": features[~features["is_home"]].set_index("game_id"),
    }
    wide = games.set_index("game_id")
    # Every column load_training_data() returns, not only the ones the model uses.
    for col in [*ORIGINAL_FEATURE_COLUMNS, *MARGIN_COLUMNS]:
        side, feature = col.split("_", 1)
        wide[col] = sides[side][feature]
    for col in ("home_is_back_to_back", "away_is_back_to_back"):
        wide[col] = wide[col].astype("boolean").astype("Int64")
    wide["home_win"] = (wide["home_score"] > wide["away_score"]).astype(int)
    return wide.reset_index(), team_features


def _rescored_season(cutoff_day=30):
    games = _games()
    box = _box(_team_games(games))
    cutoff = games["game_date"].drop_duplicates().iloc[cutoff_day]
    return (games, box), _rescore_from(games, box, cutoff), cutoff


def test_predictions_ignore_results_on_or_after_cutoff():
    original_season, changed_season, cutoff = _rescored_season()
    original_games, original_features = _season_inputs(*original_season)
    changed_games, changed_features = _season_inputs(*changed_season)

    original_probs, *_ = predict_remaining(original_games, original_features, cutoff)
    changed_probs, *_ = predict_remaining(changed_games, changed_features, cutoff)

    assert original_probs == changed_probs
    # Sanity check: the real post-cutoff features did change, so the probabilities
    # only match because predict_remaining() ignores them.
    after = original_games["game_date"] >= cutoff
    assert not original_games.loc[after, FEATURE_COLUMNS].equals(
        changed_games.loc[after, FEATURE_COLUMNS]
    )


def _history_season():
    """A completed synthetic season one year earlier, with its own game IDs."""
    games = _games(seed=7)
    games["season"] = "2023-24"
    games["game_date"] -= pd.DateOffset(years=1)
    games["game_id"] += 100_000
    history, _ = _season_inputs(games, _box(_team_games(games), seed=8))
    return history


def test_predictions_with_history_ignore_results_on_or_after_cutoff():
    original_season, changed_season, cutoff = _rescored_season()
    original_games, original_features = _season_inputs(*original_season)
    changed_games, changed_features = _season_inputs(*changed_season)
    history = _history_season()

    original_probs, *_ = predict_remaining(original_games, original_features, cutoff, history)
    changed_probs, *_ = predict_remaining(changed_games, changed_features, cutoff, history)
    without_history, *_ = predict_remaining(original_games, original_features, cutoff)

    assert original_probs == changed_probs
    # Sanity check: the history is really used, so this test is not a copy of the one above.
    assert original_probs != without_history


def test_playoff_snapshot_ignores_results_on_or_after_cutoff():
    original_season, changed_season, cutoff = _rescored_season()
    _, original_features = _season_inputs(*original_season)
    _, changed_features = _season_inputs(*changed_season)

    pd.testing.assert_frame_equal(
        cutoff_snapshot(original_features, cutoff), cutoff_snapshot(changed_features, cutoff)
    )
    assert not original_features.equals(changed_features)


def test_head_to_head_counts_only_played_games_from_both_sides():
    played = pd.DataFrame({
        "home_team_id": [1, 2, 1], "away_team_id": [2, 1, 3],
        "home_score": [110, 120, 90], "away_score": [100, 95, 99],
    })
    h2h = head_to_head_before(played)

    # Team 1 beat team 2 at home, then lost to team 2 away: 1-1.
    assert h2h[(1, 2)] == 0.5
    assert h2h[(2, 1)] == 0.5
    assert h2h[(1, 3)] == 0.0
    assert h2h[(3, 1)] == 1.0
    assert (2, 3) not in h2h.index


def test_freeze_keeps_scheduled_rest_days():
    remaining = pd.DataFrame({
        "home_team_id": [1], "away_team_id": [2],
        "home_rest_days": [3], "away_rest_days": [1],
        "home_is_back_to_back": [0], "away_is_back_to_back": [1],
    })
    snapshot = pd.DataFrame(
        [[0.6, 115.0, 108.0, 0.7, 0.5, 4.5], [0.4, 110.0, 112.0, 0.5, 0.3, -2.0]],
        index=pd.Index([1, 2], name="team_id"), columns=SNAPSHOT_COLUMNS,
    )
    frozen = freeze_remaining_features(remaining, snapshot, head_to_head_before(
        pd.DataFrame(columns=["home_team_id", "away_team_id", "home_score", "away_score"])
    ))

    row = frozen.iloc[0]
    assert (row["home_rest_days"], row["away_rest_days"]) == (3, 1)
    assert (row["home_is_back_to_back"], row["away_is_back_to_back"]) == (0, 1)
    assert row["home_rolling_win_pct_l10"] == 0.6
    assert row["away_rolling_def_rating"] == 112.0
    assert row["home_season_win_pct_home"] == 0.7
    assert row["away_season_win_pct_away"] == 0.3
    assert (row["home_season_avg_margin"], row["away_season_avg_margin"]) == (4.5, -2.0)
    assert pd.isna(row["home_h2h_win_pct_season"])
