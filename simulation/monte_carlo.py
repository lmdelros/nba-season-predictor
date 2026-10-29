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


# Results-based team features that must be frozen at the cutoff date. Rest days and
# back-to-backs are not here: they come from the schedule, which is published before
# the season, so using their scheduled values does not leak results.
SNAPSHOT_COLUMNS = [
    "rolling_win_pct_l10", "rolling_off_rating", "rolling_def_rating",
    "season_win_pct_home", "season_win_pct_away", "season_avg_margin",
]


def load_team_features(conn, season):
    """Every team_game_features row for the season (one per team per game) with its
    game date and team_game_form margin, so a snapshot can be taken as of any cutoff."""
    sql = """
        SELECT tgf.team_id, g.game_date, tgf.rolling_win_pct_l10, tgf.rolling_off_rating,
               tgf.rolling_def_rating, tgf.season_win_pct_home, tgf.season_win_pct_away,
               tgform.season_avg_margin
        FROM team_game_features tgf
        JOIN games g ON g.game_id = tgf.game_id
        JOIN team_game_form tgform
            ON tgform.game_id = tgf.game_id AND tgform.team_id = tgf.team_id
        WHERE g.season = %(season)s
    """
    df = pd.read_sql(sql, conn, params={"season": season})
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def cutoff_snapshot(team_features, cutoff):
    """Each team's form as known on the cutoff date. A team's first feature row on or
    after the cutoff was computed only from its earlier games, all of which were
    played before the cutoff, so it is exactly what was known at that point.
    """
    after = team_features[team_features["game_date"] >= pd.Timestamp(cutoff)]
    first = after.sort_values("game_date").groupby("team_id").head(1)
    return first.set_index("team_id")[SNAPSHOT_COLUMNS]


def head_to_head_before(played_games):
    """Each team's win % against each opponent in already-played games, indexed by
    (team_id, opp_id). Pairs that have not met are absent."""
    home_won = played_games["home_score"] > played_games["away_score"]
    long = pd.concat([
        pd.DataFrame({
            "team_id": played_games["home_team_id"], "opp_id": played_games["away_team_id"],
            "win": home_won,
        }),
        pd.DataFrame({
            "team_id": played_games["away_team_id"], "opp_id": played_games["home_team_id"],
            "win": ~home_won,
        }),
    ])
    return long.groupby(["team_id", "opp_id"])["win"].mean()


def freeze_remaining_features(remaining, snapshot, h2h):
    """Overwrites every results-based feature of not-yet-played games with what was
    known at the cutoff: each team's snapshot form and the pre-cutoff head-to-head.
    Scheduled rest days and back-to-backs are kept as they are.
    """
    remaining = remaining.copy()
    for side in ("home", "away"):
        form = snapshot.reindex(remaining[f"{side}_team_id"])
        for col in (
            "rolling_win_pct_l10", "rolling_off_rating", "rolling_def_rating",
            "season_avg_margin",
        ):
            remaining[f"{side}_{col}"] = form[col].to_numpy()
    remaining["home_season_win_pct_home"] = (
        snapshot["season_win_pct_home"].reindex(remaining["home_team_id"]).to_numpy()
    )
    remaining["away_season_win_pct_away"] = (
        snapshot["season_win_pct_away"].reindex(remaining["away_team_id"]).to_numpy()
    )
    pairs = pd.MultiIndex.from_arrays([remaining["home_team_id"], remaining["away_team_id"]])
    remaining["home_h2h_win_pct_season"] = h2h.reindex(pairs).to_numpy()
    return remaining


def predict_remaining(games, team_features, cutoff):
    """Trains a fresh logistic regression on games strictly before the cutoff and
    predicts home-win probability for every game on/after it, using only
    information available at the cutoff. Pure (no database), so it can be
    leakage-tested.

    games: load_training_data() output. team_features: load_team_features() output.
    Return: (dict of {game_id: home_win_probability}, model, scaler, fills).
    """
    cutoff = pd.Timestamp(cutoff)
    train_df = games[games["game_date"] < cutoff].copy()
    remaining_df = freeze_remaining_features(
        games[games["game_date"] >= cutoff],
        cutoff_snapshot(team_features, cutoff),
        head_to_head_before(train_df),
    )

    fills = fit_imputer(train_df)
    train_df = apply_imputer(train_df, fills)
    remaining_df = apply_imputer(remaining_df, fills)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df[FEATURE_COLUMNS].astype(float))
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, train_df["home_win"])

    X_remaining = scaler.transform(remaining_df[FEATURE_COLUMNS].astype(float))
    probs = model.predict_proba(X_remaining)[:, 1]

    return dict(zip(remaining_df["game_id"], probs)), model, scaler, fills


