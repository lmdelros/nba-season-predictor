# Logistic regression model: predicts home win probability for a matchup.
import argparse
import os

import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "home_rolling_win_pct_l10", "away_rolling_win_pct_l10",
    "home_rolling_off_rating", "home_rolling_def_rating",
    "away_rolling_off_rating", "away_rolling_def_rating",
    "home_rest_days", "away_rest_days",
    "home_is_back_to_back", "away_is_back_to_back",
    "home_h2h_win_pct_season",
    "home_season_win_pct_home", "away_season_win_pct_away",
]
WIN_PCT_COLUMNS = [
    "home_rolling_win_pct_l10", "away_rolling_win_pct_l10", "home_h2h_win_pct_season",
    "home_season_win_pct_home", "away_season_win_pct_away",
]
RATING_COLUMNS = [
    "home_rolling_off_rating", "home_rolling_def_rating",
    "away_rolling_off_rating", "away_rolling_def_rating",
]
REST_COLUMNS = ["home_rest_days", "away_rest_days"]
B2B_COLUMNS = ["home_is_back_to_back", "away_is_back_to_back"]


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_training_data(conn, season):
    sql = """
        SELECT g.game_id, g.game_date, g.home_team_id, g.away_team_id,
               g.home_score, g.away_score,
               hf.rolling_win_pct_l10 AS home_rolling_win_pct_l10,
               hf.rolling_off_rating AS home_rolling_off_rating,
               hf.rolling_def_rating AS home_rolling_def_rating,
               hf.rest_days AS home_rest_days,
               hf.is_back_to_back AS home_is_back_to_back,
               hf.h2h_win_pct_season AS home_h2h_win_pct_season,
               hf.season_win_pct_home AS home_season_win_pct_home,
               af.rolling_win_pct_l10 AS away_rolling_win_pct_l10,
               af.rolling_off_rating AS away_rolling_off_rating,
               af.rolling_def_rating AS away_rolling_def_rating,
               af.rest_days AS away_rest_days,
               af.is_back_to_back AS away_is_back_to_back,
               af.season_win_pct_away AS away_season_win_pct_away,
               hm.season_avg_margin AS home_season_avg_margin,
               am.season_avg_margin AS away_season_avg_margin
        FROM games g
        JOIN team_game_features hf ON hf.game_id = g.game_id AND hf.team_id = g.home_team_id
        JOIN team_game_features af ON af.game_id = g.game_id AND af.team_id = g.away_team_id
        JOIN team_game_form hm ON hm.game_id = g.game_id AND hm.team_id = g.home_team_id
        JOIN team_game_form am ON am.game_id = g.game_id AND am.team_id = g.away_team_id
        WHERE g.season = %(season)s
        ORDER BY g.game_date, g.game_id
    """
    df = pd.read_sql(sql, conn, params={"season": season})
    df["game_date"] = pd.to_datetime(df["game_date"])
    df["home_win"] = (df["home_score"] > df["away_score"]).astype(int)
    for col in B2B_COLUMNS:
        df[col] = df[col].astype("boolean").astype("Int64")
    return df


def time_ordered_split(df, test_frac=0.2):
    unique_dates = sorted(df["game_date"].unique())
    cutoff = unique_dates[int(len(unique_dates) * (1 - test_frac))]
    train = df[df["game_date"] < cutoff].copy()
    test = df[df["game_date"] >= cutoff].copy()
    return train, test


def fit_imputer(train_df):
    """Fill values computed from TRAIN data only, so test-set statistics never leak in."""
    fills = {col: 0.5 for col in WIN_PCT_COLUMNS}
    fills.update({col: train_df[col].mean() for col in RATING_COLUMNS})
    fills.update({col: train_df[col].median() for col in REST_COLUMNS})
    fills.update({col: 0 for col in B2B_COLUMNS})
    return fills


def apply_imputer(df, fills):
    df = df.copy()
    for col, value in fills.items():
        df[col] = df[col].fillna(value)
    return df


def train_model(train_df):
    X_train = train_df[FEATURE_COLUMNS].astype(float)
    y_train = train_df["home_win"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train_scaled, y_train)
    return model, scaler


def evaluate(model, scaler, test_df):
    X_test = test_df[FEATURE_COLUMNS].astype(float)
    y_test = test_df["home_win"]
    probs = model.predict_proba(scaler.transform(X_test))[:, 1]
    preds = (probs >= 0.5).astype(int)

    print(f"Test games: {len(test_df)}")
    print(f"Accuracy:    {accuracy_score(y_test, preds):.3f}")
    print(f"Log loss:    {log_loss(y_test, probs):.3f}")
    print(f"Brier score: {brier_score_loss(y_test, probs):.3f}")

    print("\nCalibration (predicted vs. actual home win rate by probability bucket):")
    buckets = pd.cut(probs, bins=[0, .3, .4, .5, .6, .7, 1.0])
    calib = pd.DataFrame({"bucket": buckets, "actual": y_test.values, "predicted": probs})
    print(calib.groupby("bucket", observed=True).agg(
        n=("actual", "size"),
        predicted_avg=("predicted", "mean"),
        actual_win_rate=("actual", "mean"),
    ))

    return probs


def save_predictions(conn, test_df, probs, model_version="logreg_v1"):
    sql = """
        INSERT INTO game_predictions (game_id, model_version, model_type, predicted_home_win_prob)
        VALUES (%(game_id)s, %(model_version)s, 'win_probability', %(prob)s)
        ON CONFLICT (game_id, model_version) DO UPDATE SET
            predicted_home_win_prob = EXCLUDED.predicted_home_win_prob,
            predicted_at = now()
    """
    records = [
        {"game_id": game_id, "model_version": model_version, "prob": float(p)}
        for game_id, p in zip(test_df["game_id"], probs)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-frac", type=float, default=0.2)
    args = parser.parse_args()

    conn = get_db_connection()
    df = load_training_data(conn, args.season)
    train_df, test_df = time_ordered_split(df, args.test_frac)

    fills = fit_imputer(train_df)
    train_df = apply_imputer(train_df, fills)
    test_df = apply_imputer(test_df, fills)

    model, scaler = train_model(train_df)
    probs = evaluate(model, scaler, test_df)
    save_predictions(conn, test_df, probs)

    conn.close()


if __name__ == "__main__":
    main()
