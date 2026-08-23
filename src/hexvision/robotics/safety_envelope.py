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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeGuard

from hexvision.config import Config
from hexvision.decision_log import decision_ids
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.observability import get_logger, log_verdict
from hexvision.robotics.diagnostics import command_identity, diagnostic_policy, redacted_excerpt
from hexvision.robotics.filesystem import trusted_regular_file

__all__ = ["SafetyEnvelopeGate"]

_LOG: Final = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Baseline:
    """One explicitly classified attempt to obtain a mission's baseline."""

    kind: str
    status: str
    document: dict[str, Any] | None
    diagnostic: Mapping[str, str]


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
            diagnostics = diagnostic_policy(config, self.clause)
            paths = tuple(
                trusted_regular_file(config.root, path, "mission configuration")
                for path in config.root.glob(policy["mission_glob"])
                if path.is_file()
            )
        except (OSError, TypeError, ValueError) as exc:
            return self._finish(
                GateResult.blocked(
                    self.name,
                    summary="mission safety inputs could not be read",
                    reason=str(exc),
                    clause=self.clause,
                ),
                "policy-or-discovery-blocked",
            )
        findings: list[Finding] = []
        baseline_status: dict[str, str] = {}
        baseline_diagnostics: dict[str, Mapping[str, str]] = {}
        _LOG.info(
            "mission safety assessment started",
            extra={"gate": self.name, "clause": self.clause, "missions": len(paths)},
        )
        for index, path in enumerate(sorted(paths), 1):
            try:
                current = _read_toml(path)
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                return self._finish(
                    GateResult.blocked(
                        self.name,
                        summary="mission configuration could not be parsed",
                        reason=f"cannot parse {path}: {exc}",
                        clause=self.clause,
                    ),
                    "mission-parse-blocked",
                )
            location = str(path.relative_to(config.root))
            findings.extend(_validity_findings(current, index, location, policy, self.clause))
            if policy["widening_required"]:
                baseline = self._baseline(config, path, policy, diagnostics)
                baseline_status[location] = baseline.status
                baseline_diagnostics[location] = baseline.diagnostic
                if baseline.kind == "blocked":
                    _LOG.error(
                        "mission baseline unavailable",
                        extra={
                            "gate": self.name,
                            "clause": self.clause,
                            "location": location,
                            "reason": baseline.status,
                            **baseline.diagnostic,
                        },
                    )
                    return self._finish(
                        _baseline_blocked_result(
                            self.name,
                            self.clause,
                            index,
                            location,
                            baseline,
                            {
                                "missions": len(paths),
                                "baseline": baseline_status,
                                "baseline_diagnostics": baseline_diagnostics,
                            },
                        ),
                        baseline.status,
                    )
                if baseline.kind == "new-mission":
                    _LOG.warning(
                        "mission baseline is absent; applying new-mission policy",
                        extra={
                            "gate": self.name,
                            "clause": self.clause,
                            "location": location,
                            "requires_decision": policy["new_mission_requires_decision"],
                            **baseline.diagnostic,
                        },
                    )
                    findings.extend(
                        self._new_mission_findings(current, index, location, config, policy)
                    )
                elif baseline.document is not None:
                    findings.extend(
                        self._widening_findings(
                            current, baseline.document, index, location, config, policy
                        )
                    )
        measurements = {
            "missions": len(paths),
            "baseline": baseline_status,
            "baseline_diagnostics": baseline_diagnostics,
        }
        _LOG.info(
            "mission safety assessed", extra={"missions": len(paths), "findings": len(findings)}
        )
        if findings:
            return self._finish(
                GateResult.failed(
                    self.name,
                    summary="mission safety envelope findings require attention",
                    findings=findings,
                    clause=self.clause,
                    measurements=measurements,
                ),
                "findings",
            )
        return self._finish(
            GateResult.passed(
                self.name,
                summary="mission safety envelopes are valid and reviewed",
                clause=self.clause,
                measurements=measurements,
            ),
            "reviewed",
        )

    def _baseline(
        self,
        config: Config,
        path: Path,
        policy: Mapping[str, Any],
        diagnostics: Mapping[str, Any],
    ) -> _Baseline:
        """Read HEAD's same path without conflating absence and runner failure."""
        relative = path.relative_to(config.root).as_posix()
        command = [str(part).format(path=relative) for part in policy["baseline_command"]]
        command_name = command_identity(command, diagnostics)
        try:
            completed = subprocess.run(
                command,
                cwd=config.root,
                check=False,
                capture_output=True,
                text=True,
                encoding=diagnostics["encoding"],
                errors=diagnostics["decode_errors"],
                timeout=policy["git_timeout_seconds"],
            )
        except subprocess.TimeoutExpired as exc:
            diagnostic = {
                "command": command_name,
                "exception_class": type(exc).__name__,
                "stderr": redacted_excerpt(exc.stderr or "", diagnostics),
            }
            return _Baseline("blocked", "baseline-timeout", None, diagnostic)
        except OSError as exc:
            diagnostic = {
                "command": command_name,
                "exception_class": type(exc).__name__,
                "stderr": redacted_excerpt(str(exc), diagnostics),
            }
            return _Baseline("blocked", "baseline-command-unavailable", None, diagnostic)
        stderr = redacted_excerpt(completed.stderr, diagnostics)
        diagnostic = {
            "command": command_name,
            "returncode": str(completed.returncode),
            "stderr": stderr,
        }
        if completed.returncode != 0:
            is_new_mission = (
                completed.returncode in policy["new_mission_returncodes"]
                and re.fullmatch(
                    str(policy["new_mission_stderr_pattern"]), completed.stderr.strip()
                )
                is not None
            )
            if is_new_mission:
                return _Baseline("new-mission", "baseline-absent-new-mission", None, diagnostic)
            return _Baseline("blocked", "baseline-command-failed", None, diagnostic)
        try:
            return _Baseline(
                "baseline", "baseline-read", tomllib.loads(completed.stdout), diagnostic
            )
        except tomllib.TOMLDecodeError as exc:
            return _Baseline(
                "blocked",
                "baseline-malformed",
                None,
                {**diagnostic, "exception_class": type(exc).__name__},
            )

    def _new_mission_findings(
        self,
        current: Mapping[str, Any],
        index: int,
        location: str,
        config: Config,
        policy: Mapping[str, Any],
    ) -> list[Finding]:
        """Require configured authority when a mission has no baseline object."""
        if not policy["new_mission_requires_decision"] or _decision_exists(
            config, policy, current.get(policy["decision_id_field"])
        ):
            return []
        return [
            Finding(
                id=f"SAFE-{index}-NEW-MISSION-DECISION",
                severity=Severity.BLOCKER,
                message="new mission has no authorising decision-log entry",
                location=location,
                clause=self.clause,
                disposition=(
                    "Record a valid decision ID in the new mission and its configured decision log."
                ),
                context={"baseline": "absent-new-mission"},
            )
        ]

    def _finish(self, result: GateResult, decision: str) -> GateResult:
        """Log every terminal verdict with the decision path that produced it."""
        log_verdict(
            _LOG,
            gate=self.name,
            status=result.status.value,
            clause=self.clause,
            decision=decision,
            findings=len(result.findings),
        )
        return result

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
        "new_mission_returncodes": "robotics.safety_envelope.new_mission_returncodes",
        "new_mission_stderr_pattern": "robotics.safety_envelope.new_mission_stderr_pattern",
        "new_mission_requires_decision": "robotics.safety_envelope.new_mission_requires_decision",
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
    if (
        not isinstance(policy["new_mission_returncodes"], list)
        or not policy["new_mission_returncodes"]
        or not all(isinstance(code, int) for code in policy["new_mission_returncodes"])
    ):
        raise ValueError("new-mission baseline return codes must be non-empty integers")
    if not isinstance(policy["new_mission_stderr_pattern"], str):
        raise TypeError("new-mission baseline stderr pattern must be a string")
    try:
        re.compile(policy["new_mission_stderr_pattern"])
    except re.error as exc:
        raise ValueError(f"new-mission baseline stderr pattern is invalid: {exc}") from exc
    if not isinstance(policy["new_mission_requires_decision"], bool):
        raise TypeError("new-mission decision policy must be boolean")
    return policy


