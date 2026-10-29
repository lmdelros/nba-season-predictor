import numpy as np
import pandas as pd
import pytest

from simulation.monte_carlo import run_simulations


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
    first = run_simulations(*_league(), n_simulations=300, seed=42)
    second = run_simulations(*_league(), n_simulations=300, seed=42)

    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_give_different_results():
    first = run_simulations(*_league(), n_simulations=300, seed=42)
    second = run_simulations(*_league(), n_simulations=300, seed=7)

    assert not first.equals(second)


def test_results_are_valid_probabilities_and_win_totals():
    current_wins, remaining, *rest = _league()
    results = run_simulations(current_wins, remaining, *rest, n_simulations=300, seed=42)

    assert results["playoff_pct"].between(0, 1).all()
    # Exactly one champion per simulated season, and 16 playoff teams (8 per conference).
    # approx: summing 20 fractions like 14/300 picks up floating-point rounding.
    assert results["championship_pct"].sum() == pytest.approx(1.0)
    assert results["playoff_pct"].sum() == pytest.approx(16.0)
    # Every remaining game produces exactly one win.
    assert results["avg_wins"].sum() == pytest.approx(sum(current_wins.values()) + len(remaining))
