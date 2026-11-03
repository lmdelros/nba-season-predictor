# Evaluates the award models (MVP, DPOY, ROY, MIP) season by season. Each test season is
# predicted by a model trained only on earlier seasons ("forward chaining"), which gives
# ten test seasons per award instead of the three in models/award_model.py. Candidate
# settings and the selection rule are fixed below, before any results are seen.
# Run from the repo root:
#   python -m evaluation.evaluate_award_models --output docs/award_models.md
import argparse
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from models.award_model import FEATURE_COLUMNS, get_db_connection, load_candidate_pool
from models.train_mip import FEATURE_COLUMNS as MIP_FEATURE_COLUMNS
from models.train_mip import load_mip_candidate_pool

SEASONS = [f"{year}-{str(year + 1)[2:]}" for year in range(2010, 2025)]
FIRST_TEST_SEASON = "2015-16"     # every test season has at least five earlier seasons
FINAL_TEST_SEASONS = ["2022-23", "2023-24", "2024-25"]
# Candidates are chosen on these earlier seasons, then reported once on the final three.
VALIDATION_SEASONS = [s for s in SEASONS if FIRST_TEST_SEASON <= s < FINAL_TEST_SEASONS[0]]
# Mean-rank differences smaller than this count as a tie, won by the simpler candidate.
TIE_TOLERANCE = 0.1

# Per award: how its shortlist is built, the stat the shortlist is ranked by (the
# baseline's pick is the shortlist's top player), and a compact feature set chosen from
# what the award is about.
AWARDS = {
    "mvp": {
        "load": lambda conn: load_candidate_pool(conn, SEASONS, "mvp", "points"),
        "baseline": "points_per_game",
        "features": FEATURE_COLUMNS,
        "compact": ["points_per_game", "rebounds_per_game", "assists_per_game",
                    "plus_minus_per_game", "team_win_pct"],
    },
    "dpoy": {
        "load": lambda conn: load_candidate_pool(conn, SEASONS, "dpoy", "stocks"),
        "baseline": "stocks_per_game",
        "features": FEATURE_COLUMNS,
        "compact": ["steals_per_game", "blocks_per_game", "rebounds_per_game",
                    "plus_minus_per_game", "team_win_pct"],
    },
    "roy": {
        "load": lambda conn: load_candidate_pool(conn, SEASONS, "roy", "points",
                                                 rookies_only=True),
        "baseline": "points_per_game",
        "features": FEATURE_COLUMNS,
        "compact": ["points_per_game", "rebounds_per_game", "assists_per_game",
                    "plus_minus_per_game"],
    },
    "mip": {
        "load": lambda conn: load_mip_candidate_pool(conn, SEASONS, "mip"),
        "baseline": "ppg_delta",
        "features": MIP_FEATURE_COLUMNS,
        "compact": ["points_per_game", "ppg_delta", "team_win_pct_delta"],
    },
}

# (name, which feature set, regularization strength C). Smaller C keeps the model
# simpler. Listed from simplest to most complex, which is the tie-break order.
CANDIDATES = [
    ("Compact features, C=0.1", "compact", 0.1),
    ("All features, C=0.01", "features", 0.01),
    ("All features, C=0.1", "features", 0.1),
    ("Compact features, C=1.0", "compact", 1.0),
    ("All features, C=1.0 (current)", "features", 1.0),
]


def winner_rank(scores, is_winner):
    """1-based rank of the real winner among the season's candidates by score, or None
    if the winner is not on the shortlist."""
    if not is_winner.any():
        return None
    winner_score = scores[is_winner.to_numpy()].max()
    return int((scores > winner_score).sum()) + 1


def fit_and_score(train, test, features, c):
    """Trains the award model's logistic regression on train and returns test scores."""
    scaler = StandardScaler()
    model = LogisticRegression(max_iter=1000, class_weight="balanced", C=c)
    model.fit(scaler.fit_transform(train[features].astype(float)), train["is_winner"])
    return model.predict_proba(scaler.transform(test[features].astype(float)))[:, 1]


