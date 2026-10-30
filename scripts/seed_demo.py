# Loads one season so a fresh install has data to show: downloads games from NBA.com,
# builds features, saves win-model predictions, and runs the season simulation. Each
# step is an existing pipeline script, run exactly as it would be by hand, and the
# seed stops at the first step that fails. Run from the repo root:
#   python -m scripts.seed_demo
#   docker compose run --rm pipeline python -m scripts.seed_demo
import argparse
import subprocess
import sys
import time


def seed_steps(season, cutoff_date, n_simulations):
    """(description, module and arguments) for each step, in the order they must run."""
    return [
        ("Download games and box scores from NBA.com",
         ["ingestion.pull_nba_data", "--season", season]),
        ("Build features", ["features.build_features", "--season", season]),
        ("Train the win model and save its predictions",
         ["models.train_win_probability", "--season", season]),
        (f"Simulate the season from {cutoff_date} ({n_simulations:,} runs)",
         ["simulation.monte_carlo", "--season", season, "--cutoff-date", cutoff_date,
          "--n-simulations", str(n_simulations)]),
    ]


def run_steps(steps):
    """Runs each step as python -m <module> and exits with an error on the first failure."""
    for number, (description, module_args) in enumerate(steps, start=1):
        print(f"[{number}/{len(steps)}] {description}", flush=True)
        start = time.perf_counter()
        result = subprocess.run([sys.executable, "-m", *module_args])
        if result.returncode != 0:
            sys.exit(f"Step {number} failed (exit code {result.returncode}): {description}")
        print(f"      done in {time.perf_counter() - start:.0f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Load one season of data so a fresh install has something to show."
    )
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--cutoff-date", default="2026-02-01",
                        help="simulate the season as if it were this date (YYYY-MM-DD)")
    parser.add_argument("--n-simulations", type=int, default=10000)
    args = parser.parse_args()
    run_steps(seed_steps(args.season, args.cutoff_date, args.n_simulations))


if __name__ == "__main__":
    main()
