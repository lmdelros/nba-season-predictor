# Tests whether early-season projections improve when each team's season margin is
# shrunk toward a share of its previous season's margin instead of toward 0. Each
# candidate changes only the shrunk-margin features, then is trained and scored the way
# the simulation predicts the rest of a season. Candidates and the rule are fixed below;
# the final season is reported but not used to choose. Run from the repo root:
#   python -m evaluation.select_margin_prior --output docs/margin_prior.md
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

from evaluation.backtest_simulation import actual_playoff_teams, load_actual_final_wins
from evaluation.select_sharpness import cutoff_for as february_cutoff
from models.train_win_probability import (
    FEATURE_COLUMNS,
    GAMES_PLAYED_COLUMNS,
    MARGIN_COLUMNS,
    MARGIN_SHRINK_GAMES,
    SHRUNK_MARGIN_COLUMNS,
    apply_imputer,
    fit_imputer,
    load_training_data,
)
from simulation.monte_carlo import (
    compute_current_standings,
    cutoff_snapshot,
    freeze_remaining_features,
    get_db_connection,
    head_to_head_before,
    load_earlier_seasons,
    load_played_games,
    load_team_features,
)

VALIDATION_SEASONS = ["2022-23", "2023-24", "2024-25"]
TEST_SEASON = "2025-26"
# Candidate: the share of last season's margin a team starts from (0 is the current model).
CANDIDATES = {
    "A: shrink toward 0 (model before this experiment)": 0.0,
    "B: toward 50% of last season's margin": 0.5,
    "C: toward 75% of last season's margin": 0.75,
    "D: toward 100% of last season's margin": 1.0,
}
CURRENT = "A: shrink toward 0 (model before this experiment)"
# Win-total errors closer than this count as a tie: the current model is kept if it is in
# the tie, otherwise the lowest playoff Brier score wins. The winner must also not raise
# the February 1 validation error by more than this.
TIE_TOLERANCE = 0.1
N_PLAYOFF_RUNS = 10000
SEED = 42
# Brier score of giving all 30 teams the same chance, 16 of 30, of making the top 8.
NO_INFORMATION_BRIER = (16 / 30) * (14 / 30)


def early_cutoff(season):
    """November 4 of the season's first calendar year: about 7 games into a season."""
    return f"{season[:4]}-11-04"


def previous_season(season):
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def load_season_margins(conn):
    """{(season, team_id): average point margin over the season's final games}."""
    df = pd.read_sql(
        """
        SELECT season, team_id, avg(margin)::float AS margin FROM (
            SELECT season, home_team_id AS team_id, home_score - away_score AS margin
            FROM games WHERE status = 'final'
            UNION ALL
            SELECT season, away_team_id, away_score - home_score
            FROM games WHERE status = 'final'
        ) g GROUP BY season, team_id
        """, conn)
    return dict(zip(zip(df["season"], df["team_id"]), df["margin"]))


def with_prior(df, weight, margins):
    """Replaces the shrunk margins with (n * margin + k * prior) / (n + k), where prior is
    weight times the team's margin in the previous season (0 if that season is not in the
    database). With weight 0 this equals the current shrinkage toward 0."""
    df = df.copy()
    k = MARGIN_SHRINK_GAMES
    previous = df["season"].map(previous_season)
    for side, margin, games, shrunk in zip(("home", "away"), MARGIN_COLUMNS,
                                           GAMES_PLAYED_COLUMNS, SHRUNK_MARGIN_COLUMNS):
        prior = weight * pd.Series(
            [margins.get(key, 0.0) for key in zip(previous, df[f"{side}_team_id"])],
            index=df.index,
        )
        n = df[games].astype(float).fillna(0)
        # A team with no games yet has no margin; its value is then the prior alone.
        observed = df[margin].astype(float).fillna(0)
        df[shrunk] = (n * observed + k * prior) / (n + k)
    return df


