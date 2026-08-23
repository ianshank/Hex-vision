"""Make hardware-in-the-loop availability a named, auditable condition.

Hardware may not be attached to every CI worker, but its absence cannot quietly
turn a physical validation gate green. This gate executes configured runners
when present and otherwise resolves each absence through the one shared
authority verifier (DEC-016), by exact equality on the subject
``hardware-in-loop:<runner>`` — never by matching a runner name as a substring
of a record row, which was the exploit PEER-REVIEW-3 demonstrated.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any, Final

from hexvision.authority import (
    SUBJECT_SEPARATOR,
    AuthorityDenial,
    VerifiedAuthority,
    verify_authority,
)
from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.observability import get_logger, log_verdict
from hexvision.robotics.diagnostics import command_identity, diagnostic_policy, redacted_excerpt
from hexvision.robotics.filesystem import trusted_regular_file

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

    def check(self, config: Config) -> GateResult:  # noqa: PLR0911 - each terminal verdict returns independently.
        """Probe commands by executable presence, run present ones, and aggregate their evidence."""
        try:
            policy = _policy(config, self.clause)
            diagnostics_policy = diagnostic_policy(config, self.clause)
        except (TypeError, ValueError) as exc:
            return self._finish(
                GateResult.blocked(
                    self.name,
                    summary="hardware-in-loop policy is not usable",
                    reason=str(exc),
                    clause=self.clause,
                ),
                "policy-blocked",
            )
        findings: list[Finding] = []
        missing: dict[str, VerifiedAuthority | None] = {}
        denials: dict[str, str] = {}
        executed: dict[str, int] = {}
        runner_diagnostics: dict[str, Mapping[str, str]] = {}
        _LOG.info(
            "hardware runner assessment started",
            extra={
                "gate": self.name,
                "clause": self.clause,
                "runners": len(policy["optional_gates"]),
            },
        )
        for gate_name in policy["optional_gates"]:
            command = policy["runners"].get(gate_name)
            if not isinstance(command, list) or not command or not isinstance(command[0], str):
                return self._finish(
                    GateResult.blocked(
                        self.name,
                        summary="hardware-in-loop runner is not configured",
                        reason=f"optional gate {gate_name!r} has no configured command",
                        clause=self.clause,
                    ),
                    "runner-not-configured",
                )
            runner = command[0]
            if shutil.which(runner) is None:
                try:
                    verdict = _authorising_decision(config, self.name, self.clause, gate_name)
                except (OSError, ValueError) as exc:
                    # An unreadable, undecodable, or untrusted ledger is "could
                    # not look", never "no decision was recorded": collapsing the
                    # two would let an operator read an evidence failure as an
                    # unauthorised-but-honest absence.
                    return self._finish(
                        GateResult.blocked(
                            self.name,
                            summary="hardware absence authority could not be verified",
                            reason=(
                                f"decision-log evidence for absent runner {gate_name!r} "
                                f"is unusable: {exc}"
                            ),
                            clause=self.clause,
                            remediation=(
                                "Restore a readable, trusted decision log and re-run "
                                "the hardware-in-loop gate."
                            ),
                        ),
                        "authority-evidence-unavailable",
                    )
                if isinstance(verdict, AuthorityDenial):
                    # A denial that ran to completion is preserved with its
                    # reason: "superseded" or "log-invalid" must not read as
                    # "no decision was ever recorded" when the gate blocks.
                    denials[gate_name] = f"{verdict.reason.value}: {verdict.detail}"
                    missing[gate_name] = None
                else:
                    missing[gate_name] = verdict
                authority = missing[gate_name]
                _LOG.warning(
                    "configured hardware runner is absent",
                    extra={
                        "gate": self.name,
                        "clause": self.clause,
                        "runner": gate_name,
                        "command": command_identity(command, diagnostics_policy),
                        "decision_id": authority.decision_id if authority else None,
                        "denial": denials.get(gate_name),
                    },
                )
                continue
            command_name = command_identity(command, diagnostics_policy)
            try:
                completed = subprocess.run(
                    command,
                    cwd=config.root,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding=diagnostics_policy["encoding"],
                    errors=diagnostics_policy["decode_errors"],
                    timeout=policy["timeout_seconds"],
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                runner_diagnostics[gate_name] = {
                    "command": command_name,
                    "exception_class": type(exc).__name__,
                    "stderr": redacted_excerpt(
                        getattr(exc, "stderr", None) or str(exc), diagnostics_policy
                    ),
                }
                _LOG.error(
                    "hardware runner could not execute",
                    extra={
                        "gate": self.name,
                        "clause": self.clause,
                        "runner": gate_name,
                        **runner_diagnostics[gate_name],
                    },
                )
                return self._finish(
                    _execution_blocked_result(
                        self.name,
                        self.clause,
                        gate_name,
                        runner_diagnostics[gate_name],
                        {
                            "executed": executed,
                            "missing": _missing_ids(missing),
                            "diagnostics": runner_diagnostics,
                        },
                    ),
                    "runner-execution-unavailable",
                )
            executed[gate_name] = completed.returncode
            runner_diagnostics[gate_name] = {
                "command": command_name,
                "returncode": str(completed.returncode),
                "stderr": redacted_excerpt(completed.stderr, diagnostics_policy),
            }
            if completed.returncode != 0:
                _LOG.error(
                    "hardware runner returned non-zero status",
                    extra={
                        "gate": self.name,
                        "clause": self.clause,
                        "runner": gate_name,
                        **runner_diagnostics[gate_name],
                    },
                )
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
                        context=runner_diagnostics[gate_name],
                    )
                )
        measurements: dict[str, Any] = {
            "executed": executed,
            "missing": _missing_ids(missing),
            "diagnostics": runner_diagnostics,
        }
        _LOG.info(
            "hardware runners assessed", extra={"executed": len(executed), "missing": len(missing)}
        )
        if missing:
            return self._absence_result(missing, denials, findings, measurements)
        if findings:
            return self._finish(
                GateResult.failed(
                    self.name,
                    summary="a configured hardware-in-loop runner failed",
                    findings=findings,
                    clause=self.clause,
                    measurements=measurements,
                ),
                "runner-failed",
            )
        return self._finish(
            GateResult.passed(
                self.name,
                summary="all configured hardware-in-loop runners completed successfully",
                clause=self.clause,
                measurements=measurements,
            ),
            "all-runners-completed",
        )

    def _absence_result(
        self,
        missing: Mapping[str, VerifiedAuthority | None],
        denials: Mapping[str, str],
        findings: Sequence[Finding],
        measurements: Mapping[str, Any],
    ) -> GateResult:
        """Classify absent hardware runners by whether verified authority owns each absence.

        Extracted from ``check`` so each absence outcome is one short branch and the
        classification can be reasoned about, and tested, on its own.
        """
        unauthorised = sorted(gate for gate, authority in missing.items() if authority is None)
        if unauthorised:
            # An absent runner that no decision authorises means the gate could not
            # look at the hardware and nobody accepted that. That is BLOCKED.
            # Reporting SKIPPED_DECLARED here would advertise an owned skip while
            # decision_id is None, which is the state collapse this project exists to
            # prevent: a reader scanning for skips treats it as already reviewed.
            # Completed denials ride along with their reasons, so a superseded or
            # graph-invalid ledger verdict stays distinguishable from a subject
            # nobody ever recorded.
            return self._finish(
                GateResult.blocked(
                    self.name,
                    summary="a configured hardware runner is absent and unauthorised",
                    reason=(
                        "absent configured hardware runners without decision-log "
                        f"authority: {', '.join(unauthorised)}"
                    ),
                    clause=self.clause,
                    remediation=(
                        "Log a decision naming this gate and the runner it needs, "
                        "or provide the runner."
                    ),
                    measurements={**measurements, "decision_id": None, "denials": dict(denials)},
                ),
                "unauthorised-runner-absence",
            )
        if findings:
            # Authorised absence converts only the skip, never unrelated failure
            # evidence: a present runner that failed its scenario keeps the gate
            # FAILED even while another runner's absence is properly owned. The
            # authorised decision ids stay visible in the missing measurement.
            return self._finish(
                GateResult.failed(
                    self.name,
                    summary="a configured hardware-in-loop runner failed",
                    findings=findings,
                    clause=self.clause,
                    measurements=measurements,
                ),
                "runner-failed-with-authorised-absence",
            )
        authority = {gate: value for gate, value in missing.items() if value is not None}
        base = GateResult.skipped_declared(
            self.name,
            summary="one or more configured hardware runners are absent",
            reason=f"absent configured hardware runners: {', '.join(sorted(missing))}",
            authority=authority,
            clause=self.clause,
        )
        return self._finish(
            dataclasses.replace(
                base,
                findings=GateResult._sorted((*base.findings, *findings)),
                measurements={**dict(base.measurements), **measurements},
            ),
            "declared-runner-absence",
        )

    def _finish(self, result: GateResult, decision: str) -> GateResult:
        """Log every terminal hardware-gate decision."""
        log_verdict(
            _LOG,
            gate=self.name,
            status=result.status.value,
            clause=self.clause,
            decision=decision,
            findings=len(result.findings),
        )
        return result


def _policy(config: Config, clause: str) -> dict[str, Any]:
    """Read variable runner policy from the configuration engine.

    Absence-authority policy deliberately has no keys here any more: the ledger
    location and identifier grammar come from the shared ``decision_log`` and
    ``traceability`` configuration through :func:`verify_authority`, so this
    gate cannot drift onto a private authority grammar again.
    """
    keys = {
        "optional_gates": "robotics.hardware_in_loop.optional_gates",
        "runners": "robotics.hardware_in_loop.runners",
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


def _execution_blocked_result(
    gate: str,
    clause: str,
    runner: str,
    diagnostic: Mapping[str, str],
    measurements: Mapping[str, Any],
) -> GateResult:
    """Return a named blocked finding when a configured runner cannot start."""
    return GateResult(
        gate=gate,
        status=GateStatus.BLOCKED,
        clause=clause,
        summary="hardware-in-loop runner could not execute",
        findings=(
            Finding(
                id=f"HIL-{runner.upper()}-UNAVAILABLE",
                severity=Severity.BLOCKER,
                message=f"runner for {runner!r} could not execute",
                clause=clause,
                disposition="Restore the runner environment and re-run its configured command.",
                context=dict(diagnostic),
            ),
        ),
        measurements=dict(measurements),
    )


def _missing_ids(missing: Mapping[str, VerifiedAuthority | None]) -> dict[str, str | None]:
    """Project typed absence authority to its JSON-safe per-runner id map."""
    return {
        runner: authority.decision_id if authority else None
        for runner, authority in missing.items()
    }


def _authorising_decision(
    config: Config, gate: str, clause: str, runner: str
) -> VerifiedAuthority | AuthorityDenial | None:
    """Resolve one absent runner's authority through the one shared verifier.

    Returns the typed authority for the exact subject ``{gate}:{runner}``; a
    typed :class:`AuthorityDenial` when verification completed and refused —
    a prose-only mention, a withdrawn or superseded record, an invalid ledger
    graph — so the caller can surface the reason; or ``None`` when the ledger
    was never written and there is nothing to deny with. A ledger that exists
    but cannot be read, decoded, or trusted as an in-repository regular file
    raises instead (``OSError``/``ValueError``) for the caller to surface as
    BLOCKED: an unreadable ledger is not the same evidence as "no decision was
    recorded".
    """
    path = config.resolve_path("decision_log.path", clause=clause)
    try:
        # lstat() rather than exists(): only ENOENT means "never written". Any
        # other stat failure (for example EACCES) propagates as an evidence
        # failure — exists() would swallow it on newer Python versions and
        # misclassify an unreadable ledger as an absent one.
        path.lstat()
    except FileNotFoundError:
        return None
    trusted_regular_file(config.root, path, "hardware absence decision log")
    return verify_authority(config, subject=f"{gate}{SUBJECT_SEPARATOR}{runner}", clause=clause)
