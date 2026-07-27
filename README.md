# nba-season-predictor

A personal portfolio project that combines a PostgreSQL database, scikit-learn
models, and a Monte Carlo simulation to project how an NBA season plays out —
per-game win probabilities and season-long projections like playoff odds,
built entirely on real historical data pulled from NBA.com via `nba_api`.

## Architecture

Five layers, each a separate concern:

1. **Data ingestion** (`ingestion/pull_nba_data.py`) — pulls teams, games, and
   player box scores from `nba_api` and upserts them into Postgres.
2. **Feature engineering** (`features/build_features.py`) — builds
   `team_game_features`: rolling win %, rest days, back-to-backs, pace-adjusted
   offensive/defensive ratings, head-to-head record, home/away splits, and a
   player-cluster diversity score — kept separate from raw ingested data so
   re-running it never mutates source tables.
3. **Modeling** (`models/`) — a logistic regression baseline for win
   probability, a linear regression model for point margin, and k-means
   clustering of players into playstyle archetypes.
4. **Monte Carlo simulation** (`simulation/monte_carlo.py`) — simulates the
   rest of a season thousands of times using the win probability model,
   tallying projected wins and playoff odds across runs (the
   FiveThirtyEight/ESPN BPI approach: probabilities across simulations, not a
   single deterministic outcome).
5. **Dashboard** (`dashboard/app.py`) — a Streamlit app reading all of the
   above from Postgres.

## Setup

Requires Docker Desktop and Python 3.12+.

```bash
# 1. Start Postgres (schema auto-loads from db/schema.sql on first run)
docker compose up -d

# 2. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt
```

Postgres runs on `localhost:5433` (not 5432 — see *Notes* below), database
`nba_predictor`, user/password `nba`/`nba`.

## Running the pipeline

Each stage is a standalone script, run in order for a given season:

```bash
python ingestion/pull_nba_data.py --season 2024-25
python features/build_features.py --season 2024-25

# Pick k by eye first (elbow/silhouette diagnostics), then fit:
python models/train_player_clusters.py --season 2024-25
python models/train_player_clusters.py --season 2024-25 --k 5

# Re-run features once clusters exist, to backfill cluster_diversity_score:
python features/build_features.py --season 2024-25

python models/train_win_probability.py --season 2024-25
python models/train_margin.py --season 2024-25

# Backtest a full season (no season is currently in progress, so this
# treats games before --cutoff-date as "already played" and simulates
# everything after using the trained model):
python simulation/monte_carlo.py --season 2024-25 --cutoff-date 2025-02-01

streamlit run dashboard/app.py
```

## Database schema

Nine tables in `db/schema.sql`: `teams`, `players`, `team_rosters`, `games`,
`player_game_stats`, `team_game_features` (engineered, separate from raw
`games`), `player_clusters` (k-means output, manually labeled after
inspection), `game_predictions` (keyed by `model_version` so multiple models
can be compared side by side), and `season_simulations` (Monte Carlo output,
keyed by `batch_id` so multiple simulation runs can coexist).

## Results (2024-25 season)

- **Win probability model** (logistic regression): 70.6% accuracy, 0.571 log
  loss, 0.193 Brier score, well-calibrated across probability buckets.
- **Margin model** (linear regression): 12.11 points MAE (vs. 14.32 baseline),
  71.8% implied win/loss accuracy from the sign of the predicted margin.
- **Player clustering** (k=5): Facilitating Guard, Secondary Scorer, 3-and-D
  Wing, Primary Scorer/Shot Creator, Traditional Big/Rim Runner.
- **Monte Carlo backtest** (2025-26, cutoff 2026-02-01, 10k simulations):
  0.977 rank correlation with actual final win totals, ~0 net bias, 3.77 MAE.
  Extreme teams (very good/bad) show expected regression-to-mean compression
  — a known artifact of these systems, not a bug, since box-score features
  can't see things like tanking or late-season motivation shifts.

## Known limitations

- **`championship_pct`** in `season_simulations` is left `NULL` — computing it
  properly needs a full playoff bracket simulation (seeding, best-of-7 series,
  round by round), which is a separate, larger piece of future work.
- **No live season to simulate.** Every Monte Carlo run here is a backtest
  against a `--cutoff-date` on an already-completed season, not a genuine
  in-progress projection, since none was available while building this.
- **Cluster labels are manual and per-fit.** k-means' cluster numbering is
  arbitrary and can shift on re-fit (different data, different library
  version), so labels like "3-and-D Wing" are applied by hand after
  inspection, not derived in code.
- **Player bio fields** (`position`, `height_in`, `weight_lb`, `birth_date`)
  are unpopulated — they'd require a separate per-player API call
  (`commonplayerinfo`) not currently part of the ingestion script.
- Postgres runs on port **5433**, not the default 5432, to avoid conflicting
  with any native Postgres install already using 5432 on the host.

## Stretch goals

- Compare the logistic regression baseline against gradient-boosted trees
  (XGBoost/LightGBM), which typically outperform plain logistic regression for
  win probability.
- Full playoff bracket simulation for `championship_pct`.
- Cloud deployment (Azure Database for PostgreSQL + Container Apps) — not
  needed for local review, but noted as a possible future step.
