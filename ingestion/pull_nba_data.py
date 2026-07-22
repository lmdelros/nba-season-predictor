# Pulls team and game data for one season via nba_api and loads it into Postgres.
import argparse
import os

import psycopg2
from nba_api.stats.endpoints import leaguegamelog
from nba_api.stats.static import teams as static_teams

# nba_api's static team list has no conference/division, so it's hardcoded here.
TEAM_CONFERENCE = {
    "BOS": ("East", "Atlantic"), "BKN": ("East", "Atlantic"), "NYK": ("East", "Atlantic"),
    "PHI": ("East", "Atlantic"), "TOR": ("East", "Atlantic"),
    "CHI": ("East", "Central"), "CLE": ("East", "Central"), "DET": ("East", "Central"),
    "IND": ("East", "Central"), "MIL": ("East", "Central"),
    "ATL": ("East", "Southeast"), "CHA": ("East", "Southeast"), "MIA": ("East", "Southeast"),
    "ORL": ("East", "Southeast"), "WAS": ("East", "Southeast"),
    "DEN": ("West", "Northwest"), "MIN": ("West", "Northwest"), "OKC": ("West", "Northwest"),
    "POR": ("West", "Northwest"), "UTA": ("West", "Northwest"),
    "GSW": ("West", "Pacific"), "LAC": ("West", "Pacific"), "LAL": ("West", "Pacific"),
    "PHX": ("West", "Pacific"), "SAC": ("West", "Pacific"),
    "DAL": ("West", "Southwest"), "HOU": ("West", "Southwest"), "MEM": ("West", "Southwest"),
    "NOP": ("West", "Southwest"), "SAS": ("West", "Southwest"),
}


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def fetch_teams():
    rows = []
    for t in static_teams.get_teams():
        conference, division = TEAM_CONFERENCE[t["abbreviation"]]
        rows.append({
            "team_id": t["id"],
            "full_name": t["full_name"],
            "abbreviation": t["abbreviation"],
            "conference": conference,
            "division": division,
        })
    return rows


def upsert_teams(conn, rows):
    sql = """
        INSERT INTO teams (team_id, full_name, abbreviation, conference, division)
        VALUES (%(team_id)s, %(full_name)s, %(abbreviation)s, %(conference)s, %(division)s)
        ON CONFLICT (team_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            conference = EXCLUDED.conference,
            division = EXCLUDED.division
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def fetch_games(season, season_type="Regular Season"):
    df = leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star=season_type
    ).get_data_frames()[0]

    rows_by_game = {}
    for _, row in df.iterrows():
        rows_by_game.setdefault(row["GAME_ID"], []).append(row)

    games = []
    for game_id, game_rows in rows_by_game.items():
        home_row = next((r for r in game_rows if "vs." in r["MATCHUP"]), None)
        away_row = next((r for r in game_rows if r is not home_row), None)
        if home_row is None:
            # Neutral-site games (e.g. NBA Cup semifinals/final) show "@" for
            # both teams since neither is truly home; fall back to row order.
            home_row, away_row = game_rows[1], game_rows[0]

        games.append({
            "game_id": game_id,
            "season": season,
            "season_type": "playoffs" if season_type == "Playoffs" else "regular",
            "game_date": home_row["GAME_DATE"],
            "status": "final",
            "home_team_id": home_row["TEAM_ID"],
            "home_score": int(home_row["PTS"]),
            "away_team_id": away_row["TEAM_ID"],
            "away_score": int(away_row["PTS"]),
        })

    return games


def upsert_games(conn, rows):
    sql = """
        INSERT INTO games (game_id, season, season_type, game_date,
                            home_team_id, away_team_id, home_score, away_score, status)
        VALUES (%(game_id)s, %(season)s, %(season_type)s, %(game_date)s,
                %(home_team_id)s, %(away_team_id)s, %(home_score)s, %(away_score)s, %(status)s)
        ON CONFLICT (game_id) DO UPDATE SET
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            status = EXCLUDED.status
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2024-25")
    args = parser.parse_args()

    conn = get_db_connection()
    upsert_teams(conn, fetch_teams())
    upsert_games(conn, fetch_games(args.season))
    conn.close()


if __name__ == "__main__":
    main()
