"""Fixtures for isolated robotics policy repositories.

Each test creates its own repository-shaped directory so gate outcomes depend on
reviewed configuration and evidence, not on files left by another test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import Config, load_config


@pytest.fixture
def configured_root(tmp_path: Path) -> Callable[[str], Config]:
    """Return a config factory rooted at a fresh repository-shaped directory."""

    def make(overlay: str = "") -> Config:
        if overlay:
            (tmp_path / "hex-vision.toml").write_text(overlay, encoding="utf-8")
        return load_config(root=tmp_path, env={})

    return make


@pytest.fixture
def passing_repo(tmp_path: Path) -> Callable[..., Path]:
    """Create a complete model, eval record and mission that meet default policy."""

    def make(**updates: Any) -> Path:
        card = {
            "model_name": "detector",
            "version": "1.0.0",
            "task": "object_detection",
            "input_shape": "[1, 3, 640, 640]",
            "precision": "fp16",
            "target_runtime": "tensorrt",
            "target_device": "Jetson Orin Nano",
            "dataset_id": "campus-patrol-v3",
            "dataset_license": "CC-BY-4.0",
            "trained_commit": "0123456789abcdef0123456789abcdef01234567",
            "eval_metric": "mAP50",
            "eval_value": 0.91,
            "eval_dataset_split": "validation",
            "known_failure_modes": "None known",
            "owner": "perception-team",
            "artifact_path": "models/detector/detector.engine",
            "latency_p95_ms": 30.0,
            "latency_percentile": 95,
        }
        card.update(updates.pop("card", {}))
        card_dir = tmp_path / "models" / "detector"
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "detector.engine").write_bytes(b"engine")
        lines = ["---"]
        for key, value in card.items():
            if isinstance(value, str):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        lines.extend(["---", "# Detector"])
        (card_dir / "model-card.md").write_text("\n".join(lines), encoding="utf-8")
        runs = updates.pop(
            "runs",
            [
                {"metric_value": 0.9100, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
                {"metric_value": 0.9104, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
                {"metric_value": 0.9099, "python_seed": 42, "numpy_seed": 42, "framework_seed": 42},
            ],
        )
        record = {"schema_version": 1, "model_name": "detector", "runs": runs}
        record.update(updates.pop("record", {}))
        (card_dir / "eval-runs.json").write_text(json.dumps(record), encoding="utf-8")
        mission = {
            "max_altitude_m": 80,
            "max_horizontal_speed_ms": 8,
            "max_tilt_deg": 25,
            "geofence_radius_m": 250,
            "rtl_battery_percent": 30,
            "failsafe_action": "rtl",
        }
        mission.update(updates.pop("mission", {}))
        mission_dir = tmp_path / "missions"
        mission_dir.mkdir(exist_ok=True)
        (mission_dir / "patrol.toml").write_text(
            "\n".join(f"{key} = {json.dumps(value)}" for key, value in mission.items()),
            encoding="utf-8",
        )
        if updates:
            raise AssertionError(f"unused passing_repo updates: {sorted(updates)}")
        return tmp_path

    return make
