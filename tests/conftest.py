"""Shared test safety rails and isolated repository fixtures.

Pytest's own session reports are the authority for zero-skip enforcement.  AST
checks give fast source feedback, but collection-time skips and dynamically
constructed skip calls exist only in pytest's accounting.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import Config, load_config
from tests.support.process import coverage_controls_sanitized, run_process

_SKIP = re.compile(r"^\s*#\s*@governance-skip:\s*(\S+)\s+(\S.*)\s*$")


@dataclass
class ZeroSkipSessionAudit:
    """Record pytest's collection and terminal reports for the zero-skip policy."""

    collected: int = 0
    deselected: int = 0
    executed_nodeids: set[str] = field(default_factory=set)
    violations: list[str] = field(default_factory=list)
    items: dict[str, pytest.Item] = field(default_factory=dict)

    def record_runtime_report(self, report: pytest.TestReport) -> None:
        """Record outcomes that terminal accounting must never permit."""
        if report.when == "call":
            self.executed_nodeids.add(report.nodeid)


_SESSION_AUDIT_HOLDER: dict[str, ZeroSkipSessionAudit | None] = {"audit": None}


def _active_audit() -> ZeroSkipSessionAudit:
    """Return the active session state required by collection reports without config."""
    audit = _SESSION_AUDIT_HOLDER["audit"]
    if audit is None:
        raise RuntimeError("zero-skip terminal accounting was not configured")
    return audit


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


def _runtime_violation_reason(report: pytest.TestReport, audit: ZeroSkipSessionAudit) -> str:
    """Describe a runtime skip while retaining any local governance decision evidence."""
    item = audit.items.get(report.nodeid)
    decision = _authorized_decision(item) if item is not None else None
    if getattr(report, "wasxfail", False):
        outcome = "XPASS" if report.outcome == "passed" else "XFAIL"
    else:
        outcome = "runtime skip"
    if decision is None:
        return (
            f"zero-skip terminal accounting failure: {outcome} recorded for {report.nodeid}; "
            "it has no valid @governance-skip decision"
        )
    return (
        f"zero-skip terminal accounting failure: {outcome} recorded for {report.nodeid}; "
        f"it cites authorized @governance-skip decision {decision}, but the project "
        "zero-skip policy still forbids it"
    )


@pytest.hookimpl
def pytest_configure(config: pytest.Config) -> None:
    """Install session-scoped accounting before collection can skip a module."""
    del config
    _SESSION_AUDIT_HOLDER["audit"] = ZeroSkipSessionAudit()


@pytest.hookimpl
def pytest_collection_finish(session: pytest.Session) -> None:
    """Snapshot the collected item set before execution changes the test outcome."""
    audit = _active_audit()
    audit.collected = len(session.items)
    audit.items = {item.nodeid: item for item in session.items}


@pytest.hookimpl
def pytest_collectreport(report: pytest.CollectReport) -> None:
    """Record collection-time skips, including importorskip and module pytest.skip."""
    if report.outcome == "skipped":
        _active_audit().violations.append(f"collection skip recorded for {report.nodeid}")


@pytest.hookimpl
def pytest_deselected(items: list[pytest.Item]) -> None:
    """Reject omitted collected items even when no skip marker caused their removal."""
    if items:
        _active_audit().deselected += len(items)


@pytest.hookimpl
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record runtime reports without rewriting them before pytest accounts for them."""
    _active_audit().record_runtime_report(report)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the whole run from pytest accounting when collection and execution diverge."""
    if session.config.option.collectonly:
        return
    audit = _active_audit()
    messages: list[str] = []
    for report_message in audit.violations:
        if report_message.startswith("collection skip"):
            messages.append(f"zero-skip terminal accounting failure: {report_message}")
    runtime_reports = [
        report
        for reports in session.config.pluginmanager.getplugin("terminalreporter").stats.values()
        for report in reports
        if isinstance(report, pytest.TestReport)
        and report.when in {"setup", "call"}
        and (report.outcome == "skipped" or getattr(report, "wasxfail", False))
    ]
    messages.extend(_runtime_violation_reason(report, audit) for report in runtime_reports)
    if audit.deselected:
        messages.append(
            f"zero-skip terminal accounting failure: {audit.deselected} deselected test(s) recorded"
        )
    executed = len(audit.executed_nodeids)
    if executed != audit.collected:
        messages.append(
            "zero-skip terminal accounting failure: "
            f"collected {audit.collected} test(s) but executed {executed} test body/bodies"
        )
    if messages:
        terminal = session.config.pluginmanager.getplugin("terminalreporter")
        for message in dict.fromkeys(messages):
            terminal.write_line(message, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


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
