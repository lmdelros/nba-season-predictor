# Tests for the SQL views in db/views.sql, run against a real Postgres database.
# Every test runs inside a transaction that is rolled back, with made-up team IDs and
# seasons, so it never changes real data. Without a reachable database these tests
# skip, unless REQUIRE_DB=1 (set in CI); see the db fixture in tests/conftest.py.
from datetime import date, timedelta

from tests.db_helpers import SEASON, TEAMS, insert_games


def _margins(conn, team_id=None):
    """{(game_id, team_id): season_avg_margin} for the test teams' rows of the view."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT game_id, team_id, season_avg_margin FROM team_game_form "
            "WHERE team_id = ANY(%s)",
            ([team_id] if team_id else TEAMS,),
        )
        return {(g, t): m for g, t, m in cur.fetchall()}


def test_margin_matches_hand_computed_values(db):
    day = date(2099, 10, 20)
    insert_games(db, [
        (990001, SEASON, day, 9001, 9002, 110, 100),                       # 9001: +10
        (990002, SEASON, day + timedelta(1), 9002, 9001, 104, 100),        # 9001: -4
        (990003, SEASON, day + timedelta(2), 9001, 9002, 106, 100),        # 9001: +6
        (990004, SEASON, day + timedelta(3), 9001, 9002, 90, 100),         # 9001: -10
        (990005, SEASON, day + timedelta(4), 9001, 9002, 100, 99),
    ])
    margins = _margins(db)

    team1 = [margins[(g, 9001)] for g in range(990001, 990006)]
    assert team1 == [None, 10.0, 3.0, 4.0, 0.5]
    # The away side is seen from its own perspective: 9002 lost game 1 by 10.
    assert margins[(990002, 9002)] == -10.0


def test_margin_ignores_results_on_or_after_game_date(db):
    day = date(2099, 10, 20)
    games, game_id = [], 990100
    for d in range(10):
        for home, away in [(9001, 9002), (9003, 9004)] if d % 2 else [(9001, 9003), (9002, 9004)]:
            games.append((game_id, SEASON, day + timedelta(d), home, away,
                          100 + (game_id * 7) % 25, 100 + (game_id * 11) % 25))
            game_id += 1
    insert_games(db, games)
    cutoff = day + timedelta(5)
    known = {g[0] for g in games if g[2] <= cutoff}

    before = _margins(db)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE games SET home_score = away_score + 40 "
            "WHERE season = %s AND game_date >= %s",
            (SEASON, cutoff),
        )
    after = _margins(db)

    # Games ON the cutoff date are included: their own result changed too.
    assert {k: v for k, v in before.items() if k[0] in known} == \
        {k: v for k, v in after.items() if k[0] in known}
    assert before != after


def test_scheduled_games_do_not_count(db):
    day = date(2099, 10, 20)
    insert_games(db, [
        (990201, SEASON, day, 9001, 9002, 110, 100),                       # 9001: +10
        (990202, SEASON, day + timedelta(1), 9001, 9002, None, None),      # not played
        (990203, SEASON, day + timedelta(2), 9001, 9002, 96, 100),         # 9001: -4
        (990204, SEASON, day + timedelta(3), 9001, 9002, None, None),
    ])
    margins = _margins(db, 9001)

    assert margins[(990203, 9001)] == 10.0
    assert margins[(990204, 9001)] == 3.0


def test_margin_resets_each_season(db):
    insert_games(db, [
        (990301, "2098-99", date(2099, 4, 10), 9001, 9002, 120, 100),
        (990302, SEASON, date(2099, 10, 20), 9001, 9002, 100, 95),
        (990303, SEASON, date(2099, 10, 22), 9001, 9002, 100, 95),
    ])
    margins = _margins(db, 9001)

    assert margins[(990302, 9001)] is None
    assert margins[(990303, 9001)] == 5.0
