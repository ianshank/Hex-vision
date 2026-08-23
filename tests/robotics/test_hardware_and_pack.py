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
    """An unauthorised runner absence is BLOCKED, not a declared skip.

    The gate could not look at the hardware and no decision accepted that, so
    reporting SKIPPED_DECLARED would advertise an owned skip while decision_id is
    None. A reader scanning for skips would treat it as already reviewed.
    """
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.measurements["decision_id"] is None
    assert result.findings[0].id == "HARDWARE-IN-LOOP-BLOCKED"
    assert result.findings[0].severity is Severity.BLOCKER
    assert "without decision-log authority" in result.findings[0].message
    assert "hil_smoke" in result.findings[0].message
    assert result.measurements["missing"] == {"hil_smoke": None, "sitl_mission": None}


# Traceability: R-15 [Absence authority is resolved by the shared verifier]
def test_hardware_missing_with_decision_is_declared(tmp_path: Path) -> None:
    """A live record whose subject names each runner owns an intentional CI absence.

    Authority resolves through the shared verifier by exact subject equality on
    ``hardware-in-loop:<runner>``, and the typed authority rides on the result
    while the measurements keep their serialisable per-runner id shape.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        (
            "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer "
            "| hardware-in-loop:hil_smoke | active | -\n"
            "2026-08-22 | DEC-2 | sitl_mission unavailable | reviewer "
            "| hardware-in-loop:sitl_mission | active | -\n"
        ),
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert not result.findings
    assert result.measurements["decision_id"] == "DEC-1,DEC-2"
    assert result.measurements["missing"] == {"hil_smoke": "DEC-1", "sitl_mission": "DEC-2"}
    assert result.declared_skip_authority is not None
    assert {
        runner: authority.decision_id
        for runner, authority in result.declared_skip_authority.items()
    } == {"hil_smoke": "DEC-1", "sitl_mission": "DEC-2"}
    assert all(
        authority.subject == f"hardware-in-loop:{runner}"
        for runner, authority in result.declared_skip_authority.items()
    )


# Traceability: R-15 [Absence authority is resolved by the shared verifier]
def test_prose_mention_of_a_runner_no_longer_authorises_its_absence(tmp_path: Path) -> None:
    """The pre-DEC-016 exploit: a runner named inside prose cells used to authorize.

    The old check matched the runner name as a substring of the whole joined
    record row. These records mention both runners in prose — one even as a
    substring of a longer rig name — but their subject cells authorize nothing,
    so the absence must stay BLOCKED.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        (
            "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer | - | active | -\n"
            "2026-08-22 | DEC-2 | sitl_mission moved to sitl_mission_extra rig | reviewer "
            "| hardware-in-loop:sitl_mission_extra | active | -\n"
        ),
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert "without decision-log authority" in result.findings[0].message
    assert result.measurements["missing"] == {"hil_smoke": None, "sitl_mission": None}


# Traceability: R-15 [Absence authority is resolved by the shared verifier]
def test_withdrawn_absence_authority_blocks_the_gate(tmp_path: Path) -> None:
    """A later supersedes reference withdraws an absence authorization for good.

    The withdrawn runner's absence becomes unauthorised even though the original
    record's own status cell still says active — the ledger is append-only, so
    only the later reference can kill it.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        (
            "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer "
            "| hardware-in-loop:hil_smoke | active | -\n"
            "2026-08-22 | DEC-2 | sitl_mission unavailable | reviewer "
            "| hardware-in-loop:sitl_mission | active | -\n"
            "2026-08-23 | DEC-3 | rig restored; DEC-1 withdrawn | reviewer | - | active | DEC-1\n"
        ),
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert "hil_smoke" in result.findings[0].message
    assert "sitl_mission" not in result.findings[0].message
    assert result.measurements["missing"] == {"hil_smoke": None, "sitl_mission": "DEC-2"}
    assert result.measurements["denials"]["hil_smoke"].startswith("superseded:")


# Traceability: R-15 [Absence authority is resolved by the shared verifier]
def test_authorised_absence_does_not_convert_a_failed_runner(tmp_path: Path) -> None:
    """An owned absence for one runner never greens another runner's failure.

    The decision authorizes the absence only; a present runner that failed its
    scenario keeps the gate FAILED, with the authorised absence still visible
    in the missing measurement.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        "2026-08-22 | DEC-1 | absent runner accepted | reviewer "
        "| hardware-in-loop:absent | active | -\n",
        encoding="utf-8",
    )
    failure_script = "import sys; raise SystemExit(1)"
    (tmp_path / "hex-vision.toml").write_text(
        f"""
[robotics.hardware_in_loop]
optional_gates = ["local", "absent"]
runners = {{ local = [{json.dumps(sys.executable)}, "-c", {json.dumps(failure_script)}], \
absent = ["hexvision-definitely-not-installed"] }}
""",
        encoding="utf-8",
    )
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.FAILED
    assert result.findings[0].id == "HIL-LOCAL-FAILED"
    assert result.measurements["executed"] == {"local": 1}
    assert result.measurements["missing"] == {"absent": "DEC-1"}


# Traceability: R-15 [Unreadable absence ledger]
def test_unstatable_ledger_blocks_instead_of_reading_as_never_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only ENOENT means "never written"; any other stat failure is evidence loss.

    ``Path.exists()`` swallows non-ENOENT errors on newer Python versions, which
    would misclassify an unreadable ledger as an absent one. The probe uses
    ``lstat`` so a permission failure surfaces as a named evidence BLOCK.
    """
    config = load_config(root=tmp_path, env={})
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda _self: (_ for _ in ()).throw(PermissionError("permission denied on ledger")),
    )
    result = HardwareInLoopGate().check(config)
    assert result.status is GateStatus.BLOCKED
    assert result.summary == "hardware absence authority could not be verified"
    assert "permission denied on ledger" in result.findings[0].message


# Traceability: R-15 [Unreadable absence ledger]
def test_undecodable_ledger_blocks_as_an_evidence_failure(tmp_path: Path) -> None:
    """A ledger that exists but cannot be decoded is 'could not look', not 'no decision'."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_bytes(b"\xff\xfe invalid utf-8 ledger bytes")
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.summary == "hardware absence authority could not be verified"
    assert "not valid UTF-8" in result.findings[0].message


# Traceability: R-15 [Unreadable absence ledger]
def test_symlinked_ledger_blocks_instead_of_authorising(tmp_path: Path) -> None:
    """Absence authority must come from a trusted regular file, never a symlink."""
    docs = tmp_path / "docs"
    docs.mkdir()
    real = tmp_path / "elsewhere.md"
    real.write_text(
        "2026-08-22 | DEC-1 | hil_smoke unavailable | reviewer "
        "| hardware-in-loop:hil_smoke | active | -\n",
        encoding="utf-8",
    )
    (docs / "decision-log.md").symlink_to(real)
    result = HardwareInLoopGate().check(load_config(root=tmp_path, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.summary == "hardware absence authority could not be verified"
    assert "symlink" in result.findings[0].message


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
