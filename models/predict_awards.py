# Generates each award's candidate rankings for every season from 2015-16 on, each from a
# model trained only on earlier seasons, using the settings the training scripts use.
# Saved under <award>_forward_v1 for the API's awards section. Run from the repo root:
#   python -m models.predict_awards
import argparse

from models import train_dpoy, train_mip, train_mvp, train_roy
from models.award_model import (
    FEATURE_COLUMNS,
    forward_chain_scores,
    get_db_connection,
    load_candidate_pool,
    save_predictions,
)
from models.train_mip import load_mip_candidate_pool

MODEL_VERSION = "{award}_forward_v1"

# Per award: how its candidate pool is loaded, its features, and its regularization.
AWARDS = {
    "mvp": (lambda conn, seasons: load_candidate_pool(conn, seasons, "mvp", "points"),
            train_mvp.FEATURE_COLUMNS, train_mvp.C),
    "dpoy": (lambda conn, seasons: load_candidate_pool(conn, seasons, "dpoy", "stocks"),
             FEATURE_COLUMNS, train_dpoy.C),
    "roy": (lambda conn, seasons: load_candidate_pool(conn, seasons, "roy", "points",
                                                      rookies_only=True),
            FEATURE_COLUMNS, train_roy.C),
    "mip": (lambda conn, seasons: load_mip_candidate_pool(conn, seasons, "mip"),
            train_mip.FEATURE_COLUMNS, train_mip.C),
}


def season_range(start, end):
    return [f"{y}-{str(y + 1)[2:]}" for y in range(int(start[:4]), int(end[:4]) + 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", default="2010-11", help="first season to learn from")
    parser.add_argument("--first-predicted", default="2015-16")
    parser.add_argument("--end-season", default="2025-26")
    args = parser.parse_args()
    seasons = season_range(args.start_season, args.end_season)

    conn = get_db_connection()
    for award, (load, features, c) in AWARDS.items():
        scored = forward_chain_scores(load(conn, seasons), features, c, args.first_predicted)
        save_predictions(conn, scored, award, MODEL_VERSION.format(award=award))
        top = scored.loc[scored.groupby("season")["predicted_prob"].idxmax()]
        hits = int(top["is_winner"].sum())
        print(f"{award.upper()}: top pick won {hits} of {len(top)} seasons "
              f"({top['season'].min()} to {top['season'].max()})")
    conn.close()


if __name__ == "__main__":
    main()