def get_win_probabilities(conn, season, cutoff_date):
    """Loads the season from the database and runs predict_remaining() at the cutoff.

    Deliberately NOT reusing game_predictions here: that table only holds
    whatever train_win_probability.py's own held-out test split happened to
    cover, which won't line up with an arbitrary --cutoff-date passed to this
    script, and its features were built from each game's real prior results,
    including results after the cutoff.

    Also returns the fitted model/scaler/fills so the playoff bracket
    simulation can score hypothetical matchups with the exact same model
    instead of training a second one.

    Return: (dict of {game_id: home_win_probability}, model, scaler, fills).
    """
    return predict_remaining(
        load_training_data(conn, season), load_team_features(conn, season), cutoff_date
    )


def load_team_snapshot_features(conn, season, cutoff_date):
    """Each team's form as of the cutoff, used to build hypothetical playoff
    matchups that may not correspond to any single real game (or any game at
    all, if two teams meeting in the Finals never played each other pre-cutoff).
    """
    return cutoff_snapshot(load_team_features(conn, season), cutoff_date)


def build_matchup_features(home_id, away_id, snapshot, fills):
    """One FEATURE_COLUMNS-shaped row for a hypothetical game between two
    teams' form snapshots as of the cutoff date.

    Two fields are deliberately NOT taken from real data: head-to-head is set
    to a neutral 0.5 rather than reconstructed from their actual regular
    season meetings (which may be zero, or lopsided by matchup luck), and
    rest/back-to-back use league-average fills rather than whatever each
    team's rest happened to be on the last day of the regular season —
    playoff scheduling has its own rest pattern unrelated to that.
    """
    home = snapshot.loc[home_id]
    away = snapshot.loc[away_id]
    return {
        "home_rolling_win_pct_l10": home["rolling_win_pct_l10"],
        "away_rolling_win_pct_l10": away["rolling_win_pct_l10"],
        "home_rolling_off_rating": home["rolling_off_rating"],
        "home_rolling_def_rating": home["rolling_def_rating"],
        "away_rolling_off_rating": away["rolling_off_rating"],
        "away_rolling_def_rating": away["rolling_def_rating"],
        "home_rest_days": fills["home_rest_days"],
        "away_rest_days": fills["away_rest_days"],
        "home_is_back_to_back": 0,
        "away_is_back_to_back": 0,
        "home_h2h_win_pct_season": 0.5,
        "home_season_win_pct_home": home["season_win_pct_home"],
        "away_season_win_pct_away": away["season_win_pct_away"],
        "home_season_avg_margin": home["season_avg_margin"],
        "away_season_avg_margin": away["season_avg_margin"],
    }


def compute_pairwise_win_probs(team_ids, snapshot, model, scaler, fills):
    """P(home team wins) for every ordered pair of teams that could plausibly
    meet in the playoffs, scored once with the same trained model used for
    the regular season — team snapshots are fixed, so this doesn't need to
    be recomputed on every one of the n_simulations bracket runs.

    Return: dict of {(home_id, away_id): home_win_probability}.
    """
    rows, pairs = [], []
    for home_id in team_ids:
        for away_id in team_ids:
            if home_id == away_id:
                continue
            rows.append(build_matchup_features(home_id, away_id, snapshot, fills))
            pairs.append((home_id, away_id))

    df = apply_imputer(pd.DataFrame(rows), fills)
    X = scaler.transform(df[FEATURE_COLUMNS].astype(float))
    probs = model.predict_proba(X)[:, 1]
    return dict(zip(pairs, probs))


# 2-2-1-1-1 format: True means the higher seed hosts that game of the series.
SERIES_HOME_GAMES = [True, True, False, False, True, False, True]


def simulate_series(higher_seed, lower_seed, pairwise_probs, rng):
    """Best-of-7 between two already-seeded teams, home court favoring the
    higher seed in the standard 2-2-1-1-1 pattern. Stops as soon as either
    side reaches 4 wins rather than always playing out 7 games.
    """
    wins = {higher_seed: 0, lower_seed: 0}
    for higher_seed_hosts in SERIES_HOME_GAMES:
        home, away = (higher_seed, lower_seed) if higher_seed_hosts else (lower_seed, higher_seed)
        winner = home if rng.random() < pairwise_probs[(home, away)] else away
        wins[winner] += 1
        if wins[winner] == 4:
            return winner
    return higher_seed if wins[higher_seed] > wins[lower_seed] else lower_seed


