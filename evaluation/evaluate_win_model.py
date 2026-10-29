# Compares the win-probability model against simple baselines on held-out games,
# so reported accuracy has a reference point. Run from the repo root:
#   python -m evaluation.evaluate_win_model --output docs/results.md
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

from models.train_win_probability import (
    FEATURE_COLUMNS,
    apply_imputer,
    fit_imputer,
    get_db_connection,
    load_training_data,
    time_ordered_split,
    train_model,
)


def load_games(conn, seasons):
    sql = """
        SELECT game_id, season, game_date, home_team_id, away_team_id, home_score, away_score
        FROM games
        WHERE season = ANY(%(seasons)s)
    """
    df = pd.read_sql(sql, conn, params={"seasons": list(seasons)})
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def pregame_win_pct(games):
    """Each side's overall season win % from games strictly before this one,
    NaN for a team's first game of the season."""
    home = games[["game_id", "season", "game_date", "home_team_id"]].rename(
        columns={"home_team_id": "team_id"}
    )
    home["win"] = (games["home_score"] > games["away_score"]).astype(int)
    home["side"] = "home"
    away = games[["game_id", "season", "game_date", "away_team_id"]].rename(
        columns={"away_team_id": "team_id"}
    )
    away["win"] = (games["away_score"] > games["home_score"]).astype(int)
    away["side"] = "away"

    long = pd.concat([home, away]).sort_values(["season", "team_id", "game_date", "game_id"])
    # shift(1) drops the current game, so a game's own result never counts toward its record.
    long["pregame_win_pct"] = long.groupby(["season", "team_id"])["win"].transform(
        lambda s: s.shift(1).expanding().mean()
    )
    wide = long.pivot(index="game_id", columns="side", values="pregame_win_pct")
    return wide.rename(columns={"home": "home_pregame_win_pct", "away": "away_pregame_win_pct"})


def score(y_true, probs):
    probs = np.clip(np.asarray(probs, dtype=float), 1e-6, 1 - 1e-6)
    return {
        "accuracy": accuracy_score(y_true, (probs >= 0.5).astype(int)),
        "log_loss": log_loss(y_true, probs, labels=[0, 1]),
        "brier": brier_score_loss(y_true, probs),
    }


def home_team_baseline(train_df, test_df):
    """Always picks the home team, with probability equal to the training home win rate."""
    return np.full(len(test_df), train_df["home_win"].mean())


def record_edge(df):
    diff = df["home_pregame_win_pct"] - df["away_pregame_win_pct"]
    return np.select([diff > 0, diff < 0], ["home_better", "away_better"], default="even")


def better_record_baseline(train_df, test_df):
    """Picks the team with the better record so far; its probability is the training home
    win rate among games with the same record edge (home better, away better, or even)."""
    rates = train_df.groupby(record_edge(train_df))["home_win"].mean()
    fallback = train_df["home_win"].mean()
    return np.array([rates.get(edge, fallback) for edge in record_edge(test_df)])


def logistic_model(train_df, test_df):
    fills = fit_imputer(train_df)
    model, scaler = train_model(apply_imputer(train_df, fills))
    X_test = apply_imputer(test_df, fills)[FEATURE_COLUMNS].astype(float)
    return model.predict_proba(scaler.transform(X_test))[:, 1]


METHODS = {
    "Home team always wins": home_team_baseline,
    "Better record so far wins": better_record_baseline,
    "Logistic regression (this project)": logistic_model,
}


def evaluate_split(train_df, test_df):
    rows = []
    for name, method in METHODS.items():
        metrics = score(test_df["home_win"], method(train_df, test_df))
        rows.append({"method": name, **metrics})
    return pd.DataFrame(rows)


def load_season(conn, season):
    df = load_training_data(conn, season)
    records = pregame_win_pct(load_games(conn, [season]))
    return df.merge(records, left_on="game_id", right_index=True, how="left")


def to_markdown(title, description, train_df, test_df, results):
    lines = [
        f"### {title}",
        "",
        description,
        "",
        f"Train: {len(train_df)} games ({train_df['game_date'].min():%Y-%m-%d} to "
        f"{train_df['game_date'].max():%Y-%m-%d}). "
        f"Test: {len(test_df)} games ({test_df['game_date'].min():%Y-%m-%d} to "
        f"{test_df['game_date'].max():%Y-%m-%d}).",
        "",
        "| Method | Accuracy | Log loss | Brier |",
        "|---|---|---|---|",
    ]
    for row in results.itertuples():
        lines.append(
            f"| {row.method} | {row.accuracy:.1%} | {row.log_loss:.3f} | {row.brier:.3f} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-season", default="2024-25")
    parser.add_argument("--test-season", default="2025-26")
    parser.add_argument("--test-frac", type=float, default=0.2)
    parser.add_argument("--output", help="optional Markdown file to write the results to")
    args = parser.parse_args()

    conn = get_db_connection()
    train_season = load_season(conn, args.train_season)
    test_season = load_season(conn, args.test_season)
    conn.close()

    sections = [
        "## Win-probability model vs. baselines\n\n"
        "Generated by `python -m evaluation.evaluate_win_model --output docs/results.md`. "
        "Accuracy counts a pick as the side given at least a 50% chance; log loss and Brier "
        "score measure probability quality, and lower is better for both."
    ]

    results = evaluate_split(train_season, test_season)
    sections.append(to_markdown(
        f"Across seasons: train {args.train_season}, test {args.test_season} (headline)",
        f"The model is trained on every {args.train_season} game and scored on every "
        f"{args.test_season} game it never saw.",
        train_season, test_season, results,
    ))

    within_train, within_test = time_ordered_split(train_season, args.test_frac)
    results = evaluate_split(within_train, within_test)
    sections.append(to_markdown(
        f"Within one season: {args.train_season}, last {args.test_frac:.0%} of dates held out",
        "Same split as `models/train_win_probability.py`.",
        within_train, within_test, results,
    ))

    report = "\n\n".join(sections)
    print(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
