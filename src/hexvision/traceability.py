"""Lint the authoritative requirement set against executable test evidence.

The source specification deltas own requirement identity.  The markdown matrix
and explicit test-source markers are projections that must agree with that
source, while every released row must cite pytest evidence that actually
collects.  This makes a matrix useful as an audit record rather than a list of
planned work that can accidentally pass a release gate.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

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


def _authoritative_requirements(config: Config) -> dict[str, Path]:
    """Read requirement headings from configured source specification deltas.

    The matrix is a projection.  Reading ids from source documents prevents a
    friendly-looking matrix from omitting a released obligation or adding an id
    that no specification declares.
    """
    globs = config.require("traceability.authoritative_spec_globs", clause=_CLAUSE)
    heading_pattern = str(
        config.require("traceability.requirement_heading_pattern", clause=_CLAUSE)
    )
    if (
        not isinstance(globs, list)
        or not globs
        or not all(isinstance(item, str) and item for item in globs)
    ):
        raise ValueError("authoritative specification globs must be non-empty strings")
    pattern = re.compile(heading_pattern, flags=re.MULTILINE)
    if "id" not in pattern.groupindex:
        raise ValueError("requirement heading pattern must define a named 'id' group")
    paths: set[Path] = set()
    for glob in globs:
        paths.update(path for path in config.root.glob(glob) if path.is_file())
    if not paths:
        raise ValueError("authoritative specification globs matched no files")
    requirements: dict[str, Path] = {}
    for path in sorted(paths):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            requirement = match.group("id")
            existing = requirements.get(requirement)
            if existing is not None:
                raise ValueError(
                    f"authoritative requirement {requirement!r} is declared in both "
                    f"{existing} and {path}"
                )
            requirements[requirement] = path
    if not requirements:
        raise ValueError("authoritative specification files declare no requirements")
    return requirements


def _test_citations(config: Config, pattern: str, ignored_globs: list[str]) -> set[str]:
    """Find explicitly marked requirement citations outside approved fixture exclusions."""
    tests_path = config.resolve_path("traceability.tests_path", clause=_CLAUSE)
    cited: set[str] = set()
    for test_file in tests_path.rglob("*.py"):
        relative = test_file.relative_to(config.root)
        if any(relative.match(glob) for glob in ignored_globs):
            continue
        text = test_file.read_text(encoding="utf-8")
        cited.update(match.group(1) for match in re.finditer(pattern, text))
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


def _nodeids(value: str, separator: str) -> tuple[str, ...]:
    """Split one matrix evidence cell into the configured collecting node ids."""
    if not separator:
        raise ValueError("traceability test-node separator must not be empty")
    return tuple(item.strip() for item in value.split(separator) if item.strip())


def _placeholder(value: str, patterns: tuple[str, ...]) -> bool:
    """Return whether a stated evidence value matches configured placeholder wording."""
    return any(re.search(pattern, value, flags=re.IGNORECASE) is not None for pattern in patterns)


def _verdict(  # noqa: PLR0913 - evidence dimensions remain explicit for audit output.
    requirement: str,
    row: Mapping[str, str] | None,
    *,
    release_status: str,
    separator: str,
    placeholders: tuple[str, ...],
    config: Config,
) -> tuple[dict[str, Any], list[Finding], bool]:
    """Assess source requirement evidence and retain an auditable per-row verdict."""
    measurement: dict[str, Any] = {
        "status": None,
        "test_node_ids": [],
        "collection": {},
        "verdict": "failed",
        "reasons": [],
    }
    findings: list[Finding] = []
    if row is None:
        measurement["reasons"].append("missing matrix row")
        findings.append(
            Finding(
                f"TRACE-{requirement}-MISSING",
                Severity.MAJOR,
                f"authoritative requirement {requirement!r} has no matrix row",
                clause=_CLAUSE,
                disposition="Add one Green matrix row with collecting test evidence.",
            )
        )
        return measurement, findings, False

    measurement["status"] = row["status"]
    if row["status"] != release_status:
        measurement["reasons"].append(f"status is not {release_status}")
        findings.append(
            Finding(
                f"TRACE-{requirement}-STATUS",
                Severity.MAJOR,
                f"released requirement {requirement!r} has status {row['status']!r}, "
                f"not required status {release_status!r}",
                clause=_CLAUSE,
                disposition=(
                    "Set the row to the required status only after verified evidence exists."
                ),
            )
        )

    evidence = row["test node id"]
    if _placeholder(evidence, placeholders):
        measurement["reasons"].append("placeholder test evidence")
        findings.append(
            Finding(
                f"TRACE-{requirement}-PLACEHOLDER",
                Severity.MAJOR,
                f"requirement {requirement!r} uses placeholder test evidence {evidence!r}",
                clause=_CLAUSE,
                disposition="Replace placeholder wording with a collecting pytest node id.",
            )
        )
        return measurement, findings, False

    nodeids = _nodeids(evidence, separator)
    measurement["test_node_ids"] = list(nodeids)
    if not nodeids:
        measurement["reasons"].append("no test node id")
        findings.append(
            Finding(
                f"TRACE-{requirement}-TEST",
                Severity.MAJOR,
                f"requirement {requirement!r} has no collecting test node id",
                clause=_CLAUSE,
                disposition="Cite at least one collecting pytest node id.",
            )
        )
        return measurement, findings, False

    pytest_unavailable = False
    for nodeid in nodeids:
        collection = _collects(config, nodeid)
        measurement["collection"][nodeid] = collection
        if collection is None:
            pytest_unavailable = True
            measurement["reasons"].append("pytest unavailable")
        elif not collection:
            measurement["reasons"].append(f"uncollected node: {nodeid}")
            findings.append(
                Finding(
                    f"TRACE-{requirement}-TEST",
                    Severity.MAJOR,
                    f"test node id {nodeid!r} for requirement {requirement!r} does not collect",
                    clause=_CLAUSE,
                    disposition="Correct the node id or restore its test.",
                )
            )
    if not measurement["reasons"]:
        measurement["verdict"] = "verified"
    return measurement, findings, pytest_unavailable


def check_traceability(  # noqa: PLR0912, PLR0915 - every evidence rule reports independently.
    config: Config,
) -> GateResult:
    """Validate source requirements, matrix projection, and collecting test evidence."""
    try:
        matrix_path = config.resolve_path("traceability.matrix_path", clause=_CLAUSE)
        columns = list(config.require("traceability.columns", clause=_CLAUSE))
        rows = parse_matrix(matrix_path, columns)
        authoritative = _authoritative_requirements(config)
        decisions = _decision_ids(config)
        statuses = set(config.require("traceability.statuses", clause=_CLAUSE))
        inherit_required = set(
            config.require("traceability.require_inherits_from_for", clause=_CLAUSE)
        )
        decision_required = set(config.require("traceability.require_decision_for", clause=_CLAUSE))
        decision_patterns = list(
            config.require("traceability.decision_id_patterns", clause=_CLAUSE)
        )
        citation_pattern = str(config.require("traceability.test_citation_pattern", clause=_CLAUSE))
        ignored_test_path_globs = list(
            config.require("traceability.ignored_test_path_globs", clause=_CLAUSE)
        )
        release_status = str(config.require("traceability.release_status", clause=_CLAUSE))
        node_separator = str(config.require("traceability.test_node_separator", clause=_CLAUSE))
        placeholders = tuple(
            str(pattern)
            for pattern in config.require(
                "traceability.placeholder_evidence_patterns", clause=_CLAUSE
            )
        )
    except (OSError, ValueError, KeyError, re.error) as exc:
        return GateResult.blocked(
            "traceability",
            summary="traceability evidence is unavailable",
            reason=str(exc),
            clause=_CLAUSE,
        )
    keys = {_normal(value) for value in columns}
    required_keys = {"requirement id", "status", "test node id", "inherits-from", "decision ref"}
    if not required_keys <= keys:
        return GateResult.blocked(
            "traceability",
            summary="traceability columns are incomplete",
            reason="configured columns omit required matrix fields",
            clause=_CLAUSE,
        )

    findings: list[Finding] = []
    rows_by_id: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=1):
        requirement = row["requirement id"]
        status = row["status"]
        location = f"{matrix_path.relative_to(config.root)}:{number}"
        if requirement in rows_by_id:
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
        else:
            rows_by_id[requirement] = row
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

    authoritative_ids = set(authoritative)
    matrix_ids = set(rows_by_id)
    for requirement in sorted(matrix_ids - authoritative_ids):
        findings.append(
            Finding(
                f"TRACE-{requirement}-EXTRA",
                Severity.MAJOR,
                f"matrix row {requirement!r} is absent from the authoritative specifications",
                clause=_CLAUSE,
                disposition="Remove the stale row or add the source requirement specification.",
            )
        )
    verdicts: dict[str, dict[str, Any]] = {}
    pytest_unavailable = False
    for requirement in sorted(authoritative_ids):
        verdict, verdict_findings, unavailable = _verdict(
            requirement,
            rows_by_id.get(requirement),
            release_status=release_status,
            separator=node_separator,
            placeholders=placeholders,
            config=config,
        )
        verdicts[requirement] = verdict
        findings.extend(verdict_findings)
        pytest_unavailable = pytest_unavailable or unavailable
    if pytest_unavailable:
        return GateResult.blocked(
            "traceability",
            summary="pytest is unavailable for traceability",
            reason="configured pytest executable could not run",
            clause=_CLAUSE,
            measurements={"requirements": verdicts, "rows": len(rows)},
        )
    try:
        cited = _test_citations(config, citation_pattern, ignored_test_path_globs)
    except (OSError, re.error) as exc:
        return GateResult.blocked(
            "traceability", summary="test evidence cannot be read", reason=str(exc), clause=_CLAUSE
        )
    for requirement in sorted(cited - authoritative_ids):
        findings.append(
            Finding(
                f"TRACE-TEST-{requirement}",
                Severity.MAJOR,
                f"test cites requirement {requirement!r} with no authoritative specification",
                str(config.resolve_path("traceability.tests_path")),
                _CLAUSE,
                "Add the requirement to the source specification or correct the test citation.",
            )
        )
    for requirement in sorted(authoritative_ids - cited):
        verdicts[requirement]["reasons"].append("no test source citation")
        verdicts[requirement]["verdict"] = "failed"
        findings.append(
            Finding(
                f"TRACE-{requirement}-CITATION",
                Severity.MAJOR,
                f"authoritative requirement {requirement!r} has no test source citation",
                clause=_CLAUSE,
                disposition="Add a Traceability marker to the cited executable test.",
            )
        )
    _LOG.info("traceability checked", extra={"rows": len(rows), "findings": len(findings)})
    measurements = {
        "rows": len(rows),
        "ignored_test_path_globs": ignored_test_path_globs,
        "authoritative_requirements": sorted(authoritative_ids),
        "requirements": verdicts,
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
