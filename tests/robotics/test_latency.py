"""Tests for device-specific latency-budget evidence."""

from __future__ import annotations

from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.latency import LatencyBudgetGate


# Traceability: R-11 [Measurement within configured budget, Ungoverned latency claim]
def test_latency_pass_and_headroom(passing_repo: Any) -> None:
    """Passing models retain measured margin for later audit interpretation."""
    root = passing_repo()
    result = LatencyBudgetGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert result.measurements["headroom"]["models/detector/model-card.md"] == 3.0


@pytest.mark.parametrize(
    ("measured", "status", "finding"),
    [(33.0, GateStatus.PASSED, None), (34.0, GateStatus.FAILED, "OVER")],
)
def test_latency_budget_boundary(
    passing_repo: Any, measured: float, status: GateStatus, finding: str | None
) -> None:
    """Exact budget is acceptable and one unit above is a failed measurement."""
    root = passing_repo(card={"latency_p95_ms": measured})
    result = LatencyBudgetGate().check(load_config(root=root, env={}))
    assert result.status is status
    if finding:
        assert any(
            finding in item.id and item.severity is Severity.MAJOR for item in result.findings
        )
    assert result.measurements["headroom"]["models/detector/model-card.md"] == 33.0 - measured


@pytest.mark.parametrize(
    ("card", "finding"),
    [
        ({"latency_p95_ms": "unknown"}, "MEASUREMENT"),
        ({"latency_percentile": "95"}, "PERCENTILE"),
        ({"latency_percentile": 90}, "PERCENTILE"),
        ({"target_runtime": "unbudgeted"}, "BUDGET"),
        ({"latency_p95_ms": "infinite"}, "MEASUREMENT"),
    ],
)
def test_latency_blocks_unusable_evidence(
    passing_repo: Any, card: dict[str, Any], finding: str
) -> None:
    """Missing measurement, percentile, or budget is a blocker, not an assumed pass."""
    root = passing_repo(card=card)
    result = LatencyBudgetGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert any(finding in item.id and item.severity is Severity.BLOCKER for item in result.findings)


def test_latency_blocks_unreadable_model_card(passing_repo: Any) -> None:
    """A latency gate sharing a malformed card fails closed through the documented loader."""
    root = passing_repo()
    (root / "models/detector/model-card.md").write_text("bad", encoding="utf-8")
    result = LatencyBudgetGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
