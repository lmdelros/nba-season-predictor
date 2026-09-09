# Backfills player_season_stats, team_season_standings, and player_awards
# across many historical seasons — cheap, season-level data for award
# modeling, as opposed to the game-by-game pipeline the win probability/
# margin models use.
import argparse
import os
import time

import psycopg2
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguestandingsv3,
    playerawards,
)
from nba_api.stats.static import teams as static_teams

# Award winners are always significant statistical performers along the axis
# that award cares about — restricting playerawards lookups (one call per
# player, expensive to run for everyone) to each season's shortlist on the
# relevant stat keeps the candidate pool small while still reliably covering
# every real winner. Points for MVP (voters reward top scorers on good
# teams), steals+blocks ("stocks") for DPOY — an imperfect proxy that can
# miss a positional/versatility-driven winner like Draymond Green, worth
# knowing as a real limitation rather than silently trusting the shortlist.
CANDIDATES_PER_SEASON = 20

AWARD_LABELS = {
    "mvp": "NBA Most Valuable Player",
    "dpoy": "NBA Defensive Player of the Year",
}

CANDIDATE_HEURISTICS = {
    "mvp": lambda df: df.sort_values("PTS", ascending=False),
    "dpoy": lambda df: df.assign(STOCKS=df["STL"] + df["BLK"]).sort_values(
        "STOCKS", ascending=False
    ),
}


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def upsert_teams_if_missing(conn):
    """Older seasons can reference relocated/renamed franchises (e.g. the
    Seattle SuperSonics) that may already be missing from `teams` if it was
    only ever populated from recent seasons. static_teams covers the full
    history, so this is a cheap one-time safety net.
    """
    sql = """
        INSERT INTO teams (team_id, full_name, abbreviation, conference, division)
        VALUES (%(team_id)s, %(full_name)s, %(abbreviation)s, 'Unknown', 'Unknown')
        ON CONFLICT (team_id) DO NOTHING
    """
    records = [
        {
            "team_id": t["id"],
            "full_name": t["full_name"],
            "abbreviation": t["abbreviation"],
        }
        for t in static_teams.get_teams()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def fetch_season_player_stats(season):
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season, season_type_all_star="Regular Season"
    ).get_data_frames()[0]
    return df[[
        "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN", "PTS", "REB",
        "AST", "STL", "BLK", "TOV", "FG_PCT", "FG3_PCT", "FT_PCT", "PLUS_MINUS",
    ]]


def fetch_season_standings(season):
    df = leaguestandingsv3.LeagueStandingsV3(season=season).get_data_frames()[0]
    return df[["TeamID", "WINS", "LOSSES", "WinPCT"]]


