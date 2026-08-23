"""Behavioral proofs that the repository secret policy can detect an actual finding.

These tests create credential-shaped values only at runtime. Keeping the values
out of fixtures prevents the gate under test from treating its own test data as
a repository secret.
"""

from __future__ import annotations

import json
import random
import shutil
import string
from pathlib import Path
from typing import Any

from tests.support.process import run_process

REPO_ROOT = Path(__file__).resolve().parents[2]
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"
SYNTHETIC_SECRET_SEED = 127
GITHUB_PAT_RULE_ID = "github-pat"


def _gitleaks() -> str:
    """Return gitleaks or fail with its supported installation remediation.

    The absence of the scanner is an efficacy-test failure, not a reason to
    skip coverage of INV-1. A green test suite without the scanner would leave
    the production fail-closed policy unproven.
    """

    executable = shutil.which("gitleaks")
    assert executable is not None, "gitleaks is required; install it with `make secrets-install`"
    return executable


def _synthetic_github_pat() -> str:
    """Build a deterministic, high-entropy test value without committing one."""

    generator = random.Random(SYNTHETIC_SECRET_SEED)  # noqa: S311 - reproducible synthetic fixture only.
    alphabet = string.ascii_letters + string.digits
    return "ghp_" + "".join(generator.choice(alphabet) for _ in range(36))


def _findings(report_path: Path) -> list[dict[str, Any]]:
    """Read a scanner JSON report and reject malformed output as a test failure."""

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(report, list), "gitleaks report must be a list of findings"
    assert all(isinstance(finding, dict) for finding in report), (
        "gitleaks report contains a non-object"
    )
    return report


def _gitleaks_command(executable: str, mode: str, target: Path, report_path: Path) -> list[str]:
    """Build a scanner command that records rule ids for meaningful assertions."""

    return [
        executable,
        mode,
        str(target),
        "--config",
        str(GITLEAKS_CONFIG),
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
        "--redact",
        "--no-banner",
    ]


def test_gitleaks_dir_detects_a_synthetic_working_tree_credential(tmp_path: Path) -> None:
    """INV-1: the real policy rejects a planted working-tree credential by rule id."""

    executable = _gitleaks()
    tree = tmp_path / "working-tree"
    tree.mkdir()
    (tree / "credential.txt").write_text(f"token = {_synthetic_github_pat()}\n", encoding="utf-8")
    report_path = tmp_path / "dir-report.json"

    result = run_process(
        _gitleaks_command(executable, "dir", tree, report_path),
        cwd=tree,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    findings = _findings(report_path)
    assert len(findings) == 1
    assert findings[0]["RuleID"] == GITHUB_PAT_RULE_ID


def test_gitleaks_git_detects_a_credential_removed_from_the_working_tree(tmp_path: Path) -> None:
    """INV-1: history scanning catches a credential even after a deletion commit."""

    executable = _gitleaks()
    repository = tmp_path / "history"
    repository.mkdir()
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Hex Vision Test"],
    ):
        result = run_process(command, cwd=repository)
        assert result.returncode == 0, result.stdout + result.stderr

    credential_path = repository / "credential.txt"
    credential_path.write_text(f"token = {_synthetic_github_pat()}\n", encoding="utf-8")
    for command in (
        ["git", "add", "credential.txt"],
        ["git", "commit", "-m", "add synthetic credential"],
        ["git", "rm", "credential.txt"],
        ["git", "commit", "-m", "remove synthetic credential"],
    ):
        result = run_process(command, cwd=repository)
        assert result.returncode == 0, result.stdout + result.stderr
    assert not credential_path.exists()

    report_path = tmp_path / "git-report.json"
    result = run_process(
        _gitleaks_command(executable, "git", repository, report_path),
        cwd=repository,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    findings = _findings(report_path)
    assert len(findings) == 1
    assert findings[0]["RuleID"] == GITHUB_PAT_RULE_ID


def test_gitleaks_dir_accepts_a_clean_tree(tmp_path: Path) -> None:
    """INV-1: the policy distinguishes a clean working tree from a secret."""

    executable = _gitleaks()
    tree = tmp_path / "clean-tree"
    tree.mkdir()
    (tree / "readme.txt").write_text(
        "This directory intentionally contains no credentials.\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "clean-report.json"

    result = run_process(
        _gitleaks_command(executable, "dir", tree, report_path),
        cwd=tree,
    )

    assert result.returncode == 0, result.stdout + result.stderr
