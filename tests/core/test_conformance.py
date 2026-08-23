"""Tests for independent Gate Harness Contract conformance clauses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from hexvision.config import Config
from hexvision.conformance import _makefile_prerequisites, check_pack
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
        specs["pre-pr"] = TargetSpec("pre-pr", ("make", "pre-pr"))
        specs["specs"] = TargetSpec(
            "specs", ("specs",), False, rationale="tool absent is loud", degrades_loudly=True
        )
        if self.defect == "missing":
            specs.pop("lint")
        if self.defect == "inline":
            specs["pre-pr"] = TargetSpec("pre-pr", tuple(config.require("contract.pre_pr_order")))
        if self.defect == "threshold":
            specs["lint"] = TargetSpec("lint", ("tool", "--fail-under=1"))
        if self.defect == "failclosed":
            specs["lint"] = TargetSpec("lint", ("lint",), False, rationale="declared exception")
        if self.defect == "degrade":
            specs["specs"] = TargetSpec("specs", ("specs",), False, rationale="exception")
        return specs

    def domain_gates(self, config):  # type: ignore[no-untyped-def]
        del config
        if self.defect == "gates-error":
            raise ValueError("cannot load gates")
        if self.defect == "no-domain-gates":
            return ()
        return (_Gate("DOMAIN-TEST"),)


def _prepare_contract_evidence(root, config, *, reordered: bool = False) -> None:  # type: ignore[no-untyped-def]
    """Write the configured AST and Makefile evidence a conforming pack delegates to."""
    (root / "src").mkdir()
    (root / "src" / "remote.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    order = list(config.require("contract.pre_pr_order"))
    if reordered:
        order.reverse()
    makefile = root / str(config.require("contract.makefile_path"))
    makefile.write_text(f"pre-pr: {' '.join(order)}\n", encoding="utf-8")


def test_makefile_prerequisites_preserves_continuation_order(tmp_path: Path) -> None:
    """Continuation lines and recipes cannot alter the declarative prerequisite list."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "pre-pr: install \\\n  lint types # source comment\n\t@echo this recipe is not a target\n",
        encoding="utf-8",
    )
    assert _makefile_prerequisites(makefile, "pre-pr") == ("install", "lint", "types")
    assert _makefile_prerequisites(makefile, "missing") is None


# Traceability: R-8
def test_conformance_clean(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Domain gates need not fake claims for invariants enforced by core controls."""
    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    assert check_pack(config, _Conforming()).status.value == "passed"


def test_conformance_detects_target_and_threshold(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Target omission and embedded quality flags independently fail contract policy."""
    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    assert check_pack(config, _Conforming("missing")).status.value == "failed"
    assert check_pack(config, _Conforming("threshold")).status.value == "failed"


@pytest.mark.parametrize("defect", ["inline", "failclosed", "degrade"])
def test_conformance_independent_contract_defects(make_config, tmp_repo, defect: str) -> None:  # type: ignore[no-untyped-def]
    """Delegation, tool policy, and degradation are independently measured."""
    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    assert check_pack(config, _Conforming(defect)).status.value == "failed"


def test_conformance_rejects_reordered_makefile_pre_pr(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """The Makefile chain, not a pack's delegation command, owns the required order."""
    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config, reordered=True)
    result = check_pack(config, _Conforming())
    assert result.status.value == "failed"
    assert any("Makefile pre-pr prerequisites" in finding.message for finding in result.findings)


def test_conformance_reports_unmapped_and_missing_invariant_mechanisms(
    make_config: Callable[..., Config], tmp_repo: Callable[..., Path]
) -> None:
    """An omitted mapping and a nonexistent mapped mechanism remain Major findings."""
    root = tmp_repo(
        "[contract.invariants]\n"
        "inv_6='A deliberately unmapped invariant for this conformance test.'\n"
        "\n"
        "[contract.invariant_enforcement]\n"
        "inv_1='does-not-exist'\n"
        "inv_2='INV-2'\n"
        "inv_3='remotes'\n"
        "inv_4='install'\n"
    )
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    result = check_pack(config, _Conforming())
    assert result.status.value == "failed"
    messages = [finding.message for finding in result.findings]
    assert any("INV-1" in message and "does-not-exist" in message for message in messages)
    assert any(
        "INV-6" in message and "no invariant_enforcement entry" in message for message in messages
    )


def test_conformance_blocks_unreadable_source_and_domain_gates(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Conformance fails closed when AST evidence or domain-gate declarations cannot load."""
    bad_source = tmp_repo()
    (bad_source / "src").mkdir()
    (bad_source / "src" / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    config = make_config(bad_source)
    (bad_source / str(config.require("contract.makefile_path"))).write_text(
        f"pre-pr: {' '.join(config.require('contract.pre_pr_order'))}\n", encoding="utf-8"
    )
    assert check_pack(config, _Conforming()).status.value == "blocked"
    (bad_source / "src" / "bad.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    assert check_pack(config, _Conforming("gates-error")).status.value == "blocked"
