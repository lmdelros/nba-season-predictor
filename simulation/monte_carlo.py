# Simulates the remaining season thousands of times using model win probabilities,
# tallying standings, playoff odds, and championship odds across runs.
#
# Since the ingested season (2024-25) is fully complete and no season is
# currently in progress, there's no real "future schedule" to simulate. The
# workaround (also a nice validation trick) is backtesting: pick a
# --cutoff-date partway through a completed season, treat games before it as
# "already played" (real results), and games on/after it as "the remaining
# season" to simulate using model win probabilities instead of their actual
# scores. Afterward you can compare the simulation's projected standings
# against what actually happened.
import argparse
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# train_win_probability.py lives in models/, a sibling directory rather than
# this file's own — unlike train_margin.py (same folder), a plain import
# needs models/ added to sys.path first to resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "models"))
from train_win_probability import (  # noqa: E402
    FEATURE_COLUMNS,
    apply_imputer,
    fit_imputer,
    load_training_data,
)


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_played_games(conn, season, cutoff_date):
    """Games with game_date < cutoff_date: their REAL results count toward
    each team's current win/loss record going into the simulation.

    Return columns: game_id, game_date, home_team_id, away_team_id,
    home_score, away_score.
    """
    sql = """
        SELECT game_id, game_date, home_team_id, away_team_id, home_score, away_score
        FROM games
        WHERE season = %(season)s AND game_date < %(cutoff_date)s
    """
    df = pd.read_sql(sql, conn, params={"season": season, "cutoff_date": cutoff_date})
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def load_remaining_games(conn, season, cutoff_date):
    """Games with game_date >= cutoff_date: these get simulated, not read
    from their actual (real) scores.

    Return columns: game_id, home_team_id, away_team_id (no scores needed —
    the whole point is we pretend we don't know them yet).
    """
    sql = """
        SELECT game_id, home_team_id, away_team_id
        FROM games
        WHERE season = %(season)s AND game_date >= %(cutoff_date)s
    """
    return pd.read_sql(sql, conn, params={"season": season, "cutoff_date": cutoff_date})


def compute_current_standings(played_games):
    """Each team's real win count from games already played before the cutoff.

    Careful: a team appears as home_team_id in some rows and away_team_id in
    others — you need to count wins from both sides.

    Return: dict or Series of {team_id: win_count}.
    """
    home_wins = played_games[played_games["home_score"] > played_games["away_score"]]
    away_wins = played_games[played_games["away_score"] > played_games["home_score"]]

    wins = pd.concat([
        home_wins["home_team_id"],
        away_wins["away_team_id"],
    ]).value_counts()

    all_teams = pd.concat([played_games["home_team_id"], played_games["away_team_id"]]).unique()
    return {team_id: int(wins.get(team_id, 0)) for team_id in all_teams}


def get_win_probabilities(conn, season, cutoff_date):
    """Trains a fresh logistic regression on this season's games strictly
    before cutoff_date, then predicts home-win probability for every game
    on/after it — i.e. exactly the games simulate_one_season() needs.

    Deliberately NOT reusing game_predictions here: that table only holds
    whatever train_win_probability.py's own held-out test split happened to
    cover, which won't line up with an arbitrary --cutoff-date passed to this
    script. Training fresh at this exact cutoff keeps train/predict strictly
    time-ordered, matching the same no-leakage rule used everywhere else.

    Return: dict of {game_id: home_win_probability}.
    """
    df = load_training_data(conn, season)
    cutoff = pd.Timestamp(cutoff_date)
    train_df = df[df["game_date"] < cutoff].copy()
    remaining_df = df[df["game_date"] >= cutoff].copy()

    fills = fit_imputer(train_df)
    train_df = apply_imputer(train_df, fills)
    remaining_df = apply_imputer(remaining_df, fills)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df[FEATURE_COLUMNS].astype(float))
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, train_df["home_win"])

    X_remaining = scaler.transform(remaining_df[FEATURE_COLUMNS].astype(float))
    probs = model.predict_proba(X_remaining)[:, 1]

    return dict(zip(remaining_df["game_id"], probs))


def simulate_one_season(current_wins, remaining_games, win_probs, rng):
    """One random playthrough of every remaining game.

    For each remaining game:
      - draw a random number in [0, 1) from rng (e.g. rng.random())
      - if it's < that game's home_win_probability: home team wins
      - otherwise: away team wins
      - increment the winning team's tally, starting from current_wins

    `rng` should be a numpy random Generator (np.random.default_rng(seed)),
    passed in rather than created here, so results are reproducible and you
    aren't re-seeding on every single simulation.

    Return: dict of {team_id: final_win_total} for this one simulated season.
    """
    home_probs = remaining_games["game_id"].map(win_probs).to_numpy()
    draws = rng.random(len(remaining_games))
    home_won = draws < home_probs

    winners = np.where(home_won, remaining_games["home_team_id"], remaining_games["away_team_id"])
    win_counts = pd.Series(winners).value_counts()

    final_wins = dict(current_wins)
    for team_id, wins in win_counts.items():
        final_wins[team_id] = final_wins.get(team_id, 0) + int(wins)
    return final_wins


