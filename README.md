# NBA Season Predictor

Predicts NBA game winners and simulates the rest of a season to project standings, playoff odds, and championship odds, using five seasons of real NBA.com data.

[![CI](https://github.com/lmdelros/nba-season-predictor/actions/workflows/ci.yml/badge.svg)](https://github.com/lmdelros/nba-season-predictor/actions/workflows/ci.yml)

![The web app showing 2025-26 standings and Monte Carlo playoff and championship odds](docs/screenshot.png)

**Live demo:** http://3.148.147.49, hosted on AWS ([how it's deployed](docs/deployment.md))

## Highlights

- **68.5% of games predicted correctly on a season the model never saw** (all 1,230 games of 2025-26), 13.1 points better than always picking the home team, with lower log loss and Brier score than every baseline. [Results](docs/results.md)
- **Found and fixed data leakage in the season simulator.** The original backtest scored future games with features built from their real results, which inflated its accuracy (0.976 rank correlation). After freezing every feature at the cutoff date it measured an honest 0.921. [Backtest](docs/backtest.md)
- **Found and fixed an overcautious model, measured against real champions.** Projections were too cautious in every season (calibration slope 1.47, where 1.0 is calibrated): noisy early-season margins taught the model to under-trust margins. Shrinking each margin by how few games it is based on brought the slope to 1.11, cut the backtest's win-total error from 4.02 to 3.63, and lowered log loss on the real champion from 1.80 to 1.64. [Title odds](docs/title_odds.md)
- **Leakage is guarded by tests.** Every feature, the simulator, and a SQL window-function view are tested by rewriting future results and asserting nothing earlier changes; each test was checked by injecting the bug on purpose.
- **Deployed on AWS (EC2 and RDS).** The Docker stack runs on an EC2 server in front of a private, encrypted RDS PostgreSQL database that only that server can reach, over connections that require TLS. [Deployment](docs/deployment.md)
- **Runs with one command.** Docker Compose starts PostgreSQL, a FastAPI service, and a React app served by nginx; a second command loads real data.
- **50 automated tests in CI** on every push: Python and database tests against a real PostgreSQL instance, frontend tests and build, and a smoke test of the whole stack through nginx.

## Overview

The project pulls game results and box scores from NBA.com, stores them in PostgreSQL, and turns them into per-team features such as season-to-date point margin and rest days. A logistic regression model estimates each game's home-win probability. A Monte Carlo simulation then plays out the rest of the season 10,000 times, seeds a best-of-seven playoff bracket from each simulated season, and counts how often each team makes the playoffs and wins the title. The results are served by a REST API and shown in a React web app.

Every reported number comes from a script in this repository that anyone can rerun, and the win model and the simulation are both compared with simple baselines, so a claim like "+13.1 points" has a reference point. Projections are evaluated as backtests on completed seasons: the simulation pretends it is February 1, 2026, and its projections are compared with how the 2025-26 season actually ended.

```mermaid
flowchart LR
    NBA["NBA.com stats API"] -->|nba_api| ING["Ingestion"]
    ING --> DB[("PostgreSQL")]
    DB --> FEAT["Features<br/>(pandas + SQL view)"]
    FEAT --> DB
    DB --> MODEL["Win model<br/>(scikit-learn)"]
    MODEL --> SIM["Monte Carlo<br/>season + playoffs"]
    SIM --> DB
    DB --> API["FastAPI"]
    API --> WEB["nginx + React"]
    WEB --> USER["Browser"]
```

## Tech stack

| Tool | What it does here |
|---|---|
| **Python 3.12** | Data pipeline, models, simulation, and API |
| **nba_api** | Downloads game logs, box scores, and award history from NBA.com |
| **PostgreSQL 16** | Stores 15 tables of games, box scores, features, predictions, simulation runs and their Finals matchups, and each season's real champion; a SQL view computes each team's season-to-date point margin with window functions |
| **pandas, NumPy** | Feature engineering and simulation |
| **scikit-learn** | Logistic regression win model, gradient boosting comparison, linear regression margin model, k-means player clustering |
| **FastAPI** | REST API for standings, predictions, and simulation results |
| **React 19 + Vite** | Web app showing the most likely Finals, standings, playoff odds, and award cards |
| **nginx** | Serves the built React app and forwards `/api` requests to FastAPI |
| **Docker Compose** | Runs PostgreSQL, a schema migration step, the API, and the web app together |
| **AWS (EC2, RDS, Elastic IP)** | Hosts the live app: EC2 runs the containers, RDS runs PostgreSQL privately, and an Elastic IP keeps the address fixed |
| **pytest, Vitest** | Python, database, API, and frontend tests |
| **GitHub Actions** | Runs lint, all tests, and a full-stack smoke test on every push |

## Getting started

### Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with Compose v2)
- Git
- Free ports 5433 (PostgreSQL), 8000 (API), and 8080 (web app)
- Internet access to NBA.com for loading data

### Run it

1. Clone the repository:

   ```bash
   git clone https://github.com/lmdelros/nba-season-predictor.git
   cd nba-season-predictor
   ```

2. Build and start the app (PostgreSQL, the API, and the web app):

   ```bash
   docker compose up -d --wait
   ```

3. Load one season of real data. This downloads the 2025-26 season from NBA.com, builds features, trains the model, and runs 10,000 simulations. It usually takes about a minute, depending on how quickly NBA.com responds.

   ```bash
   docker compose run --rm pipeline python -m scripts.seed_demo
   ```

4. Open **http://localhost:8080**.

To stop everything, run `docker compose down`. Your data stays in a Docker volume; add `-v` to delete it too.

No environment file is needed: the Compose file sets every setting, and the database password is a local-only default.

## Usage

The web app shows the final standings for each loaded season and, for seasons with a simulation run, the most likely NBA Finals matchup and each team's playoff and championship odds. Each projection is labeled with the date it was made from; the live demo projects every season from February 1 of that season.

The API is available directly on port 8000, with interactive documentation at **http://localhost:8000/docs**, and through the web app under `/api`:

```bash
curl "http://localhost:8080/api/simulations?season=2025-26"
```

Each team's entry looks like this (your `batch_id`, `run_at`, and odds will differ with the data you loaded):

```json
{
  "team_id": 1610612760,
  "abbreviation": "OKC",
  "full_name": "Oklahoma City Thunder",
  "batch_id": "69580a28-b99a-4791-92e4-36ef9c2d52ae",
  "run_at": "2026-10-30T19:18:59.847019Z",
  "num_simulations": 10000,
  "avg_wins": 61.14,
  "playoff_pct": 1.0,
  "championship_pct": 0.4763
}
```

Other endpoints: `/health`, `/seasons`, `/teams`, `/standings?season=`, `/predictions?season=`, `/simulations/finals?season=` (the most likely Finals matchups), and `/awards?season=` (each award's winner and the model's top 3 picks, from models trained only on earlier seasons).

To run individual pipeline steps, load more seasons, retrain models, or reproduce the evaluations, see [docs/pipeline.md](docs/pipeline.md).

## Results

All numbers below are produced by scripts in `evaluation/` and `models/`; each linked page shows the exact command.

**Win model:** trained on 2021-22 through 2024-25, tested once on all 1,230 games of 2025-26. ([docs/results.md](docs/results.md))

| Method | Accuracy | Log loss | Brier |
|---|---|---|---|
| Always pick the home team | 55.4% | 0.687 | 0.247 |
| Pick the team with the better record so far | 66.9% | 0.631 | 0.220 |
| Gradient boosting, same features | 67.4% | 0.631 | 0.217 |
| **Logistic regression (this project)** | **68.5%** | **0.599** | **0.206** |

Log loss and Brier score measure how good the predicted probabilities are; lower is better for both. The model's six features (season-to-date point margin, rest days, and back-to-backs for each team) were chosen by validating on earlier seasons only ([docs/feature_selection.md](docs/feature_selection.md)). Each margin is shrunk toward zero by how few games it is based on, so noisy early-season margins do not teach the model to under-trust the reliable ones later in the season ([docs/margin_treatment.md](docs/margin_treatment.md)).

**Season simulation:** projecting 2025-26 from February 1, 2026. ([docs/backtest.md](docs/backtest.md))

| Method | Rank correlation with final standings | Mean error (wins) |
|---|---|---|
| Keep each team's February 1 win % for all 82 games | 0.943 | 3.54 |
| **Monte Carlo simulation (this project)** | **0.943** | **3.63** |

The simulation matches the naive projection's ordering and comes within 0.1 wins of its accuracy while also producing playoff and title odds; it found 14 of the 16 playoff teams. Scored against the real champions of 2021-22 to 2025-26, the February 1 favorite won 3 of 5 titles, and the model's log loss on the champion is 1.64, against 3.40 for giving every team equal odds. ([docs/title_odds.md](docs/title_odds.md))

**Point-margin model:** a linear regression on the original 13 features predicts the final margin within 12.11 points on average, against 14.32 for always predicting the average margin (2024-25, last 20% of the season, 262 games).

**Award models (MVP, DPOY, ROY, MIP):** for each award, a logistic regression ranks every season's 20 most likely candidates. Evaluated season by season from 2015-16 to 2024-25, each season predicted only from earlier seasons, the top pick was the real winner 19 times out of 40: MVP 7 of 10, Rookie of the Year 8 of 10, Defensive Player of the Year 3 of 10, and Most Improved Player 1 of 10. Each model's settings were chosen on the earlier seasons only; stronger regularization fixed overfitting in the Rookie of the Year model. Most Improved Player remains unreliable, and the Defensive Player of the Year shortlist misses two of the ten winners. On 2025-26, a season no setting was chosen on, three of the four real winners were in the model's top 3 and two were its first pick. ([docs/award_models.md](docs/award_models.md))

## Running tests

Python tests (the database and API tests use the Compose database on port 5433 and are skipped if it is not running):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d --wait
ruff check .
python -m pytest
```

Frontend tests, lint, and build:

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
```

## Limitations

- **Projections are still slightly cautious, most in lopsided seasons.** Across five seasons the calibration slope is 1.11 (1.0 is calibrated), but 1.41 in 2025-26, when one team won 64 games. Championships also depend on things the data does not contain, such as injuries, trades, and playoff rotations, so long shots like the 2026 Knicks get little probability.
- **Backtests only.** Every projection is evaluated on a completed season with a pretend cutoff date; no season was in progress while this was built.
- **The oldest season has the least to learn from.** Each projection trains on earlier seasons plus that season's games before the cutoff, so 2021-22, the first season in the data, is projected from its own games only.
- **The play-in tournament is not modeled.** The top eight teams in each conference by wins make the playoffs.
- **The data download depends on NBA.com,** which can be slow and is reported to block requests from cloud servers.
- **Applying `db/schema.sql` adds missing tables but not new columns** to tables that already exist.
- **Player clusters are labeled by hand** after each fit, since k-means numbers clusters arbitrarily.
- **The live demo uses HTTP, not HTTPS.** HTTPS needs a domain name and a certificate, which the deployment does not have yet.
- **Team logos are trademarks of the NBA and its teams.** The app loads them from NBA.com to identify teams; they are not stored in this repository. If a logo cannot be loaded, the team's abbreviation is shown instead.

## Project status

Actively developed as a portfolio project, and deployed on AWS at http://3.148.147.49.

## Contributing

Issues and suggestions are welcome. For larger changes, please open an issue first to discuss the idea.

## Author

**Luis del Rosario**, [GitHub](https://github.com/lmdelros)
