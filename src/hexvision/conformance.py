"""Check a dynamically loaded pack against the Gate Harness Contract v1.1.

The contract is checked independently of individual stacks so each pack can vary
commands but cannot silently omit common controls or weaken their failure modes.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from hexvision.config import Config
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.packs.base import Pack, TargetSpec

__all__ = ["check_pack"]

_CLAUSE: Final = "CONFORMANCE"


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


def _has_forbidden_flag(spec: TargetSpec, flags: list[str]) -> str | None:
    """Return the policy-owned forbidden threshold token found in a target command."""
    for command_part in spec.command:
        for flag in flags:
            if flag in command_part:
                return flag
    return None


def check_pack(  # noqa: PLR0912 - the contract deliberately has eight independent clauses.
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
        flags = list(config.require("contract.forbidden_threshold_flags", clause=_CLAUSE))
        source_root = config.resolve_path("contract.source_path", clause=_CLAUSE)
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
    if pre_pr is not None and tuple(pre_pr.command) != tuple(order):
        findings.append(
            _finding(
                1,
                "pre-pr command does not exactly chain contract.pre_pr_order",
                "Set the pre-pr command to the configured target order.",
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
        domain_gates = tuple(pack.domain_gates(config))
    except Exception as exc:
        return GateResult.blocked(
            "conformance",
            summary="pack domain gates cannot be read",
            reason=str(exc),
            clause=_CLAUSE,
        )
    claimed = {gate.clause for gate in domain_gates if gate.clause}
    for invariant in sorted(invariants - claimed):
        findings.append(
            _finding(
                5,
                f"no domain gate claims invariant {invariant!r}",
                "Provide a gate with this invariant as its clause.",
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
        measurements={"targets": len(targets), "domain_gates": len(domain_gates)},
    )
