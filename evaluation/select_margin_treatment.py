# Tests whether early-season point margins, which rest on only a few games, make the
# model under-trust margin later in the season. Each candidate changes only how season
# margin enters the model, then is trained and scored the way the simulation predicts
# games after February 1. Candidates and the rule are fixed below; the final season is
# reported but not used to choose. Run from the repo root:
#   python -m evaluation.select_margin_treatment --output docs/margin_treatment.md
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

from evaluation.score_title_odds import calibration_slope
from evaluation.select_sharpness import cutoff_for
from models.train_win_probability import (
    B2B_COLUMNS,
    MARGIN_COLUMNS,
    REST_COLUMNS,
    apply_imputer,
    fit_imputer,
    load_training_data,
)
from simulation.monte_carlo import (
    cutoff_snapshot,
    freeze_remaining_features,
    get_db_connection,
    head_to_head_before,
    load_earlier_seasons,
    load_team_features,
)

# The win model's features at the time of the experiment, with raw margins; the
# treatments below change how those margins enter.
FEATURES = MARGIN_COLUMNS + REST_COLUMNS + B2B_COLUMNS
VALIDATION_SEASONS = ["2022-23", "2023-24", "2024-25"]
TEST_SEASON = "2025-26"
MARGINS = {"home": "home_season_avg_margin", "away": "away_season_avg_margin"}
# Log-loss differences smaller than this count as a tie, won by the candidate whose
# calibration slope is closest to 1.0.
TIE_TOLERANCE = 0.002


def shrink(strength):
    """Treatment: scale each margin by games / (games + strength), pulling margins based on
    few games toward 0, the league average."""
    def apply(df, train):
        df = df.copy()
        for side, col in MARGINS.items():
            n = df[f"{side}_games_played"]
            df[col] = df[col] * n / (n + strength)
        return df, train
    return apply


def drop_early_games(minimum):
    """Treatment: train only on games where both teams had already played `minimum`."""
    def apply(df, train):
        if train:
            df = df[(df["home_games_played"] >= minimum) & (df["away_games_played"] >= minimum)]
        return df, train
    return apply


CANDIDATES = {
    "A: current model": lambda df, train: (df, train),
    "B: shrunken margin, strength 10": shrink(10),
    "C: shrunken margin, strength 20": shrink(20),
    "D: train only after 20 games each": drop_early_games(20),
}


def add_games_played(games):
    """Adds home_games_played and away_games_played: each team's games earlier in the
    season, counted from the games table rows of that season."""
    long = pd.concat([
        games[["game_id", "game_date", "home_team_id"]].rename(columns={"home_team_id": "team_id"}),
        games[["game_id", "game_date", "away_team_id"]].rename(columns={"away_team_id": "team_id"}),
    ]).sort_values(["team_id", "game_date", "game_id"])
    long["games_played"] = long.groupby("team_id").cumcount()
    played = long.set_index(["game_id", "team_id"])["games_played"]
    games = games.copy()
    for side in ("home", "away"):
        keys = list(zip(games["game_id"], games[f"{side}_team_id"]))
        games[f"{side}_games_played"] = played.loc[keys].to_numpy()
    return games


def freeze_games_played(remaining, played_before_cutoff):
    """Each remaining game gets the number of games its teams had played by the cutoff,
    matching how the simulation freezes every other results-based feature."""
    remaining = remaining.copy()
    for side in ("home", "away"):
        remaining[f"{side}_games_played"] = (
            remaining[f"{side}_team_id"].map(played_before_cutoff).to_numpy()
        )
    return remaining


