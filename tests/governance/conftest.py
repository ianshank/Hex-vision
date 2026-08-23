"""Local fixtures for governance tests while the shared CORE fixture layer is in flight."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.support.process import run_process as _run_process

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_process(
    arguments: list[str], *, cwd: Path, input_text: str = "", env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Preserve governance callers while sharing hermetic process execution."""
    return _run_process(arguments, cwd=cwd, input_text=input_text, env=env)


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
        "printf 'fake normalizer verdict for %s\\n' \"${GIT_CONFIG_VALUE_0:-missing}\" >&2\n"
        'if [ -n "${HV_EXPECTED_URL:-}" ] '
        '&& [ "${GIT_CONFIG_VALUE_0:-}" != "$HV_EXPECTED_URL" ]; then\n'
        "  printf 'normalizer input was ignored\\n' >&2\n"
        "  exit 0\n"
        "fi\n"
        'exit "${HV_NORMALIZER_EXIT:-0}"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)


def install_fake_uv_normalizer(repo: Path) -> Path:
    """Expose the same input-checking normalizer only through the uv fallback."""
    install_fake_normalizer(repo)
    venv_normalizer = repo / ".venv" / "bin" / "python"
    normalizer = repo / ".fake-normalizer"
    venv_normalizer.replace(normalizer)
    shutil.rmtree(repo / ".venv")
    bin_dir = repo / ".fake-bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        '[ "$1" = "run" ]\n'
        "shift\n"
        '[ "$1" = "--project" ]\n'
        "shift 2\n"
        '[ "$1" = "python" ]\n'
        "shift\n"
        f'exec "{normalizer}" "$@"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    return bin_dir
