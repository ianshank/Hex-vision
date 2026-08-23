"""Tests for the strict-plus-structural OpenSpec validation wrapper."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from pathlib import Path

from tests.governance.conftest import REPO_ROOT, run_process


def write_valid_change(repo: Path, *, requirement_id: str = "R-100") -> Path:
    """Create the smallest valid OpenSpec change used to isolate validator rules."""
    change = repo / "openspec" / "changes" / "example"
    specs = change / "specs"
    specs.mkdir(parents=True)
    for filename in ("proposal.md", "design.md", "tasks.md"):
        (change / filename).write_text(f"# {filename}\n", encoding="utf-8")
    (specs / "feature.md").write_text(
        "# Feature\n\n## ADDED Requirements\n\n"
        f"### Requirement: {requirement_id} — Governed behavior\n\n"
        "#### Scenario: Valid input\n"
        "- **WHEN** a valid input is supplied\n"
        "- **THEN** the gate passes.\n",
        encoding="utf-8",
    )
    return change


def run_validator(
    repo: Path, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Execute the versioned wrapper through this checkout's isolated environment."""
    runtime_bin = REPO_ROOT / ".venv" / "bin"
    return run_process(
        ["/bin/bash", "scripts/validate_specs.sh"],
        cwd=repo,
        env={
            "PATH": f"{runtime_bin}{os.pathsep}{os.environ['PATH']}",
            **({} if env is None else env),
        },
    )


def test_validate_specs_loudly_degrades_without_strict_validator(git_repo: Path) -> None:
    """The structural tier is useful but the missing strict tool stays visible."""
    write_valid_change(git_repo)
    result = run_validator(git_repo)
    assert result.returncode == 0, result.stderr
    assert (
        "WARNING — strict validator is unavailable or its configured artifact is unverified."
        in result.stderr
    )
    assert "specification validator identity BLOCKED" in result.stderr
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
        "## MODIFIED Requirements\n### Requirement: " + f"R-{100} — Missing scenario\n"
        "A requirement without an executable scenario.\n",
        encoding="utf-8",
    )
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert "no WHEN/THEN scenario" in result.stderr


def test_validate_specs_blocks_duplicate_requirement_ids_across_specs(git_repo: Path) -> None:
    """Cross-file uniqueness prevents one traceability ID from naming two promises."""
    change = write_valid_change(git_repo, requirement_id=f"R-{101}")
    (change / "specs" / "second.md").write_text(
        "## REMOVED Requirements\n### Requirement: " + f"R-{101} — Unique\n"
        "#### Scenario: Duplicate id\n- **WHEN** checked\n- **THEN** it fails.\n",
        encoding="utf-8",
    )
    result = run_validator(git_repo)
    assert result.returncode == 1
    assert f"duplicate requirement id R-{101}" in result.stderr


def test_validate_specs_ignores_environment_validator_override(git_repo: Path) -> None:
    """An arbitrary successful environment command never claims strict validation."""
    write_valid_change(git_repo)
    result = run_validator(git_repo, env={"SPEC_VALIDATOR": "true"})
    assert result.returncode == 0, result.stderr
    assert "strict validation via true" not in result.stderr
    assert (
        "strict validator is unavailable or its configured artifact is unverified." in result.stderr
    )
    assert "structural validation passed" in result.stdout


def test_validate_specs_propagates_verified_strict_validator_failure(git_repo: Path) -> None:
    """A verified strict tool failure cannot be masked by a passing structural tier."""
    write_valid_change(git_repo)
    strict = git_repo / "strict-validator"
    strict.write_text("#!/bin/sh\necho strict failure >&2\nexit 9\n", encoding="utf-8")
    strict.chmod(0o755)
    system = platform.system().lower()
    machine = platform.machine().lower()
    digest = hashlib.sha256(strict.read_bytes()).hexdigest()
    (git_repo / "hex-vision.toml").write_text(
        "\n".join(
            (
                "[specification_validator]",
                f'executable = "{strict}"',
                'version = "test"',
                f"[specification_validator.platforms.{system}.{machine}]",
                f'artifact_sha256 = "{digest}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    result = run_validator(git_repo)
    assert result.returncode == 9
    assert f"strict validation via {strict}" in result.stderr
    assert "strict failure" in result.stderr
