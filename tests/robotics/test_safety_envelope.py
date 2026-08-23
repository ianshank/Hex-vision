"""Tests for mission-envelope validity and per-bound widening review."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.errors import FrozenKeyOverrideError
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.safety_envelope import SafetyEnvelopeGate
from tests.robotics.boundaries import commit_file


def _baseline_text(mission: dict[str, Any]) -> str:
    """Render the prior committed mission as TOML for the git-show stub."""
    import json

    return "\n".join(f"{key} = {json.dumps(value)}" for key, value in mission.items())


# Traceability: R-13 [Internally consistent mission, Missing or invalid bound]
# Traceability: R-16 [Mission review, Hardware execution request]
def test_safety_passes_valid_new_mission(passing_repo: Any) -> None:
    """A complete internally consistent new mission is measurable and passes."""
    root = passing_repo()
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert not result.findings
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-absent-new-mission"
    assert (
        result.measurements["baseline_diagnostics"]["missions/patrol.toml"]["returncode"] == "128"
    )


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
def test_safety_widening_direction_is_per_bound(
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
    commit_file(root, Path("missions/patrol.toml"), _baseline_text(baseline))
    (root / "missions/patrol.toml").write_text(
        _baseline_text({**baseline, bound: wider_value}), encoding="utf-8"
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert result.findings[0].id == "SAFE-1-WIDENING"
    assert result.findings[0].severity is Severity.BLOCKER
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-read"

    (root / "missions/patrol.toml").write_text(
        _baseline_text({**baseline, bound: narrower_value}), encoding="utf-8"
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert not any("WIDENING" in item.id for item in result.findings)


# Traceability: R-14 [Authorized widening, Unauthorised or unavailable comparison]
def test_safety_widening_with_valid_decision_passes(passing_repo: Any) -> None:
    """A declared, present decision log entry authorises an otherwise permissive change."""
    root = passing_repo(mission={"max_altitude_m": 81, "safety_decision_id": "DEC-42"})
    docs = root / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        "2026-08-22 | DEC-42 | approved altitude review | reviewer | - | active | -",
        encoding="utf-8",
    )
    baseline = {
        "max_altitude_m": 80,
        "max_horizontal_speed_ms": 8,
        "max_tilt_deg": 25,
        "geofence_radius_m": 250,
        "rtl_battery_percent": 30,
        "failsafe_action": "rtl",
    }
    commit_file(root, Path("missions/patrol.toml"), _baseline_text(baseline))
    (root / "missions/patrol.toml").write_text(
        _baseline_text({**baseline, "max_altitude_m": 81, "safety_decision_id": "DEC-42"}),
        encoding="utf-8",
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert not result.findings
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-read"


def test_safety_blocks_malformed_baseline_with_redacted_diagnostics(passing_repo: Any) -> None:
    """Malformed committed baseline evidence blocks instead of being classified as a new mission."""
    root = passing_repo()
    commit_file(root, Path("missions/patrol.toml"), "unclosed = [")
    (root / "missions/patrol.toml").write_text(
        "max_altitude_m = 80\nmax_horizontal_speed_ms = 8\nmax_tilt_deg = 25\n"
        'geofence_radius_m = 250\nrtl_battery_percent = 30\nfailsafe_action = "rtl"\n',
        encoding="utf-8",
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "SAFE-1-BASELINE-MALFORMED"
    assert "baseline malformed" in result.findings[0].message
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-malformed"
    assert result.findings[0].context["exception_class"] == "TOMLDecodeError"


def test_safety_blocks_failed_baseline_command_and_redacts_stderr(passing_repo: Any) -> None:
    """A real failed configured comparison command is infrastructure evidence, never a pass."""
    root = passing_repo()
    (root / "hex-vision.toml").write_text(
        """
[robotics.safety_envelope]
baseline_command = ["git", "show", "MISSING:{path}"]
""",
        encoding="utf-8",
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "SAFE-1-BASELINE-COMMAND-FAILED"
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-command-failed"
    assert result.findings[0].context["returncode"] == "128"


def test_safety_new_mission_policy_can_require_reviewed_decision(passing_repo: Any) -> None:
    """A reviewed configuration can require an explicit decision for absent baseline objects."""
    root = passing_repo()
    (root / "hex-vision.toml").write_text(
        """
[robotics.safety_envelope]
new_mission_requires_decision = true
""",
        encoding="utf-8",
    )
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.FAILED
    assert result.findings[0].id == "SAFE-1-NEW-MISSION-DECISION"
    assert "new mission" in result.findings[0].message
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-absent-new-mission"


def test_safety_timeout_is_blocked_with_secret_redacted_diagnostics(
    monkeypatch: pytest.MonkeyPatch, passing_repo: Any
) -> None:
    """A timeout is the only mocked process condition and its diagnostic stays bounded."""
    root = passing_repo()
    secret = "token=super-secret-value"  # noqa: S105 - redaction test fixture.

    def timed_out(*_args: Any, **_kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(["git"], 1, stderr=secret)

    monkeypatch.setattr("hexvision.robotics.safety_envelope.subprocess.run", timed_out)
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "SAFE-1-BASELINE-TIMEOUT"
    assert result.measurements["baseline"]["missions/patrol.toml"] == "baseline-timeout"
    assert secret not in result.findings[0].context["stderr"]
    assert "[REDACTED]" in result.findings[0].context["stderr"]


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
