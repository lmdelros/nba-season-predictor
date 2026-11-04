import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import accuracy_score

from models.train_win_probability import (
    add_shrunk_margins,
    apply_imputer,
    evaluate,
    fit_imputer,
    time_ordered_split,
    train_model,
)

ACCURACY_THRESHOLD = 0.65


def _synthetic_games(n_games=1200, seed=0):
    """Games with a real (noisy) signal, so a correctly-trained model beats a coin flip
    but the threshold still catches a broken pipeline (e.g. shuffled labels, dropped features)."""
    rng = np.random.default_rng(seed)

    home_off = rng.normal(112, 5, n_games)
    home_def = rng.normal(112, 5, n_games)
    away_off = rng.normal(112, 5, n_games)
    away_def = rng.normal(112, 5, n_games)
    home_win_pct = rng.uniform(0.2, 0.8, n_games)
    away_win_pct = rng.uniform(0.2, 0.8, n_games)

    df = pd.DataFrame({
        "game_date": pd.date_range("2024-10-01", periods=n_games, freq="D"),
        "home_rolling_win_pct_l10": home_win_pct,
        "away_rolling_win_pct_l10": away_win_pct,
        "home_rolling_off_rating": home_off,
        "home_rolling_def_rating": home_def,
        "away_rolling_off_rating": away_off,
        "away_rolling_def_rating": away_def,
        "home_rest_days": rng.integers(0, 4, n_games),
        "away_rest_days": rng.integers(0, 4, n_games),
        "home_is_back_to_back": rng.integers(0, 2, n_games),
        "away_is_back_to_back": rng.integers(0, 2, n_games),
        "home_h2h_win_pct_season": rng.uniform(0.2, 0.8, n_games),
        "home_season_win_pct_home": rng.uniform(0.3, 0.8, n_games),
        "away_season_win_pct_away": rng.uniform(0.2, 0.7, n_games),
        "home_season_avg_margin": rng.normal(0, 5, n_games),
        "away_season_avg_margin": rng.normal(0, 5, n_games),
        "home_games_played": rng.integers(10, 70, n_games),
        "away_games_played": rng.integers(10, 70, n_games),
        "home_prior_season_margin": rng.normal(0, 4, n_games),
        "away_prior_season_margin": rng.normal(0, 4, n_games),
    })

    # The signal runs through the model's features: season margin and back-to-backs.
    logit = (
        0.25 * (df["home_season_avg_margin"] - df["away_season_avg_margin"])
        - 0.4 * df["home_is_back_to_back"]
        + 0.4 * df["away_is_back_to_back"]
        + 0.3  # home-court edge
    )
    win_prob = 1 / (1 + np.exp(-logit))
    df["home_win"] = (rng.uniform(0, 1, n_games) < win_prob).astype(int)
    df = add_shrunk_margins(df)
    return df


def test_win_probability_model_beats_accuracy_threshold():
    df = _synthetic_games()
    train_df, test_df = time_ordered_split(df, test_frac=0.2)

    fills = fit_imputer(train_df)
    train_df = apply_imputer(train_df, fills)
    test_df = apply_imputer(test_df, fills)

    model, scaler = train_model(train_df)
    probs = evaluate(model, scaler, test_df)
    preds = (probs >= 0.5).astype(int)

    accuracy = accuracy_score(test_df["home_win"], preds)
    assert accuracy >= ACCURACY_THRESHOLD, (
        f"accuracy {accuracy:.3f} fell below {ACCURACY_THRESHOLD}"
    )


def test_margins_based_on_few_games_are_pulled_toward_last_season():
    df = pd.DataFrame({
        "home_season_avg_margin": [12.0, 12.0, 12.0, None],
        "away_season_avg_margin": [-6.0, -6.0, -6.0, -6.0],
        "home_games_played": [5, 20, 50, 0],
        "away_games_played": [10, 10, 10, 10],
        # Home team was +8 last season (prior 0.75 * 8 = 6); away has no previous season.
        "home_prior_season_margin": [8.0, 8.0, 8.0, 8.0],
        "away_prior_season_margin": [None, None, None, None],
    })

    shrunk = add_shrunk_margins(df)

    # (n * 12 + 10 * 6) / (n + 10): few games stay near 6, many games approach 12.
    assert shrunk["home_season_avg_margin_shrunk"].tolist()[:3] == pytest.approx(
        [120 / 15, 300 / 30, 660 / 60])
    # No previous season means prior 0, the league average: -6 * 10 / 20.
    assert (shrunk["away_season_avg_margin_shrunk"] == -3.0).all()
    # Before the first game, the value is the prior alone.
    assert shrunk["home_season_avg_margin_shrunk"].iloc[3] == pytest.approx(6.0)
