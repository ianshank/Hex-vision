"""Focused tests for policy-validation and alternate evidence-format paths."""

from __future__ import annotations

from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus
from hexvision.robotics.determinism import DeterminismGate
from hexvision.robotics.hardware_in_loop import HardwareInLoopGate
from hexvision.robotics.safety_envelope import SafetyEnvelopeGate, _is_widened


def test_determinism_reads_toml_record(passing_repo: Any) -> None:
    """TOML is a supported record form under the configured record globs."""
    root = passing_repo()
    json_record = root / "models/detector/eval-runs.json"
    json_record.unlink()
    (root / "models/detector/eval-runs.toml").write_text(
        "schema_version = 1\nmodel_name = 'detector'\n"
        "[[runs]]\nmetric_value = 0.9\npython_seed = 1\nnumpy_seed = 1\nframework_seed = 1\n"
        "[[runs]]\nmetric_value = 0.9\npython_seed = 1\nnumpy_seed = 1\nframework_seed = 1\n"
        "[[runs]]\nmetric_value = 0.9\npython_seed = 1\nnumpy_seed = 1\nframework_seed = 1\n",
        encoding="utf-8",
    )
    assert DeterminismGate().check(load_config(root=root, env={})).status is GateStatus.PASSED


@pytest.mark.parametrize(
    "overlay",
    [
        "[robotics.determinism]\nrecord_globs = []\n",
        "[robotics.determinism]\nseed_fields = []\n",
        "[robotics.determinism]\nrequired_runs = 0\n",
        "[robotics.determinism]\nmetric_tolerance = -1\n",
    ],
)
def test_determinism_blocks_invalid_policy(passing_repo: Any, overlay: str) -> None:
    """Malformed policy prevents the check from claiming an evidence result."""
    root = passing_repo()
    (root / "hex-vision.toml").write_text(overlay, encoding="utf-8")
    assert DeterminismGate().check(load_config(root=root, env={})).status is GateStatus.BLOCKED


def test_determinism_blocks_record_without_name(passing_repo: Any) -> None:
    """A record cannot be associated with an artifact when its model name is absent."""
    root = passing_repo(record={"model_name": ""})
    assert DeterminismGate().check(load_config(root=root, env={})).status is GateStatus.BLOCKED


@pytest.mark.parametrize(
    "overlay",
    [
        "[robotics.hardware_in_loop]\noptional_gates = []\n",
        "[robotics.hardware_in_loop]\nrunners = 'bad'\n",
        "[robotics.hardware_in_loop]\ntimeout_seconds = 0\n",
    ],
)
def test_hardware_blocks_invalid_policy(tmp_path: Any, overlay: str) -> None:
    """Hardware absence policy must itself be structured and executable."""
    (tmp_path / "hex-vision.toml").write_text(overlay, encoding="utf-8")
    assert (
        HardwareInLoopGate().check(load_config(root=tmp_path, env={})).status is GateStatus.BLOCKED
    )


@pytest.mark.parametrize(
    ("current", "baseline", "direction", "expected"),
    [(1, 2, "higher", False), (1, 2, "lower", True), ("bad", "worse", "weaker", False)],
)
def test_safety_widening_helper_handles_narrow_and_unknown_values(
    current: Any, baseline: Any, direction: str, expected: bool
) -> None:
    """Unsupported comparisons never become a permissive change by accident."""
    assert _is_widened(current, baseline, direction, ["terminate", "land"]) is expected


@pytest.mark.parametrize(
    "overlay",
    [
        "[robotics.safety_envelope]\nrequired_bounds = []\n",
        "[robotics.safety_envelope]\nallowed_failsafe_actions = []\n",
        "[robotics.safety_envelope]\nnumeric_limits = 'bad'\n",
        "[robotics.safety_envelope]\nbaseline_command = []\n",
        "[robotics.safety_envelope]\ngit_timeout_seconds = 0\n",
    ],
)
def test_safety_blocks_invalid_policy(passing_repo: Any, overlay: str) -> None:
    """Safety policy errors are fail-closed before a mission gets a verdict."""
    root = passing_repo()
    (root / "hex-vision.toml").write_text(overlay, encoding="utf-8")
    assert SafetyEnvelopeGate().check(load_config(root=root, env={})).status is GateStatus.BLOCKED