def _baseline_blocked_result(  # noqa: PLR0913 - named baseline evidence is intentionally explicit.
    gate: str,
    clause: str,
    index: int,
    location: str,
    baseline: _Baseline,
    measurements: Mapping[str, Any],
) -> GateResult:
    """Build a named fail-closed result for an unreadable comparison baseline."""
    return GateResult(
        gate=gate,
        status=GateStatus.BLOCKED,
        clause=clause,
        summary="mission baseline comparison could not be completed",
        findings=(
            Finding(
                id=f"SAFE-{index}-{baseline.status.upper().replace('-', '-')}",
                severity=Severity.BLOCKER,
                message=(
                    "mission baseline comparison is unavailable: "
                    f"{baseline.status.replace('-', ' ')}"
                ),
                location=location,
                clause=clause,
                disposition=(
                    "Restore a readable baseline comparison or record the mission as a "
                    "new reviewed mission."
                ),
                context=dict(baseline.diagnostic),
            ),
        ),
        measurements=dict(measurements),
    )


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
    """Confirm that a mission's ID is valid and occurs in a real configured log record."""
    if not isinstance(decision_id, str) or not re.fullmatch(
        str(policy["decision_id_pattern"]), decision_id
    ):
        return False
    path = config.root / str(policy["decision_log_path"])
    try:
        return decision_id in decision_ids(config, path)
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
