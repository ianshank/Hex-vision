"""Protect declared mission safety envelopes from unreviewed widening.

The gate only reads configuration; it never sends a vehicle command. Its value is
making a safety-bound change visible before it reaches a flight branch, including
bounds such as RTL battery percentage whose permissive direction is downward.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TypeGuard

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger

__all__ = ["SafetyEnvelopeGate"]

_LOG: Final = get_logger(__name__)


class SafetyEnvelopeGate(Gate):
    """Validate missions and require a decision record for a permissive bound change."""

    @property
    def name(self) -> str:
        """Return the stable mission-safety gate name used in audit output."""
        return "safety-envelope"

    @property
    def clause(self) -> str:
        """Return the flight-envelope clause this check implements."""
        return "R-SAFE"

    def check(self, config: Config) -> GateResult:
        """Assess every configured mission, retaining baseline availability in measurements."""
        try:
            policy = _policy(config, self.clause)
            paths = tuple(
                path for path in config.root.glob(policy["mission_glob"]) if path.is_file()
            )
        except (OSError, TypeError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="mission safety inputs could not be read",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        baseline_status: dict[str, str] = {}
        for index, path in enumerate(sorted(paths), 1):
            try:
                current = _read_toml(path)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                return GateResult.blocked(
                    self.name,
                    summary="mission configuration could not be parsed",
                    reason=f"cannot parse {path}: {exc}",
                    clause=self.clause,
                )
            location = str(path.relative_to(config.root))
            findings.extend(_validity_findings(current, index, location, policy, self.clause))
            if policy["widening_required"]:
                baseline, status = self._baseline(config, path, policy)
                baseline_status[location] = status
                if baseline is not None:
                    findings.extend(
                        self._widening_findings(current, baseline, index, location, config, policy)
                    )
        measurements = {"missions": len(paths), "baseline": baseline_status}
        _LOG.info(
            "mission safety assessed", extra={"missions": len(paths), "findings": len(findings)}
        )
        if findings:
            return GateResult.failed(
                self.name,
                summary="mission safety envelope findings require attention",
                findings=findings,
                clause=self.clause,
                measurements=measurements,
            )
        return GateResult.passed(
            self.name,
            summary="mission safety envelopes are valid and reviewed",
            clause=self.clause,
            measurements=measurements,
        )

    def _baseline(
        self, config: Config, path: Path, policy: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """Read HEAD's same path, treating unavailable history as an explicitly new mission."""
        relative = path.relative_to(config.root).as_posix()
        command = [str(part).format(path=relative) for part in policy["baseline_command"]]
        try:
            completed = subprocess.run(
                command,
                cwd=config.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=policy["git_timeout_seconds"],
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, "new-or-git-unavailable"
        if completed.returncode != 0:
            return None, "new-or-baseline-unavailable"
        try:
            return tomllib.loads(completed.stdout), "baseline-read"
        except tomllib.TOMLDecodeError:
            return None, "baseline-invalid"

    def _widening_findings(  # noqa: PLR0913 - compare current/baseline policy explicitly.
        self,
        current: Mapping[str, Any],
        baseline: Mapping[str, Any],
        index: int,
        location: str,
        config: Config,
        policy: Mapping[str, Any],
    ) -> list[Finding]:
        """Require an extant decision ID only for configured permissive directions."""
        widened = [
            bound
            for bound, direction in policy["directions"].items()
            if _is_widened(
                current.get(bound), baseline.get(bound), direction, policy["failsafe_strength"]
            )
        ]
        if not widened:
            return []
        decision_id = current.get(policy["decision_id_field"])
        if _decision_exists(config, policy, decision_id):
            return []
        joined_bounds = ", ".join(sorted(widened))
        return [
            Finding(
                id=f"SAFE-{index}-WIDENING",
                severity=Severity.BLOCKER,
                message=(
                    f"permissive change to {joined_bounds} has no authorising decision-log entry"
                ),
                location=location,
                clause=self.clause,
                disposition=(
                    "Record a valid decision ID in the mission and its configured decision log."
                ),
                context={"widened_bounds": widened, "decision_id": decision_id},
            )
        ]


def _policy(config: Config, clause: str) -> dict[str, Any]:
    """Resolve all mission policy so no safety threshold is baked into Python."""
    keys = {
        "mission_glob": "robotics.safety_envelope.mission_config_glob",
        "required_bounds": "robotics.safety_envelope.required_bounds",
        "allowed_actions": "robotics.safety_envelope.allowed_failsafe_actions",
        "numeric_limits": "robotics.safety_envelope.numeric_limits",
        "directions": "robotics.safety_envelope.permissive_directions",
        "failsafe_strength": "robotics.safety_envelope.failsafe_strength",
        "widening_required": "robotics.safety_envelope.widening_requires_decision",
        "decision_id_field": "robotics.safety_envelope.decision_id_field",
        "decision_log_path": "robotics.safety_envelope.decision_log_path",
        "decision_id_pattern": "robotics.safety_envelope.decision_id_pattern",
        "baseline_command": "robotics.safety_envelope.baseline_command",
        "git_timeout_seconds": "robotics.safety_envelope.git_timeout_seconds",
    }
    policy = {name: config.require(key, clause=clause) for name, key in keys.items()}
    if (
        not isinstance(policy["required_bounds"], list)
        or not policy["required_bounds"]
        or not all(isinstance(bound, str) and bound for bound in policy["required_bounds"])
    ):
        raise ValueError("required safety bounds must be non-empty strings")
    if (
        not isinstance(policy["allowed_actions"], list)
        or not policy["allowed_actions"]
        or not all(isinstance(action, str) and action for action in policy["allowed_actions"])
    ):
        raise ValueError("allowed failsafe actions must be non-empty strings")
    if not isinstance(policy["numeric_limits"], Mapping) or not isinstance(
        policy["directions"], Mapping
    ):
        raise TypeError("safety numeric limits and permissive directions must be tables")
    if (
        not isinstance(policy["baseline_command"], list)
        or not policy["baseline_command"]
        or not all(isinstance(part, str) and part for part in policy["baseline_command"])
    ):
        raise ValueError("baseline command must be a non-empty command list")
    if not _numeric(policy["git_timeout_seconds"]) or float(policy["git_timeout_seconds"]) <= 0:
        raise ValueError("git baseline timeout must be positive")
    return policy


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a mission file as TOML, preserving parsing errors for a fail-closed caller."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _validity_findings(
    mission: Mapping[str, Any],
    index: int,
    location: str,
    policy: Mapping[str, Any],
    clause: str,
) -> list[Finding]:
    """Validate required values and configured numeric consistency ranges.

    Each range is policy, not code: the declarations explain that battery percent
    is a percentage, tilt is an angle, and altitude/geofence must describe a
    non-zero operating envelope while allowing certification policy to evolve.
    """
    findings: list[Finding] = []
    for bound in policy["required_bounds"]:
        value = mission.get(bound)
        if bound == "failsafe_action":
            if value not in policy["allowed_actions"]:
                findings.append(
                    _finding(
                        f"SAFE-{index}-{bound.upper()}",
                        Severity.BLOCKER,
                        "failsafe action must be one of the configured allowed actions",
                        location,
                        clause,
                        "Set a reviewed failsafe action from the configured allowlist.",
                    )
                )
        elif not _numeric(value):
            findings.append(
                _finding(
                    f"SAFE-{index}-{bound.upper()}",
                    Severity.BLOCKER,
                    f"required safety bound {bound!r} must be numeric",
                    location,
                    clause,
                    "Record a numeric reviewed safety bound.",
                )
            )
    for bound, limits in policy["numeric_limits"].items():
        value = mission.get(bound)
        if not _numeric(value) or not isinstance(limits, Mapping):
            continue
        minimum = limits.get("minimum")
        maximum = limits.get("maximum")
        exclusive_minimum = limits.get("exclusive_minimum")
        if (
            (_numeric(minimum) and float(value) < float(minimum))
            or (_numeric(maximum) and float(value) > float(maximum))
            or (_numeric(exclusive_minimum) and float(value) <= float(exclusive_minimum))
        ):
            findings.append(
                _finding(
                    f"SAFE-{index}-{str(bound).upper()}-RANGE",
                    Severity.BLOCKER,
                    f"safety bound {bound!r} is outside its configured internally consistent range",
                    location,
                    clause,
                    "Set the bound inside its configured safety range.",
                )
            )
    return findings


