# MIP model: unlike MVP/DPOY/ROY, this award is about year-over-year
# improvement, not absolute level — so the feature set is built from deltas
# against each player's own prior season (plus their current level, since
# voters favor a jump that reaches a genuinely strong season, not just a big
# percentage increase off a tiny base). Candidate pool mirrors
# ingestion/pull_award_data.py's build_mip_candidates(): each season's
# top-20 by points-per-game increase over their immediately preceding
# season in our data.
import argparse

import pandas as pd

from models.award_model import run

CANDIDATES_PER_SEASON = 20

FEATURE_COLUMNS = [
    "points_per_game", "ppg_delta",
    "rebounds_per_game", "reb_delta",
    "assists_per_game", "ast_delta",
    "team_win_pct", "team_win_pct_delta",
]


def load_mip_candidate_pool(conn, seasons, award_type):
    sql = """
        WITH with_prior AS (
            SELECT pss.player_id, pss.season, pss.team_id, pss.games_played,
                   pss.points, pss.rebounds, pss.assists,
                   LAG(pss.season) OVER w AS prior_season,
                   LAG(pss.games_played) OVER w AS prior_games_played,
                   LAG(pss.points) OVER w AS prior_points,
                   LAG(pss.rebounds) OVER w AS prior_rebounds,
                   LAG(pss.assists) OVER w AS prior_assists
            FROM player_season_stats pss
            WINDOW w AS (PARTITION BY pss.player_id ORDER BY pss.season)
        )
        SELECT wp.*, tss.win_pct AS team_win_pct, ptss.win_pct AS prior_team_win_pct
        FROM with_prior wp
        JOIN team_season_standings tss
            ON tss.team_id = wp.team_id AND tss.season = wp.season
        LEFT JOIN player_season_stats pps
            ON pps.player_id = wp.player_id AND pps.season = wp.prior_season
        LEFT JOIN team_season_standings ptss
            ON ptss.team_id = pps.team_id AND ptss.season = wp.prior_season
        WHERE wp.season = ANY(%(seasons)s)
          AND wp.prior_season IS NOT NULL
          AND substring(wp.season, 1, 4)::int - substring(wp.prior_season, 1, 4)::int = 1
    """
    df = pd.read_sql(sql, conn, params={"seasons": seasons})

    df["points_per_game"] = df["points"] / df["games_played"]
    df["rebounds_per_game"] = df["rebounds"] / df["games_played"]
    df["assists_per_game"] = df["assists"] / df["games_played"]
    prior_ppg = df["prior_points"] / df["prior_games_played"]
    prior_rpg = df["prior_rebounds"] / df["prior_games_played"]
    prior_apg = df["prior_assists"] / df["prior_games_played"]
    df["ppg_delta"] = df["points_per_game"] - prior_ppg
    df["reb_delta"] = df["rebounds_per_game"] - prior_rpg
    df["ast_delta"] = df["assists_per_game"] - prior_apg
    df["team_win_pct_delta"] = df["team_win_pct"] - df["prior_team_win_pct"]

    shortlisted = [
        group.sort_values("ppg_delta", ascending=False).head(CANDIDATES_PER_SEASON)
        for _, group in df.groupby("season")
    ]
    pool = pd.concat(shortlisted, ignore_index=True)

    awards_sql = """
        SELECT player_id, season FROM player_awards WHERE award_type = %(award_type)s
    """
    winners = pd.read_sql(awards_sql, conn, params={"award_type": award_type})
    winner_keys = set(zip(winners["player_id"], winners["season"]))
    pool["is_winner"] = [
        (pid, season) in winner_keys for pid, season in zip(pool["player_id"], pool["season"])
    ]
    return pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-seasons", type=int, default=3)
    args = parser.parse_args()

    run(
        award_type="mip", rank_by=None, model_version="mip_logreg_v1",
        start_season=args.start_season, end_season=args.end_season,
        test_seasons=args.test_seasons,
        feature_columns=FEATURE_COLUMNS, load_fn=load_mip_candidate_pool,
    )


if __name__ == "__main__":
    main()