def forward_chain_ranks(pool, features, c):
    """{season: winner rank} for each test season, training on earlier seasons only."""
    ranks = {}
    for season in [s for s in SEASONS if s >= FIRST_TEST_SEASON]:
        train, test = pool[pool["season"] < season], pool[pool["season"] == season]
        scores = fit_and_score(train, test, features, c)
        ranks[season] = winner_rank(pd.Series(scores), test["is_winner"])
    return ranks


def baseline_ranks(pool, column):
    """{season: winner rank} when candidates are ranked by the shortlist stat alone."""
    return {
        season: winner_rank(group[column].reset_index(drop=True), group["is_winner"])
        for season, group in pool.groupby("season") if season >= FIRST_TEST_SEASON
    }


def summarize(ranks, seasons):
    """Top-pick hits, seasons, and mean winner rank over seasons whose winner is on the
    shortlist (seasons without one count as misses but have no rank)."""
    covered = [ranks[s] for s in seasons if ranks[s] is not None]
    hits = sum(r == 1 for r in covered)
    mean_rank = sum(covered) / len(covered) if covered else float("nan")
    return hits, len(seasons), mean_rank


def choose(results):
    """The candidate with the lowest mean validation rank; within TIE_TOLERANCE of the
    best, the first (simplest) in CANDIDATES wins."""
    best = min(r["val_rank"] for r in results)
    return next(r for r in results if r["val_rank"] <= best + TIE_TOLERANCE)


def evaluate_award(pool, config):
    pool = pool.copy()
    if "steals_per_game" in pool:
        pool["stocks_per_game"] = pool["steals_per_game"] + pool["blocks_per_game"]
    results = []
    for name, feature_key, c in CANDIDATES:
        ranks = forward_chain_ranks(pool, config[feature_key], c)
        results.append({
            "name": name, "ranks": ranks,
            "val_rank": summarize(ranks, VALIDATION_SEASONS)[2],
        })
    baseline = baseline_ranks(pool, config["baseline"])
    return results, choose(results), baseline


def to_markdown(award, pool, results, chosen, baseline):
    test_seasons = [s for s in SEASONS if s >= FIRST_TEST_SEASON]
    covered = sum(baseline[s] is not None for s in test_seasons)
    lines = [
        f"### {award.upper()}",
        "",
        f"Real winner on the 20-player shortlist in {covered} of {len(test_seasons)} test "
        "seasons; a season whose winner is missing counts as a miss for every method.",
        "",
        "| Method | Validation top pick | Validation mean winner rank "
        "| Final test top pick | Final test mean winner rank |",
        "|---|---|---|---|---|",
    ]
    rows = [{"name": "Baseline: shortlist stat alone", "ranks": baseline}] + results
    for row in rows:
        vh, vn, vr = summarize(row["ranks"], VALIDATION_SEASONS)
        th, tn, tr = summarize(row["ranks"], FINAL_TEST_SEASONS)
        label = row["name"] + (" **(chosen)**" if row is chosen else "")
        lines.append(f"| {label} | {vh} of {vn} | {vr:.2f} | {th} of {tn} | {tr:.2f} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="optional Markdown file to write the results to")
    args = parser.parse_args()

    conn = get_db_connection()
    sections = [
        "## Award models: forward-chained evaluation",
        "",
        "Generated by `python -m evaluation.evaluate_award_models --output "
        "docs/award_models.md`. Each season from "
        f"{FIRST_TEST_SEASON} on is predicted by a model trained only on earlier seasons. "
        f"Candidates are chosen by mean winner rank on {VALIDATION_SEASONS[0]} to "
        f"{VALIDATION_SEASONS[-1]} (ties within {TIE_TOLERANCE} go to the simpler "
        f"candidate) and reported once on {FINAL_TEST_SEASONS[0]} to {FINAL_TEST_SEASONS[-1]}. "
        "Winner rank is where the real winner placed among the season's candidates "
        "(1 is best).",
    ]
    for award, config in AWARDS.items():
        pool = config["load"](conn)
        results, chosen, baseline = evaluate_award(pool, config)
        sections += ["", to_markdown(award, pool, results, chosen, baseline)]
    conn.close()

    report = "\n".join(sections)
    print(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