def upsert_players(conn, stats_df):
    """player_season_stats FKs into players — insert any not-yet-seen
    player_ids first (full_name only; bio fields stay null, same as the
    game-by-game ingestion path).
    """
    sql = """
        INSERT INTO players (player_id, full_name)
        VALUES (%(player_id)s, %(full_name)s)
        ON CONFLICT (player_id) DO NOTHING
    """
    records = [
        {"player_id": int(r.PLAYER_ID), "full_name": r.PLAYER_NAME}
        for r in stats_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def upsert_player_season_stats(conn, stats_df, season):
    sql = """
        INSERT INTO player_season_stats (player_id, season, team_id, games_played,
                                          minutes, points, rebounds, assists, steals,
                                          blocks, turnovers, fg_pct, fg3_pct, ft_pct,
                                          plus_minus)
        VALUES (%(player_id)s, %(season)s, %(team_id)s, %(games_played)s, %(minutes)s,
                %(points)s, %(rebounds)s, %(assists)s, %(steals)s, %(blocks)s,
                %(turnovers)s, %(fg_pct)s, %(fg3_pct)s, %(ft_pct)s, %(plus_minus)s)
        ON CONFLICT (player_id, season) DO UPDATE SET
            team_id = EXCLUDED.team_id, games_played = EXCLUDED.games_played,
            minutes = EXCLUDED.minutes, points = EXCLUDED.points,
            rebounds = EXCLUDED.rebounds, assists = EXCLUDED.assists,
            steals = EXCLUDED.steals, blocks = EXCLUDED.blocks,
            turnovers = EXCLUDED.turnovers, fg_pct = EXCLUDED.fg_pct,
            fg3_pct = EXCLUDED.fg3_pct, ft_pct = EXCLUDED.ft_pct,
            plus_minus = EXCLUDED.plus_minus
    """
    records = [
        {
            "player_id": int(r.PLAYER_ID), "season": season, "team_id": int(r.TEAM_ID),
            "games_played": int(r.GP), "minutes": float(r.MIN), "points": float(r.PTS),
            "rebounds": float(r.REB), "assists": float(r.AST), "steals": float(r.STL),
            "blocks": float(r.BLK), "turnovers": float(r.TOV),
            "fg_pct": float(r.FG_PCT), "fg3_pct": float(r.FG3_PCT), "ft_pct": float(r.FT_PCT),
            "plus_minus": float(r.PLUS_MINUS),
        }
        for r in stats_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def upsert_team_standings(conn, standings_df, season):
    sql = """
        INSERT INTO team_season_standings (team_id, season, wins, losses, win_pct)
        VALUES (%(team_id)s, %(season)s, %(wins)s, %(losses)s, %(win_pct)s)
        ON CONFLICT (team_id, season) DO UPDATE SET
            wins = EXCLUDED.wins, losses = EXCLUDED.losses, win_pct = EXCLUDED.win_pct
    """
    records = [
        {
            "team_id": int(r.TeamID), "season": season,
            "wins": int(r.WINS), "losses": int(r.LOSSES), "win_pct": float(r.WinPCT),
        }
        for r in standings_df.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def upsert_award(conn, player_id, season, award_type):
    sql = """
        INSERT INTO player_awards (player_id, season, award_type)
        VALUES (%(player_id)s, %(season)s, %(award_type)s)
        ON CONFLICT (season, award_type) DO UPDATE SET player_id = EXCLUDED.player_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"player_id": player_id, "season": season, "award_type": award_type})
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument(
        "--awards", default="mvp",
        help=f"comma-separated, from {list(AWARD_LABELS)}",
    )
    args = parser.parse_args()

    start_year = int(args.start_season[:4])
    end_year = int(args.end_season[:4])
    seasons = [f"{y}-{str(y + 1)[2:]}" for y in range(start_year, end_year + 1)]
    awards = args.awards.split(",")

    conn = get_db_connection()
    upsert_teams_if_missing(conn)

    candidate_player_ids = set()

    for season in seasons:
        print(f"{season}: pulling player stats + standings...")
        stats_df = fetch_season_player_stats(season)
        standings_df = fetch_season_standings(season)

        upsert_players(conn, stats_df)
        upsert_player_season_stats(conn, stats_df, season)
        upsert_team_standings(conn, standings_df, season)

        for award in awards:
            shortlist = CANDIDATE_HEURISTICS[award](stats_df).head(CANDIDATES_PER_SEASON)
            candidate_player_ids.update(int(pid) for pid in shortlist["PLAYER_ID"])
        time.sleep(0.6)  # be polite to stats.nba.com between season calls

    print(f"Checking award history for {len(candidate_player_ids)} candidate players...")
    for player_id in candidate_player_ids:
        awards_df = playerawards.PlayerAwards(player_id=player_id).get_data_frames()[0]
        for award in awards:
            matching_seasons = awards_df.loc[
                awards_df["DESCRIPTION"] == AWARD_LABELS[award], "SEASON"
            ]
            for season in matching_seasons:
                if season in seasons:
                    upsert_award(conn, player_id, season, award)
                    print(f"  {award.upper()} {season}: player_id={player_id}")
        time.sleep(0.6)

    conn.close()


if __name__ == "__main__":
    main()
