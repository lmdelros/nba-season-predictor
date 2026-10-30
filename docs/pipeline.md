# Running the pipeline by hand

The [README](../README.md) loads one season with a single command. This page covers running each step yourself: loading more seasons, retraining models, reproducing the evaluations, and the award models.

Every script is run from the repository root with `python -m`, because the scripts import each other as packages (`models.train_win_probability`, and so on). Running a file directly, such as `python models/train_margin.py`, fails with `ModuleNotFoundError`.

## Setup

You can run the scripts either inside Docker or with a local Python environment.

**Inside Docker** (no local Python needed): prefix any command below with `docker compose run --rm pipeline`, for example:

```bash
docker compose run --rm pipeline python -m features.build_features --season 2024-25
```

**Locally** (Python 3.12):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d --wait      # PostgreSQL on localhost:5433
```

The scripts connect to `localhost:5433` by default. To use another database, set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`.

## Load a season

Each season takes about 20 seconds to download, depending on NBA.com. Re-running either step updates existing rows instead of duplicating them.

```bash
python -m ingestion.pull_nba_data --season 2024-25
python -m features.build_features --season 2024-25
```

The evaluations below expect five seasons, 2021-22 through 2025-26:

```bash
for season in 2021-22 2022-23 2023-24 2024-25 2025-26; do
  python -m ingestion.pull_nba_data --season "$season"
  python -m features.build_features --season "$season"
done
```

## Player clusters

Groups players into playstyle archetypes with k-means. First print the elbow and silhouette diagnostics to choose `k` (this writes nothing):

```bash
python -m models.train_player_clusters --season 2024-25
```

Then fit and save the clusters, and re-run the features so `cluster_diversity_score` is filled in:

```bash
python -m models.train_player_clusters --season 2024-25 --k 5
python -m features.build_features --season 2024-25
```

**Labels are written by hand.** Cluster numbers are arbitrary, so names such as "3-and-D Wing" are set in the `cluster_label` column after inspecting each cluster. Re-fitting a season updates `cluster_id` but not `cluster_label`, so if a re-fit numbers the clusters differently, the existing labels end up on the wrong groups. Re-check or clear the labels after re-fitting a labeled season.

## Win model

Trains on the first 80% of a season's dates, tests on the rest, prints accuracy, log loss, Brier score, and calibration, and saves the test-game predictions as model version `logreg_v2`:

```bash
python -m models.train_win_probability --season 2025-26
```

## Point-margin model

A linear regression on the model's original 13 features, with the same split. It saves predictions as `linreg_margin_v1`:

```bash
python -m models.train_margin --season 2024-25
```

Expected output:

```text
Test games: 262
MAE:  12.11 points  (baseline 'always predict train-avg margin': 14.32)
RMSE: 15.31 points
Implied win/loss accuracy (sign of predicted margin): 0.718
```

## Season simulation

Pretends it is `--cutoff-date`, counts real results before it, and simulates everything after it 10,000 times, including the playoff bracket. It trains on every earlier season in the database plus this season's games before the cutoff; `--no-history` uses this season only. Each run is saved as a new batch, and the API shows the newest.

```bash
python -m simulation.monte_carlo --season 2025-26 --cutoff-date 2026-02-01
```

## Evaluations

These reproduce the files in `docs/`. They only read from the database. Each needs the five seasons above loaded.

```bash
python -m evaluation.evaluate_win_model --output docs/results.md
python -m evaluation.select_features --output docs/feature_selection.md
python -m evaluation.backtest_simulation --output docs/backtest.md
```

## Award models

Award models use season-level data rather than game-by-game data. First download player season stats, standings, and award winners. Checking each candidate's award history takes one request per player, so this takes about 15 minutes. `--buffer-seasons 2` also loads two earlier seasons of stats so the Rookie of the Year model can tell rookies from players who were already in the league.

```bash
python -m ingestion.pull_award_data --start-season 2010-11 --end-season 2024-25 \
  --awards mvp,dpoy,roy,mip --buffer-seasons 2
```

Then train and evaluate each model. Each trains on every season except the last three, checks whether its top-ranked candidate won in each held-out season, and saves its predictions:

```bash
python -m models.train_mvp --start-season 2010-11 --end-season 2024-25
python -m models.train_dpoy --start-season 2010-11 --end-season 2024-25
python -m models.train_roy --start-season 2010-11 --end-season 2024-25
python -m models.train_mip --start-season 2010-11 --end-season 2024-25
```

Results on 2022-23 through 2024-25 (top pick was the real winner):

| Award | Correct | Notes |
|---|---|---|
| MVP | 2 of 3 | Missed 2022-23 (picked Nikola Jokić; Joel Embiid won) |
| Defensive Player of the Year | 1 of 3 | Candidates are the top 20 in steals plus blocks, which misses some winners |
| Rookie of the Year | 2 of 3 | Missed 2022-23 (Paolo Banchero) |
| Most Improved Player | 2 of 3 | Missed 2024-25 (Dyson Daniels) |

## Streamlit dashboard

An older presentation layer that reads straight from PostgreSQL. The React app replaces it, but it still runs:

```bash
streamlit run dashboard/app.py
```
