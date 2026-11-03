import numpy as np
import pandas as pd

from models import award_model
from models.award_model import forward_chain_scores

SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2010, 2020)]


def _pool(seed=0):
    """Ten candidates per season with one winner, whose 'skill' feature carries a signal."""
    rng = np.random.default_rng(seed)
    rows = []
    for season in SEASONS:
        skill = rng.normal(size=10)
        winner = int(np.argmax(skill))
        rows += [{"season": season, "player_id": i, "skill": skill[i], "is_winner": i == winner}
                 for i in range(10)]
    return pd.DataFrame(rows)


def test_scores_every_candidate_of_each_predicted_season():
    scored = forward_chain_scores(_pool(), ["skill"], 1.0, "2015-16")

    assert sorted(scored["season"].unique()) == SEASONS[5:]
    assert len(scored) == 10 * 5
    assert scored["predicted_prob"].between(0, 1).all()


def test_no_season_is_scored_by_a_model_trained_on_it(monkeypatch):
    trained_on = []
    real_train = award_model.train_model

    def recording_train(train_df, feature_columns, c):
        trained_on.append(set(train_df["season"]))
        return real_train(train_df, feature_columns=feature_columns, c=c)

    monkeypatch.setattr(award_model, "train_model", recording_train)
    scored = forward_chain_scores(_pool(), ["skill"], 1.0, "2015-16")

    predicted = sorted(scored["season"].unique())
    assert len(trained_on) == len(predicted)
    for season, train_seasons in zip(predicted, trained_on):
        assert max(train_seasons) < season
