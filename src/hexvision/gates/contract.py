"""Concrete invariant gates shared across every stack pack.

These gates own controls whose evidence is repository-wide rather than language
specific: coverage quality bars, zero skipped tests, and CI Makefile authority.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Final

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity

__all__ = ["CoverageFloorGate", "MakefileAuthorityGate", "ZeroSkipAuditGate"]

_SKIP_COMMENT: Final = re.compile(r"@governance-skip:\s*(\S+)\s+(.+)")


def _decisions(config: Config) -> set[str]:
    """Extract all policy-shaped decision ids from the configured decision log."""
    log = config.resolve_path("traceability.decision_log_path")
    text = log.read_text(encoding="utf-8")
    return {
        match.group(0)
        for pattern in config.require("traceability.decision_id_patterns")
        for match in re.finditer(str(pattern), text)
    }


def _valid_skip_comment(
    lines: list[str], line: int, decisions: set[str], patterns: list[str]
) -> bool:
    """Validate a nearby governing annotation against both syntax and real evidence."""
    for candidate in lines[max(0, line - 2) : line]:
        match = _SKIP_COMMENT.search(candidate)
        if (
            match
            and any(re.fullmatch(pattern, match.group(1)) for pattern in patterns)
            and match.group(1) in decisions
        ):
            return True
    return False


class CoverageFloorGate(Gate):
    """Enforce frozen per-file line and branch coverage floors from coverage JSON."""

    def __init__(self, report_path: Path | None = None) -> None:
        """Allow the CLI to select a report artifact without changing frozen floors."""
        self._report_path = report_path

    @property
    def name(self) -> str:
        """Return the Makefile-compatible contract target name."""
        return "coverage"

    @property
    def clause(self) -> str:
        """Identify the quality bar this gate enforces."""
        return "C-COVERAGE"

    def check(self, config: Config) -> GateResult:
        """Report every file below configured floor, blocking unreadable evidence."""
        path = self._report_path or config.resolve_path("coverage.report_path", clause=self.clause)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            files = payload["files"]
            line_floor = float(config.require("coverage.per_file_lines", clause=self.clause))
            branch_floor = float(config.require("coverage.per_file_branches", clause=self.clause))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="coverage report is unavailable",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        for filename, detail in sorted(files.items()):
            summary: dict[str, Any] = detail.get("summary", {})
            lines = float(summary.get("percent_covered", -1))
            branches = float(summary.get("percent_covered_branches", -1))
            if lines < line_floor:
                findings.append(
                    Finding(
                        f"COVERAGE-LINES-{filename}",
                        Severity.MAJOR,
                        f"{filename} line coverage {lines:g}% is below {line_floor:g}%",
                        filename,
                        self.clause,
                        "Add tests until this file reaches the configured line floor.",
                        {"measured": lines, "floor": line_floor},
                    )
                )
            if branches < branch_floor:
                findings.append(
                    Finding(
                        f"COVERAGE-BRANCHES-{filename}",
                        Severity.MAJOR,
                        f"{filename} branch coverage {branches:g}% is below {branch_floor:g}%",
                        filename,
                        self.clause,
                        "Add branch tests until this file reaches the configured branch floor.",
                        {"measured": branches, "floor": branch_floor},
                    )
                )
        if findings:
            return GateResult.failed(
                self.name,
                summary="per-file coverage floors are not met",
                findings=findings,
                clause=self.clause,
            )
        return GateResult.passed(
            self.name,
            summary="per-file coverage floors are met",
            clause=self.clause,
            measurements={
                "files": len(files),
                "line_floor": line_floor,
                "branch_floor": branch_floor,
            },
        )


class ZeroSkipAuditGate(Gate):
    """Reject skipped and xfailed test syntax unless a real decision authorizes it."""

    @property
    def name(self) -> str:
        """Return the CLI target for this invariant."""
        return "zero-skip"

    @property
    def clause(self) -> str:
        """Identify INV-2 for conformance and audit narratives."""
        return "INV-2"

    def check(self, config: Config) -> GateResult:
        """AST-scan test code so comments and prose cannot masquerade as test controls."""
        try:
            test_root = config.resolve_path("traceability.tests_path", clause=self.clause)
            decisions = _decisions(config)
            patterns = list(config.require("traceability.decision_id_patterns", clause=self.clause))
        except (OSError, re.error, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="skip authorization cannot be read",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        for path in test_root.rglob("*.py"):
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError) as exc:
                return GateResult.blocked(
                    self.name,
                    summary="test source cannot be inspected",
                    reason=str(exc),
                    clause=self.clause,
                )
            lines = source.splitlines()
            for node in ast.walk(tree):
                forbidden = False
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"skip", "xfail"}
                ):
                    forbidden = (
                        isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest"
                    )
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    forbidden = any(
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in {"skip", "skipif", "xfail"}
                        for decorator in node.decorator_list
                    )
                line_number = getattr(node, "lineno", 0)
                if forbidden and not _valid_skip_comment(lines, line_number, decisions, patterns):
                    relative = str(path.relative_to(config.root))
                    findings.append(
                        Finding(
                            f"SKIP-{relative}-{line_number}",
                            Severity.MAJOR,
                            "skip or xfail lacks a valid governance decision annotation",
                            f"{relative}:{line_number}",
                            self.clause,
                            (
                                "Remove the skip or add a nearby @governance-skip "
                                "comment citing an existing decision."
                            ),
                        )
                    )
        if findings:
            return GateResult.failed(
                self.name,
                summary="unauthorized test skips found",
                findings=findings,
                clause=self.clause,
            )
        return GateResult.passed(
            self.name, summary="no unauthorized test skips found", clause=self.clause
        )


class MakefileAuthorityGate(Gate):
    """Require CI to invoke governed checks through Makefile targets only."""

    @property
    def name(self) -> str:
        """Return the CLI target for Makefile authority."""
        return "makefile-authority"

    @property
    def clause(self) -> str:
        """Identify INV-5 for conformance and audit narratives."""
        return "INV-5"

    def check(self, config: Config) -> GateResult:
        """Check configured CI workflow for Make invocations and raw command bypasses."""
        try:
            workflow = config.resolve_path("makefile_authority.workflow_path", clause=self.clause)
            text = workflow.read_text(encoding="utf-8")
            raw_patterns = list(
                config.require("makefile_authority.raw_command_patterns", clause=self.clause)
            )
            targets = list(config.require("contract.targets", clause=self.clause))
        except (OSError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="CI workflow cannot be inspected",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        for target in targets:
            if f"make {target}" not in text:
                findings.append(
                    Finding(
                        f"MAKE-MISSING-{target}",
                        Severity.MAJOR,
                        f"workflow does not invoke make {target}",
                        str(workflow.relative_to(config.root)),
                        self.clause,
                        "Invoke the configured target through make.",
                    )
                )
        for pattern in raw_patterns:
            if pattern in text:
                findings.append(
                    Finding(
                        f"MAKE-RAW-{pattern}",
                        Severity.BLOCKER,
                        f"workflow contains forbidden raw command pattern {pattern!r}",
                        str(workflow.relative_to(config.root)),
                        self.clause,
                        "Replace the raw command with its Makefile target.",
                    )
                )
        if findings:
            return GateResult.failed(
                self.name,
                summary="CI bypasses Makefile authority",
                findings=findings,
                clause=self.clause,
            )
        return GateResult.passed(
            self.name, summary="CI uses Makefile authority", clause=self.clause
        )
