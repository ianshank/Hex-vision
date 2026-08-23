"""Tests for declared hardware absence and configurable Jetson pack registration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus, Severity
from hexvision.packs.jetson import JetsonPack, _strings, pack
from hexvision.robotics.hardware_in_loop import HardwareInLoopGate


# Traceability: R-15 [Runner is present, Runner is absent]
def test_hardware_missing_without_decision_is_visible_blocker(tmp_path: Path) -> None:
    """A missing runner yields the declared-skip status with its unauthorised blocker."""
    config = load_config(root=tmp_path, env={})
    result = HardwareInLoopGate().check(config)
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert result.findings[0].id == "HARDWARE-IN-LOOP-UNDECLARED-SKIP"
    assert result.findings[0].severity is Severity.BLOCKER
    assert "absent configured hardware runners" in result.findings[0].message
    assert result.measurements["missing"] == {"hil_smoke": None, "sitl_mission": None}


def test_hardware_missing_with_decision_is_declared(tmp_path: Path) -> None:
    """A decision log entry naming each runner owns an intentional CI absence."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        (
            "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer\n"
            "2026-08-22 | DEC-2 | sitl_mission unavailable | reviewer\n"
        ),
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert not result.findings
    assert result.measurements["decision_id"] == "DEC-1,DEC-2"
    assert result.measurements["missing"] == {"hil_smoke": "DEC-1", "sitl_mission": "DEC-2"}


def test_hardware_present_runner_passes(tmp_path: Path) -> None:
    """Presence, rather than a --help exit code, controls probing before execution."""
    (tmp_path / "hex-vision.toml").write_text(
        f"""
[robotics.hardware_in_loop]
optional_gates = ["local"]
runners = {{ local = [{json.dumps(sys.executable)}, "-c", ""] }}
""",
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.PASSED
    assert not result.findings
    assert result.measurements["executed"] == {"local": 0}
    assert result.measurements["diagnostics"]["local"]["returncode"] == "0"


def test_hardware_present_runner_failure_is_failed(tmp_path: Path) -> None:
    """A runner that talks to hardware but fails its scenario is a real finding."""
    secret = "token=do-not-record"  # noqa: S105 - redaction test fixture.
    failure_script = f"import sys; sys.stderr.write({secret!r}); raise SystemExit(1)"
    (tmp_path / "hex-vision.toml").write_text(
        f"""
[robotics.hardware_in_loop]
optional_gates = ["local"]
runners = {{ local = [{json.dumps(sys.executable)}, "-c", {json.dumps(failure_script)}] }}
""",
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.FAILED
    assert result.findings[0].id == "HIL-LOCAL-FAILED"
    assert "exited with status 1" in result.findings[0].message
    assert result.measurements["executed"] == {"local": 1}
    assert secret not in result.findings[0].context["stderr"]
    assert "[REDACTED]" in result.findings[0].context["stderr"]


def test_hardware_blocks_unconfigured_runner(configured_root: Any) -> None:
    """A declared optional gate without a command cannot pretend to have been probed."""
    config = configured_root(
        '[robotics.hardware_in_loop.runners]\nhil_smoke = []\nsitl_mission = ["tool"]\n'
    )
    result = HardwareInLoopGate().check(config)
    assert result.status is GateStatus.BLOCKED


def test_hardware_blocks_runner_timeout_with_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A runner timeout is infrastructure absence, not a pass or skip."""
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.shutil.which", lambda _command: "/tool"
    )
    monkeypatch.setattr(
        "hexvision.robotics.hardware_in_loop.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["tool"], 1, stderr="secret=offline")
        ),
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "HIL-HIL_SMOKE-UNAVAILABLE"
    assert result.findings[0].context["exception_class"] == "TimeoutExpired"
    assert result.measurements["diagnostics"]["hil_smoke"]["stderr"] == "[REDACTED]"


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