def simulate_conference(seeds, pairwise_probs, rng):
    """seeds: the conference's 8 playoff teams ordered 1st through 8th by
    final win total. Fixed NBA bracket (no reseeding after round 1):
    (1v8)/(4v5) meet in one semifinal, (2v7)/(3v6) meet in the other.
    """
    by_seed = seeds.index
    r1 = [
        simulate_series(seeds[0], seeds[7], pairwise_probs, rng),
        simulate_series(seeds[3], seeds[4], pairwise_probs, rng),
        simulate_series(seeds[2], seeds[5], pairwise_probs, rng),
        simulate_series(seeds[1], seeds[6], pairwise_probs, rng),
    ]
    semi_a = simulate_series(*sorted(r1[0:2], key=by_seed), pairwise_probs, rng)
    semi_b = simulate_series(*sorted(r1[2:4], key=by_seed), pairwise_probs, rng)
    return simulate_series(*sorted([semi_a, semi_b], key=by_seed), pairwise_probs, rng)


def simulate_playoff_bracket(final_wins, teams_df, pairwise_probs, rng):
    """One simulated postseason built on top of one simulate_one_season()
    result: seed each conference's top 8 by that simulation's final_wins,
    play out both conference brackets, then the two conference champions
    meet in the Finals with home court going to whoever has the better
    regular-season record overall (the real NBA rule since 2014).

    Return: champion team_id for this one simulation.
    """
    champions = []
    for _, group in teams_df.groupby("conference"):
        seeds = sorted(group["team_id"], key=lambda t: -final_wins.get(t, 0))[:8]
        champions.append(simulate_conference(seeds, pairwise_probs, rng))

    higher, lower = sorted(champions, key=lambda t: -final_wins.get(t, 0))
    return simulate_series(higher, lower, pairwise_probs, rng)


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


def run_simulations(
    current_wins, remaining_games, win_probs, teams_df, pairwise_probs,
    n_simulations=10000, seed=42,
):
    """Runs simulate_one_season() n_simulations times and aggregates:
      - avg_wins: mean final win total per team across all sims
      - playoff_pct: fraction of sims where each team made the playoffs
      - championship_pct: fraction of sims where each team won the Finals,
        via simulate_playoff_bracket() on top of that same simulated season

    Return: DataFrame with columns team_id, avg_wins, playoff_pct, championship_pct.
    """
    rng = np.random.default_rng(seed)
    win_totals = []
    made_playoffs = []
    champions = []

    for _ in range(n_simulations):
        final_wins = simulate_one_season(current_wins, remaining_games, win_probs, rng)
        win_totals.append(final_wins)

        playoff_teams = determine_playoff_teams(final_wins, teams_df)
        made_playoffs.append({team_id: team_id in playoff_teams for team_id in final_wins})

        champions.append(simulate_playoff_bracket(final_wins, teams_df, pairwise_probs, rng))

    wins_df = pd.DataFrame(win_totals)
    playoffs_df = pd.DataFrame(made_playoffs)
    champion_counts = pd.Series(champions).value_counts()
    championship_pct = wins_df.columns.map(
        lambda team_id: champion_counts.get(team_id, 0) / n_simulations
    )

    return pd.DataFrame({
        "team_id": wins_df.columns,
        "avg_wins": wins_df.mean().values,
        "playoff_pct": playoffs_df.mean().values,
        "championship_pct": championship_pct,
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
                                         avg_wins, playoff_pct, championship_pct)
        VALUES (%(season)s, %(team_id)s, %(batch_id)s, %(num_simulations)s,
                %(avg_wins)s, %(playoff_pct)s, %(championship_pct)s)
        ON CONFLICT (season, team_id, batch_id) DO UPDATE SET
            num_simulations = EXCLUDED.num_simulations,
            avg_wins = EXCLUDED.avg_wins,
            playoff_pct = EXCLUDED.playoff_pct,
            championship_pct = EXCLUDED.championship_pct
    """
    records = [
        {
            "season": season,
            "team_id": int(row.team_id),
            "batch_id": batch_id,
            "num_simulations": n_simulations,
            "avg_wins": float(row.avg_wins),
            "playoff_pct": float(row.playoff_pct),
            "championship_pct": float(row.championship_pct),
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
    win_probs, model, scaler, fills = get_win_probabilities(conn, args.season, args.cutoff_date)
    teams_df = pd.read_sql("SELECT team_id, conference FROM teams", conn)

    snapshot = load_team_snapshot_features(conn, args.season, args.cutoff_date)
    pairwise_probs = compute_pairwise_win_probs(teams_df["team_id"], snapshot, model, scaler, fills)

    results = run_simulations(
        current_wins, remaining, win_probs, teams_df, pairwise_probs,
        n_simulations=args.n_simulations,
    )
    batch_id = save_simulation_results(conn, results, args.season, args.n_simulations)

    print(
        f"Simulated {args.n_simulations} seasons from {args.cutoff_date} onward. "
        f"batch_id={batch_id}"
    )
    standings = results.merge(teams_df, on="team_id").sort_values(
        "playoff_pct", ascending=False
    )
    print(standings.to_string())

    conn.close()


if __name__ == "__main__":
    main()
