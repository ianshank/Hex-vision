"""Filesystem trust boundaries shared by robotics evidence gates."""

from __future__ import annotations

from pathlib import Path


def trusted_regular_file(root: Path, path: Path, label: str) -> Path:
    """Return a regular in-root evidence path or raise a fail-closed error.

    Evidence discovered through a repository glob must not quietly resolve
    through a symlink into an unrelated location.  A review of that repository
    cannot establish the provenance of such a file.
    """
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} resolves outside the repository root: {path}") from exc
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path
