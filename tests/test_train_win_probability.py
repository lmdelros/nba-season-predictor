import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score

from models.train_win_probability import (
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
    })

    net_rating_edge = (home_off - home_def) - (away_off - away_def)
    logit = (
        4.0 * (df["home_rolling_win_pct_l10"] - df["away_rolling_win_pct_l10"])
        + 0.05 * net_rating_edge
        + 0.3  # home-court edge
    )
    win_prob = 1 / (1 + np.exp(-logit))
    df["home_win"] = (rng.uniform(0, 1, n_games) < win_prob).astype(int)
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
