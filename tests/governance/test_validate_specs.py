"""Tests for the strict-plus-structural OpenSpec validation wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

from governance.conftest import run_process


def write_valid_change(repo: Path, *, requirement_id: str = "R-100") -> Path:
    """Create the smallest valid OpenSpec change used to isolate validator rules."""
    change = repo / "openspec" / "changes" / "example"
    specs = change / "specs"
    specs.mkdir(parents=True)
    for filename in ("proposal.md", "design.md", "tasks.md"):
        (change / filename).write_text(f"# {filename}\n", encoding="utf-8")
    (specs / "feature.md").write_text(
        "# Feature\n\n## Requirements\n\n"
        f"- {requirement_id} MUST remain governed.\n\n"
        "## Acceptance criteria\n\nWHEN a valid input is supplied THEN the gate passes.\n",
        encoding="utf-8",
    )
    return change


def run_validator(
    repo: Path, *, validator: str = "definitely-not-installed-validator"
) -> subprocess.CompletedProcess[str]:
    """Execute the versioned wrapper with a deliberately absent strict tool."""
    return run_process(
        ["/bin/bash", "scripts/validate_specs.sh"],
        cwd=repo,
        env={"SPEC_VALIDATOR": validator},
    )


def test_validate_specs_loudly_degrades_without_strict_validator(git_repo: Path) -> None:
    """The structural tier is useful but the missing strict tool stays visible."""
    write_valid_change(git_repo)
    result = run_validator(git_repo)
    assert result.returncode == 0, result.stderr
    assert "WARNING — strict validator" in result.stderr
    assert "structural validation passed" in result.stdout


def test_validate_specs_blocks_absent_change_tree(git_repo: Path) -> None:
    """A gate may not report a clean validation of a missing OpenSpec tree."""
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert "does not exist; refusing to validate nothing" in result.stderr


def test_validate_specs_blocks_missing_required_document(git_repo: Path) -> None:
    """Tier 2 catches a required design artifact even without the strict tool."""
    change = write_valid_change(git_repo)
    (change / "design.md").unlink()
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert "missing or empty design.md" in result.stderr


def test_validate_specs_blocks_missing_when_then_scenario(git_repo: Path) -> None:
    """A delta without an executable scenario cannot serve as a test oracle."""
    write_valid_change(git_repo)
    spec = git_repo / "openspec" / "changes" / "example" / "specs" / "feature.md"
    spec.write_text(
        "## Requirements\nR-100 MUST exist.\n## Acceptance criteria\nMeasurable.\n",
        encoding="utf-8",
    )
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert "no WHEN/THEN scenario" in result.stderr


def test_validate_specs_blocks_duplicate_requirement_ids_across_specs(git_repo: Path) -> None:
    """Cross-file uniqueness prevents one traceability ID from naming two promises."""
    change = write_valid_change(git_repo, requirement_id="R-101")
    (change / "specs" / "second.md").write_text(
        "## Requirements\nR-101 MUST be unique.\n"
        "## Acceptance criteria\nWHEN checked THEN it fails.\n",
        encoding="utf-8",
    )
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert "duplicate requirement id R-101" in result.stderr


def test_validate_specs_propagates_strict_validator_failure(git_repo: Path) -> None:
    """A present strict tool that fails cannot be masked by a passing Tier 2."""
    write_valid_change(git_repo)
    strict = git_repo / "strict-validator"
    strict.write_text("#!/bin/sh\necho strict failure >&2\nexit 9\n", encoding="utf-8")
    strict.chmod(0o755)
    result = run_validator(git_repo, validator=str(strict))
    assert result.returncode == 9
    assert "strict failure" in result.stderr
