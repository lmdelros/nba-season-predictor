# Scores each season's newest dated simulation run against what actually happened: the
# probability it gave the real champion and Finals pairing, and whether its projected
# win totals were too cautious. Reads from the database only. Run from the repo root:
#   python -m evaluation.score_title_odds --output docs/title_odds.md
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from simulation.monte_carlo import get_db_connection

GAMES_PER_SEASON = 82
TEAMS = 30
# A team that never won in 10,000 runs gets this probability instead of zero, so its log
# loss stays finite (it is below one run in 10,000).
MIN_PROBABILITY = 1e-5

LATEST_DATED_RUNS_SQL = """
    SELECT DISTINCT ON (season) season, batch_id, cutoff_date, num_simulations
    FROM season_simulations
    WHERE cutoff_date IS NOT NULL
    ORDER BY season, run_at DESC
"""


def champion_score(teams, champion_id):
    """(probability given to the champion, its rank among all teams, log loss)."""
    teams = teams.sort_values("championship_pct", ascending=False).reset_index(drop=True)
    probability = float(teams.loc[teams["team_id"] == champion_id, "championship_pct"].iloc[0])
    rank = int((teams["championship_pct"] > probability).sum()) + 1
    return probability, rank, -math.log(max(probability, MIN_PROBABILITY))


def finals_score(matchups, team_a, team_b):
    """(share of runs with this Finals pairing, its rank among pairings), with zero and no
    rank if the pairing never occurred."""
    pair = (min(team_a, team_b), max(team_a, team_b))
    match = matchups[(matchups["team_a_id"] == pair[0]) & (matchups["team_b_id"] == pair[1])]
    if match.empty:
        return 0.0, None
    share = float(match["matchup_pct"].iloc[0])
    return share, int((matchups["matchup_pct"] > share).sum()) + 1


def calibration_slope(projected, actual):
    """Slope of actual on projected values. 1.0 means teams finished where they were
    projected on average; above 1 means projections were too cautious (teams projected
    above average did even better, and teams below did even worse). Regressing actual on
    projected, not the reverse, keeps luck in the outcome from biasing the slope."""
    projected, actual = np.asarray(projected, dtype=float), np.asarray(actual, dtype=float)
    return float(np.polyfit(projected, actual, 1)[0])


def load_season(conn, run):
    season, batch_id = run.season, run.batch_id
    teams = pd.read_sql(
        "SELECT ss.team_id, t.abbreviation, ss.avg_wins::float AS avg_wins, "
        "ss.championship_pct::float AS championship_pct "
        "FROM season_simulations ss JOIN teams t USING (team_id) WHERE ss.batch_id = %(b)s",
        conn, params={"b": batch_id})
    matchups = pd.read_sql(
        "SELECT team_a_id, team_b_id, matchup_pct::float AS matchup_pct "
        "FROM simulation_finals WHERE batch_id = %(b)s", conn, params={"b": batch_id})
    record = pd.read_sql(
        """
        SELECT team_id,
               sum(win) AS final_wins,
               sum(win) FILTER (WHERE game_date < %(cutoff)s) AS cutoff_wins,
               count(*) FILTER (WHERE game_date < %(cutoff)s) AS cutoff_games
        FROM (
            SELECT home_team_id AS team_id, game_date, (home_score > away_score)::int AS win
            FROM games WHERE season = %(season)s
            UNION ALL
            SELECT away_team_id, game_date, (away_score > home_score)::int
            FROM games WHERE season = %(season)s
        ) g GROUP BY team_id
        """, conn, params={"season": season, "cutoff": run.cutoff_date})
    return teams.merge(record, on="team_id"), matchups