def determine_playoff_teams(final_wins, teams_df):
    """Given one simulation's final win totals, return the set of team_ids
    that made the playoffs.

    Simplification worth making explicit in a comment when you write this:
    use top-8 by win total per conference, ignoring the real NBA's play-in
    tournament wrinkle for seeds 7-10 — unless you want to model that too,
    which is a meaningfully bigger step.
    """
    df = teams_df.copy()
    df["final_wins"] = df["team_id"].map(final_wins)

    playoff_teams = set()
    for _, group in df.groupby("conference"):
        top8 = group.sort_values("final_wins", ascending=False).head(8)
        playoff_teams.update(top8["team_id"])
    return playoff_teams


def run_simulations(current_wins, remaining_games, win_probs, teams_df, n_simulations=10000, seed=42):
    """Runs simulate_one_season() n_simulations times and aggregates:
      - avg_wins: mean final win total per team across all sims
      - playoff_pct: fraction of sims where each team made the playoffs

    championship_pct is NOT computed here yet — that needs a full playoff
    bracket simulation (seeding, best-of-7 series, round by round), which is
    a separate, bigger piece of work. Leave it out of season_simulations for
    now (NULL) rather than faking it.

    Return: DataFrame with columns team_id, avg_wins, playoff_pct.
    """
    rng = np.random.default_rng(seed)
    win_totals = []
    made_playoffs = []

    for _ in range(n_simulations):
        final_wins = simulate_one_season(current_wins, remaining_games, win_probs, rng)
        win_totals.append(final_wins)

        playoff_teams = determine_playoff_teams(final_wins, teams_df)
        made_playoffs.append({team_id: team_id in playoff_teams for team_id in final_wins})

    wins_df = pd.DataFrame(win_totals)
    playoffs_df = pd.DataFrame(made_playoffs)

    return pd.DataFrame({
        "team_id": wins_df.columns,
        "avg_wins": wins_df.mean().values,
        "playoff_pct": playoffs_df.mean().values,
    })


def save_simulation_results(conn, results_df, season, n_simulations, batch_id=None):
    """Upserts into season_simulations.

    batch_id groups all 30 teams' rows from this one run together — generate
    one (e.g. str(uuid.uuid4()) or a timestamp string) if the caller doesn't
    pass one, so you can keep multiple historical simulation runs side by
    side instead of overwriting them.
    """
    batch_id = batch_id or str(uuid.uuid4())

    sql = """
        INSERT INTO season_simulations (season, team_id, batch_id, num_simulations,
                                         avg_wins, playoff_pct)
        VALUES (%(season)s, %(team_id)s, %(batch_id)s, %(num_simulations)s,
                %(avg_wins)s, %(playoff_pct)s)
        ON CONFLICT (season, team_id, batch_id) DO UPDATE SET
            num_simulations = EXCLUDED.num_simulations,
            avg_wins = EXCLUDED.avg_wins,
            playoff_pct = EXCLUDED.playoff_pct
    """
    records = [
        {
            "season": season,
            "team_id": int(row.team_id),
            "batch_id": batch_id,
            "num_simulations": n_simulations,
            "avg_wins": float(row.avg_wins),
            "playoff_pct": float(row.playoff_pct),
        }
        for row in results_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()
    return batch_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2024-25")
    parser.add_argument(
        "--cutoff-date", required=True,
        help="YYYY-MM-DD; games before this are 'already played', on/after are simulated",
    )
    parser.add_argument("--n-simulations", type=int, default=10000)
    args = parser.parse_args()

    conn = get_db_connection()

    played = load_played_games(conn, args.season, args.cutoff_date)
    remaining = load_remaining_games(conn, args.season, args.cutoff_date)
    current_wins = compute_current_standings(played)
    win_probs = get_win_probabilities(conn, args.season, args.cutoff_date)
    teams_df = pd.read_sql("SELECT team_id, conference FROM teams", conn)

    results = run_simulations(
        current_wins, remaining, win_probs, teams_df, n_simulations=args.n_simulations
    )
    batch_id = save_simulation_results(conn, results, args.season, args.n_simulations)

    print(f"Simulated {args.n_simulations} seasons from {args.cutoff_date} onward. batch_id={batch_id}")
    print(results.merge(teams_df, on="team_id").sort_values("playoff_pct", ascending=False).to_string())

    conn.close()


if __name__ == "__main__":
    main()
