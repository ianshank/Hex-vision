"""Concrete invariant gates shared across every stack pack.

These gates own controls whose evidence is repository-wide rather than language
specific: coverage quality bars, zero skipped tests, and CI Makefile authority.
"""

from __future__ import annotations

import ast
import json
import re
import tokenize
from collections.abc import Mapping
from io import StringIO
from pathlib import Path
from typing import Any, Final

from hexvision.config import Config
from hexvision.decision_log import decision_ids
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity

__all__ = ["CoverageFloorGate", "MakefileAuthorityGate", "ZeroSkipAuditGate"]

_SKIP_COMMENT: Final = re.compile(r"@governance-skip:\s*(\S+)\s+(.+)")


def _branch_percentage(summary: dict[str, Any]) -> float:
    """Read legacy or current coverage.py branch summaries without losing a zero-branch pass."""
    legacy = summary.get("percent_covered_branches")
    if legacy is not None:
        return float(legacy)
    total = float(summary.get("num_branches", 0))
    if total == 0:
        return 100.0
    return 100.0 * float(summary.get("covered_branches", 0)) / total


def _decisions(config: Config) -> set[str]:
    """Extract IDs only from records that pass the shared decision-log grammar."""
    log = config.resolve_path("traceability.decision_log_path")
    return decision_ids(config, log, clause="INV-2")


def _authorized_skip_decision(
    lines: list[str], line: int, decisions: set[str], patterns: list[str]
) -> str | None:
    """Return a valid nearby decision id without treating it as permission to skip."""
    for candidate in lines[max(0, line - 3) : line]:
        match = _SKIP_COMMENT.search(candidate)
        if (
            match
            and any(re.fullmatch(pattern, match.group(1)) for pattern in patterns)
            and match.group(1) in decisions
        ):
            return match.group(1)
    return None


def _policy_exception_reasons(config: Config, key: str, *, clause: str) -> dict[str, str]:
    """Read explicit coverage exceptions, refusing malformed policy instead of guessing it."""
    exceptions = config.require(key, clause=clause)
    if not isinstance(exceptions, list):
        raise TypeError(f"{key} must be a list of path-and-reason entries")
    reasons: dict[str, str] = {}
    for exception in exceptions:
        if not isinstance(exception, Mapping):
            raise TypeError(f"{key} contains a non-table exception")
        path = exception.get("path")
        reason = exception.get("reason")
        if not isinstance(path, str) or not path or not isinstance(reason, str) or not reason:
            raise ValueError(f"{key} entries require non-empty path and reason values")
        reasons[path] = reason
    return reasons


