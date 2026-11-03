import numpy as np
import pandas as pd

from evaluation import evaluate_award_models
from evaluation.evaluate_award_models import (
    SEASONS,
    choose,
    forward_chain_ranks,
    summarize,
    winner_rank,
)


def test_winner_rank_counts_candidates_scored_higher():
    scores = pd.Series([0.9, 0.2, 0.7, 0.4])

    assert winner_rank(scores, pd.Series([True, False, False, False])) == 1
    assert winner_rank(scores, pd.Series([False, False, False, True])) == 3
    # A winner who is not on the shortlist has no rank.
    assert winner_rank(scores, pd.Series([False, False, False, False])) is None


def test_summarize_counts_missing_winners_as_misses_without_a_rank():
    ranks = {"a": 1, "b": 3, "c": None}

    hits, seasons, mean_rank = summarize(ranks, ["a", "b", "c"])

    assert (hits, seasons, mean_rank) == (1, 3, 2.0)


def test_choose_gives_near_ties_to_the_simpler_candidate():
    results = [
        {"name": "simple", "val_rank": 1.55},
        {"name": "complex", "val_rank": 1.50},
        {"name": "worse", "val_rank": 2.00},
    ]

    # Within the 0.1 tolerance of the best, the earlier (simpler) candidate wins.
    assert choose(results)["name"] == "simple"
    assert choose([results[1], results[2]])["name"] == "complex"


def _pool(seed=0):
    """Ten candidates per season with one winner, whose features carry a real signal."""
    rng = np.random.default_rng(seed)
    rows = []
    for season in SEASONS:
        skill = rng.normal(size=10)
        winner = int(np.argmax(skill + rng.normal(scale=0.5, size=10)))
        for i in range(10):
            rows.append({"season": season, "skill": skill[i], "noise": rng.normal(),
                         "is_winner": i == winner})
    return pd.DataFrame(rows)


def test_each_season_is_predicted_from_earlier_seasons_only():
    pool = _pool()
    changed = pool.copy()
    later = changed["season"] >= "2020-21"
    changed.loc[later, "skill"] = -changed.loc[later, "skill"]

    original = forward_chain_ranks(pool, ["skill", "noise"], 1.0)
    rewritten = forward_chain_ranks(changed, ["skill", "noise"], 1.0)

    # Rewriting 2020-21 onward cannot change any earlier season's result.
    earlier = [s for s in original if s < "2020-21"]
    assert {s: original[s] for s in earlier} == {s: rewritten[s] for s in earlier}
    assert original != rewritten


def test_training_never_includes_the_season_being_predicted(monkeypatch):
    trained_on = {}

    def recording_fit(train, test, features, c):
        trained_on[test["season"].iloc[0]] = set(train["season"])
        return np.zeros(len(test))

    monkeypatch.setattr(evaluate_award_models, "fit_and_score", recording_fit)
    forward_chain_ranks(_pool(), ["skill"], 1.0)

    assert trained_on, "no seasons were predicted"
    for season, train_seasons in trained_on.items():
        assert max(train_seasons) < season, f"{season} trained on {max(train_seasons)}"
