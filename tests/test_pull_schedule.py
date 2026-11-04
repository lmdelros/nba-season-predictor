from datetime import date

import pandas as pd

from ingestion.pull_schedule import insert_scheduled_games, scheduled_games
from tests.db_helpers import SEASON, insert_games


def _schedule(games):
    """games: (game_id, game_date "MM/DD/YYYY", status, home_id, away_id)."""
    return pd.DataFrame(
        [(gid, f"{day} 00:00:00", status, home, away) for gid, day, status, home, away in games],
        columns=["gameId", "gameDate", "gameStatus", "homeTeam_teamId", "awayTeam_teamId"],
    )


def test_keeps_only_unplayed_regular_season_games_with_known_teams():
    schedule = _schedule([
        ("0012600001", "10/03/2026", 3, 9001, 9002),  # preseason
        ("0022600001", "10/20/2026", 3, 9001, 9002),  # regular season, already final
        ("0022600002", "11/10/2026", 1, 9003, 9004),  # regular season, scheduled
        ("0022600003", "12/14/2026", 1, 0, 0),        # NBA Cup knockout, teams not set
        ("0062600001", "12/16/2026", 1, 9001, 9003),  # NBA Cup final, not a standings game
    ])

    assert scheduled_games(schedule, SEASON) == [{
        "game_id": 22600002, "season": SEASON, "game_date": date(2026, 11, 10),
        "home_team_id": 9003, "away_team_id": 9004,
    }]


class _NoCommit:
    """The test connection with commit() disabled, so the SQL runs for real but the db
    fixture can still roll it back."""

    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        pass


def _game(db, game_id):
    with db.cursor() as cur:
        cur.execute("SELECT game_date, status, home_score FROM games WHERE game_id = %s",
                    (game_id,))
        return cur.fetchone()


def test_scheduled_games_are_added_and_moved_when_rescheduled(db):
    row = {"game_id": 990101, "season": SEASON, "game_date": date(2099, 11, 1),
           "home_team_id": 9001, "away_team_id": 9002}

    insert_scheduled_games(_NoCommit(db), [row])
    assert _game(db, 990101) == (date(2099, 11, 1), "scheduled", None)

    insert_scheduled_games(_NoCommit(db), [{**row, "game_date": date(2099, 12, 5)}])
    assert _game(db, 990101) == (date(2099, 12, 5), "scheduled", None)


def test_a_final_game_is_never_changed(db):
    insert_games(db, [(990102, SEASON, date(2099, 11, 1), 9001, 9002, 110, 100)])

    insert_scheduled_games(_NoCommit(db), [{"game_id": 990102, "season": SEASON,
                                            "game_date": date(2099, 12, 5),
                                            "home_team_id": 9001, "away_team_id": 9002}])

    assert _game(db, 990102) == (date(2099, 11, 1), "final", 110)