def _decorator_attribute(decorator: ast.expr) -> str | None:
    """Return a decorator's terminal attribute for bare and called pytest markers."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return target.attr if isinstance(target, ast.Attribute) else None


class CoverageFloorGate(Gate):
    """Enforce coverage floors and prevent source exclusions from posing as coverage."""

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

    def check(self, config: Config) -> GateResult:  # noqa: PLR0912 - emit every policy failure together.
        """Report low, unmeasured, or pragma-excluded source files as policy failures."""
        path = self._report_path or config.resolve_path("coverage.report_path", clause=self.clause)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            files = payload["files"]
            line_floor = float(config.require("coverage.per_file_lines", clause=self.clause))
            branch_floor = float(config.require("coverage.per_file_branches", clause=self.clause))
            source_root = config.resolve_path("contract.source_path", clause=self.clause)
            zero_statement_exceptions = _policy_exception_reasons(
                config, "coverage.zero_statement_exceptions", clause=self.clause
            )
            pragma_exceptions = _policy_exception_reasons(
                config, "coverage.pragma_no_cover_exceptions", clause=self.clause
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="coverage report is unavailable",
                reason=str(exc),
                clause=self.clause,
            )
        findings: list[Finding] = []
        if not source_root.is_dir():
            return GateResult.blocked(
                self.name,
                summary="coverage source root is unavailable",
                reason=f"configured source root does not exist: {source_root}",
                clause=self.clause,
            )
        for source_path in sorted(source_root.rglob("*.py")):
            relative = source_path.relative_to(config.root).as_posix()
            try:
                comments = tokenize.generate_tokens(
                    StringIO(source_path.read_text(encoding="utf-8")).readline
                )
                pragma_lines = [
                    token.start[0]
                    for token in comments
                    if token.type == tokenize.COMMENT
                    and "# pragma: no cover" in token.string.lower()
                ]
            except (OSError, tokenize.TokenError) as exc:
                return GateResult.blocked(
                    self.name,
                    summary="coverage source cannot be inspected",
                    reason=str(exc),
                    clause=self.clause,
                )
            if pragma_lines and relative not in pragma_exceptions:
                for line in pragma_lines:
                    findings.append(
                        Finding(
                            f"COVERAGE-PRAGMA-{relative}-{line}",
                            Severity.MAJOR,
                            (
                                "source-level coverage pragma is not an approved "
                                "coverage-policy exception"
                            ),
                            f"{relative}:{line}",
                            self.clause,
                            (
                                "Remove the pragma or add its path and reviewed reason "
                                "to coverage policy."
                            ),
                        )
                    )
        for filename, detail in sorted(files.items()):
            summary: dict[str, Any] = detail.get("summary", {})
            lines = float(summary.get("percent_covered", -1))
            branches = _branch_percentage(summary)
            report_path = Path(filename)
            candidate = report_path if report_path.is_absolute() else config.root / report_path
            try:
                relative = candidate.resolve().relative_to(source_root.resolve()).as_posix()
            except ValueError:
                relative = ""
            statements = summary.get("num_statements")
            if relative and statements == 0:
                configured_path = (source_root.relative_to(config.root) / relative).as_posix()
                if configured_path not in zero_statement_exceptions:
                    findings.append(
                        Finding(
                            f"COVERAGE-UNMEASURED-{configured_path}",
                            Severity.MAJOR,
                            (
                                f"{configured_path} is unmeasured: coverage reports zero "
                                "executable statements"
                            ),
                            configured_path,
                            self.clause,
                            (
                                "Add executable behavior and tests, or add a reviewed "
                                "statement-free exception."
                            ),
                        )
                    )
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
                summary="coverage policy or per-file floors are not met",
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
    """Reject every skipped and xfailed test while retaining cited-decision evidence."""

    @property
    def name(self) -> str:
        """Return the CLI target for this invariant."""
        return "zero-skip"

    @property
    def clause(self) -> str:
        """Identify INV-2 for conformance and audit narratives."""
        return "INV-2"

    def check(self, config: Config) -> GateResult:
        """AST-scan test code so a decision annotation cannot authorize non-execution."""
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
                        _decorator_attribute(decorator) in {"skip", "skipif", "xfail"}
                        for decorator in node.decorator_list
                    )
                line_number = getattr(node, "lineno", 0)
                if forbidden:
                    relative = str(path.relative_to(config.root))
                    decision = _authorized_skip_decision(lines, line_number, decisions, patterns)
                    if decision is None:
                        message = "skip or xfail lacks a valid governance decision annotation"
                        disposition = (
                            "Remove the skip or add a nearby @governance-skip comment citing an "
                            "existing decision."
                        )
                    else:
                        message = (
                            f"skip or xfail cites authorized @governance-skip decision {decision}; "
                            "the project zero-skip policy still forbids unexecuted tests"
                        )
                        disposition = (
                            "Remove the skip; the cited decision remains audit evidence but cannot "
                            "authorize non-execution."
                        )
                    findings.append(
                        Finding(
                            f"SKIP-{relative}-{line_number}",
                            Severity.MAJOR,
                            message,
                            f"{relative}:{line_number}",
                            self.clause,
                            disposition,
                        )
                    )
        if findings:
            return GateResult.failed(
                self.name,
                summary="test skips found",
                findings=findings,
                clause=self.clause,
            )
        return GateResult.passed(self.name, summary="no test skips found", clause=self.clause)


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
