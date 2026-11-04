import importlib.util
from datetime import date

from scripts.refresh_season import download_steps, simulation_cutoff
from tests.db_helpers import SEASON, insert_games


def test_every_step_runs_a_module_that_exists():
    for _, (module, *_args) in download_steps(SEASON):
        assert importlib.util.find_spec(module) is not None, module


def test_games_are_downloaded_before_the_schedule_and_features():
    modules = [module for _, (module, *_args) in download_steps(SEASON)]

    assert modules == ["ingestion.pull_nba_data", "ingestion.pull_schedule",
                       "features.build_features"]


def test_cutoff_is_the_day_after_the_latest_final_game(db):
    insert_games(db, [
        (990601, SEASON, date(2099, 11, 1), 9001, 9002, 110, 100),
        (990602, SEASON, date(2099, 11, 3), 9003, 9004, 99, 101),
        (990603, SEASON, date(2099, 11, 5), 9001, 9003, None, None),   # scheduled
    ])

    assert simulation_cutoff(db, SEASON) == (date(2099, 11, 4), [])


def test_unplayed_games_before_the_cutoff_are_reported(db):
    insert_games(db, [
        (990611, SEASON, date(2099, 11, 1), 9001, 9002, None, None),   # postponed
        (990612, SEASON, date(2099, 11, 3), 9003, 9004, 99, 101),
    ])

    assert simulation_cutoff(db, SEASON) == (date(2099, 11, 4), [(990611, date(2099, 11, 1))])


def test_a_season_without_final_games_has_no_cutoff(db):
    insert_games(db, [(990621, SEASON, date(2099, 11, 1), 9001, 9002, None, None)])

    assert simulation_cutoff(db, SEASON) == (None, [])
