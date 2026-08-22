"""Hex-vision: a modular governance and gate harness for drone, robotics and edge-AI repositories.

The public surface is deliberately small and re-exported here, so an adopting
repository imports from ``hexvision`` and is unaffected by internal module moves.
That is the backwards-compatibility contract: modules under ``hexvision.*`` may be
reorganised between minor versions; these names may not.
"""

from __future__ import annotations

from hexvision.config import Config, load_config
from hexvision.errors import ExitCode, HexVisionError
from hexvision.gates.base import Gate, run_gate, run_gates
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.packs.base import Pack, PackMeta, TargetSpec

__version__ = "0.1.0"

__all__ = [
    "Config",
    "ExitCode",
    "Finding",
    "Gate",
    "GateResult",
    "GateStatus",
    "HexVisionError",
    "Pack",
    "PackMeta",
    "Severity",
    "TargetSpec",
    "__version__",
    "load_config",
    "run_gate",
    "run_gates",
]
