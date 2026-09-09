# MVP model: predicts each candidate player's probability of winning MVP
# that season. Restricted to a per-season top-N-by-points shortlist rather
# than every player in the league — with one winner out of 400+ players a
# season, an unrestricted model would just learn "predict not-MVP" and be
# uselessly "accurate". The real question this answers is a ranking one:
# among the season's realistic contenders, who's most MVP-like.
import argparse

from models.award_model import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-seasons", type=int, default=3)
    args = parser.parse_args()

    run(
        award_type="mvp", rank_by="points", model_version="mvp_logreg_v1",
        start_season=args.start_season, end_season=args.end_season,
        test_seasons=args.test_seasons,
    )


if __name__ == "__main__":
    main()
