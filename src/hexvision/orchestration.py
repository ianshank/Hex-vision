"""Execute every reviewed pack's registered domain gates as one release control.

Pack discovery is intentionally dynamic, but release authority is not.  An
installed entry point becomes eligible only when its name appears in the frozen,
reviewed ``orchestration.active_packs`` allowlist.  This prevents an unrelated
development plugin from changing a release verdict while still allowing a
reviewed third-party pack to join without a core import-list edit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from hexvision.config import Config
from hexvision.gates.base import Gate, run_gates
from hexvision.gates.model import Finding, GateResult, GateStatus
from hexvision.observability import get_logger, log_verdict
from hexvision.packs.base import Pack
from hexvision.packs.registry import available, load_all

__all__ = ["run_active_domain_gates"]

_CLAUSE: Final = "RELEASE-ORCHESTRATION"
_GATE_NAME: Final = "domain-gates"
_LOG: Final = get_logger(__name__)


def _active_names(config: Config) -> tuple[str, ...]:
    """Read a non-empty, duplicate-free reviewed pack allowlist."""
    configured = config.require("orchestration.active_packs", clause=_CLAUSE)
    if (
        not isinstance(configured, list)
        or not configured
        or not all(isinstance(name, str) and name for name in configured)
    ):
        raise ValueError("orchestration.active_packs must be a non-empty list of pack names")
    names = tuple(configured)
    if len(set(names)) != len(names):
        raise ValueError("orchestration.active_packs must not repeat a pack name")
    return names


def _gate_results(pack: Pack, config: Config) -> tuple[GateResult, ...]:
    """Resolve and run one pack's complete registered domain-gate sequence."""
    try:
        gates = tuple(pack.domain_gates(config))
    except Exception as exc:
        raise ValueError(
            f"pack {pack.name!r} cannot provide domain gates: {type(exc).__name__}: {exc}"
        ) from exc
    if not all(isinstance(gate, Gate) for gate in gates):
        raise ValueError(f"pack {pack.name!r} registered a non-Gate domain control")
    return run_gates(gates, config)


def _measurements(
    names: Sequence[str], ignored: Sequence[str], results: Sequence[tuple[str, GateResult]]
) -> dict[str, Any]:
    """Retain each individual verdict so aggregation never hides gate evidence."""
    return {
        "active_packs": list(names),
        "ignored_installed_packs": list(ignored),
        "gate_results": [
            {"pack": pack_name, "result": result.to_dict()} for pack_name, result in results
        ],
    }


def _failure_findings(results: Sequence[tuple[str, GateResult]]) -> tuple[Finding, ...]:
    """Copy findings with pack identity so identical domain IDs remain actionable."""
    findings: list[Finding] = []
    for pack_name, result in results:
        for finding in result.findings:
            findings.append(
                Finding(
                    id=f"{pack_name.upper()}-{finding.id}",
                    severity=finding.severity,
                    message=f"[{pack_name}/{result.gate}] {finding.message}",
                    location=finding.location,
                    clause=finding.clause,
                    disposition=finding.disposition,
                    context=finding.context,
                )
            )
    return tuple(findings)


def _block_reason(results: Sequence[tuple[str, GateResult]]) -> str:
    """Summarize every blocked gate reason without relabeling it as a failure."""
    messages = [
        f"{pack_name}/{result.gate}: {finding.message}"
        for pack_name, result in results
        if result.status is GateStatus.BLOCKED
        for finding in result.findings
    ]
    return "; ".join(messages)


def _aggregate(
    names: Sequence[str], ignored: Sequence[str], results: Sequence[tuple[str, GateResult]]
) -> GateResult:
    """Reduce executed gates to one four-state release verdict without information loss."""
    measurements = _measurements(names, ignored, results)
    statuses = {result.status for _, result in results}
    if GateStatus.BLOCKED in statuses:
        return GateResult.blocked(
            _GATE_NAME,
            summary="one or more domain gates could not evaluate required evidence",
            reason=_block_reason(results),
            clause=_CLAUSE,
            remediation=(
                "Restore the named evidence or gate preconditions, then re-run domain-gates."
            ),
            measurements=measurements,
        )
    findings = _failure_findings(results)
    if GateStatus.FAILED in statuses:
        return GateResult.failed(
            _GATE_NAME,
            summary="one or more domain gates found release-blocking evidence",
            findings=findings,
            clause=_CLAUSE,
            measurements=measurements,
        )
    declared = [
        (pack_name, result)
        for pack_name, result in results
        if result.status is GateStatus.SKIPPED_DECLARED
    ]
    if declared:
        # GateStatus.SKIPPED_DECLARED maps to the FAILED exit code by default so an
        # unowned skip is red unless something converts it. The converting authority
        # is the decision-log entry, and per that mapping's own documentation the
        # conversion belongs to the gate rather than to the mapping. A skip whose
        # authority is missing is now reported BLOCKED by the producing gate, so
        # anything still declared here is authorised. The unauthorised branch below
        # remains as a defence against a future gate that forgets to resolve
        # authority: it names the offending gate instead of emitting a bare
        # non-zero exit that an operator would have to guess at.
        unauthorised = [
            f"{pack_name}/{result.gate}"
            for pack_name, result in declared
            if not result.measurements.get("decision_id")
        ]
        if unauthorised:
            return GateResult.failed(
                _GATE_NAME,
                summary="a declared domain-gate skip carries no authorising decision",
                findings=findings,
                clause=_CLAUSE,
                measurements={**measurements, "unauthorised_declared_skips": unauthorised},
            )
        authorised = {
            f"{pack_name}/{result.gate}": result.measurements["decision_id"]
            for pack_name, result in declared
        }
        return GateResult.passed(
            _GATE_NAME,
            summary=(
                "every active pack domain gate passed; "
                f"{len(authorised)} declared unavailable under recorded decisions"
            ),
            clause=_CLAUSE,
            measurements={**measurements, "authorised_declared_skips": authorised},
        )
    return GateResult.passed(
        _GATE_NAME,
        summary="every active pack domain gate passed",
        clause=_CLAUSE,
        measurements=measurements,
    )


def run_active_domain_gates(config: Config) -> GateResult:
    """Run all gates registered by every configured active pack.

    This is the release-facing orchestration path.  It invokes the shared
    ``run_gates`` runner for each pack and waits for every gate even after a
    failure, so a single result reports the complete release evidence.
    """
    try:
        names = _active_names(config)
        discovered = available()
        ignored = tuple(name for name in discovered if name not in names)
        _LOG.info(
            "domain-gate run started",
            extra={"active_packs": names, "ignored_installed_packs": ignored},
        )
        packs = load_all(names)
        results = tuple(
            (pack.name, result) for pack in packs for result in _gate_results(pack, config)
        )
        aggregate = _aggregate(names, ignored, results)
    except Exception as exc:
        aggregate = GateResult.blocked(
            _GATE_NAME,
            summary="active-pack domain-gate orchestration is unavailable",
            reason=f"{type(exc).__name__}: {exc}",
            clause=_CLAUSE,
        )
    log_verdict(
        _LOG,
        gate=aggregate.gate,
        status=aggregate.status.value,
        clause=aggregate.clause,
        active_packs=aggregate.measurements.get("active_packs", []),
        gates=len(aggregate.measurements.get("gate_results", [])),
        findings=len(aggregate.findings),
    )
    return aggregate
