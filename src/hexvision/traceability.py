"""Lint the requirement matrix against executable evidence.

A traceability row is useful only when its links resolve: this module validates
matrix structure, test collection, inheritance, decision references, and test
citations so status text cannot drift away from evidence.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

from hexvision.config import Config
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger

__all__ = ["check_traceability", "parse_matrix"]

_LOG: Final = get_logger(__name__)
_CLAUSE: Final = "TRACEABILITY"


def _normal(value: str) -> str:
    """Normalize a header or status for policy comparisons without changing evidence."""
    return value.strip().casefold()


def parse_matrix(path: Path, columns: list[str]) -> list[dict[str, str]]:
    """Parse the first Markdown pipe table using configured column names.

    A small strict parser is preferable to a Markdown dependency: the gate needs
    only a matrix and must report malformed governance evidence rather than make
    a rendering library part of the control's availability.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    expected = [_normal(item) for item in columns]
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        header = [_normal(item) for item in line.strip().strip("|").split("|")]
        if header != expected or index + 1 >= len(lines):
            continue
        separator = lines[index + 1].strip().strip("|").split("|")
        if not all(set(cell.strip()) <= {"-", ":"} and "-" in cell for cell in separator):
            continue
        rows: list[dict[str, str]] = []
        for row in lines[index + 2 :]:
            if "|" not in row or not row.strip():
                break
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            if len(cells) != len(columns):
                raise ValueError(f"matrix row has {len(cells)} cells; expected {len(columns)}")
            rows.append(dict(zip(expected, cells, strict=True)))
        return rows
    raise ValueError("configured traceability table header was not found")


def _decision_ids(config: Config) -> set[str]:
    """Return configured decision identifiers from the decision log."""
    decision_path = config.resolve_path("traceability.decision_log_path", clause=_CLAUSE)
    content = decision_path.read_text(encoding="utf-8")
    patterns = config.require("traceability.decision_id_patterns", clause=_CLAUSE)
    return {match.group(0) for pattern in patterns for match in re.finditer(str(pattern), content)}


def _test_citations(config: Config, patterns: list[str], ignored_globs: list[str]) -> set[str]:
    """Find requirement identifiers outside configured synthetic-fixture exclusions."""
    tests_path = config.resolve_path("traceability.tests_path", clause=_CLAUSE)
    cited: set[str] = set()
    for test_file in tests_path.rglob("*.py"):
        relative = test_file.relative_to(config.root)
        if any(relative.match(pattern) for pattern in ignored_globs):
            continue
        text = test_file.read_text(encoding="utf-8")
        for pattern in patterns:
            cited.update(match.group(0) for match in re.finditer(str(pattern), text))
    return cited


