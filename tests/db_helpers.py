# Shared constants and helpers for tests that run against a real Postgres database
# (see the db fixture in tests/conftest.py). The made-up team IDs and season can never
# collide with real NBA data.
TEAMS = [9001, 9002, 9003, 9004]
SEASON = "2099-00"


def insert_games(conn, games):
    """games: (game_id, season, game_date, home_id, away_id, home_score, away_score);
    a game with NULL scores is inserted as scheduled rather than final."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO games (game_id, season, season_type, game_date, home_team_id, "
            "away_team_id, home_score, away_score, status) "
            "VALUES (%s, %s, 'regular', %s, %s, %s, %s, %s, "
            "CASE WHEN %s IS NULL THEN 'scheduled' ELSE 'final' END)",
            [(*g, g[5]) for g in games],
        )
