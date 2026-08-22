"""Jetson edge-AI pack for the common Hex-vision contract.

The pack maps contract names to the repository's Makefile through configuration
and contributes robotics evidence gates without teaching the generic harness
about NVIDIA hardware or perception models.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.packs.base import Pack, PackMeta, TargetSpec
from hexvision.robotics import (
    DeterminismGate,
    HardwareInLoopGate,
    LatencyBudgetGate,
    ModelCardGate,
    SafetyEnvelopeGate,
)

__all__ = ["JetsonPack", "pack"]


class JetsonPack(Pack):
    """Provide contract commands and robotics gates for Python Jetson perception repositories."""

    @property
    def meta(self) -> PackMeta:
        """Describe the stack and primary vendor/runtime references for adopters."""
        return PackMeta(
            name="jetson",
            stack="python-edge-ai",
            summary="Governance gates for Jetson-deployed perception and mission safety.",
            reference_docs=(
                "https://docs.nvidia.com/jetson/",
                "https://docs.nvidia.com/deeplearning/tensorrt/",
                "https://docs.ros.org/en/rolling/",
            ),
        )

    def targets(self, config: Config) -> Mapping[str, TargetSpec]:
        """Build all contract target specifications from the configured Makefile commands.

        Delegating to Makefile target names preserves the repository's single
        invocation source while keeping executable, target strings and degraded
        rationale reviewable configuration rather than Python literals.
        """
        target_names = _strings(config.require("contract.targets"))
        configured = config.section("packs.jetson.targets")
        tools = config.section("packs.jetson.tools")
        fail_closed = set(_strings(config.require("contract.fail_closed_on_missing_tool")))
        degrade_loudly = set(_strings(config.require("contract.degrade_loudly")))
        rationales = config.section("packs.jetson.degraded_rationale")
        specs: dict[str, TargetSpec] = {}
        for target in target_names:
            command = _strings(configured.get(target))
            specs[target] = TargetSpec(
                target=target,
                command=command,
                tool=str(tools.get(target, command[0])),
                fail_closed_on_missing_tool=target in fail_closed or target not in degrade_loudly,
                degrades_loudly=target in degrade_loudly,
                rationale=str(rationales[target]) if target in degrade_loudly else None,
            )
        return specs

    def domain_gates(self, config: Config) -> Sequence[Gate]:
        """Return the five robotics controls that make this pack domain-specific."""
        _ = config.require("packs.jetson.package_manager")
        _ = config.require("packs.jetson.runner")
        return (
            ModelCardGate(),
            LatencyBudgetGate(),
            DeterminismGate(),
            SafetyEnvelopeGate(),
            HardwareInLoopGate(),
        )


def _strings(value: Any) -> tuple[str, ...]:
    """Validate configured argument vectors so pack execution cannot guess a command."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("configured target command must be a non-empty string list")
    return tuple(value)


pack: Final = JetsonPack()
