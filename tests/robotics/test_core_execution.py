"""Execution-path tests for shared runner and observability contracts used by robotics gates."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Literal

import pytest

from hexvision.config import Config, load_config
from hexvision.errors import GateBlockedError, GateFailure
from hexvision.gates.base import Gate, run_gate, run_gates
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.observability import JsonFormatter, configure_logging, get_logger, log_verdict


class StubGate(Gate):
    """A controlled gate isolates the common fail-closed runner's outcome branches."""

    def __init__(self, outcome: Literal["pass", "failure", "blocked", "crash"]) -> None:
        """Store the requested runner outcome so each shared execution path can be asserted."""
        self.outcome = outcome

    @property
    def name(self) -> str:
        """Return a stable synthetic gate identifier for structured results."""
        return "stub"

    @property
    def clause(self) -> str:
        """Return the clause used to confirm runner clause propagation."""
        return "T-STUB"

    def check(self, config: Config) -> GateResult:
        """Return or raise a deliberately selected outcome without consulting policy."""
        del config
        if self.outcome == "failure":
            raise GateFailure("failed", clause="T-FAIL")
        if self.outcome == "blocked":
            raise GateBlockedError("blocked", clause="T-BLOCK")
        if self.outcome == "crash":
            raise RuntimeError("crashed")
        return GateResult.passed(self.name, summary="ok")


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Provide a resolved config for runner tests without mutating process state."""
    return load_config(root=tmp_path, env={})


@pytest.mark.parametrize(
    ("outcome", "status", "clause"),
    [
        ("pass", GateStatus.PASSED, "T-STUB"),
        ("failure", GateStatus.FAILED, "T-FAIL"),
        ("blocked", GateStatus.BLOCKED, "T-BLOCK"),
        ("crash", GateStatus.BLOCKED, "T-STUB"),
    ],
)
def test_runner_returns_structured_results_for_every_outcome(
    config: Config,
    outcome: Literal["pass", "failure", "blocked", "crash"],
    status: GateStatus,
    clause: str,
) -> None:
    """Unexpected exceptions and governance errors retain a result rather than escaping CI."""
    result = run_gate(StubGate(outcome), config)
    assert result.status is status
    assert result.clause == clause
    assert "duration_ms" in result.measurements


def test_runner_runs_all_gates(config: Config) -> None:
    """A failing early gate does not hide another gate's result from a reviewer."""
    results = run_gates((StubGate("failure"), StubGate("pass")), config)
    assert [result.status for result in results] == [GateStatus.FAILED, GateStatus.PASSED]


def test_gate_default_properties() -> None:
    """Default metadata supplies a useful description and repository requirement."""
    gate = StubGate("pass")
    assert gate.description.startswith("A controlled gate")
    assert gate.requires_repository


def test_structured_logging_writes_json_to_given_stream() -> None:
    """Diagnostics retain context in stderr-like streams without contaminating gate JSON stdout."""
    stream = io.StringIO()
    logger = configure_logging(fmt="json", level="INFO", env={}, stream=stream)
    log_verdict(logger, gate="stub", passed=False, clause="T", measured=1)
    record = json.loads(stream.getvalue())
    assert record["gate"] == "stub"
    assert record["verdict"] == "fail"
    assert get_logger("hexvision").name == "hexvision"


@pytest.mark.parametrize("kwargs", [{"level": "NOPE"}, {"fmt": "binary"}])
def test_logging_rejects_unknown_configuration(kwargs: dict[str, str]) -> None:
    """A misspelled observability setting cannot silently hide a governance result."""
    with pytest.raises(ValueError):
        configure_logging(env={}, **kwargs)


def _raise_example() -> None:
    """Raise a controlled error so formatter tests retain real exception context."""
    raise RuntimeError("example")


def test_json_formatter_includes_extra_and_exception() -> None:
    """Formatter preserves arbitrary structured context and traceback evidence."""
    formatter = JsonFormatter()
    try:
        _raise_example()
    except RuntimeError:
        record = logging.getLogger("test").makeRecord(
            "test",
            logging.ERROR,
            "",
            0,
            "bad",
            (),
            exc_info=__import__("sys").exc_info(),
            extra={"model": "x"},
        )
    rendered = json.loads(formatter.format(record))
    assert rendered["model"] == "x"
    assert "exception" in rendered


def test_gate_result_serialises_and_sorts_findings() -> None:
    """Result helpers produce stable audit output and reject empty failures."""
    major = Finding("b", Severity.MAJOR, "bad")
    minor = Finding("a", Severity.MINOR, "note")
    result = GateResult.failed("g", summary="bad", findings=(minor, major))
    assert [item["id"] for item in result.to_dict()["findings"]] == ["b", "a"]
    with pytest.raises(ValueError):
        GateResult.failed("g", summary="bad", findings=())