def _is_widened(current: Any, baseline: Any, direction: Any, failsafe_strength: Any) -> bool:
    """Compare a single bound using its configured permissive direction.

    Altitude, speed, tilt and geofence are wider when larger; RTL battery is
    wider when lower; fail-safe actions use an ordered safety-strength policy.
    Per-bound directions prevent a generic 'larger is worse' comparison from
    reversing the battery rule.
    """
    if direction == "higher":
        return _numeric(current) and _numeric(baseline) and float(current) > float(baseline)
    if direction == "lower":
        return _numeric(current) and _numeric(baseline) and float(current) < float(baseline)
    if direction == "weaker" and isinstance(failsafe_strength, list):
        try:
            return failsafe_strength.index(current) > failsafe_strength.index(baseline)
        except ValueError:
            return False
    return False


def _decision_exists(config: Config, policy: Mapping[str, Any], decision_id: Any) -> bool:
    """Confirm that a mission's decision ID is syntactically valid and recorded adjacent to code."""
    if not isinstance(decision_id, str) or not re.fullmatch(
        str(policy["decision_id_pattern"]), decision_id
    ):
        return False
    path = config.root / str(policy["decision_log_path"])
    try:
        return decision_id in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _numeric(value: Any) -> TypeGuard[int | float]:
    """Recognise numeric TOML values without allowing booleans as safety values."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _finding(  # noqa: PLR0913 - Finding fields stay explicit for audit readability.
    identifier: str,
    severity: Severity,
    message: str,
    location: str,
    clause: str,
    disposition: str,
) -> Finding:
    """Create a consistently actionable safety finding."""
    return Finding(
        id=identifier,
        severity=severity,
        message=message,
        location=location,
        clause=clause,
        disposition=disposition,
    )
