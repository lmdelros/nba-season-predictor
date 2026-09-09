# ROY model: same shortlist-and-rank approach as MVP/DPOY, but restricted to
# each season's rookies (ranked by points among just them) rather than the
# whole league — "top scorer league-wide" is the wrong pool for an award only
# rookies are eligible for. Rookie status is derived from
# ingestion/pull_award_data.py's --buffer-seasons: a player's rookie season
# is the earliest one they appear in our own data, which only works if
# enough seasons before --start-season were pulled to correctly seed who was
# already active.
import argparse

from models.award_model import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", required=True, help="e.g. 2010-11")
    parser.add_argument("--end-season", required=True, help="e.g. 2024-25")
    parser.add_argument("--test-seasons", type=int, default=3)
    args = parser.parse_args()

    run(
        award_type="roy", rank_by="points", model_version="roy_logreg_v1",
        start_season=args.start_season, end_season=args.end_season,
        test_seasons=args.test_seasons, rookies_only=True,
    )


if __name__ == "__main__":
    main()
