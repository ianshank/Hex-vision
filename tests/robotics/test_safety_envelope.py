"""Tests for mission-envelope validity and per-bound widening review."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.errors import FrozenKeyOverrideError
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.safety_envelope import SafetyEnvelopeGate


def _baseline_text(mission: dict[str, Any]) -> str:
    """Render the prior committed mission as TOML for the git-show stub."""
    import json

    return "\n".join(f"{key} = {json.dumps(value)}" for key, value in mission.items())


def _baseline_run(text: str) -> Any:
    """Return a git-like completed command result without relying on repository history."""
    return subprocess.CompletedProcess(["git"], 0, stdout=text, stderr="")


# Traceability: R-13
# Traceability: R-16
def test_safety_passes_valid_new_mission(passing_repo: Any) -> None:
    """A complete internally consistent new mission is measurable and passes."""
    root = passing_repo()
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert result.measurements["baseline"]["missions/patrol.toml"].startswith("new-")


@pytest.mark.parametrize(
    "bound",
    [
        "max_altitude_m",
        "max_horizontal_speed_ms",
        "max_tilt_deg",
        "geofence_radius_m",
        "rtl_battery_percent",
    ],
)
def test_safety_requires_numeric_bounds(passing_repo: Any, bound: str) -> None:
    """Every declared numeric bound rejects a non-numeric mission value."""
    root = passing_repo(mission={bound: "wrong"})
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert any(
        bound.upper() in item.id and item.severity is Severity.BLOCKER for item in result.findings
    )


@pytest.mark.parametrize(
    "mission",
    [
        {"rtl_battery_percent": -1},
        {"rtl_battery_percent": 101},
        {"max_tilt_deg": -1},
        {"max_tilt_deg": 91},
        {"geofence_radius_m": 0},
        {"max_altitude_m": 0},
        {"failsafe_action": "continue"},
    ],
)
def test_safety_enforces_configured_consistency_limits(
    passing_repo: Any, mission: dict[str, Any]
) -> None:
    """Percent, tilt, and positive-envelope policy boundaries are independently enforced."""
    root = passing_repo(mission=mission)
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert any(item.severity is Severity.BLOCKER for item in result.findings)


@pytest.mark.parametrize(
    ("bound", "baseline_value", "wider_value", "narrower_value"),
    [
        ("max_altitude_m", 80, 81, 79),
        ("max_horizontal_speed_ms", 8, 9, 7),
        ("max_tilt_deg", 25, 26, 24),
        ("geofence_radius_m", 250, 251, 249),
        # RTL is deliberately inverted: lowering the return threshold is wider.
        ("rtl_battery_percent", 30, 29, 31),
        ("failsafe_action", "terminate", "land", "terminate"),
    ],
)
def test_safety_widening_direction_is_per_bound(  # noqa: PLR0913 - direction cases are intentionally explicit.
    monkeypatch: pytest.MonkeyPatch,
    passing_repo: Any,
    bound: str,
    baseline_value: Any,
    wider_value: Any,
    narrower_value: Any,
) -> None:
    """Each configured permissive direction blocks only its widening side without a decision."""
    root = passing_repo(mission={bound: wider_value})
    baseline = {
        "max_altitude_m": 80,
        "max_horizontal_speed_ms": 8,
        "max_tilt_deg": 25,
        "geofence_radius_m": 250,
        "rtl_battery_percent": 30,
        "failsafe_action": "rtl",
    }
    baseline[bound] = baseline_value
    monkeypatch.setattr(
        "hexvision.robotics.safety_envelope.subprocess.run",
        lambda *_args, **_kwargs: _baseline_run(_baseline_text(baseline)),
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert any(
        "WIDENING" in item.id and item.severity is Severity.BLOCKER for item in result.findings
    )

    root = passing_repo(mission={bound: narrower_value})
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert not any("WIDENING" in item.id for item in result.findings)


# Traceability: R-14
def test_safety_widening_with_valid_decision_passes(
    monkeypatch: pytest.MonkeyPatch, passing_repo: Any
) -> None:
    """A declared, present decision log entry authorises an otherwise permissive change."""
    root = passing_repo(mission={"max_altitude_m": 81, "safety_decision_id": "DEC-42"})
    docs = root / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        "2026-08-22 | DEC-42 | approved altitude review | reviewer", encoding="utf-8"
    )
    baseline = {
        "max_altitude_m": 80,
        "max_horizontal_speed_ms": 8,
        "max_tilt_deg": 25,
        "geofence_radius_m": 250,
        "rtl_battery_percent": 30,
        "failsafe_action": "rtl",
    }
    monkeypatch.setattr(
        "hexvision.robotics.safety_envelope.subprocess.run",
        lambda *_args, **_kwargs: _baseline_run(_baseline_text(baseline)),
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED


def test_safety_records_invalid_baseline_as_new(
    monkeypatch: pytest.MonkeyPatch, passing_repo: Any
) -> None:
    """Unavailable or corrupt history never silently claims a baseline comparison passed."""
    root = passing_repo()
    monkeypatch.setattr(
        "hexvision.robotics.safety_envelope.subprocess.run",
        lambda *_args, **_kwargs: _baseline_run("not toml"),
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-invalid"


def test_safety_prefix_is_frozen(passing_repo: Any) -> None:
    """Environment overrides cannot lower safety policy outside reviewable configuration."""
    root = passing_repo()
    with pytest.raises(FrozenKeyOverrideError):
        load_config(
            root=root, env={"HEXVISION_ROBOTICS__SAFETY_ENVELOPE__GIT_TIMEOUT_SECONDS": "1"}
        )


def test_safety_blocks_invalid_mission_toml(passing_repo: Any) -> None:
    """An unreadable mission is BLOCKED rather than interpreted as a safe empty one."""
    root = passing_repo()
    (root / "missions/patrol.toml").write_text("invalid = [", encoding="utf-8")
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
