"""Branch-level traceability tests for parser and collection failure modes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hexvision import traceability
from hexvision.config import Config


def test_parse_matrix_rejects_bad_tables(tmp_path: Path) -> None:
    """The strict parser distinguishes absent headers, separators, and malformed rows."""
    path = tmp_path / "matrix.md"
    path.write_text("intro\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        traceability.parse_matrix(path, ["id"])
    path.write_text("| id |\n| bad |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        traceability.parse_matrix(path, ["id"])
    path.write_text("| id | name |\n| --- | --- |\n| one |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cells"):
        traceability.parse_matrix(path, ["id", "name"])


def test_collects_distinguishes_missing_tool_and_uncollected(
    make_config: Callable[[Path, dict[str, Any] | None], Config],
    tmp_repo: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing pytest executable blocks while a completed collection reports false."""
    config = make_config(tmp_repo(), None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert traceability._collects(config, "x") is None
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 1, "", ""),
    )
    assert traceability._collects(config, "x") is False


def test_green_traceability_collection_paths(
    make_config: Callable[[Path, dict[str, Any] | None], Config],
    tmp_repo: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collectable and uncollectable Green evidence drive the real result branches."""
    root = tmp_repo()
    (root / "traceability").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "docs" / "decision-log.md").write_text("DEC-1\n", encoding="utf-8")
    (root / "tests" / "test_x.py").write_text("# R-1\n", encoding="utf-8")
    (root / "traceability" / "REQUIREMENT-TRACEABILITY.md").write_text(
        "| requirement id | statement | status | test node id "
        "| inherits-from | decision ref | notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| R-1 | s | Green | tests/test_x.py::test_x | | | |\n",
        encoding="utf-8",
    )
    config = make_config(root, None)
    monkeypatch.setattr(traceability, "_collects", lambda _config, _node: True)
    assert traceability.check_traceability(config).status.value == "passed"
    monkeypatch.setattr(traceability, "_collects", lambda _config, _node: None)
    assert traceability.check_traceability(config).status.value == "blocked"
    monkeypatch.setattr(traceability, "_collects", lambda _config, _node: False)
    assert traceability.check_traceability(config).status.value == "failed"
