"""Tests for declared hardware absence and configurable Jetson pack registration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus, Severity
from hexvision.packs.jetson import JetsonPack, _strings, pack
from hexvision.robotics.hardware_in_loop import HardwareInLoopGate


# Traceability: R-15
def test_hardware_missing_without_decision_is_visible_blocker(tmp_path: Path) -> None:
    """A missing runner yields the declared-skip status with its unauthorised blocker."""
    config = load_config(root=tmp_path, env={})
    result = HardwareInLoopGate().check(config)
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert result.findings[0].severity is Severity.BLOCKER


def test_hardware_missing_with_decision_is_declared(tmp_path: Path) -> None:
    """A decision log entry naming each runner owns an intentional CI absence."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text("DEC-1 hil_smoke\nDEC-2 sitl_mission", encoding="utf-8")
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert not result.findings
    assert result.measurements["decision_id"] == "DEC-1,DEC-2"


def test_hardware_present_runner_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Presence, rather than a --help exit code, controls probing before execution."""
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.shutil.which", lambda _command: "/tool"
    )
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(_args[0], 0, stdout="", stderr=""),
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.PASSED
    assert result.measurements["executed"] == {"hil_smoke": 0, "sitl_mission": 0}


def test_hardware_present_runner_failure_is_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A runner that talks to hardware but fails its scenario is a real finding."""
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.shutil.which", lambda _command: "/tool"
    )
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(_args[0], 1, stdout="", stderr=""),
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.FAILED
    assert len(result.findings) == 2


def test_hardware_blocks_unconfigured_runner(configured_root: Any) -> None:
    """A declared optional gate without a command cannot pretend to have been probed."""
    config = configured_root(
        '[robotics.hardware_in_loop.runners]\nhil_smoke = []\nsitl_mission = ["tool"]\n'
    )
    result = HardwareInLoopGate().check(config)
    assert result.status is GateStatus.BLOCKED


def test_hardware_blocks_runner_execution_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An executable that cannot start is infrastructure absence, not a pass or skip."""
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.shutil.which", lambda _command: "/tool"
    )
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED


def test_jetson_pack_registers_contract_targets_and_domain_gates(tmp_path: Path) -> None:
    """The entry-point instance exposes all contract names and exactly five robotics gates."""
    config = load_config(root=tmp_path, env={})
    targets = pack.targets(config)
    assert isinstance(pack, JetsonPack)
    assert set(targets) == set(config.require("contract.targets"))
    assert targets["specs"].degrades_loudly
    assert targets["lint"].fail_closed_on_missing_tool
    assert [gate.clause for gate in pack.domain_gates(config)] == [
        "R-MC",
        "R-LAT",
        "R-DET",
        "R-SAFE",
        "R-HIL",
    ]


def test_jetson_pack_metadata_has_real_reference_docs() -> None:
    """Pack metadata gives adopters the vendor and runtime documentation it references."""
    assert pack.meta.name == "jetson"
    assert all(url.startswith("https://") for url in pack.meta.reference_docs)


@pytest.mark.parametrize("value", [[], [""]])
def test_jetson_command_vectors_must_be_non_empty_strings(value: list[str]) -> None:
    """An empty command cannot satisfy the pack's fail-closed target contract."""
    with pytest.raises(ValueError, match="non-empty string list"):
        _strings(value)
