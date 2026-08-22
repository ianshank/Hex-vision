"""Tests for versioned deterministic evaluation records."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.determinism import DeterminismGate


def test_determinism_passes_with_identical_seeds(passing_repo: Any) -> None:
    """Matching results only count after every seed is confirmed identical."""
    root = passing_repo()
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert result.measurements["spread"]["detector"] < 0.001


@pytest.mark.parametrize("seed", ["python_seed", "numpy_seed", "framework_seed"])
def test_determinism_blocks_different_seed_despite_matching_metric(
    passing_repo: Any, seed: str
) -> None:
    """Equal metrics from different seeds are explicitly the wrong determinism experiment."""
    runs = [
        {"metric_value": 0.9, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
        {"metric_value": 0.9, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
        {"metric_value": 0.9, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
    ]
    runs[1][seed] = 7
    root = passing_repo(runs=runs)
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert any(
        seed.upper() in item.id and item.severity is Severity.BLOCKER for item in result.findings
    )


@pytest.mark.parametrize("seed", ["python_seed", "numpy_seed", "framework_seed"])
def test_determinism_blocks_missing_seed(passing_repo: Any, seed: str) -> None:
    """Every run must state every seed field, even when a metric is recorded."""
    runs = [
        {"metric_value": 0.9, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42}
        for _ in range(3)
    ]
    del runs[0][seed]
    root = passing_repo(runs=runs)
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert any(seed.upper() in item.id and "MISSING" in item.id for item in result.findings)


@pytest.mark.parametrize(
    ("runs", "finding", "severity"),
    [
        (
            [{"metric_value": 0.9, "python_seed": 1, "numpy_seed": 1, "framework_seed": 1}],
            "RUNS",
            Severity.BLOCKER,
        ),
        (
            [{"metric_value": 0.9, "python_seed": 1, "numpy_seed": 1, "framework_seed": 1}] * 3,
            "SPREAD",
            Severity.MAJOR,
        ),
    ],
)
def test_determinism_run_count_and_metric_spread(
    passing_repo: Any, runs: list[dict[str, Any]], finding: str, severity: Severity
) -> None:
    """Insufficient evidence blocks while observed over-tolerance spread fails."""
    if finding == "SPREAD":
        runs[1] = {**runs[1], "metric_value": 0.91}
    root = passing_repo(runs=runs)
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert any(finding in item.id and item.severity is severity for item in result.findings)


@pytest.mark.parametrize(
    "record",
    [
        {"schema_version": 2},
        {"runs": "not-a-list"},
        {
            "runs": [
                {"metric_value": "bad", "python_seed": 1, "numpy_seed": 1, "framework_seed": 1}
            ]
            * 3
        },
        {
            "runs": [
                {
                    "metric_value": float("inf"),
                    "python_seed": 1,
                    "numpy_seed": 1,
                    "framework_seed": 1,
                }
            ]
            * 3
        },
    ],
)
def test_determinism_blocks_invalid_record_shapes(
    passing_repo: Any, record: dict[str, Any]
) -> None:
    """Unsupported schemas and non-numeric metrics cannot be evaluated safely."""
    root = passing_repo(record=record)
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert any(item.severity is Severity.BLOCKER for item in result.findings)


def test_determinism_blocks_missing_record(passing_repo: Any) -> None:
    """A missing record means the gate could not inspect determinism at all."""
    root = passing_repo()
    (root / "models/detector/eval-runs.json").unlink()
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED


def test_determinism_blocks_duplicate_model_records(passing_repo: Any) -> None:
    """Two records for one model are ambiguous evidence and cannot silently select one."""
    root = passing_repo()
    duplicate = root / "models/detector/second"
    duplicate.mkdir()
    record = json.loads((root / "models/detector/eval-runs.json").read_text())
    (duplicate / "eval-runs.json").write_text(json.dumps(record), encoding="utf-8")
    result = DeterminismGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
