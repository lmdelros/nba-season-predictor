# Updates a season in progress: downloads the games played so far and the remaining
# schedule, rebuilds features, and simulates the rest of the season from the day after
# the latest final game. NBA.com blocks cloud servers, so this runs on a laptop, against
# the local database or the production one through an SSH tunnel (see
# docs/deployment.md). Run from the repo root:
#   python -m scripts.refresh_season --season 2026-27
import argparse
import sys
from datetime import timedelta

from ingestion.pull_nba_data import get_db_connection
from scripts.seed_demo import run_steps


def download_steps(season):
    """(description, module and arguments) for each step before the simulation."""
    return [
        ("Download played games and box scores from NBA.com",
         ["ingestion.pull_nba_data", "--season", season]),
        ("Download the remaining schedule", ["ingestion.pull_schedule", "--season", season]),
        ("Build features", ["features.build_features", "--season", season]),
    ]


def simulation_cutoff(conn, season):
    """(cutoff date, unplayed games dated before it). The cutoff is the day after the
    latest final game, so every game before it should have a result; any that does not
    (postponed, or not yet in NBA.com's game log) is returned so the refresh can stop
    instead of simulating with a missing result."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(game_date) FROM games WHERE season = %s AND status = 'final'",
            (season,),
        )
        latest = cur.fetchone()[0]
        if latest is None:
            return None, []
        cutoff = latest + timedelta(days=1)
        cur.execute(
            "SELECT game_id, game_date FROM games "
            "WHERE season = %s AND status <> 'final' AND game_date < %s ORDER BY game_date",
            (season, cutoff),
        )
        return cutoff, cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Update a season in progress.")
    parser.add_argument("--season", required=True, help="e.g. 2026-27")
    parser.add_argument("--n-simulations", type=int, default=10000)
    args = parser.parse_args()

    run_steps(download_steps(args.season))

    conn = get_db_connection()
    cutoff, unplayed = simulation_cutoff(conn, args.season)
    conn.close()
    if cutoff is None:
        sys.exit(f"No final {args.season} games yet; nothing to simulate from.")
    if unplayed:
        listed = ", ".join(f"{game_id} ({day})" for game_id, day in unplayed)
        sys.exit(f"Games before {cutoff} have no result yet: {listed}. "
                 "Run again once NBA.com's game log has them.")

    run_steps([(
        f"Simulate the rest of the season from {cutoff} ({args.n_simulations:,} runs)",
        ["simulation.monte_carlo", "--season", args.season, "--cutoff-date", str(cutoff),
         "--n-simulations", str(args.n_simulations)],
    )])


if __name__ == "__main__":
    main()
