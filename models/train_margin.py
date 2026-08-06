# Linear regression model: predicts point margin for a matchup.
import argparse

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

from models.train_win_probability import (
    FEATURE_COLUMNS,
    apply_imputer,
    fit_imputer,
    get_db_connection,
    load_training_data,
    time_ordered_split,
)


def train_model(train_df):
    X_train = train_df[FEATURE_COLUMNS].astype(float)
    y_train = train_df["home_score"] - train_df["away_score"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    model = LinearRegression()
    model.fit(X_train_scaled, y_train)
    return model, scaler


def evaluate(model, scaler, train_df, test_df):
    X_test = test_df[FEATURE_COLUMNS].astype(float)
    y_test = (test_df["home_score"] - test_df["away_score"]).astype(float)
    preds = model.predict(scaler.transform(X_test))

    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))

    # Baseline: always predict the training set's average home margin.
    train_mean_margin = (train_df["home_score"] - train_df["away_score"]).mean()
    baseline_mae = mean_absolute_error(y_test, np.full(len(y_test), train_mean_margin))

    implied_win = (preds > 0).astype(int)
    actual_win = (y_test > 0).astype(int)
    implied_accuracy = (implied_win == actual_win).mean()

    print(f"Test games: {len(test_df)}")
    print(f"MAE:  {mae:.2f} points  "
          f"(baseline 'always predict train-avg margin': {baseline_mae:.2f})")
    print(f"RMSE: {rmse:.2f} points")
    print(f"Implied win/loss accuracy (sign of predicted margin): {implied_accuracy:.3f}")

    return preds


def save_predictions(conn, test_df, preds, model_version="linreg_margin_v1"):
    sql = """
        INSERT INTO game_predictions (game_id, model_version, model_type, predicted_margin)
        VALUES (%(game_id)s, %(model_version)s, 'margin', %(margin)s)
        ON CONFLICT (game_id, model_version) DO UPDATE SET
            predicted_margin = EXCLUDED.predicted_margin,
            predicted_at = now()
    """
    records = [
        {"game_id": game_id, "model_version": model_version, "margin": float(m)}
        for game_id, m in zip(test_df["game_id"], preds)
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
    preds = evaluate(model, scaler, train_df, test_df)
    save_predictions(conn, test_df, preds)

    conn.close()


if __name__ == "__main__":
    main()
