import importlib.util
import subprocess

import pytest

from scripts.seed_demo import run_steps, seed_steps

STEPS = seed_steps("2025-26", "2026-02-01", 10000)


def test_every_step_runs_a_module_that_exists():
    # Catches a pipeline script being renamed or moved without updating the seed.
    for _, (module, *_args) in STEPS:
        assert importlib.util.find_spec(module) is not None, module


def test_steps_run_in_pipeline_order_with_the_given_options():
    modules = [module for _, (module, *_args) in STEPS]
    assert modules == [
        "ingestion.pull_nba_data", "features.build_features",
        "models.train_win_probability", "simulation.monte_carlo",
    ]
    _, simulation_args = STEPS[-1]
    assert simulation_args[1:] == [
        "--season", "2025-26", "--cutoff-date", "2026-02-01", "--n-simulations", "10000",
    ]


def test_seed_stops_at_the_first_failing_step(monkeypatch):
    calls = []

    def fake_run(command):
        calls.append(command[2])
        return subprocess.CompletedProcess(command, returncode=1 if len(calls) == 2 else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="Step 2 failed"):
        run_steps(STEPS)

    # Steps 3 and 4 never ran, so nothing is trained on missing features.
    assert calls == ["ingestion.pull_nba_data", "features.build_features"]