def predict(season_games, team_features, cutoff, history, treatment):
    """Home-win probabilities for games on or after the cutoff, trained the way
    simulation.monte_carlo.predict_remaining() trains, with the treatment applied."""
    cutoff = pd.Timestamp(cutoff)
    train = season_games[season_games["game_date"] < cutoff]
    played = pd.concat([train["home_team_id"], train["away_team_id"]]).value_counts()
    remaining = freeze_remaining_features(
        season_games[season_games["game_date"] >= cutoff],
        cutoff_snapshot(team_features, cutoff), head_to_head_before(train),
    )
    remaining = freeze_games_played(remaining, played)
    train = pd.concat([history, train], ignore_index=True)

    fills = fit_imputer(train)
    train, remaining = apply_imputer(train, fills), apply_imputer(remaining, fills)
    train, _ = treatment(train, True)
    remaining, _ = treatment(remaining, False)

    scaler = StandardScaler()
    model = LogisticRegression(max_iter=1000)
    model.fit(scaler.fit_transform(train[FEATURES].astype(float)), train["home_win"])
    probs = model.predict_proba(scaler.transform(remaining[FEATURES].astype(float)))[:, 1]
    return remaining.assign(prob=probs)


def expected_vs_actual_rest(scored):
    """Per team: expected wins after the cutoff (sum of its game probabilities) and actual."""
    home = scored.assign(team=scored["home_team_id"], p=scored["prob"], won=scored["home_win"])
    away = scored.assign(team=scored["away_team_id"], p=1 - scored["prob"],
                         won=1 - scored["home_win"])
    both = pd.concat([home, away]).groupby("team")[["p", "won"]].sum()
    return both["p"].to_numpy(), both["won"].to_numpy()


def evaluate(conn, seasons):
    """{candidate: (log loss, calibration slope)} pooled over the given seasons."""
    data = {}
    for season in seasons:
        earlier = load_earlier_seasons(conn, season)
        history = pd.concat([add_games_played(load_training_data(conn, s)) for s in earlier],
                            ignore_index=True)
        data[season] = (add_games_played(load_training_data(conn, season)),
                        load_team_features(conn, season), cutoff_for(season), history)
    results = {}
    for name, treatment in CANDIDATES.items():
        scored = [predict(*data[s], treatment) for s in seasons]
        outcomes = np.concatenate([s["home_win"].to_numpy() for s in scored])
        probs = np.concatenate([s["prob"].to_numpy() for s in scored])
        expected, actual = zip(*[expected_vs_actual_rest(s) for s in scored])
        results[name] = (log_loss(outcomes, probs, labels=[0, 1]),
                         calibration_slope(np.concatenate(expected), np.concatenate(actual)))
    return results


def choose(results):
    """Lowest log loss; within TIE_TOLERANCE of it, the slope closest to 1.0 wins."""
    best = min(loss for loss, _ in results.values())
    tied = {name: slope for name, (loss, slope) in results.items() if loss <= best + TIE_TOLERANCE}
    return min(tied, key=lambda name: abs(tied[name] - 1.0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="optional Markdown file to write the results to")
    args = parser.parse_args()

    conn = get_db_connection()
    validation = evaluate(conn, VALIDATION_SEASONS)
    test = evaluate(conn, [TEST_SEASON])
    conn.close()
    chosen = choose(validation)

    lines = [
        "## How season point margin enters the model",
        "",
        "Generated by `python -m evaluation.select_margin_treatment --output "
        "docs/margin_treatment.md`. Each candidate is trained as the simulation trains on "
        "February 1 and scored on the games after that date: log loss, and the calibration "
        "slope of teams' real remaining wins on their expected remaining wins (1.0 is "
        f"calibrated, above 1 is too cautious). Chosen on {', '.join(VALIDATION_SEASONS)} "
        f"(log-loss ties within {TIE_TOLERANCE} go to the slope closest to 1.0) and "
        f"reported once on {TEST_SEASON}.",
        "",
        "| Candidate | Validation log loss | Validation slope | Test log loss | Test slope |",
        "|---|---|---|---|---|",
    ]
    for name in CANDIDATES:
        label = name + (" **(chosen)**" if name == chosen else "")
        vl, vs = validation[name]
        tl, ts = test[name]
        lines.append(f"| {label} | {vl:.4f} | {vs:.2f} | {tl:.4f} | {ts:.2f} |")
    report = "\n".join(lines)
    print(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