def predict(season_games, team_features, cutoff, history, weight, margins):
    """Home-win probabilities for games on or after the cutoff, trained the way
    simulation.monte_carlo.predict_remaining() trains, with the candidate's prior."""
    cutoff = pd.Timestamp(cutoff)
    train = season_games[season_games["game_date"] < cutoff]
    remaining = freeze_remaining_features(
        season_games[season_games["game_date"] >= cutoff],
        cutoff_snapshot(team_features, cutoff), head_to_head_before(train),
    )
    train = with_prior(pd.concat([history, train], ignore_index=True), weight, margins)
    remaining = with_prior(remaining, weight, margins)

    fills = fit_imputer(train)
    train, remaining = apply_imputer(train, fills), apply_imputer(remaining, fills)
    scaler = StandardScaler()
    model = LogisticRegression(max_iter=1000)
    model.fit(scaler.fit_transform(train[FEATURE_COLUMNS].astype(float)), train["home_win"])
    probs = model.predict_proba(scaler.transform(remaining[FEATURE_COLUMNS].astype(float)))[:, 1]
    return remaining.assign(prob=probs)


def playoff_odds(current_wins, scored, conferences, rng):
    """Share of N_PLAYOFF_RUNS simulated finishes in which each team is top 8 in its
    conference, playing each remaining game once with its predicted probability."""
    teams = sorted(conferences)
    index = {team: i for i, team in enumerate(teams)}
    # One row per game, one column per team: 1 where that team is home (or away).
    is_home = np.zeros((len(scored), len(teams)))
    is_home[np.arange(len(scored)), scored["home_team_id"].map(index)] = 1
    is_away = np.zeros((len(scored), len(teams)))
    is_away[np.arange(len(scored)), scored["away_team_id"].map(index)] = 1
    home_won = (rng.random((N_PLAYOFF_RUNS, len(scored))) < scored["prob"].to_numpy()).astype(float)
    wins = (np.array([current_wins.get(t, 0) for t in teams], dtype=float)
            + home_won @ is_home + (1 - home_won) @ is_away)
    wins += rng.random(wins.shape) * 0.5  # random tiebreak between equal records
    made = np.zeros(len(teams))
    for conference in set(conferences.values()):
        cols = [index[t] for t in teams if conferences[t] == conference]
        top = np.argsort(-wins[:, cols], axis=1)[:, :8]
        np.add.at(made, np.array(cols)[top].ravel(), 1)
    return dict(zip(teams, made / N_PLAYOFF_RUNS))


def score(data, weight, margins, conferences):
    """(win-total MAE, playoff Brier, game log loss) pooled over the given seasons."""
    errors, briers, outcomes, probs = [], [], [], []
    rng = np.random.default_rng(SEED)
    for games, team_features, cutoff, history, played, actual in data:
        scored = predict(games, team_features, cutoff, history, weight, margins)
        current = compute_current_standings(played)
        expected = {t: current.get(t, 0) for t in conferences}
        for side, p in (("home_team_id", scored["prob"]), ("away_team_id", 1 - scored["prob"])):
            for team, total in p.groupby(scored[side]).sum().items():
                expected[team] += total
        errors += [abs(expected[t] - actual[t]) for t in conferences]
        odds = playoff_odds(current, scored, conferences, rng)
        made = actual_playoff_teams(actual, pd.DataFrame(
            {"team_id": list(conferences), "conference": list(conferences.values())}))
        briers += [(odds[t] - (t in made)) ** 2 for t in conferences]
        outcomes.append(scored["home_win"].to_numpy())
        probs.append(scored["prob"].to_numpy())
    return (float(np.mean(errors)), float(np.mean(briers)),
            log_loss(np.concatenate(outcomes), np.concatenate(probs), labels=[0, 1]))


