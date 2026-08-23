"""Make hardware-in-the-loop availability a named, auditable condition.

Hardware may not be attached to every CI worker, but its absence cannot quietly
turn a physical validation gate green. This gate executes configured runners when
present and otherwise requires a decision-log entry that names the omitted gate.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, Final

from hexvision.config import Config
from hexvision.decision_log import load_decision_log_schema, read_decision_log
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger

__all__ = ["HardwareInLoopGate"]

_LOG: Final = get_logger(__name__)


class HardwareInLoopGate(Gate):
    """Run present hardware checks and surface every absent runner as a declared decision."""

    @property
    def name(self) -> str:
        """Return the stable hardware-validation gate name used in audit output."""
        return "hardware-in-loop"

    @property
    def clause(self) -> str:
        """Return the hardware-evidence clause this check implements."""
        return "R-HIL"

    def check(self, config: Config) -> GateResult:
        """Probe commands by executable presence, run present ones, and aggregate their evidence."""
        try:
            policy = _policy(config, self.clause)
        except (TypeError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="hardware-in-loop policy is not usable",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        missing: dict[str, str | None] = {}
        executed: dict[str, int] = {}
        for gate_name in policy["optional_gates"]:
            command = policy["runners"].get(gate_name)
            if not isinstance(command, list) or not command or not isinstance(command[0], str):
                return GateResult.blocked(
                    self.name,
                    summary="hardware-in-loop runner is not configured",
                    reason=f"optional gate {gate_name!r} has no configured command",
                    clause=self.clause,
                )
            runner = command[0]
            if shutil.which(runner) is None:
                missing[gate_name] = _authorising_decision(config, policy, gate_name)
                continue
            try:
                completed = subprocess.run(
                    command,
                    cwd=config.root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=policy["timeout_seconds"],
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return GateResult.blocked(
                    self.name,
                    summary="hardware-in-loop runner could not execute",
                    reason=f"runner for {gate_name!r} could not execute: {exc}",
                    clause=self.clause,
                )
            executed[gate_name] = completed.returncode
            if completed.returncode != 0:
                findings.append(
                    Finding(
                        id=f"HIL-{gate_name.upper()}-FAILED",
                        severity=Severity.MAJOR,
                        message=(
                            f"hardware runner {gate_name!r} exited with status "
                            f"{completed.returncode}"
                        ),
                        clause=self.clause,
                        disposition=(
                            "Restore the hardware scenario and re-run its configured command."
                        ),
                    )
                )
        measurements: dict[str, Any] = {"executed": executed, "missing": missing}
        _LOG.info(
            "hardware runners assessed", extra={"executed": len(executed), "missing": len(missing)}
        )
        if missing:
            unauthorised = [gate for gate, decision in missing.items() if decision is None]
            decision_id = ",".join(decision for decision in missing.values() if decision) or None
            base = GateResult.skipped_declared(
                self.name,
                summary="one or more configured hardware runners are absent",
                reason=f"absent configured hardware runners: {', '.join(sorted(missing))}",
                decision_id=decision_id if not unauthorised else None,
                clause=self.clause,
            )
            combined_findings = (*base.findings, *findings)
            return GateResult(
                gate=base.gate,
                status=base.status,
                clause=base.clause,
                summary=base.summary,
                findings=GateResult._sorted(combined_findings),
                measurements={**dict(base.measurements), **measurements},
            )
        if findings:
            return GateResult.failed(
                self.name,
                summary="a configured hardware-in-loop runner failed",
                findings=findings,
                clause=self.clause,
                measurements=measurements,
            )
        return GateResult.passed(
            self.name,
            summary="all configured hardware-in-loop runners completed successfully",
            clause=self.clause,
            measurements=measurements,
        )


def _policy(config: Config, clause: str) -> dict[str, Any]:
    """Read variable runner and authorisation policy from the configuration engine."""
    keys = {
        "optional_gates": "robotics.hardware_in_loop.optional_gates",
        "runners": "robotics.hardware_in_loop.runners",
        "decision_log_path": "robotics.hardware_in_loop.decision_log_path",
        "decision_id_pattern": "robotics.hardware_in_loop.decision_id_pattern",
        "timeout_seconds": "robotics.hardware_in_loop.timeout_seconds",
    }
    policy = {name: config.require(key, clause=clause) for name, key in keys.items()}
    if (
        not isinstance(policy["optional_gates"], list)
        or not policy["optional_gates"]
        or not all(isinstance(gate, str) and gate for gate in policy["optional_gates"])
    ):
        raise ValueError("optional hardware gates must be non-empty strings")
    if not isinstance(policy["runners"], Mapping):
        raise TypeError("hardware runners must be a mapping")
    if not isinstance(policy["timeout_seconds"], int | float) or policy["timeout_seconds"] <= 0:
        raise ValueError("hardware runner timeout must be positive")
    return policy


def _authorising_decision(config: Config, policy: Mapping[str, Any], gate_name: str) -> str | None:
    """Find a valid record that explicitly names the absent gate and configured ID."""
    path = config.root / str(policy["decision_log_path"])
    try:
        schema = load_decision_log_schema(config)
        records = read_decision_log(path, schema).records
    except OSError:
        return None
    pattern = re.compile(str(policy["decision_id_pattern"]))
    for record in records:
        identifier = record.value(schema, schema.identifier_column)
        if gate_name in schema.delimiter.join(record.cells) and pattern.fullmatch(identifier):
            return identifier
    return None
