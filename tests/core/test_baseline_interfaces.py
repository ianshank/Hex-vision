"""Behavioral tests for shared safety interfaces owned by the integration baseline."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import Config, load_config
from hexvision.errors import (
    ConfigError,
    FrozenKeyOverrideError,
    GateBlockedError,
    GateFailure,
    MissingKeyError,
)
from hexvision.gates.base import Gate, run_gate, run_gates
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.observability import JsonFormatter, configure_logging, get_logger, log_verdict
from hexvision.packs.base import TargetSpec


def test_json_formatter_and_verdict_logging_use_structured_stderr() -> None:
    """Formatter and verdict output preserve structure without contaminating stdout."""
    record = get_logger("formatter").makeRecord(
        "hexvision.formatter", 20, "", 0, "message %s", ("ok",), None, extra={"gate": "x"}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "message ok"
    assert payload["gate"] == "x"
    stream = io.StringIO()
    logger = configure_logging(fmt="json", env={}, stream=stream)
    log_verdict(logger, gate="remotes", passed=False, clause="INV-3", finding_count=1)
    logged = json.loads(stream.getvalue())
    assert logged["verdict"] == "fail"
    assert logged["clause"] == "INV-3"


@pytest.mark.parametrize(
    ("level", "fmt", "message"),
    [
        ("bogus", "text", r"unknown log level 'BOGUS'"),
        ("INFO", "bad", r"unknown log format 'bad'"),
    ],
)
def test_logging_rejects_invalid_configuration(level: str, fmt: str, message: str) -> None:
    """Invalid logging settings fail loudly instead of hiding diagnostics."""
    with pytest.raises(ValueError, match=message):
        configure_logging(level=level, fmt=fmt, env={})


def test_logging_defaults_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Default diagnostic output remains on stderr, leaving stdout machine-safe."""
    logger = configure_logging(env={})
    logger.info("diagnostic")
    captured = capsys.readouterr()
    assert "diagnostic" in captured.err
    assert captured.out == ""


# Traceability: R-1 [Later allowed layer wins with provenance, Malformed configured layer]
# Traceability: R-2 [Frozen safety override, Authorized repository safety change]
def test_config_frozen_refusal_provenance_and_accessors(tmp_path: Path) -> None:
    """Frozen policy cannot be weakened while ordinary values retain full provenance."""
    (tmp_path / "hex-vision.toml").write_text(
        "[remotes]\nallowlist=['gitlab.com/team/repo']\n", encoding="utf-8"
    )
    config = load_config(
        root=tmp_path,
        env={"HEXVISION_REMOTES__ALLOWLIST": '["github.com/team/repo"]'},
    )
    explained = config.explain("remotes.allowlist")
    assert explained.layer == "env"
    assert explained.shadowed
    assert (
        config.resolve_path("traceability.matrix_path")
        == tmp_path / "traceability/REQUIREMENT-TRACEABILITY.md"
    )
    with pytest.raises(MissingKeyError):
        config.require("missing.key", clause="X")
    with pytest.raises(MissingKeyError):
        config.explain("missing.key")
    with pytest.raises(FrozenKeyOverrideError):
        load_config(root=tmp_path, env={"HEXVISION_COVERAGE__PER_FILE_LINES": "1"})
    with pytest.raises(FrozenKeyOverrideError):
        load_config(root=tmp_path, overrides={"coverage": {"per_file_lines": 1}})
    malformed = tmp_path / "malformed.toml"
    malformed.write_text("[broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(root=tmp_path, config_path=malformed)


def test_config_environment_types_and_section_validation(tmp_path: Path) -> None:
    """Environment TOML values retain scalar types and invalid sections do not drift silently."""
    config = load_config(
        root=tmp_path,
        env={"HEXVISION_ROBOTICS__HARDWARE_IN_LOOP__TIMEOUT_SECONDS": "7"},
    )
    assert config.get("robotics.hardware_in_loop.timeout_seconds") == 7
    scalar = load_config(root=tmp_path, overrides={"remotes": "wrong"})
    with pytest.raises(ConfigError):
        scalar.section("remotes")


@dataclass(frozen=True)
class _TestGate(Gate):
    """Small controllable gate used to verify the shared fail-closed runner."""

    outcome: GateResult | Exception
    gate_name: str = "test-gate"

    @property
    def name(self) -> str:
        return self.gate_name

    @property
    def clause(self) -> str:
        return "TEST"

    def check(self, config: Config) -> GateResult:
        del config
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _failed_result() -> GateResult:
    """Provide a legitimate failed result for runner status preservation tests."""
    return GateResult.failed(
        "test-gate",
        summary="bad",
        findings=(Finding("F", Severity.MAJOR, "bad"),),
    )


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (GateResult.passed("test-gate", summary="ok"), GateStatus.PASSED),
        (_failed_result(), GateStatus.FAILED),
        (GateResult.blocked("test-gate", summary="no", reason="no"), GateStatus.BLOCKED),
        (GateFailure("bad"), GateStatus.FAILED),
        (GateBlockedError("missing"), GateStatus.BLOCKED),
        (ValueError("crash"), GateStatus.BLOCKED),
    ],
)
def test_run_gate_preserves_or_fail_closes_status(
    make_config: Callable[[Path, dict[str, Any] | None], Config],
    tmp_repo: Callable[..., Path],
    outcome: GateResult | Exception,
    expected: GateStatus,
) -> None:
    """Returned statuses survive and every escaped exception becomes a recorded non-pass."""
    result = run_gate(_TestGate(outcome), make_config(tmp_repo(), None))
    assert result.status is expected
    assert "duration_ms" in result.measurements