def _collects(config: Config, nodeid: str) -> bool | None:
    """Ask pytest to collect one node; ``None`` distinguishes tool failure from absence."""
    executable = str(config.require("traceability.pytest_executable", clause=_CLAUSE))
    try:
        completed = subprocess.run(
            [executable, "--collect-only", "-q", nodeid],
            cwd=config.root,
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    return completed.returncode == 0 and nodeid in completed.stdout


def check_traceability(  # noqa: PLR0912 - independent evidence rules must all report.
    config: Config,
) -> GateResult:
    """Validate every configured traceability rule and aggregate actionable findings."""
    try:
        matrix_path = config.resolve_path("traceability.matrix_path", clause=_CLAUSE)
        columns = list(config.require("traceability.columns", clause=_CLAUSE))
        rows = parse_matrix(matrix_path, columns)
        decisions = _decision_ids(config)
        statuses = set(config.require("traceability.statuses", clause=_CLAUSE))
        test_required = set(config.require("traceability.require_test_node_for", clause=_CLAUSE))
        inherit_required = set(
            config.require("traceability.require_inherits_from_for", clause=_CLAUSE)
        )
        decision_required = set(config.require("traceability.require_decision_for", clause=_CLAUSE))
        decision_patterns = list(
            config.require("traceability.decision_id_patterns", clause=_CLAUSE)
        )
        requirement_patterns = list(
            config.require("traceability.requirement_id_patterns", clause=_CLAUSE)
        )
        ignored_test_path_globs = list(
            config.require("traceability.ignored_test_path_globs", clause=_CLAUSE)
        )
    except (OSError, ValueError, KeyError, re.error) as exc:
        return GateResult.blocked(
            "traceability",
            summary="traceability evidence is unavailable",
            reason=str(exc),
            clause=_CLAUSE,
        )
    keys = [_normal(value) for value in columns]
    required_keys = {"requirement id", "status", "test node id", "inherits-from", "decision ref"}
    if not required_keys <= set(keys):
        return GateResult.blocked(
            "traceability",
            summary="traceability columns are incomplete",
            reason="configured columns omit required matrix fields",
            clause=_CLAUSE,
        )
    findings: list[Finding] = []
    ids: set[str] = set()
    for number, row in enumerate(rows, start=1):
        requirement = row["requirement id"]
        status = row["status"]
        location = f"{matrix_path.relative_to(config.root)}:{number}"
        if requirement in ids:
            findings.append(
                Finding(
                    f"TRACE-{number:03d}",
                    Severity.BLOCKER,
                    f"duplicate requirement id {requirement!r}",
                    location,
                    _CLAUSE,
                    "Assign a unique requirement id.",
                )
            )
        ids.add(requirement)
        if status not in statuses:
            findings.append(
                Finding(
                    f"TRACE-{number:03d}-STATUS",
                    Severity.MAJOR,
                    f"status {status!r} is not configured",
                    location,
                    _CLAUSE,
                    "Use a status from traceability.statuses.",
                )
            )
        if status in test_required:
            nodeid = row["test node id"]
            if not nodeid:
                findings.append(
                    Finding(
                        f"TRACE-{number:03d}-TEST",
                        Severity.MAJOR,
                        "status requires a test node id",
                        location,
                        _CLAUSE,
                        "Add a collecting pytest node id.",
                    )
                )
            else:
                collection = _collects(config, nodeid)
                if collection is None:
                    return GateResult.blocked(
                        "traceability",
                        summary="pytest is unavailable for traceability",
                        reason="configured pytest executable could not run",
                        clause=_CLAUSE,
                    )
                if not collection:
                    findings.append(
                        Finding(
                            f"TRACE-{number:03d}-TEST",
                            Severity.MAJOR,
                            f"test node id {nodeid!r} does not collect",
                            location,
                            _CLAUSE,
                            "Correct the node id or restore its test.",
                        )
                    )
        if status in inherit_required and (
            "from" not in row["inherits-from"].casefold()
            or not re.search(r"\S", row["inherits-from"])
        ):
            findings.append(
                Finding(
                    f"TRACE-{number:03d}-INHERIT",
                    Severity.MAJOR,
                    "inherited status lacks a source requirement",
                    location,
                    _CLAUSE,
                    "Name what is inherited and the source requirement id.",
                )
            )
        if status in decision_required:
            reference = row["decision ref"]
            valid_form = any(re.fullmatch(str(pattern), reference) for pattern in decision_patterns)
            if not valid_form or reference not in decisions:
                findings.append(
                    Finding(
                        f"TRACE-{number:03d}-DECISION",
                        Severity.MAJOR,
                        f"decision reference {reference!r} is absent or invalid",
                        location,
                        _CLAUSE,
                        "Cite an existing configured decision id.",
                    )
                )
    try:
        cited = _test_citations(config, requirement_patterns, ignored_test_path_globs)
    except OSError as exc:
        return GateResult.blocked(
            "traceability", summary="test evidence cannot be read", reason=str(exc), clause=_CLAUSE
        )
    for requirement in sorted(cited - ids):
        findings.append(
            Finding(
                f"TRACE-TEST-{requirement}",
                Severity.MAJOR,
                f"test cites requirement {requirement!r} with no matrix row",
                str(config.resolve_path("traceability.tests_path")),
                _CLAUSE,
                "Add the requirement to the matrix or correct the test citation.",
            )
        )
    _LOG.info("traceability checked", extra={"rows": len(rows), "findings": len(findings)})
    measurements = {
        "rows": len(rows),
        "ignored_test_path_globs": ignored_test_path_globs,
    }
    if findings:
        return GateResult.failed(
            "traceability",
            summary="traceability matrix has findings",
            findings=findings,
            clause=_CLAUSE,
            measurements=measurements,
        )
    return GateResult.passed(
        "traceability",
        summary="traceability matrix is complete",
        clause=_CLAUSE,
        measurements=measurements,
    )
