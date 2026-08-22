"""Local fixtures for governance tests while the shared CORE fixture layer is in flight."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_process(
    arguments: list[str], *, cwd: Path, input_text: str = "", env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an argument vector so tests exercise scripts without shell interpolation."""
    merged_env = os.environ.copy()
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        arguments,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Build a small Git repository that carries the tested versioned scripts."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for script in (
        "install_hooks.sh",
        "pre_push_scan.sh",
        "pretooluse_guard.sh",
        "validate_specs.sh",
    ):
        target = repo / "scripts" / script
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(REPO_ROOT / "scripts" / script, target)
    for arguments in (
        ["git", "init"],
        ["git", "config", "user.email", "governance@example.test"],
        ["git", "config", "user.name", "Governance Test"],
    ):
        result = run_process(arguments, cwd=repo)
        assert result.returncode == 0, result.stderr
    return repo


def install_fake_normalizer(repo: Path) -> None:
    """Provide a local Python-shaped executable whose exit code tests delegation."""
    executable = repo / ".venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'fake normalizer verdict\\n' >&2\n"
        'exit "${HV_NORMALIZER_EXIT:-0}"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
