import numpy as np
import pandas as pd
import pytest

from simulation.monte_carlo import run_simulations, save_simulation_results


def _league(seed=0):
    """Inputs for run_simulations(): 20 teams in two conferences, 2-8 wins already banked
    per team, 200 remaining games with random home-win probabilities, and a home-win
    probability for every possible playoff matchup."""
    rng = np.random.default_rng(seed)
    team_ids = list(range(1, 21))
    teams_df = pd.DataFrame({
        "team_id": team_ids, "conference": ["East"] * 10 + ["West"] * 10,
    })
    current_wins = {t: int(rng.integers(2, 9)) for t in team_ids}
    remaining = pd.DataFrame({
        "game_id": range(1, 201),
        "home_team_id": rng.choice(team_ids, 200),
        "away_team_id": rng.choice(team_ids, 200),
    })
    remaining = remaining[remaining["home_team_id"] != remaining["away_team_id"]]
    win_probs = dict(zip(remaining["game_id"], rng.uniform(0.2, 0.8, len(remaining))))
    pairwise = {(h, a): rng.uniform(0.3, 0.8) for h in team_ids for a in team_ids if h != a}
    return current_wins, remaining, win_probs, teams_df, pairwise


def test_same_seed_gives_identical_results():
    first, first_finals = run_simulations(*_league(), n_simulations=300, seed=42)
    second, second_finals = run_simulations(*_league(), n_simulations=300, seed=42)

    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(first_finals, second_finals)


def test_different_seeds_give_different_results():
    first, _ = run_simulations(*_league(), n_simulations=300, seed=42)
    second, _ = run_simulations(*_league(), n_simulations=300, seed=7)

    assert not first.equals(second)


def test_results_are_valid_probabilities_and_win_totals():
    current_wins, remaining, *rest = _league()
    results, _ = run_simulations(current_wins, remaining, *rest, n_simulations=300, seed=42)

    assert results["playoff_pct"].between(0, 1).all()
    # Exactly one champion per simulated season, and 16 playoff teams (8 per conference).
    # approx: summing 20 fractions like 14/300 picks up floating-point rounding.
    assert results["championship_pct"].sum() == pytest.approx(1.0)
    assert results["playoff_pct"].sum() == pytest.approx(16.0)
    # Every remaining game produces exactly one win.
    assert results["avg_wins"].sum() == pytest.approx(sum(current_wins.values()) + len(remaining))


def test_finals_matchups_agree_with_championship_odds():
    current_wins, remaining, win_probs, teams_df, pairwise = _league()
    results, finals = run_simulations(
        current_wins, remaining, win_probs, teams_df, pairwise, n_simulations=300, seed=42
    )

    # Every simulated season has exactly one Finals, and each pair is stored once.
    assert finals["meetings"].sum() == 300
    assert finals["matchup_pct"].sum() == pytest.approx(1.0)
    assert (finals["team_a_id"] < finals["team_b_id"]).all()
    assert finals["meetings"].is_monotonic_decreasing
    # A team's titles across all its Finals equal its championship odds.
    titles = {}
    for row in finals.itertuples():
        titles[row.team_a_id] = titles.get(row.team_a_id, 0) + row.team_a_wins
        titles[row.team_b_id] = titles.get(row.team_b_id, 0) + row.meetings - row.team_a_wins
    for row in results.itertuples():
        assert titles.get(row.team_id, 0) / 300 == pytest.approx(row.championship_pct)
    # Conference champions only: both teams in a Finals come from different conferences.
    conference = dict(zip(teams_df["team_id"], teams_df["conference"]))
    pairs = zip(finals["team_a_id"], finals["team_b_id"])
    assert all(conference[a] != conference[b] for a, b in pairs)


class _RecordingConnection:
    """Stands in for a database connection and records what would be written."""

    def __init__(self):
        self.rows = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        self.rows.extend(rows)

    def commit(self):
        pass


def test_saved_runs_record_their_cutoff_date():
    results, _ = run_simulations(*_league(), n_simulations=50, seed=42)
    conn = _RecordingConnection()

    save_simulation_results(conn, results, "2025-26", 50, "batch-1", cutoff_date="2026-02-01")

    assert len(conn.rows) == len(results)
    assert {row["cutoff_date"] for row in conn.rows} == {"2026-02-01"}
    assert {row["batch_id"] for row in conn.rows} == {"batch-1"}
