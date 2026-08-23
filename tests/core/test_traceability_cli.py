"""Tests covering traceability evidence and CLI result serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hexvision.cli import main
from hexvision.traceability import check_traceability
from tests.support.process import coverage_controls_sanitized


def _trace_repo(root: Path, matrix_rows: str, requirements: tuple[str, ...] = ("R-1",)) -> None:
    """Build an isolated source spec, matrix, and collecting test projection."""
    (root / "traceability").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    spec = root / "openspec" / "changes" / "demo" / "specs"
    spec.mkdir(parents=True)
    headings = "\n".join(
        (
            f"### Requirement: {item} — Demonstrable evidence\n\n"
            "#### Scenario: Example scenario\n"
            "- **WHEN** evidence is declared\n"
            "- **THEN** it is checked\n"
        )
        for item in requirements
    )
    (spec / "traceability.md").write_text(f"# Demo\n\n{headings}\n", encoding="utf-8")
    (root / "docs" / "decision-log.md").write_text("DEC-1\n", encoding="utf-8")
    markers = "\n".join(f"# Traceability: {item} [Example scenario]" for item in requirements)
    (root / "tests" / "test_sample.py").write_text(
        f"{markers}\n\ndef test_ok() -> None:\n    assert True\n", encoding="utf-8"
    )
    (root / "traceability" / "REQUIREMENT-TRACEABILITY.md").write_text(
        (
            "| requirement id | statement | status | test node id | "
            "inherits-from | decision ref | notes |\n"
        )
        + "| --- | --- | --- | --- | --- | --- | --- |\n"
        + matrix_rows,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "row",
    [
        "| R-1 | s | Bad | tests/test_sample.py::test_ok | | | |\n",
        "| R-1 | s | Green | | | | |\n",
        "| R-1 | s | Inherited | tests/test_sample.py::test_ok | nope | | |\n",
        "| R-1 | s | Waived | tests/test_sample.py::test_ok | | DEC-999 | |\n",
        "| R-1 | s | Red | in flight: test | | | |\n",
        "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n"
        "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n",
    ],
)
def test_traceability_rule_failures(make_config: Any, tmp_repo: Any, row: str) -> None:
    """Invalid statuses, placeholders, and duplicate source rows all fail visibly."""
    root = tmp_repo()
    _trace_repo(root, row)
    assert check_traceability(make_config(root)).status.value == "failed"


def test_traceability_clean_case(make_config: Any, tmp_repo: Any) -> None:
    """A source-complete Green row with a collecting node and marker passes."""
    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n")
    result = check_traceability(make_config(root))
    assert result.status.value == "passed"
    assert result.measurements["requirements"]["R-1"]["verdict"] == "verified"


# Traceability: R-5 [Missing or duplicate requirement row, Inherited or waived row authority]
def test_traceability_requires_exact_source_requirement_set(
    make_config: Any, tmp_repo: Any
) -> None:
    """Missing and extra matrix identifiers cannot be disguised by otherwise good rows."""
    root = tmp_repo()
    _trace_repo(
        root,
        "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n"
        "| R-3 | s | Green | tests/test_sample.py::test_ok | | | |\n",
        requirements=("R-1", "R-2"),
    )
    result = check_traceability(make_config(root))
    assert result.status.value == "failed"
    assert {finding.id for finding in result.findings} >= {"TRACE-R-2-MISSING", "TRACE-R-3-EXTRA"}
    assert result.measurements["requirements"]["R-2"]["reasons"] == ["missing matrix row"]


# Traceability: R-6 [Collecting Green node, Noncollecting Green node]
def test_traceability_requires_collecting_node_and_test_marker(
    make_config: Any, tmp_repo: Any
) -> None:
    """Node strings and matrix rows alone are not accepted as executable evidence."""
    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Green | tests/test_sample.py::missing | | | |\n")
    (root / "tests" / "test_sample.py").write_text(
        "def test_ok() -> None:\n    assert True\n", encoding="utf-8"
    )
    result = check_traceability(make_config(root))
    assert result.status.value == "failed"
    assert {finding.id for finding in result.findings} >= {"TRACE-R-1-TEST", "TRACE-R-1-CITATION"}


def test_traceability_rejects_a_cited_node_with_another_requirement_marker(
    make_config: Any, tmp_repo: Any
) -> None:
    """A marker elsewhere in source cannot satisfy the matrix node's exact requirement claim."""

    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n")
    (root / "tests" / "test_sample.py").write_text(
        ("# Traceability: R-2 [Example scenario]\n\ndef test_ok() -> None:\n    assert True\n"),
        encoding="utf-8",
    )

    result = check_traceability(make_config(root))

    assert result.status.value == "failed"
    assert any(
        finding.id == "TRACE-R-1-MARKER"
        and "lacks exact Traceability marker for 'R-1'" in finding.message
        for finding in result.findings
    )


def test_traceability_rejects_a_cited_unknown_scenario_tag(make_config: Any, tmp_repo: Any) -> None:
    """A self-authored tag outside the source WHEN/THEN set is a specific evidence failure."""

    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n")
    (root / "tests" / "test_sample.py").write_text(
        ("# Traceability: R-1 [Counterfeit scenario]\n\ndef test_ok() -> None:\n    assert True\n"),
        encoding="utf-8",
    )

    result = check_traceability(make_config(root))

    assert result.status.value == "failed"
    assert any(
        finding.id == "TRACE-R-1-SCENARIO-TAG" and "Counterfeit scenario" in finding.message
        for finding in result.findings
    )


def test_traceability_ignores_only_configured_validator_fixture(
    make_config: Any, tmp_repo: Any
) -> None:
    """The narrow configured fixture exclusion cannot hide citations elsewhere."""
    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Green | tests/test_sample.py::test_ok | | | |\n")
    fixture = root / "tests" / "governance"
    fixture.mkdir()
    ignored_requirement = "R-100"
    (fixture / "test_validate_specs.py").write_text(
        f"# Traceability: {ignored_requirement}\n", encoding="utf-8"
    )
    result = check_traceability(make_config(root))
    assert result.status.value == "passed"
    outside_requirement = "R-101"
    (root / "tests" / "test_outside_fixture.py").write_text(
        f"# Traceability: {outside_requirement}\n", encoding="utf-8"
    )
    result = check_traceability(make_config(root))
    assert result.status.value == "failed"
    assert any(outside_requirement in finding.message for finding in result.findings)


def test_cli_json_config_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI emits one JSON result object without diagnostic text on stdout."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.hexvision.coverage]\nper_file_lines=90\nper_file_branches=80\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert main(["config", "dump", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"


def test_cli_usage_error() -> None:
    """Malformed invocation exits with argparse's non-zero usage result."""
    assert main([]) == 3


def test_cli_no_arguments_returns_usage() -> None:
    """Direct Python invocation cannot silently treat no arguments as success."""
    assert main([]) == 3


def test_cli_malformed_arguments_return_usage() -> None:
    """Unknown remote options report the documented usage exit instead of a green no-op."""
    assert main(["remotes", "--unknown-option"]) == 3


def test_cli_remotes_without_configured_destination_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_repo: Any
) -> None:
    """The actual remote command blocks when Git supplies no inspectable destination."""
    root = tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n")
    monkeypatch.chdir(root)
    with coverage_controls_sanitized():
        assert main(["remotes"]) == 2
