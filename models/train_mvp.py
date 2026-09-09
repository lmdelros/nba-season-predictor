# MVP model: predicts each candidate player's probability of winning MVP
# that season. Restricted to a per-season top-N-by-points shortlist rather
# than every player in the league — with one winner out of 400+ players a
# season, an unrestricted model would just learn "predict not-MVP" and be
# uselessly "accurate". The real question this answers is a ranking one:
# among the season's realistic contenders, who's most MVP-like.
import argparse
import os

import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

CANDIDATES_PER_SEASON = 20

FEATURE_COLUMNS = [
    "points_per_game", "rebounds_per_game", "assists_per_game",
    "steals_per_game", "blocks_per_game", "turnovers_per_game",
    "fg_pct", "fg3_pct", "ft_pct", "plus_minus_per_game", "team_win_pct",
]


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_candidate_pool(conn, seasons):
    """Per season: the top CANDIDATES_PER_SEASON players by season-total
    points, joined with their team's win% and (if applicable) the mvp label.

    Same shortlist heuristic used to decide who to check playerawards for
    during ingestion — every real MVP winner is a clear top-scoring player,
    so this reliably includes the true winner while dropping the ~95% of
    the league that was never realistically in contention.
    """
    sql = """
        WITH ranked AS (
            SELECT pss.*, tss.win_pct AS team_win_pct,
                   row_number() OVER (
                       PARTITION BY pss.season ORDER BY pss.points DESC
                   ) AS rank_in_season
            FROM player_season_stats pss
            JOIN team_season_standings tss
                ON tss.team_id = pss.team_id AND tss.season = pss.season
            WHERE pss.season = ANY(%(seasons)s)
        )
        SELECT r.*, (pa.player_id IS NOT NULL) AS is_mvp
        FROM ranked r
        LEFT JOIN player_awards pa
            ON pa.player_id = r.player_id AND pa.season = r.season AND pa.award_type = 'mvp'
        WHERE r.rank_in_season <= %(top_n)s
    """
    df = pd.read_sql(sql, conn, params={"seasons": seasons, "top_n": CANDIDATES_PER_SEASON})

    df["points_per_game"] = df["points"] / df["games_played"]
    df["rebounds_per_game"] = df["rebounds"] / df["games_played"]
    df["assists_per_game"] = df["assists"] / df["games_played"]
    df["steals_per_game"] = df["steals"] / df["games_played"]
    df["blocks_per_game"] = df["blocks"] / df["games_played"]
    df["turnovers_per_game"] = df["turnovers"] / df["games_played"]
    df["plus_minus_per_game"] = df["plus_minus"] / df["games_played"]
    return df


def train_model(train_df):
    X_train = train_df[FEATURE_COLUMNS].astype(float)
    y_train = train_df["is_mvp"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train_scaled, y_train)
    return model, scaler


def evaluate(model, scaler, test_df):
    """The metric that actually matters here: per season, is the model's
    #1-ranked candidate the real MVP? Raw accuracy/log loss are reported too
    but are easy to game with this much class imbalance even after the
    top-20 shortlist, so top-1-per-season is the headline number.
    """
    X_test = test_df[FEATURE_COLUMNS].astype(float)
    probs = model.predict_proba(scaler.transform(X_test))[:, 1]
    test_df = test_df.assign(predicted_prob=probs)

    hits = 0
    for season, group in test_df.groupby("season"):
        top_pick = group.loc[group["predicted_prob"].idxmax()]
        actual_mvp = group.loc[group["is_mvp"], "player_id"]
        correct = len(actual_mvp) > 0 and top_pick["player_id"] == actual_mvp.iloc[0]
        hits += int(correct)
        print(f"  {season}: predicted {top_pick['player_id']}"
              f" ({'correct' if correct else 'MISS'})")

    n_seasons = test_df["season"].nunique()
    print(f"\nTop-1-per-season accuracy: {hits}/{n_seasons}")
    return test_df


def save_predictions(conn, test_df, model_version="mvp_logreg_v1"):
    sql = """
        INSERT INTO award_predictions (season, award_type, player_id, model_version, predicted_prob)
        VALUES (%(season)s, 'mvp', %(player_id)s, %(model_version)s, %(predicted_prob)s)
        ON CONFLICT (season, award_type, player_id, model_version) DO UPDATE SET
            predicted_prob = EXCLUDED.predicted_prob,
            predicted_at = now()
    """
    records = [
        {
            "season": row.season, "player_id": int(row.player_id),
            "model_version": model_version, "predicted_prob": float(row.predicted_prob),
        }
        for row in test_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-seasons", type=int, default=3)
    args = parser.parse_args()

    start_year = int(args.start_season[:4])
    end_year = int(args.end_season[:4])
    seasons = [f"{y}-{str(y + 1)[2:]}" for y in range(start_year, end_year + 1)]

    conn = get_db_connection()
    df = load_candidate_pool(conn, seasons)

    train_seasons = seasons[:-args.test_seasons]
    test_seasons = seasons[-args.test_seasons:]
    train_df = df[df["season"].isin(train_seasons)]
    test_df = df[df["season"].isin(test_seasons)]

    print(f"Train seasons: {train_seasons}")
    print(f"Test seasons:  {test_seasons}")
    print(f"Train rows: {len(train_df)} ({train_df['is_mvp'].sum()} MVPs)")
    print(f"Test rows:  {len(test_df)} ({test_df['is_mvp'].sum()} MVPs)\n")

    model, scaler = train_model(train_df)
    scored_test_df = evaluate(model, scaler, test_df)
    save_predictions(conn, scored_test_df)

    conn.close()


if __name__ == "__main__":
    main()
