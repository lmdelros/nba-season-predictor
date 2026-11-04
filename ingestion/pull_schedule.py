# Loads a season's unplayed regular-season games so the simulation can play out the rest
# of a season in progress. Played games and their scores still come from
# ingestion.pull_nba_data, which turns a scheduled game into a final one. Run from the
# repo root:
#   python -m ingestion.pull_schedule --season 2026-27
import argparse
from datetime import datetime

from nba_api.stats.endpoints import ScheduleLeagueV2

from ingestion.pull_nba_data import get_db_connection

# NBA.com game IDs start with 001 for preseason, 002 for the regular season, 004 for the
# playoffs and 006 for the NBA Cup final, which does not count toward standings.
REGULAR_SEASON_PREFIX = "002"
FINAL_STATUS = 3


def fetch_schedule(season):
    return ScheduleLeagueV2(season=season, timeout=60).get_data_frames()[0]


def scheduled_games(schedule, season):
    """Rows for the regular-season games not yet played. Skips games whose teams are not
    decided yet (team ID 0, such as NBA Cup knockout games before the bracket is set)."""
    games = schedule[
        schedule["gameId"].astype(str).str.startswith(REGULAR_SEASON_PREFIX)
        & (schedule["gameStatus"] != FINAL_STATUS)
        & (schedule["homeTeam_teamId"] != 0)
        & (schedule["awayTeam_teamId"] != 0)
    ]
    return [
        {
            "game_id": int(g.gameId),
            "season": season,
            "game_date": datetime.strptime(g.gameDate, "%m/%d/%Y %H:%M:%S").date(),
            "home_team_id": int(g.homeTeam_teamId),
            "away_team_id": int(g.awayTeam_teamId),
        }
        for g in games.itertuples()
    ]


def insert_scheduled_games(conn, rows):
    """Adds new scheduled games and moves rescheduled ones to their new date; a game
    already recorded as final is never changed."""
    sql = """
        INSERT INTO games (game_id, season, season_type, game_date,
                           home_team_id, away_team_id, status)
        VALUES (%(game_id)s, %(season)s, 'regular', %(game_date)s,
                %(home_team_id)s, %(away_team_id)s, 'scheduled')
        ON CONFLICT (game_id) DO UPDATE SET game_date = EXCLUDED.game_date
        WHERE games.status = 'scheduled'
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2026-27")
    args = parser.parse_args()

    rows = scheduled_games(fetch_schedule(args.season), args.season)
    conn = get_db_connection()
    insert_scheduled_games(conn, rows)
    conn.close()
    print(f"{len(rows)} unplayed {args.season} regular-season games loaded")


if __name__ == "__main__":
    main()
