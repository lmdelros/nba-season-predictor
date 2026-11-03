# Records each season's champion and Finals opponent from NBA.com's playoff game log.
# Results go into season_results, separate from games: games holds regular-season games
# only, and the features, standings, and simulations all rely on that.
import argparse
import os
import time

import psycopg2
from nba_api.stats.endpoints import leaguegamelog

FINALS_WINS_NEEDED = 4


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def fetch_playoff_log(season):
    """One row per team per playoff game (TEAM_ID, GAME_ID, GAME_DATE, WL, ...)."""
    return leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star="Playoffs"
    ).get_data_frames()[0]


def finals_from_playoff_log(log):
    """(champion_id, runner_up_id, finals_games) from a playoff game log, or None if the
    Finals are not finished. The Finals are the series containing the last playoff game;
    its two teams are from different conferences, so they meet in no other round."""
    if log.empty:
        return None
    last_game = log.sort_values(["GAME_DATE", "GAME_ID"]).iloc[-1]["GAME_ID"]
    finalists = frozenset(log.loc[log["GAME_ID"] == last_game, "TEAM_ID"])
    if len(finalists) != 2:
        return None

    teams_per_game = log.groupby("GAME_ID")["TEAM_ID"].agg(frozenset)
    finals_games = teams_per_game[teams_per_game == finalists].index
    finals = log[log["GAME_ID"].isin(finals_games)]
    wins = finals[finals["WL"] == "W"]["TEAM_ID"].value_counts()
    if wins.max() < FINALS_WINS_NEEDED:
        return None
    champion = int(wins.idxmax())
    runner_up = int(next(iter(finalists - {champion})))
    return champion, runner_up, len(finals_games)


def upsert_season_result(conn, season, result):
    champion, runner_up, finals_games = result
    sql = """
        INSERT INTO season_results (season, champion_team_id, runner_up_team_id, finals_games)
        VALUES (%(season)s, %(champion)s, %(runner_up)s, %(finals_games)s)
        ON CONFLICT (season) DO UPDATE SET
            champion_team_id = EXCLUDED.champion_team_id,
            runner_up_team_id = EXCLUDED.runner_up_team_id,
            finals_games = EXCLUDED.finals_games
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"season": season, "champion": champion, "runner_up": runner_up,
                          "finals_games": finals_games})
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", required=True, help="e.g. 2022-23 2023-24")
    args = parser.parse_args()

    conn = get_db_connection()
    for season in args.seasons:
        result = finals_from_playoff_log(fetch_playoff_log(season))
        if result is None:
            print(f"{season}: Finals not finished, nothing recorded")
        else:
            upsert_season_result(conn, season, result)
            print(f"{season}: champion {result[0]}, runner-up {result[1]}, "
                  f"{result[2]} Finals games")
        time.sleep(0.6)  # be polite to stats.nba.com between seasons
    conn.close()


if __name__ == "__main__":
    main()