def load(conn, seasons, cutoff_of):
    data = []
    for season in seasons:
        history = pd.concat([load_training_data(conn, s).assign(season=s)
                             for s in load_earlier_seasons(conn, season)], ignore_index=True)
        cutoff = cutoff_of(season)
        data.append((load_training_data(conn, season).assign(season=season),
                     load_team_features(conn, season), cutoff, history,
                     load_played_games(conn, season, cutoff), load_actual_final_wins(conn, season)))
    return data


def evaluate(conn, seasons, cutoff_of, margins, conferences):
    data = load(conn, seasons, cutoff_of)
    return {name: score(data, w, margins, conferences) for name, w in CANDIDATES.items()}


def choose(early, february):
    """Lowest early win-total error; the current model is kept if within TIE_TOLERANCE of
    it, otherwise the lowest playoff Brier among those within it wins. A winner that raises
    the February 1 error by more than TIE_TOLERANCE over the current model is rejected."""
    best = min(mae for mae, _, _ in early.values())
    tied = {name: brier for name, (mae, brier, _) in early.items() if mae <= best + TIE_TOLERANCE}
    if CURRENT in tied:
        return CURRENT
    winner = min(tied, key=tied.get)
    if february[winner][0] > february[CURRENT][0] + TIE_TOLERANCE:
        return CURRENT
    return winner


def table(results, chosen):
    lines = ["| Candidate | Win-total error (wins) | Playoff Brier | Game log loss |",
             "|---|---|---|---|"]
    for name, (mae, brier, loss) in results.items():
        label = name + (" **(chosen)**" if name == chosen else "")
        lines.append(f"| {label} | {mae:.2f} | {brier:.4f} | {loss:.4f} |")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="optional Markdown file to write the results to")
    args = parser.parse_args()

    conn = get_db_connection()
    margins = load_season_margins(conn)
    teams = pd.read_sql("SELECT team_id, conference FROM teams ORDER BY team_id", conn)
    conferences = dict(zip(teams["team_id"], teams["conference"]))
    early = evaluate(conn, VALIDATION_SEASONS, early_cutoff, margins, conferences)
    february = evaluate(conn, VALIDATION_SEASONS, february_cutoff, margins, conferences)
    test_early = evaluate(conn, [TEST_SEASON], early_cutoff, margins, conferences)
    test_february = evaluate(conn, [TEST_SEASON], february_cutoff, margins, conferences)
    conn.close()
    chosen = choose(early, february)

    lines = [
        "## Starting each team from last season's margin",
        "",
        "Generated by `python -m evaluation.select_margin_prior --output docs/margin_prior.md`. "
        "Each candidate shrinks a team's season margin toward a share of its previous "
        "season's margin instead of toward 0: (n × margin + "
        f"{MARGIN_SHRINK_GAMES} × prior) / (n + {MARGIN_SHRINK_GAMES}). It is trained as the "
        "simulation trains at the cutoff and scored on the rest of the season: the error of "
        "each team's expected final win total, the Brier score of its playoff odds "
        f"({N_PLAYOFF_RUNS:,} simulated finishes, top 8 per conference), and log loss on the "
        "remaining games. Lower is better for all three.",
        "",
        f"Chosen on November 4 of {', '.join(VALIDATION_SEASONS)}: lowest win-total error; "
        f"the current model is kept if within {TIE_TOLERANCE} wins of it, otherwise the "
        "lowest playoff Brier among those within it wins, and the winner must not raise the "
        f"February 1 error by more than {TIE_TOLERANCE}. {TEST_SEASON} is reported once.",
        "",
        "For reference, giving every team the same 16-in-30 playoff chance scores a playoff "
        f"Brier of {NO_INFORMATION_BRIER:.4f}.",
        "",
        "### Validation, November 4",
        "",
        *table(early, chosen),
        "",
        "### Validation, February 1",
        "",
        *table(february, chosen),
        "",
        f"### Test ({TEST_SEASON}), November 4",
        "",
        *table(test_early, chosen),
        "",
        f"### Test ({TEST_SEASON}), February 1",
        "",
        *table(test_february, chosen),
    ]
    report = "\n".join(lines)
    print(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
