"""Reusable hermetic filesystem and process boundaries for robotics gate tests."""

from __future__ import annotations

from pathlib import Path

from tests.support.process import run_process


def commit_file(root: Path, relative: Path, content: str | bytes) -> None:
    """Commit a real file as the baseline used by the configured git command."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    run_process(["git", "add", relative.as_posix()], cwd=root).check_returncode()
    run_process(
        ["git", "commit", "--quiet", "-m", "baseline evidence"], cwd=root
    ).check_returncode()


def external_symlink(link: Path, target: Path) -> Path:
    """Create a real symlink to a file intentionally outside the repository root."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("outside evidence", encoding="utf-8")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return link


def unreadable(path: Path) -> Path:
    """Remove read permissions from a real path; callers restore permissions if needed."""
    path.chmod(0)
    return path


def restore_readable(path: Path) -> None:
    """Restore owner read/write permissions before temporary-directory cleanup."""
    path.chmod(0o600)
