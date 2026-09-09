# Shared logic for per-season-shortlist award models (MVP, DPOY, ...): rank
# each season's candidates by an award-specific stat, join the team win/loss
# record and ground-truth label, train a logistic regression, and evaluate
# by whether the model's #1 pick matches the real winner each season.
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

# Must match the heuristic ingestion/pull_award_data.py used to decide whose
# award history to check — the model can only be as complete as that ground
# truth, so the ranking here has to line up with CANDIDATE_HEURISTICS there.
RANK_EXPRESSIONS = {
    "points": "pss.points",
    "stocks": "(pss.steals + pss.blocks)",
}


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_candidate_pool(conn, seasons, award_type, rank_by, rookies_only=False):
    """Per season: the top CANDIDATES_PER_SEASON players by `rank_by`,
    joined with their team's win% and the award_type ground-truth label.

    rookies_only (for ROY): restricts the pool to each player's first season
    in player_season_stats before ranking — same "first appearance in our
    data" heuristic ingestion/pull_award_data.py uses, so the candidates a
    season's rows should be identical between the two.
    """
    source = "player_season_stats pss"
    if rookies_only:
        source = """(
            SELECT pss.* FROM player_season_stats pss
            JOIN (
                SELECT player_id, MIN(season) AS rookie_season
                FROM player_season_stats GROUP BY player_id
            ) fs ON fs.player_id = pss.player_id AND fs.rookie_season = pss.season
        ) pss"""

    sql = f"""
        WITH ranked AS (
            SELECT pss.*, tss.win_pct AS team_win_pct,
                   row_number() OVER (
                       PARTITION BY pss.season ORDER BY {RANK_EXPRESSIONS[rank_by]} DESC
                   ) AS rank_in_season
            FROM {source}
            JOIN team_season_standings tss
                ON tss.team_id = pss.team_id AND tss.season = pss.season
            WHERE pss.season = ANY(%(seasons)s)
        )
        SELECT r.*, (pa.player_id IS NOT NULL) AS is_winner
        FROM ranked r
        LEFT JOIN player_awards pa
            ON pa.player_id = r.player_id AND pa.season = r.season
               AND pa.award_type = %(award_type)s
        WHERE r.rank_in_season <= %(top_n)s
    """
    df = pd.read_sql(
        sql, conn,
        params={"seasons": seasons, "top_n": CANDIDATES_PER_SEASON, "award_type": award_type},
    )

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
    y_train = train_df["is_winner"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train_scaled, y_train)
    return model, scaler


def evaluate(model, scaler, test_df):
    """The metric that actually matters here: per season, is the model's
    #1-ranked candidate the real winner? Raw accuracy/log loss are easy to
    game with this much class imbalance even after the shortlist, so
    top-1-per-season is the headline number.
    """
    X_test = test_df[FEATURE_COLUMNS].astype(float)
    probs = model.predict_proba(scaler.transform(X_test))[:, 1]
    test_df = test_df.assign(predicted_prob=probs)

    hits = 0
    for season, group in test_df.groupby("season"):
        top_pick = group.loc[group["predicted_prob"].idxmax()]
        actual_winner = group.loc[group["is_winner"], "player_id"]
        correct = len(actual_winner) > 0 and top_pick["player_id"] == actual_winner.iloc[0]
        hits += int(correct)
        print(f"  {season}: predicted {top_pick['player_id']}"
              f" ({'correct' if correct else 'MISS'})")

    n_seasons = test_df["season"].nunique()
    print(f"\nTop-1-per-season accuracy: {hits}/{n_seasons}")
    return test_df


def save_predictions(conn, test_df, award_type, model_version):
    sql = """
        INSERT INTO award_predictions (season, award_type, player_id, model_version, predicted_prob)
        VALUES (%(season)s, %(award_type)s, %(player_id)s, %(model_version)s, %(predicted_prob)s)
        ON CONFLICT (season, award_type, player_id, model_version) DO UPDATE SET
            predicted_prob = EXCLUDED.predicted_prob,
            predicted_at = now()
    """
    records = [
        {
            "season": row.season, "award_type": award_type, "player_id": int(row.player_id),
            "model_version": model_version, "predicted_prob": float(row.predicted_prob),
        }
        for row in test_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def run(award_type, rank_by, model_version, start_season, end_season, test_seasons,
        rookies_only=False):
    start_year = int(start_season[:4])
    end_year = int(end_season[:4])
    seasons = [f"{y}-{str(y + 1)[2:]}" for y in range(start_year, end_year + 1)]

    conn = get_db_connection()
    df = load_candidate_pool(conn, seasons, award_type, rank_by, rookies_only=rookies_only)

    train_seasons = seasons[:-test_seasons]
    eval_seasons = seasons[-test_seasons:]
    train_df = df[df["season"].isin(train_seasons)]
    test_df = df[df["season"].isin(eval_seasons)]

    print(f"Train seasons: {train_seasons}")
    print(f"Test seasons:  {eval_seasons}")
    print(f"Train rows: {len(train_df)} ({train_df['is_winner'].sum()} winners)")
    print(f"Test rows:  {len(test_df)} ({test_df['is_winner'].sum()} winners)\n")

    model, scaler = train_model(train_df)
    scored_test_df = evaluate(model, scaler, test_df)
    save_predictions(conn, scored_test_df, award_type, model_version)

    conn.close()