def score_runs(conn):
    runs = pd.read_sql(LATEST_DATED_RUNS_SQL, conn)
    results = pd.read_sql("SELECT * FROM season_results", conn).set_index("season")
    rows = []
    for run in runs.itertuples():
        if run.season not in results.index:
            continue
        outcome = results.loc[run.season]
        teams, matchups = load_season(conn, run)
        names = dict(zip(teams["team_id"], teams["abbreviation"]))
        prob, rank, loss = champion_score(teams, outcome.champion_team_id)
        finals_share, finals_rank = finals_score(
            matchups, outcome.champion_team_id, outcome.runner_up_team_id)
        # Wins after the cutoff: what each projection actually had to predict.
        actual_rest = teams["final_wins"] - teams["cutoff_wins"]
        sim_rest = teams["avg_wins"] - teams["cutoff_wins"]
        remaining_games = GAMES_PER_SEASON - teams["cutoff_games"]
        pace_rest = teams["cutoff_wins"] / teams["cutoff_games"] * remaining_games
        favorite = teams.loc[teams["championship_pct"].idxmax()]
        rows.append({
            "season": run.season, "cutoff": run.cutoff_date,
            "champion": names[outcome.champion_team_id],
            "runner_up": names[outcome.runner_up_team_id],
            "champion_prob": prob, "champion_rank": rank, "champion_log_loss": loss,
            "favorite": favorite["abbreviation"], "favorite_prob": favorite["championship_pct"],
            "finals_share": finals_share, "finals_rank": finals_rank,
            "sim_rest": sim_rest.to_numpy(), "pace_rest": pace_rest.to_numpy(),
            "actual_rest": actual_rest.to_numpy(),
        })
    return pd.DataFrame(rows)


def to_markdown(df):
    uniform_loss = math.log(TEAMS)
    lines = [
        "## Title odds scorecard",
        "",
        "Generated by `python -m evaluation.score_title_odds --output docs/title_odds.md`. "
        "Each season's newest dated simulation run is compared with the real postseason.",
        "",
        "| Season | Projected as of | Champion | Its title odds (rank) | Favorite "
        "| Real Finals | Its share of runs (rank) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in df.itertuples():
        finals_rank = f"#{r.finals_rank}" if r.finals_rank else "never"
        lines.append(
            f"| {r.season} | {r.cutoff} | {r.champion} | {r.champion_prob:.1%} "
            f"(#{r.champion_rank}) | {r.favorite} {r.favorite_prob:.1%} "
            f"| {r.champion} vs {r.runner_up} | {r.finals_share:.1%} ({finals_rank}) |"
        )
    favorite_won = int((df["favorite"] == df["champion"]).sum())
    lines += [
        "",
        f"The favorite won {favorite_won} of {len(df)} titles; the favorites' odds add up to "
        f"{df['favorite_prob'].sum():.2f} expected titles. Mean log loss on the champion: "
        f"{df['champion_log_loss'].mean():.3f}, against {uniform_loss:.3f} for giving all "
        f"{TEAMS} teams equal odds (lower is better).",
        "",
        "### Calibration of projected wins after the cutoff",
        "",
        "Each team's real wins after the cutoff regressed on its projected wins after the "
        "cutoff. A slope of 1.0 means well calibrated; above 1 means the projections were "
        "too cautious (strong teams underrated, weak teams overrated). The comparison "
        "projection keeps each team's cutoff win percentage for its remaining games.",
        "",
        "| Season | Simulation slope | Keep-cutoff-win% slope |",
        "|---|---|---|",
    ]
    for r in df.itertuples():
        lines.append(f"| {r.season} | {calibration_slope(r.sim_rest, r.actual_rest):.2f} "
                     f"| {calibration_slope(r.pace_rest, r.actual_rest):.2f} |")
    actual = np.concatenate(df["actual_rest"].to_list())
    pooled_sim = calibration_slope(np.concatenate(df["sim_rest"].to_list()), actual)
    pooled_pace = calibration_slope(np.concatenate(df["pace_rest"].to_list()), actual)
    lines.append(f"| All seasons | {pooled_sim:.2f} | {pooled_pace:.2f} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="optional Markdown file to write the results to")
    args = parser.parse_args()

    conn = get_db_connection()
    report = to_markdown(score_runs(conn))
    conn.close()
    print(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
