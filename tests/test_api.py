# Tests for the FastAPI endpoints, run against a real Postgres database. The API's
# pooled connection is swapped for the test's rolled-back transaction (see the db
# fixture in tests/conftest.py), so the endpoints see only the rows each test inserts
# plus whatever real data the database already holds.
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.db import get_db
from api.main import app
from tests.db_helpers import SEASON, insert_games

EARLIER = datetime(2099, 11, 1, tzinfo=timezone.utc)
LATER = datetime(2099, 11, 2, tzinfo=timezone.utc)


@pytest.fixture
def client(db):
    def use_test_connection():
        yield db

    app.dependency_overrides[get_db] = use_test_connection
    yield TestClient(app)
    app.dependency_overrides.clear()


def _insert_predictions(db, rows):
    """rows: (game_id, model_version, model_type, win_prob, margin, predicted_at)."""
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO game_predictions (game_id, model_version, model_type, "
            "predicted_home_win_prob, predicted_margin, predicted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )


def _insert_simulations(db, rows):
    """rows: (team_id, batch_id, run_at, avg_wins, playoff_pct, championship_pct)."""
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO season_simulations (season, team_id, batch_id, run_at, "
            "num_simulations, avg_wins, playoff_pct, championship_pct) "
            "VALUES (%s, %s, %s, %s, 1000, %s, %s, %s)",
            [(SEASON, *r) for r in rows],
        )


def _insert_finals(db, batch_id, rows):
    """rows: (team_a_id, team_b_id, meetings, team_a_wins), out of 1000 simulations."""
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO simulation_finals (season, batch_id, team_a_id, team_b_id, "
            "meetings, team_a_wins, matchup_pct) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(SEASON, batch_id, a, b, m, w, m / 1000) for a, b, m, w in rows],
        )


def test_health_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_seasons_are_listed_newest_first(db, client):
    insert_games(db, [
        (990001, "2098-99", date(2099, 3, 1), 9001, 9002, 100, 90),
        (990002, SEASON, date(2099, 11, 1), 9001, 9002, 100, 90),
    ])
    seasons = client.get("/seasons").json()

    assert seasons[0] == SEASON
    assert seasons.index(SEASON) < seasons.index("2098-99")


def test_teams_include_conference_and_division(client):
    teams = {t["team_id"]: t for t in client.get("/teams").json()}

    assert teams[9001] == {
        "team_id": 9001, "full_name": "Test Team 9001", "abbreviation": "T9001",
        "conference": "East", "division": "Test",
    }


def test_standings_count_home_and_away_results_and_skip_unplayed_games(db, client):
    insert_games(db, [
        (990101, SEASON, date(2099, 11, 1), 9001, 9002, 110, 100),   # 9001 wins at home
        (990102, SEASON, date(2099, 11, 2), 9003, 9001, 95, 101),    # 9001 wins away
        (990103, SEASON, date(2099, 11, 3), 9002, 9001, 108, 99),    # 9001 loses away
        (990104, SEASON, date(2099, 11, 4), 9001, 9003, None, None),  # not played yet
    ])
    standings = client.get("/standings", params={"season": SEASON}).json()
    by_team = {row["team_id"]: row for row in standings}

    assert standings[0]["team_id"] == 9001
    assert (by_team[9001]["wins"], by_team[9001]["losses"]) == (2, 1)
    assert by_team[9001]["games_played"] == 3
    assert by_team[9001]["win_pct"] == 0.667
    assert (by_team[9002]["wins"], by_team[9002]["losses"]) == (1, 1)
    assert (by_team[9003]["wins"], by_team[9003]["losses"]) == (0, 1)


@pytest.mark.parametrize(
    "path", ["/standings", "/predictions", "/simulations", "/simulations/finals"]
)
@pytest.mark.parametrize("params", [{}, {"season": "2099"}, {"season": "99-00"}])
def test_season_parameter_is_required_and_validated(client, path, params):
    assert client.get(path, params=params).status_code == 422


def test_predictions_default_to_the_latest_model_of_each_type(db, client):
    insert_games(db, [(990201, SEASON, date(2099, 11, 1), 9001, 9002, 110, 100)])
    _insert_predictions(db, [
        (990201, "logreg_v1", "win_probability", 0.55, None, EARLIER),
        (990201, "logreg_v2", "win_probability", 0.65, None, LATER),
        (990201, "linreg_margin_v1", "margin", None, 3.5, EARLIER),
    ])
    [prediction] = client.get("/predictions", params={"season": SEASON}).json()

    assert prediction["home_team"] == "T9001"
    assert prediction["away_team"] == "T9002"
    assert prediction["win_prob_model_version"] == "logreg_v2"
    assert prediction["predicted_home_win_prob"] == 0.65
    assert prediction["predicted_margin"] == 3.5


def test_predictions_can_be_filtered_by_model_version_and_game(db, client):
    insert_games(db, [
        (990301, SEASON, date(2099, 11, 1), 9001, 9002, 110, 100),
        (990302, SEASON, date(2099, 11, 2), 9003, 9004, 100, 110),
    ])
    _insert_predictions(db, [
        (990301, "logreg_v1", "win_probability", 0.55, None, EARLIER),
        (990301, "logreg_v2", "win_probability", 0.65, None, LATER),
        (990302, "logreg_v1", "win_probability", 0.40, None, EARLIER),
    ])
    response = client.get(
        "/predictions", params={"season": SEASON, "model_version": "logreg_v1"}
    ).json()
    assert {p["game_id"]: p["predicted_home_win_prob"] for p in response} == {
        990301: 0.55, 990302: 0.40,
    }

    response = client.get("/predictions", params={"season": SEASON, "game_id": 990302}).json()
    assert [p["game_id"] for p in response] == [990302]


def test_simulations_default_to_the_latest_batch(db, client):
    _insert_simulations(db, [
        (9001, "old", EARLIER, 30.0, 0.20, 0.01),
        (9002, "old", EARLIER, 50.0, 0.90, 0.10),
        (9001, "new", LATER, 55.0, 0.95, 0.30),
        (9002, "new", LATER, 41.0, 0.60, None),
    ])
    latest = client.get("/simulations", params={"season": SEASON}).json()

    assert {row["batch_id"] for row in latest} == {"new"}
    # Ordered by playoff odds, best first.
    assert [row["team_id"] for row in latest] == [9001, 9002]
    assert latest[1]["championship_pct"] is None

    older = client.get("/simulations", params={"season": SEASON, "batch_id": "old"}).json()
    assert [(row["team_id"], row["avg_wins"]) for row in older] == [(9002, 50.0), (9001, 30.0)]


def test_simulations_for_a_season_without_runs_are_empty(client):
    assert client.get("/simulations", params={"season": SEASON}).json() == []


def test_finals_matchups_come_from_the_latest_batch_most_likely_first(db, client):
    _insert_simulations(db, [
        (9001, "old", EARLIER, 50.0, 0.9, 0.5),
        (9001, "new", LATER, 55.0, 0.95, 0.3),
    ])
    _insert_finals(db, "old", [(9001, 9004, 900, 100)])
    _insert_finals(db, "new", [(9001, 9003, 120, 90), (9001, 9002, 300, 210)])
    matchups = client.get("/simulations/finals", params={"season": SEASON}).json()

    assert [(m["team_a_id"], m["team_b_id"]) for m in matchups] == [(9001, 9002), (9001, 9003)]
    top = matchups[0]
    assert top["team_a_abbreviation"] == "T9001" and top["team_b_name"] == "Test Team 9002"
    assert (top["meetings"], top["num_simulations"]) == (300, 1000)
    assert top["matchup_pct"] == 0.3
    assert top["team_a_win_pct"] == 0.7

    limited = client.get("/simulations/finals", params={"season": SEASON, "limit": 1}).json()
    assert len(limited) == 1


def test_finals_are_empty_when_the_latest_run_has_no_matchups(db, client):
    _insert_simulations(db, [
        (9001, "with-finals", EARLIER, 50.0, 0.9, 0.5),
        (9001, "without-finals", LATER, 55.0, 0.95, 0.3),
    ])
    _insert_finals(db, "with-finals", [(9001, 9002, 500, 250)])

    # The page shows the newest run's odds, so it must not mix in an older run's Finals.
    assert client.get("/simulations/finals", params={"season": SEASON}).json() == []


def test_simulation_endpoints_report_the_projection_date(db, client):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO season_simulations (season, team_id, batch_id, run_at, num_simulations, "
            "avg_wins, playoff_pct, championship_pct, cutoff_date) "
            "VALUES (%s, 9001, 'dated', %s, 1000, 50, 0.9, 0.5, '2099-02-01')",
            (SEASON, LATER),
        )
    _insert_finals(db, "dated", [(9001, 9002, 400, 300)])

    [team] = client.get("/simulations", params={"season": SEASON}).json()
    [matchup] = client.get("/simulations/finals", params={"season": SEASON}).json()

    assert team["cutoff_date"] == "2099-02-01"
    assert matchup["cutoff_date"] == "2099-02-01"


def test_runs_saved_before_dates_were_recorded_have_no_date(db, client):
    _insert_simulations(db, [(9001, "undated", LATER, 50.0, 0.9, 0.5)])

    [team] = client.get("/simulations", params={"season": SEASON}).json()

    assert team["cutoff_date"] is None


def _insert_award_players(db, players):
    """players: (player_id, team_id, season points); made-up IDs, with season totals over
    70 games for SEASON, as player_season_stats stores them."""
    with db.cursor() as cur:
        cur.executemany("INSERT INTO players (player_id, full_name) VALUES (%s, %s)",
                        [(p, f"Test Player {p}") for p, _, _ in players])
        cur.executemany(
            "INSERT INTO player_season_stats (player_id, season, team_id, games_played, "
            "points, rebounds, assists, steals, blocks) "
            "VALUES (%s, %s, %s, 70, %s, 560, 420, 105, 35)",
            [(p, SEASON, team, pts) for p, team, pts in players],
        )


def _insert_award_predictions(db, rows):
    """rows: (award_type, player_id, model_version, predicted_prob)."""
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO award_predictions (season, award_type, player_id, model_version, "
            "predicted_prob) VALUES (%s, %s, %s, %s, %s)",
            [(SEASON, *r) for r in rows],
        )


def _insert_award_winner(db, award_type, player_id):
    with db.cursor() as cur:
        cur.execute("INSERT INTO player_awards (player_id, season, award_type) "
                    "VALUES (%s, %s, %s)", (player_id, SEASON, award_type))


def test_awards_show_the_winner_and_the_top_three_picks_in_order(db, client):
    _insert_award_players(db, [(99901, 9001, 2100), (99902, 9002, 1960),
                               (99903, 9003, 1750), (99904, 9004, 1400)])
    _insert_award_predictions(db, [
        ("mvp", 99904, "mvp_forward_v1", 0.10),
        ("mvp", 99902, "mvp_forward_v1", 0.90),
        ("mvp", 99901, "mvp_forward_v1", 0.60),
        ("mvp", 99903, "mvp_forward_v1", 0.40),
    ])
    _insert_award_winner(db, "mvp", 99901)

    [mvp] = client.get("/awards", params={"season": SEASON}).json()

    assert (mvp["award_type"], mvp["award_name"]) == ("mvp", "Most Valuable Player")
    assert mvp["low_confidence"] is False
    assert [p["player_id"] for p in mvp["picks"]] == [99902, 99901, 99903]
    assert [p["rank"] for p in mvp["picks"]] == [1, 2, 3]
    assert [p["won"] for p in mvp["picks"]] == [False, True, False]
    winner = mvp["winner"]
    assert (winner["player_id"], winner["team_id"], winner["team_abbreviation"]) == (
        99901, 9001, "T9001")
    # Season totals over 70 games, shown per game.
    assert (winner["points_per_game"], winner["rebounds_per_game"],
            winner["assists_per_game"], winner["steals_per_game"],
            winner["blocks_per_game"]) == (30.0, 8.0, 6.0, 1.5, 0.5)


def test_awards_ignore_picks_from_other_model_versions(db, client):
    _insert_award_players(db, [(99901, 9001, 2100), (99902, 9002, 1960)])
    _insert_award_predictions(db, [
        ("mvp", 99901, "mvp_forward_v1", 0.30),
        # Saved by a training script whose model saw this season: never shown.
        ("mvp", 99902, "mvp_logreg_v2", 0.99),
    ])

    [mvp] = client.get("/awards", params={"season": SEASON}).json()

    assert [p["player_id"] for p in mvp["picks"]] == [99901]


def test_awards_not_yet_given_have_no_winner_and_unknown_results(db, client):
    _insert_award_players(db, [(99901, 9001, 840)])
    _insert_award_predictions(db, [("mip", 99901, "mip_forward_v1", 0.50)])

    awards = client.get("/awards", params={"season": SEASON}).json()

    # Only awards with a winner or picks are listed; MIP is flagged as unreliable.
    [mip] = awards
    assert mip["award_type"] == "mip"
    assert mip["low_confidence"] is True
    assert mip["winner"] is None
    assert mip["picks"][0]["won"] is None


def test_awards_reject_a_malformed_season(client):
    assert client.get("/awards", params={"season": "2099"}).status_code == 422
