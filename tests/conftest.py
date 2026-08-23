"""Shared test safety rails and isolated repository fixtures.

The collection hook is intentionally unconditional: a skipped test is invisible
coverage debt unless an actual recorded decision authorizes the exception.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from pluggy import Result

from hexvision.config import Config, load_config
from tests.support.process import coverage_controls_sanitized, run_process

_SKIP = re.compile(r"^\s*#\s*@governance-skip:\s*(\S+)\s+(\S.*)\s*$")


def _authorized_decision(item: pytest.Item) -> str | None:
    """Resolve a test-local marker to preserve its audit trail, never to permit a skip.

    The annotation is searched only in the contiguous comment/decorator block
    immediately above this item's test declaration. A valid marker elsewhere in
    a file cannot exempt a different test, and an unreadable log authorizes
    nothing by design.
    """
    path = Path(str(item.path))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        config = load_config(root=Path(item.config.rootpath))
        decision_log = config.resolve_path("traceability.decision_log_path")
        decisions = decision_log.read_text(encoding="utf-8")
        patterns = tuple(config.require("traceability.decision_id_patterns"))
    except Exception:
        return None
    start = item.location[1]
    header: list[str] = []
    for line in reversed(lines[:start]):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("@"):
            header.append(line)
            continue
        break
    for line in header:
        marker = _SKIP.match(line)
        if (
            marker
            and any(re.fullmatch(pattern, marker.group(1)) for pattern in patterns)
            and marker.group(1) in decisions
            and bool(marker.group(2).strip())
        ):
            return marker.group(1)
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[object]
) -> Generator[None, Result[pytest.TestReport], None]:
    """Convert every runtime skip or xfail into failure while naming a cited decision."""
    outcome = yield
    report = outcome.get_result()
    if report.when in {"setup", "call"} and (
        report.outcome == "skipped" or hasattr(report, "wasxfail")
    ):
        decision = _authorized_decision(item)
        report.outcome = "failed"
        report.longrepr = (
            "governance guard: skipped or xfailed test has no valid @governance-skip decision"
            if decision is None
            else (
                "governance guard: skipped or xfailed test cites authorized "
                f"@governance-skip decision {decision}; the project zero-skip policy "
                "still forbids it"
            )
        )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Callable[[str], Path]:
    """Build a minimal Git-configured repository so gates never rely on this checkout."""

    def create(overlay: str = "") -> Path:
        (tmp_path / "pyproject.toml").write_text(
            "[tool.hexvision.coverage]\nper_file_lines=90\nper_file_branches=80\n", encoding="utf-8"
        )
        (tmp_path / "hex-vision.toml").write_text(overlay, encoding="utf-8")
        run_process(["/usr/bin/git", "init"], cwd=tmp_path).check_returncode()
        return tmp_path

    return create


@pytest.fixture(autouse=True)
def sanitize_coverage_controls_for_indirect_test_processes() -> Generator[None, None, None]:
    """Keep production subprocesses caused by tests outside parent coverage collection.

    Tests may call a production API that starts a child internally. The child is
    fixture behavior rather than code under coverage, so the shared sanitizer
    removes pytest-cov controls for the test interval and restores the parent's
    branch measurement afterward.
    """
    with coverage_controls_sanitized():
        yield


@pytest.fixture
def make_config() -> Callable[[Path, dict[str, Any] | None], Config]:
    """Resolve an isolated config with optional non-frozen caller overrides."""

    def create(root: Path, overrides: dict[str, Any] | None = None) -> Config:
        return load_config(root=root, overrides=overrides)

    return create
