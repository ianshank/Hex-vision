"""Execute every reviewed pack's registered domain gates as one release control.

Pack discovery is intentionally dynamic, but release authority is not.  An
installed entry point becomes eligible only when its name appears in the frozen,
reviewed ``orchestration.active_packs`` allowlist.  This prevents an unrelated
development plugin from changing a release verdict while still allowing a
reviewed third-party pack to join without a core import-list edit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from hexvision.authority import SUBJECT_SEPARATOR, VerifiedAuthority, joined_decision_ids
from hexvision.config import Config
from hexvision.gates.base import Gate, run_gates
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
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


def _skip_authority_problem(result: GateResult) -> str | None:
    """Explain why a declared skip's attached authority is untrusted, or ``None``.

    Trust comes only from typed :class:`VerifiedAuthority` values minted by the
    shared verifier — never from a ``decision_id`` string in measurements, which
    is the display shape and was the forgeable surface the PEER-REVIEW-3 exploit
    spent. Each attached authority's subject must exactly equal the producing
    gate's name, the subject separator, and the runner key it is attached under,
    so authority recorded for one gate or runner cannot be borrowed by another
    and a whole-gate or empty-runner subject is never a wildcard. A gate whose
    own name contains the separator is refused outright: its recorded subjects
    would be ambiguous between gates, so it can never be authorised (fail
    closed by construction). Subjects are deliberately not pack-scoped — one
    active pack today — which is a recorded residual bound, not an oversight.
    """
    authorities = result.declared_skip_authority
    if not authorities:
        return "no verified authority is attached to the declared skip"
    if SUBJECT_SEPARATOR in result.gate:
        return (
            f"gate name contains the subject separator {SUBJECT_SEPARATOR!r}, "
            "making its recorded subjects ambiguous; it can never be authorised"
        )
    fakes = sorted(
        key for key, value in authorities.items() if not isinstance(value, VerifiedAuthority)
    )
    if fakes:
        return f"attached authority is not verifier-minted for: {', '.join(fakes)}"
    mismatched = sorted(
        f"{key} -> {value.subject}"
        for key, value in authorities.items()
        if value.subject != f"{result.gate}{SUBJECT_SEPARATOR}{key}"
    )
    if mismatched:
        return "verified authority does not name this gate and runner: " + ", ".join(mismatched)
    return None


def _unverified_skip_findings(problems: Mapping[str, str]) -> tuple[Finding, ...]:
    """Name every unverified declared skip so the failure is actionable, not a bare exit."""
    return tuple(
        Finding(
            id=f"{name.replace('/', '-').upper()}-UNVERIFIED-SKIP",
            severity=Severity.BLOCKER,
            message=f"[{name}] declared skip is not authorised: {problem}",
            clause=_CLAUSE,
            disposition=(
                "Resolve the absence through hexvision.authority.verify_authority and "
                "attach the returned authority to the declared-skip result, or restore "
                "the runner."
            ),
        )
        for name, problem in sorted(problems.items())
    )


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
        # is the typed VerifiedAuthority the producing gate resolved through the
        # shared verifier (DEC-016) — never the decision_id measurement, which is
        # derived display data a gate could once forge with any non-empty string.
        # A skip whose authority is missing is reported BLOCKED by the producing
        # gate, so anything still declared here should carry authority. The
        # unverified branch below is the defence against a gate that forgets to
        # resolve it, forges a bare id, or borrows another gate's decision: it
        # names the offending gate and the exact problem instead of emitting a
        # bare non-zero exit that an operator would have to guess at.
        problems = {
            f"{pack_name}/{result.gate}": problem
            for pack_name, result in declared
            if (problem := _skip_authority_problem(result)) is not None
        }
        if problems:
            return GateResult.failed(
                _GATE_NAME,
                summary="a declared domain-gate skip carries no verified authority",
                findings=(*findings, *_unverified_skip_findings(problems)),
                clause=_CLAUSE,
                measurements={**measurements, "unauthorised_declared_skips": sorted(problems)},
            )
        # Authorised absence converts the skip, not the evidence around it: a
        # declared result that also carries blocking findings (a present runner
        # failed while another was authorised absent) must not ride the
        # conversion into a green release verdict with its Major finding buried
        # in nested measurements.
        degraded = sorted(
            f"{pack_name}/{result.gate}"
            for pack_name, result in declared
            if result.blocking_findings
        )
        if degraded:
            return GateResult.failed(
                _GATE_NAME,
                summary="a declared domain-gate skip carries blocking findings",
                findings=findings,
                clause=_CLAUSE,
                measurements={**measurements, "degraded_declared_skips": degraded},
            )
        authorised = {
            f"{pack_name}/{result.gate}": joined_decision_ids(result.declared_skip_authority or {})
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
