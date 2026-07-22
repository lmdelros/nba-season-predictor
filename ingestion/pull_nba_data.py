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


def fetch_player_box_scores(season, season_type="Regular Season"):
    return leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star=season_type, player_or_team_abbreviation="P"
    ).get_data_frames()[0]


def fetch_players(df):
    dedup = df.drop_duplicates(subset="PLAYER_ID")
    return [
        {"player_id": int(r.PLAYER_ID), "full_name": r.PLAYER_NAME}
        for r in dedup.itertuples()
    ]


def upsert_players(conn, rows):
    sql = """
        INSERT INTO players (player_id, full_name)
        VALUES (%(player_id)s, %(full_name)s)
        ON CONFLICT (player_id) DO UPDATE SET full_name = EXCLUDED.full_name
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def fetch_player_game_stats(df):
    return [
        {
            "game_id": r.GAME_ID,
            "player_id": int(r.PLAYER_ID),
            "team_id": int(r.TEAM_ID),
            "minutes": r.MIN,
            "points": r.PTS,
            "rebounds": r.REB,
            "assists": r.AST,
            "steals": r.STL,
            "blocks": r.BLK,
            "turnovers": r.TOV,
            "fg_made": r.FGM,
            "fg_attempted": r.FGA,
            "fg3_made": r.FG3M,
            "fg3_attempted": r.FG3A,
            "ft_made": r.FTM,
            "ft_attempted": r.FTA,
            "plus_minus": r.PLUS_MINUS,
        }
        for r in df.itertuples()
    ]


def upsert_player_game_stats(conn, rows):
    sql = """
        INSERT INTO player_game_stats (game_id, player_id, team_id, minutes, points,
                                        rebounds, assists, steals, blocks, turnovers,
                                        fg_made, fg_attempted, fg3_made, fg3_attempted,
                                        ft_made, ft_attempted, plus_minus)
        VALUES (%(game_id)s, %(player_id)s, %(team_id)s, %(minutes)s, %(points)s,
                %(rebounds)s, %(assists)s, %(steals)s, %(blocks)s, %(turnovers)s,
                %(fg_made)s, %(fg_attempted)s, %(fg3_made)s, %(fg3_attempted)s,
                %(ft_made)s, %(ft_attempted)s, %(plus_minus)s)
        ON CONFLICT (game_id, player_id) DO UPDATE SET
            minutes = EXCLUDED.minutes,
            points = EXCLUDED.points,
            rebounds = EXCLUDED.rebounds,
            assists = EXCLUDED.assists,
            steals = EXCLUDED.steals,
            blocks = EXCLUDED.blocks,
            turnovers = EXCLUDED.turnovers,
            fg_made = EXCLUDED.fg_made,
            fg_attempted = EXCLUDED.fg_attempted,
            fg3_made = EXCLUDED.fg3_made,
            fg3_attempted = EXCLUDED.fg3_attempted,
            ft_made = EXCLUDED.ft_made,
            ft_attempted = EXCLUDED.ft_attempted,
            plus_minus = EXCLUDED.plus_minus
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

    box_scores = fetch_player_box_scores(args.season)
    upsert_players(conn, fetch_players(box_scores))
    upsert_player_game_stats(conn, fetch_player_game_stats(box_scores))

    conn.close()


if __name__ == "__main__":
    main()
