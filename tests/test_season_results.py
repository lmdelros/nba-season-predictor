import pandas as pd

from ingestion.pull_season_results import finals_from_playoff_log


def _log(games):
    """games: (game_id, date, winner, loser) -> one row per team per game, like NBA.com."""
    rows = []
    for game_id, date, winner, loser in games:
        rows.append({"GAME_ID": game_id, "GAME_DATE": date, "TEAM_ID": winner, "WL": "W"})
        rows.append({"GAME_ID": game_id, "GAME_DATE": date, "TEAM_ID": loser, "WL": "L"})
    return pd.DataFrame(rows)


EARLIER_ROUND = [  # team 1 beats team 3, team 2 beats team 4, in other series
    ("g1", "2023-05-01", 1, 3), ("g2", "2023-05-03", 2, 4),
]


def test_champion_is_the_team_that_won_four_finals_games():
    finals = [("f1", "2023-06-01", 1, 2), ("f2", "2023-06-04", 2, 1), ("f3", "2023-06-07", 1, 2),
              ("f4", "2023-06-09", 1, 2), ("f5", "2023-06-12", 1, 2)]

    assert finals_from_playoff_log(_log(EARLIER_ROUND + finals)) == (1, 2, 5)


def test_unfinished_finals_record_nothing():
    finals = [("f1", "2023-06-01", 1, 2), ("f2", "2023-06-04", 2, 1), ("f3", "2023-06-07", 1, 2)]

    assert finals_from_playoff_log(_log(EARLIER_ROUND + finals)) is None


def test_a_season_without_playoff_games_records_nothing():
    no_games = pd.DataFrame(columns=["GAME_ID", "GAME_DATE", "TEAM_ID", "WL"])

    assert finals_from_playoff_log(no_games) is None


def test_a_sweep_counts_four_games():
    finals = [(f"f{i}", f"2023-06-0{i}", 2, 1) for i in range(1, 5)]

    assert finals_from_playoff_log(_log(EARLIER_ROUND + finals)) == (2, 1, 4)