def test_run_gates_collects_all_results(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """The shared runner does not fail fast after an earlier failing gate."""
    gates = (
        _TestGate(_failed_result(), "first"),
        _TestGate(GateResult.passed("second", summary="ok"), "second"),
    )
    assert [result.gate for result in run_gates(gates, make_config(tmp_repo(), None))] == [
        "test-gate",
        "second",
    ]


def test_model_rejections_sorting_and_target_spec_validation() -> None:
    """Result and pack primitives reject fail-open shapes and keep findings deterministic."""
    with pytest.raises(ValueError, match=r"unknown severity 'unknown'"):
        Severity.from_label("unknown")
    blocker = Finding("z", Severity.BLOCKER, "z")
    major = Finding("a", Severity.MAJOR, "a")
    with pytest.raises(ValueError, match=r"reported PASSED while carrying"):
        GateResult.passed("x", summary="bad", findings=(major,))
    assert [
        finding.id
        for finding in GateResult.failed("x", summary="bad", findings=(major, blocker)).findings
    ] == ["z", "a"]
    with pytest.raises(ValueError, match=r"declares an empty command"):
        TargetSpec("x", ())
    with pytest.raises(ValueError, match=r"opts out of fail-closed behaviour"):
        TargetSpec("x", ("tool",), fail_closed_on_missing_tool=False)


# Traceability: R-18
def test_log_verdict_preserves_the_four_state_gate_model() -> None:
    """A blocked gate must never be reported to an operator as a failure.

    BLOCKED means the gate could not look; FAILED means it looked and found a
    violation. Collapsing the two is how a gate that never ran gets mistaken for a
    gate that ran and disagreed, so each status gets its own label and log level.
    """
    cases = {
        "passed": ("PASS", logging.INFO),
        "failed": ("FAIL", logging.ERROR),
        "blocked": ("BLOCKED", logging.ERROR),
        "skipped-declared": ("SKIPPED (DECLARED)", logging.WARNING),
    }
    for status, (label, level) in cases.items():
        stream = io.StringIO()
        logger = configure_logging(fmt="json", env={}, stream=stream)
        logger.setLevel(logging.DEBUG)
        log_verdict(logger, gate="publication", status=status, clause="R-17")
        logged = json.loads(stream.getvalue())
        assert logged["message"] == f"gate publication: {label}", status
        assert logged["verdict"] == status
        assert logged["status"] == status
        assert logged["level"] == logging.getLevelName(level), status


# Traceability: R-18
def test_log_verdict_keeps_the_published_boolean_path_working() -> None:
    """`passed` is published surface, so it must keep working unchanged."""
    stream = io.StringIO()
    logger = configure_logging(fmt="json", env={}, stream=stream)
    log_verdict(logger, gate="remotes", passed=True, clause="INV-3")
    assert json.loads(stream.getvalue())["verdict"] == "pass"


# Traceability: R-18
def test_log_verdict_refuses_an_unknown_or_absent_verdict() -> None:
    """An unrecognised status is refused rather than defaulted to a failure label."""
    logger = configure_logging(fmt="json", env={}, stream=io.StringIO())
    with pytest.raises(ValueError, match="unknown gate status"):
        log_verdict(logger, gate="x", status="probably-fine")
    with pytest.raises(ValueError, match="requires either"):
        log_verdict(logger, gate="x")
