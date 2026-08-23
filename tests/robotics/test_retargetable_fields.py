"""Prove a third-party robotics policy can rename its evidence schema without core edits."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus
from hexvision.robotics.determinism import DeterminismGate
from hexvision.robotics.latency import LatencyBudgetGate
from hexvision.robotics.model_card import ModelCardGate


@pytest.fixture
def external_pack_root(tmp_path: Path) -> Callable[[], Path]:
    """Build a non-Jetson pack fixture with independently named evidence fields."""

    def make() -> Path:
        card_directory = tmp_path / "models" / "sentinel"
        card_directory.mkdir(parents=True)
        (card_directory / "sentinel.engine").write_bytes(b"engine")
        fields: dict[str, Any] = {
            "vehicle_model": "sentinel",
            "revision": "1.0.0",
            "function": "object_detection",
            "tensor_layout": "[1, 3, 640, 640]",
            "numeric_format": "fp16",
            "compute_format": "tensorrt",
            "deployed_on": "Third-party accelerator",
            "corpus_identifier": "patrol-v1",
            "license_code": "CC-BY-4.0",
            "source_revision": "0123456789abcdef0123456789abcdef01234567",
            "score_name": "mAP50",
            "score": 0.91,
            "validation_partition": "validation",
            "known_hazards": "None known",
            "steward": "third-party-team",
            "asset_location": "models/sentinel/sentinel.engine",
            "timing": 30.0,
            "timing_percentile": 95,
        }
        _write_card(card_directory / "model-card.md", fields)
        record = {
            "evidence_schema": 1,
            "evaluated_model": "sentinel",
            "trials": [
                {"score_observation": 0.91, "seed_one": 7, "seed_two": 7, "seed_three": 7},
                {"score_observation": 0.9102, "seed_one": 7, "seed_two": 7, "seed_three": 7},
                {"score_observation": 0.9099, "seed_one": 7, "seed_two": 7, "seed_three": 7},
            ],
        }
        (card_directory / "eval-runs.json").write_text(json.dumps(record), encoding="utf-8")
        (tmp_path / "hex-vision.toml").write_text(_external_policy(), encoding="utf-8")
        return tmp_path

    return make


def _write_card(path: Path, fields: dict[str, Any]) -> None:
    """Render the fixture's strict model-card front matter from named external fields."""
    lines = ["---"]
    for key, value in fields.items():
        rendered = f'"{value}"' if isinstance(value, str) else str(value)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "# Sentinel"])
    path.write_text("\n".join(lines), encoding="utf-8")


def _external_policy() -> str:
    """Return the external pack overlay that owns all renamed schema identities."""
    return """
[robotics.model_card]
required_fields = [
  "vehicle_model", "revision", "function", "tensor_layout", "numeric_format", "compute_format",
  "deployed_on", "corpus_identifier", "license_code", "source_revision",
  "score_name", "score", "validation_partition", "known_hazards", "steward",
  "asset_location",
]
artifact_field = "asset_location"
model_name_field = "vehicle_model"
precision_field = "numeric_format"
runtime_field = "compute_format"
device_field = "deployed_on"
provenance_license_field = "license_code"
provenance_commit_field = "source_revision"
eval_value_field = "score"
failure_modes_field = "known_hazards"

[robotics.latency]
measurement_field = "timing"
percentile_field = "timing_percentile"
runtime_field = "compute_format"
device_field = "deployed_on"

[robotics.determinism]
schema_version_field = "evidence_schema"
model_name_field = "evaluated_model"
runs_field = "trials"
metric_field = "score_observation"
seed_fields = ["seed_one", "seed_two", "seed_three"]
"""


def test_external_pack_with_renamed_fields_passes_all_evidence_gates(
    external_pack_root: Callable[[], Path],
) -> None:
    """Configuration alone retargets card, latency, and determinism semantics."""
    root = external_pack_root()
    config = load_config(root=root, env={})
    assert ModelCardGate().check(config).status is GateStatus.PASSED
    assert LatencyBudgetGate().check(config).status is GateStatus.PASSED
    assert DeterminismGate().check(config).status is GateStatus.PASSED


def test_external_pack_renamed_fields_keep_specific_block_reasons(
    external_pack_root: Callable[[], Path],
) -> None:
    """Renamed runtime and seed evidence still yields the semantic failure identifiers."""
    root = external_pack_root()
    card_path = root / "models" / "sentinel" / "model-card.md"
    card = card_path.read_text(encoding="utf-8")
    card_path.write_text(
        card.replace('compute_format: "tensorrt"', 'compute_format: "bespoke"'),
        encoding="utf-8",
    )
    model_result = ModelCardGate().check(load_config(root=root, env={}))
    assert model_result.status is GateStatus.FAILED
    assert any(finding.id == "MC-1-RUNTIME" for finding in model_result.findings)

    record_path = root / "models" / "sentinel" / "eval-runs.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["trials"][1]["seed_one"] = 11
    record_path.write_text(json.dumps(record), encoding="utf-8")
    determinism_result = DeterminismGate().check(load_config(root=root, env={}))
    assert determinism_result.status is GateStatus.FAILED
    assert any(finding.id == "DET-1-SEED_ONE-DIFFERS" for finding in determinism_result.findings)
