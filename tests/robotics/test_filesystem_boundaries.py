"""Hermetic hostile-filesystem coverage shared by the robotics evidence gates."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus
from hexvision.robotics.determinism import DeterminismGate
from hexvision.robotics.diagnostics import command_identity, diagnostic_policy, redacted_excerpt
from hexvision.robotics.filesystem import trusted_regular_file
from hexvision.robotics.hardware_in_loop import HardwareInLoopGate
from hexvision.robotics.latency import LatencyBudgetGate
from hexvision.robotics.model_card import ModelCardGate
from hexvision.robotics.safety_envelope import SafetyEnvelopeGate
from tests.robotics.boundaries import external_symlink, restore_readable, unreadable


def test_diagnostic_policy_redacts_and_bounds_external_context(tmp_path: Path) -> None:
    """The shared policy validates configuration and redacts before truncation."""
    policy = diagnostic_policy(load_config(root=tmp_path, env={}), clause="test")
    command = command_identity(("runner", "token=super-secret-value"), policy)
    excerpt = redacted_excerpt("password=also-secret " + "x" * 1_000, policy)
    assert command == "runner [REDACTED]"
    assert excerpt.startswith("[REDACTED]")
    assert len(excerpt) == policy["excerpt_max_chars"]


@pytest.mark.parametrize(
    ("overlay", "message"),
    [
        ("stderr_excerpt_max_chars = 0", "excerpt length"),
        ("secret_patterns = []", "secret patterns"),
        ('redaction = ""', "redaction marker"),
        ('command_encoding = ""', "encoding"),
        ('command_decode_errors = ""', "decode error policy"),
        ('secret_patterns = ["["]', "pattern is invalid"),
    ],
)
def test_diagnostic_policy_rejects_unsafe_configuration(
    tmp_path: Path, overlay: str, message: str
) -> None:
    """Invalid diagnostic controls fail at configuration use, not in a runner."""
    (tmp_path / "hex-vision.toml").write_text(
        f"[robotics.diagnostics]\n{overlay}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=message):
        diagnostic_policy(load_config(root=tmp_path, env={}), clause="test")


def test_trusted_regular_file_rejects_outside_and_non_regular_paths(tmp_path: Path) -> None:
    """Direct boundary checks cover paths discovered outside a gate's glob."""
    external = tmp_path.parent / f"{tmp_path.name}-external-evidence"
    external.write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the repository root"):
        trusted_regular_file(tmp_path, external, "evidence")
    directory = tmp_path / "evidence-directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        trusted_regular_file(tmp_path, directory, "evidence")


@pytest.mark.parametrize(
    ("relative", "gate", "expected_finding"),
    [
        ("models/detector/model-card.md", ModelCardGate, "MODEL-CARD-BLOCKED"),
        ("models/detector/model-card.md", LatencyBudgetGate, "LATENCY-BUDGET-BLOCKED"),
        ("models/detector/eval-runs.json", DeterminismGate, "DETERMINISM-BLOCKED"),
        ("missions/patrol.toml", SafetyEnvelopeGate, "SAFETY-ENVELOPE-BLOCKED"),
    ],
)
def test_evidence_symlink_outside_repository_is_blocked(
    passing_repo: Any, tmp_path: Path, relative: str, gate: type[Any], expected_finding: str
) -> None:
    """Every filesystem-reading gate refuses evidence that escapes the repository."""
    root = passing_repo()
    evidence = root / relative
    evidence.unlink()
    external_symlink(evidence, tmp_path.parent / f"{tmp_path.name}-outside" / evidence.name)
    result = gate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == expected_finding
    assert "symlink" in result.findings[0].message
    assert not result.measurements


def test_hardware_decision_symlink_does_not_authorise_absence(tmp_path: Path) -> None:
    """A decision log outside the repository cannot turn missing hardware green."""
    docs = tmp_path / "docs"
    decision_log = docs / "decision-log.md"
    external_symlink(
        decision_log,
        tmp_path.parent / f"{tmp_path.name}-outside" / "decision-log.md",
    )
    (decision_log.resolve()).write_text(
        "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer\n"
        "2026-08-22 | DEC-2 | sitl_mission unavailable | reviewer\n",
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert result.findings[0].id == "HARDWARE-IN-LOOP-UNDECLARED-SKIP"
    assert result.measurements["missing"] == {"hil_smoke": None, "sitl_mission": None}


@pytest.mark.parametrize(
    ("relative", "gate", "expected_finding"),
    [
        ("models/detector/model-card.md", ModelCardGate, "MODEL-CARD-BLOCKED"),
        ("models/detector/eval-runs.json", DeterminismGate, "DETERMINISM-BLOCKED"),
        ("missions/patrol.toml", SafetyEnvelopeGate, "SAFETY-ENVELOPE-BLOCKED"),
    ],
)
def test_non_utf8_evidence_is_blocked(
    passing_repo: Any, relative: str, gate: type[Any], expected_finding: str
) -> None:
    """Non-UTF-8 and non-TOML/JSON bytes cannot be trusted as evidence."""
    root = passing_repo()
    (root / relative).write_bytes(b"\xff\xfe\x00")
    result = gate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == expected_finding
    assert "could not be read" in result.summary or "could not be parsed" in result.summary
    assert not result.measurements


def test_unreadable_model_card_is_blocked_without_a_skip(passing_repo: Any) -> None:
    """A real permission-denied evidence path follows the gate's fail-closed branch."""
    root = passing_repo()
    card = unreadable(root / "models/detector/model-card.md")
    try:
        result = ModelCardGate().check(load_config(root=root, env={}))
    finally:
        restore_readable(card)
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "MODEL-CARD-BLOCKED"
    assert "cannot read model card" in result.findings[0].message
    assert not result.measurements


@pytest.mark.parametrize("gate", [ModelCardGate, LatencyBudgetGate])
def test_unicode_and_oversized_card_content_has_measured_outcome(
    passing_repo: Any, gate: type[Any]
) -> None:
    """Unicode and a large real document do not cause a silent or partial result."""
    root = passing_repo()
    card = root / "models/detector/model-card.md"
    original = card.read_text(encoding="utf-8")
    card.write_text(f"{original}\nユニコード evidence\n{'x' * 1_000_000}", encoding="utf-8")
    result = gate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert not result.findings
    assert (
        result.measurements["models"] == 1
        if gate is LatencyBudgetGate
        else result.measurements["cards"] == 1
    )


def test_concurrent_mission_replacement_is_never_reported_as_clean_if_invalid(
    passing_repo: Any,
) -> None:
    """Concurrent atomic replacement of invalid evidence remains fail-closed."""
    root = passing_repo()
    mission = root / "missions/patrol.toml"
    replacement_started = Event()
    replacement_finished = Event()
    invalid_content = 'incomplete = "' + "x" * 200_000

    def replace_mission() -> None:
        for generation in range(4):
            replacement = mission.with_suffix(f".replacement-{generation}")
            replacement.write_text(invalid_content, encoding="utf-8")
            replacement.replace(mission)
            replacement_started.set()
        replacement_finished.set()

    writer = Thread(target=replace_mission)
    writer.start()
    assert replacement_started.wait(timeout=2)
    result = SafetyEnvelopeGate().check(load_config(root=root, env={}))
    writer.join(timeout=2)
    assert replacement_finished.is_set()
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "SAFETY-ENVELOPE-BLOCKED"
    assert "cannot parse" in result.findings[0].message
    assert not result.measurements
