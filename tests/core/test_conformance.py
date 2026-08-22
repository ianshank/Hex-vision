"""Tests for independent Gate Harness Contract conformance clauses."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hexvision.config import Config
from hexvision.conformance import check_pack
from hexvision.gates.base import Gate
from hexvision.gates.model import GateResult
from hexvision.packs.base import Pack, PackMeta, TargetSpec


class _Gate(Gate):
    """Simple claiming gate used to exercise conformance metadata checks."""

    def __init__(self, clause: str, description: str = "declared") -> None:
        self._clause = clause
        self._description = description

    @property
    def name(self) -> str:
        return self._clause

    @property
    def clause(self) -> str:
        return self._clause

    @property
    def description(self) -> str:
        return self._description

    def check(self, config: Config) -> GateResult:
        del config
        return GateResult.passed(self.name, summary="ok")


@dataclass
class _Conforming(Pack):
    """Config-driven fake pack with a switchable command-map defect."""

    defect: str = ""

    @property
    def meta(self) -> PackMeta:
        return PackMeta("fake", "test", "test")

    def targets(self, config):  # type: ignore[no-untyped-def]
        names = config.require("contract.targets")
        specs = {name: TargetSpec(name, (name,)) for name in names}
        specs["pre-pr"] = TargetSpec("pre-pr", tuple(config.require("contract.pre_pr_order")))
        specs["specs"] = TargetSpec(
            "specs", ("specs",), False, rationale="tool absent is loud", degrades_loudly=True
        )
        if self.defect == "missing":
            specs.pop("lint")
        if self.defect == "order":
            specs["pre-pr"] = TargetSpec("pre-pr", ("lint",))
        if self.defect == "threshold":
            specs["lint"] = TargetSpec("lint", ("tool", "--fail-under=1"))
        if self.defect == "failclosed":
            specs["lint"] = TargetSpec("lint", ("lint",), False, rationale="declared exception")
        if self.defect == "degrade":
            specs["specs"] = TargetSpec("specs", ("specs",), False, rationale="exception")
        return specs

    def domain_gates(self, config):  # type: ignore[no-untyped-def]
        if self.defect == "gates-error":
            raise ValueError("cannot load gates")
        if self.defect == "unclaimed":
            return ()
        return tuple(_Gate(name) for name in config.section("contract.invariants"))


def test_conformance_clean(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A pack declaring all contract evidence passes against the shared engine."""
    root = tmp_repo()
    (root / "src").mkdir()
    (root / "src" / "remote.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    assert check_pack(make_config(root), _Conforming()).status.value == "passed"


def test_conformance_detects_target_and_threshold(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Target omission and embedded quality flags independently fail contract policy."""
    config = make_config(tmp_repo())
    assert check_pack(config, _Conforming("missing")).status.value == "failed"
    assert check_pack(config, _Conforming("threshold")).status.value == "failed"


@pytest.mark.parametrize("defect", ["order", "failclosed", "degrade", "unclaimed"])
def test_conformance_independent_contract_defects(make_config, tmp_repo, defect: str) -> None:  # type: ignore[no-untyped-def]
    """Order, tool policy, degradation, and invariant claims are independently measured."""
    root = tmp_repo()
    (root / "src").mkdir()
    (root / "src" / "remote.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    assert check_pack(make_config(root), _Conforming(defect)).status.value == "failed"


def test_conformance_blocks_unreadable_source_and_domain_gates(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Conformance fails closed when AST evidence or domain-gate declarations cannot load."""
    bad_source = tmp_repo()
    (bad_source / "src").mkdir()
    (bad_source / "src" / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    assert check_pack(make_config(bad_source), _Conforming()).status.value == "blocked"
    (bad_source / "src" / "bad.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    assert check_pack(make_config(bad_source), _Conforming("gates-error")).status.value == "blocked"
