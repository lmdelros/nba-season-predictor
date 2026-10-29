import os

import psycopg2
import pytest

from models.train_win_probability import get_db_connection
from tests.db_helpers import TEAMS


@pytest.fixture
def db():
    """A database connection inside a transaction that is always rolled back, with the
    test teams already inserted. Skips without a reachable database unless REQUIRE_DB=1
    (set in CI), which turns a missing database into a failure."""
    try:
        conn = get_db_connection()
    except psycopg2.OperationalError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no database reachable: {exc}")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('team_game_form')")
            assert cur.fetchone()[0] is not None, "team_game_form missing: apply db/views.sql"
            cur.executemany(
                "INSERT INTO teams (team_id, full_name, abbreviation, conference, division) "
                "VALUES (%s, %s, %s, 'East', 'Test')",
                [(t, f"Test Team {t}", f"T{t}") for t in TEAMS],
            )
        yield conn
    finally:
        conn.rollback()
        conn.close()
