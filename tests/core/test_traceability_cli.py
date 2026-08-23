"""Tests covering traceability evidence and CLI result serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hexvision.cli import main
from hexvision.traceability import check_traceability
from tests.support.process import coverage_controls_sanitized


def _trace_repo(root: Path, matrix_rows: str) -> None:
    (root / "traceability").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "docs" / "decision-log.md").write_text("DEC-1\n", encoding="utf-8")
    (root / "tests" / "test_sample.py").write_text(
        "# R-1\ndef test_ok(): assert True\n", encoding="utf-8"
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
    "row, status",
    [
        ("| R-1 | s | Bad | | | | |\n", "failed"),
        ("| R-1 | s | Green | | | | |\n", "failed"),
        ("| R-1 | s | Inherited | | nope | | |\n", "failed"),
        ("| R-1 | s | Waived | | | DEC-999 | |\n", "failed"),
        ("| R-1 | s | Red | | | | |\n| R-1 | s | Red | | | | |\n", "failed"),
    ],
)
def test_traceability_rule_failures(make_config, tmp_repo, row: str, status: str) -> None:  # type: ignore[no-untyped-def]
    """Each matrix rule is independently surfaced as a measured finding."""
    root = tmp_repo()
    _trace_repo(root, row)
    assert check_traceability(make_config(root)).status.value == status


def test_traceability_clean_case(make_config, tmp_repo, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A Red row needs no execution evidence and validates the complete matrix shape."""
    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Red | | | | |\n")
    assert check_traceability(make_config(root)).status.value == "passed"


def test_traceability_missing_test_citation(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A test requirement citation without a matrix row is a Major evidence gap."""
    root = tmp_repo()
    _trace_repo(root, "| R-2 | s | Red | | | | |\n")
    assert check_traceability(make_config(root)).status.value == "failed"


def test_traceability_ignores_only_configured_validator_fixture(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Keep synthetic parser fixtures visible while enforcing all other citations."""
    root = tmp_repo()
    _trace_repo(root, "| R-1 | s | Red | | | | |\n")
    fixture = root / "tests" / "governance"
    fixture.mkdir()
    ignored_requirement = f"R-{100}"
    (fixture / "test_validate_specs.py").write_text(f"# {ignored_requirement}\n", encoding="utf-8")
    result = check_traceability(make_config(root))
    assert result.status.value == "passed"
    assert result.measurements["ignored_test_path_globs"] == [
        "tests/governance/test_validate_specs.py"
    ]
    outside_requirement = f"R-{101}"
    (root / "tests" / "test_outside_fixture.py").write_text(
        f"# {outside_requirement}\n", encoding="utf-8"
    )
    result = check_traceability(make_config(root))
    assert result.status.value == "failed"
    assert any(outside_requirement in finding.message for finding in result.findings)


def test_cli_json_config_dump(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
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


def test_cli_remotes_without_configured_destination_blocks(monkeypatch, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """The actual remote command blocks when Git supplies no inspectable destination."""
    root = tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n")
    monkeypatch.chdir(root)
    with coverage_controls_sanitized():
        assert main(["remotes"]) == 2
