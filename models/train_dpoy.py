# DPOY model: same approach as train_mvp.py, restricted to a per-season
# top-N-by-stocks (steals+blocks) shortlist. That's an imperfect defensive
# proxy — it can miss a positional/versatility-driven winner whose case
# wasn't built on raw steal/block counts (e.g. Draymond Green's 2016-17
# case), worth knowing as a real limitation rather than a guarantee this
# always finds the right candidates.
import argparse

from models.award_model import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-seasons", type=int, default=3)
    args = parser.parse_args()

    run(
        award_type="dpoy", rank_by="stocks", model_version="dpoy_logreg_v1",
        start_season=args.start_season, end_season=args.end_season,
        test_seasons=args.test_seasons,
    )


if __name__ == "__main__":
    main()
