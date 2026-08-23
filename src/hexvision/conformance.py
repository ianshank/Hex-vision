"""Check a dynamically loaded pack against the Gate Harness Contract v1.1.

The contract is checked independently of individual stacks so each pack can vary
commands but cannot silently omit common controls or weaken their failure modes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from hexvision.config import Config
from hexvision.gates.contract import MakefileAuthorityGate, ZeroSkipAuditGate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.invariant_verifiers import InvariantVerifier, ProbeEvidence, load_all
from hexvision.packs.base import Pack, TargetSpec

__all__ = ["check_pack"]

_CLAUSE: Final = "CONFORMANCE"
# A target's spelling is a structural part of Contract v1.1, not an operational
# policy value; the configured Makefile path and executable provide its runtime
# context.
_PRE_PR_TARGET: Final = "pre-pr"
_MAKE_RULE: Final = re.compile(r"^(?P<target>[A-Za-z0-9_.-]+)\s*:(?P<prerequisites>.*)$")


def _finding(number: int, message: str, disposition: str, *, blocker: bool = False) -> Finding:
    """Create stable contract findings whose ids make each clause separately auditable."""
    return Finding(
        f"CONFORMANCE-{number:02d}",
        Severity.BLOCKER if blocker else Severity.MAJOR,
        message,
        clause=_CLAUSE,
        disposition=disposition,
    )


def _normalizer_count(source_root: Path) -> int:
    """Count declarations AST-first so comments and imports cannot produce false positives."""
    count = 0
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += sum(
            isinstance(node, ast.FunctionDef) and node.name == "normalize_remote_url"
            for node in ast.walk(tree)
        )
    return count


# The verified-authority class name is a structural contract identifier exactly
# like "normalize_remote_url" above: DEC-016's corrective action is that this
# type has one declaration and is constructed nowhere outside its own module,
# so a fourth per-site authority re-implementation is rejected before merge.
_AUTHORITY_CLASS: Final = "VerifiedAuthority"


def _authority_declaration_files(source_root: Path) -> list[Path]:
    """Return every file declaring the verified-authority class, AST-first."""
    files: list[Path] = []
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef) and node.name == _AUTHORITY_CLASS
            for node in ast.walk(tree)
        ):
            files.append(path)
    return files


def _authority_construction_sites(source_root: Path, defining: set[Path]) -> list[str]:
    """Return authority construction call sites outside the defining module.

    The matcher deliberately resolves the forms a well-intentioned
    re-implementation would actually take — a direct call, an aliased import
    (``from hexvision.authority import VerifiedAuthority as VA``), any
    attribute call ending in the class name (``authority.VerifiedAuthority(...)``),
    and the ``object.__new__(VerifiedAuthority)`` bypass — because a guard that
    only matched the bare name would miss exactly the aliased copy that a
    fourth recurrence would use. Attribute matching is conservative on purpose:
    any ``.VerifiedAuthority(...)`` call counts, so a colliding third-party
    name is surfaced for review rather than silently exempted.
    """
    sites: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path in defining:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = {_AUTHORITY_CLASS}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for imported in node.names:
                    if imported.name == _AUTHORITY_CLASS:
                        aliases.add(imported.asname or imported.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            direct = isinstance(func, ast.Name) and func.id in aliases
            attribute = isinstance(func, ast.Attribute) and func.attr == _AUTHORITY_CLASS
            dunder_new = (
                isinstance(func, ast.Attribute)
                and func.attr == "__new__"
                and any(
                    (isinstance(argument, ast.Name) and argument.id in aliases)
                    or (isinstance(argument, ast.Attribute) and argument.attr == _AUTHORITY_CLASS)
                    for argument in node.args
                )
            )
            if direct or attribute or dunder_new:
                sites.append(f"{path}:{node.lineno}")
    return sites


def _has_forbidden_flag(spec: TargetSpec, flags: list[str]) -> str | None:
    """Return the policy-owned forbidden threshold token found in a target command."""
    for command_part in spec.command:
        for flag in flags:
            if flag in command_part:
                return flag
    return None


def _invariant_identifier(value: str) -> str:
    """Canonicalize config keys and clause IDs in the one place they meet.

    Invariant keys are TOML-friendly ``inv_2`` spellings while gate clauses use
    the operator-facing ``INV-2`` form. Normalizing here keeps every subsequent
    conformance comparison exact and prevents scattered case/underscore fixes.
    """
    return value.strip().upper().replace("_", "-")


def _makefile_prerequisites(path: Path, target: str) -> tuple[str, ...] | None:
    """Return one Makefile target's ordered prerequisites without recipe comments.

    Only the simple target declaration needed by the contract is interpreted;
    recipes are deliberately not executed or evaluated while conformance runs.
    Continuation lines are joined first, so a maintained multi-line ``pre-pr``
    declaration receives the same ordering check as the compact project form.
    """
    logical_lines: list[str] = []
    pending = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.endswith("\\"):
            pending += f"{line[:-1]} "
            continue
        logical_lines.append(f"{pending}{line}")
        pending = ""
    if pending:
        logical_lines.append(pending)
    for line in logical_lines:
        if line.startswith("\t"):
            continue
        match = _MAKE_RULE.match(line.split("#", maxsplit=1)[0].strip())
        if match and match.group("target") == target:
            return tuple(match.group("prerequisites").split())
    return None


def _makefile_targets(path: Path) -> set[str]:
    """Return declared Makefile targets without evaluating recipes or variables.

    Conformance needs to bind a pack's target declaration to the governed
    Makefile, not merely to a similarly named arbitrary command.  This parser
    intentionally accepts the simple target grammar the contract permits and
    never executes a Makefile while deciding whether that authority exists.
    """

    targets: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("\t"):
            continue
        match = _MAKE_RULE.match(raw_line.split("#", maxsplit=1)[0].strip())
        if match:
            targets.add(match.group("target"))
    return targets


def _is_governed_target_invocation(
    target: TargetSpec, mechanism: str, make_executable: str, makefile_targets: set[str]
) -> bool:
    """Return whether a pack names the real governed target without shell indirection."""

    return (
        mechanism in makefile_targets
        and target.target == mechanism
        and target.command == (make_executable, mechanism)
    )


def _core_contract_gates() -> tuple[ZeroSkipAuditGate | MakefileAuthorityGate, ...]:
    """Return repository-wide invariant gates that every pack inherits."""
    return (ZeroSkipAuditGate(), MakefileAuthorityGate())


def _invariant_evidence_finding(
    invariant: str, evidence: ProbeEvidence, *, detail: str | None = None
) -> Finding:
    """Create a stable finding when a synthetic violation did not prove enforcement."""

    suffix = f": {detail}" if detail else ""
    return _finding(
        10,
        (
            f"invariant {invariant!r} probe was not detected by its declared mechanism; "
            f"probe={evidence.probe!r}, outcome={evidence.outcome!r}{suffix}"
        ),
        (
            "Register an invariant verifier that detects the synthetic violation and "
            "reports its reason."
        ),
        blocker=True,
    )


def _select_verifier(
    verifiers: tuple[InvariantVerifier, ...],
    invariant: str,
    mechanism: str,
    target: TargetSpec | None,
    gate: object | None,
) -> InvariantVerifier | None:
    """Return exactly one installed proof for a mapping, refusing ambiguous evidence."""

    matching = tuple(
        verifier for verifier in verifiers if verifier.supports(invariant, mechanism, target, gate)
    )
    return matching[0] if len(matching) == 1 else None


def check_pack(  # noqa: PLR0911, PLR0912, PLR0915 - each contract clause reports independently.
    config: Config, pack: Pack
) -> GateResult:
    """Return all conformance findings rather than hiding later violations behind one."""
    try:
        targets = dict(pack.targets(config))
        contract_targets = list(config.require("contract.targets", clause=_CLAUSE))
        order = list(config.require("contract.pre_pr_order", clause=_CLAUSE))
        must_fail_closed = set(
            config.require("contract.fail_closed_on_missing_tool", clause=_CLAUSE)
        )
        must_degrade = set(config.require("contract.degrade_loudly", clause=_CLAUSE))
        invariants = set(config.section("contract.invariants"))
        enforcement = config.section("contract.invariant_enforcement")
        flags = list(config.require("contract.forbidden_threshold_flags", clause=_CLAUSE))
        source_root = config.resolve_path("contract.source_path", clause=_CLAUSE)
        makefile_path = config.resolve_path("contract.makefile_path", clause=_CLAUSE)
        make_executable = str(config.require("contract.make_executable", clause=_CLAUSE))
        no_op_commands = {
            str(command).casefold()
            for command in config.require("contract.conformance.no_op_commands", clause=_CLAUSE)
        }
        reason_patterns = {
            _invariant_identifier(str(invariant)): str(pattern)
            for invariant, pattern in config.section("contract.conformance.reason_patterns").items()
        }
    except Exception as exc:
        return GateResult.blocked(
            "conformance", summary="contract policy unavailable", reason=str(exc), clause=_CLAUSE
        )
    findings: list[Finding] = []
    missing = sorted(set(contract_targets) - set(targets))
    if missing:
        findings.append(
            _finding(
                1,
                f"pack {pack.name!r} is missing contract targets: {', '.join(missing)}",
                "Declare every configured contract target.",
            )
        )
    pre_pr = targets.get("pre-pr")
    if pre_pr is not None and tuple(pre_pr.command) != (make_executable, _PRE_PR_TARGET):
        findings.append(
            _finding(
                1,
                "pack pre-pr target does not delegate through the configured Makefile executable",
                "Set the pre-pr command to the configured Makefile executable and pre-pr target.",
            )
        )
    try:
        makefile_order = _makefile_prerequisites(makefile_path, _PRE_PR_TARGET)
        makefile_targets = _makefile_targets(makefile_path)
    except OSError as exc:
        return GateResult.blocked(
            "conformance",
            summary="Makefile cannot be inspected",
            reason=str(exc),
            clause=_CLAUSE,
        )
    if makefile_order != tuple(order):
        findings.append(
            _finding(
                9,
                ("Makefile pre-pr prerequisites do not exactly match contract.pre_pr_order"),
                "Set the Makefile pre-pr prerequisites to contract.pre_pr_order in order.",
            )
        )
    for name in sorted(must_fail_closed):
        if name in targets and not targets[name].fail_closed_on_missing_tool:
            findings.append(
                _finding(
                    2,
                    f"target {name!r} is not fail-closed",
                    "Set fail_closed_on_missing_tool=True.",
                )
            )
    for name in sorted(must_degrade):
        spec = targets.get(name)
        if spec is not None and (not spec.degrades_loudly or not spec.rationale):
            findings.append(
                _finding(
                    3,
                    f"target {name!r} lacks loud degradation and rationale",
                    "Declare degrades_loudly=True and a rationale.",
                )
            )
    try:
        normalizers = _normalizer_count(source_root)
    except (OSError, SyntaxError) as exc:
        return GateResult.blocked(
            "conformance",
            summary="normalizer source cannot be inspected",
            reason=str(exc),
            clause=_CLAUSE,
        )
    if normalizers != 1:
        findings.append(
            _finding(
                4,
                f"expected exactly one normalize_remote_url declaration, found {normalizers}",
                "Keep the shared normalizer as the only declaration.",
                blocker=True,
            )
        )
    try:
        authority_files = _authority_declaration_files(source_root)
        construction_sites = _authority_construction_sites(source_root, set(authority_files))
    except (OSError, SyntaxError) as exc:
        return GateResult.blocked(
            "conformance",
            summary="authority source cannot be inspected",
            reason=str(exc),
            clause=_CLAUSE,
        )
    if len(authority_files) != 1:
        findings.append(
            _finding(
                11,
                (
                    f"expected exactly one {_AUTHORITY_CLASS} declaration, "
                    f"found {len(authority_files)}"
                ),
                "Keep hexvision.authority as the only verified-authority declaration.",
                blocker=True,
            )
        )
    if construction_sites:
        findings.append(
            _finding(
                12,
                (
                    f"{_AUTHORITY_CLASS} is constructed outside its defining module at: "
                    f"{', '.join(construction_sites)}"
                ),
                "Call hexvision.authority.verify_authority instead of constructing authority.",
                blocker=True,
            )
        )
    try:
        domain_gates = tuple(pack.domain_gates(config))
    except Exception as exc:
        return GateResult.blocked(
            "conformance",
            summary="pack domain gates cannot be read",
            reason=str(exc),
            clause=_CLAUSE,
        )
    gate_clauses = {
        _invariant_identifier(gate.clause)
        for gate in (*_core_contract_gates(), *domain_gates)
        if gate.clause
    }
    target_names = {target.casefold() for target in targets}
    gates_by_clause = {
        _invariant_identifier(gate.clause): gate
        for gate in (*_core_contract_gates(), *domain_gates)
        if gate.clause
    }
    invariant_mapping = {
        _invariant_identifier(str(invariant)): str(mechanism)
        for invariant, mechanism in enforcement.items()
    }
    try:
        verifiers = load_all()
    except RuntimeError as exc:
        return GateResult.blocked(
            "conformance",
            summary="invariant verifier registry cannot be read",
            reason=str(exc),
            clause=_CLAUSE,
        )
    for configured_invariant in sorted(invariants):
        invariant = _invariant_identifier(configured_invariant)
        mechanism = invariant_mapping.get(invariant)
        if mechanism is None:
            findings.append(
                _finding(
                    5,
                    (
                        f"invariant {invariant!r} has no invariant_enforcement entry; "
                        "its enforcement mechanism is unspecified"
                    ),
                    "Map this invariant to an existing core/domain gate clause or pack target.",
                )
            )
        elif (
            _invariant_identifier(mechanism) not in gate_clauses
            and mechanism.casefold() not in target_names
        ):
            findings.append(
                _finding(
                    5,
                    (
                        f"invariant {invariant!r} names enforcement mechanism {mechanism!r}, "
                        "but no core/domain gate clause or pack target provides it"
                    ),
                    "Declare the named gate clause or Makefile target, or correct the mapping.",
                )
            )
        else:
            target = targets.get(mechanism)
            gate = gates_by_clause.get(_invariant_identifier(mechanism))
            if target is not None and not _is_governed_target_invocation(
                target, mechanism, make_executable, makefile_targets
            ):
                findings.append(
                    _invariant_evidence_finding(
                        invariant,
                        ProbeEvidence(
                            probe="governed Makefile target binding",
                            detected=False,
                            outcome=(
                                f"declared command={target.command!r}, "
                                f"governed target={mechanism!r}"
                            ),
                            reason="",
                        ),
                        detail=(
                            "declared command is not the configured Makefile executable "
                            "invoking its real governed target"
                        ),
                    )
                )
                continue
            if target is not None and target.command[0].casefold() in no_op_commands:
                findings.append(
                    _invariant_evidence_finding(
                        invariant,
                        ProbeEvidence(
                            probe="synthetic invariant violation",
                            detected=False,
                            outcome=f"declared command begins with {target.command[0]!r}",
                            reason="",
                        ),
                        detail="declared command is a configured no-op",
                    )
                )
                continue
            verifier = _select_verifier(verifiers, invariant, mechanism, target, gate)
            if verifier is None:
                findings.append(
                    _invariant_evidence_finding(
                        invariant,
                        ProbeEvidence(
                            probe="synthetic invariant violation",
                            detected=False,
                            outcome="no unambiguous registered verifier",
                            reason="",
                        ),
                    )
                )
                continue
            try:
                evidence = verifier.verify(config, mechanism, target, gate)
            except Exception as exc:
                findings.append(
                    _invariant_evidence_finding(
                        invariant,
                        ProbeEvidence(
                            probe="synthetic invariant violation",
                            detected=False,
                            outcome=f"verifier raised {type(exc).__name__}: {exc}",
                            reason="",
                        ),
                    )
                )
                continue
            expected_reason = reason_patterns.get(invariant)
            if not evidence.detected:
                findings.append(_invariant_evidence_finding(invariant, evidence))
            elif expected_reason is None or re.search(expected_reason, evidence.reason) is None:
                findings.append(
                    _invariant_evidence_finding(
                        invariant,
                        evidence,
                        detail=f"reason did not match configured pattern {expected_reason!r}",
                    )
                )
    for gate in domain_gates:
        if not gate.clause or not gate.description:
            findings.append(
                _finding(
                    6,
                    f"domain gate {gate.name!r} lacks clause or description",
                    "Declare a non-empty clause and description.",
                )
            )
    for name, spec in targets.items():
        flag = _has_forbidden_flag(spec, flags)
        if flag is not None:
            findings.append(
                _finding(
                    7,
                    f"target {name!r} embeds forbidden threshold flag {flag!r}",
                    "Move quality thresholds to frozen pyproject policy.",
                    blocker=True,
                )
            )
        if not spec.fail_closed_on_missing_tool and not spec.rationale:
            findings.append(
                _finding(
                    8,
                    f"target {name!r} opts out of fail-closed behavior without a rationale",
                    "Add a policy rationale.",
                )
            )
    if findings:
        return GateResult.failed(
            "conformance",
            summary=f"pack {pack.name} violates contract",
            findings=findings,
            clause=_CLAUSE,
        )
    return GateResult.passed(
        "conformance",
        summary=f"pack {pack.name} conforms",
        clause=_CLAUSE,
        measurements={
            "targets": len(targets),
            "domain_gates": len(domain_gates),
            "invariant_enforcement": invariant_mapping,
        },
    )
