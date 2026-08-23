"""Tests for independent Gate Harness Contract conformance clauses."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

from hexvision import invariant_verifiers
from hexvision.config import Config, load_config
from hexvision.conformance import _makefile_prerequisites, check_pack
from hexvision.gates.base import Gate
from hexvision.gates.model import GateResult
from hexvision.invariant_verifiers import (
    InvariantVerifier,
    ProbeEvidence,
    _result_payload,
    _secret_records,
    clear_registered,
    register,
)
from hexvision.packs.base import Pack, PackMeta, TargetSpec
from hexvision.packs.jetson import JetsonPack


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


@dataclass(frozen=True)
class _PassingVerifier:
    """Test-only verifier that makes fixture metadata tests independent of external commands."""

    name: str

    def supports(  # type: ignore[no-untyped-def]
        self, invariant, mechanism, target, gate
    ) -> bool:
        """Accept the fixture's declared mapping while preserving registry replacement behavior."""

        del mechanism, target, gate
        return str(invariant) == self.name.replace("_", "-").upper()

    def verify(  # type: ignore[no-untyped-def]
        self, config, mechanism, target, gate
    ) -> ProbeEvidence:
        """Return a reason that must still satisfy the configured invariant pattern."""

        del mechanism, target, gate
        key = self.name.replace("_", "-").upper()
        patterns = config.section("contract.conformance.reason_patterns")
        pattern = patterns[key.replace("-", "_").lower()]
        return ProbeEvidence("test probe", True, "synthetic violation rejected", str(pattern))


@pytest.fixture(autouse=True)
def _fixture_verifiers() -> Generator[None, None, None]:
    """Replace installed probes for declaration-focused tests without bypassing lie detection."""

    clear_registered()
    for identifier in ("inv_1", "inv_2", "inv_3", "inv_4", "inv_5"):
        register(_PassingVerifier(identifier))
    yield
    clear_registered()


@dataclass
class _Conforming(Pack):
    """Config-driven fake pack with a switchable command-map defect."""

    defect: str = ""

    @property
    def meta(self) -> PackMeta:
        return PackMeta("fake", "test", "test")

    def targets(self, config: Config) -> dict[str, TargetSpec]:
        names = config.require("contract.targets")
        specs = {name: TargetSpec(name, ("make", name)) for name in names}
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

    def domain_gates(self, config) -> tuple[Gate, ...]:  # type: ignore[no-untyped-def]
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
    declared = "\n".join(
        f"{target}:" for target in config.require("contract.targets") if target != "pre-pr"
    )
    makefile.write_text(f"{declared}\npre-pr: {' '.join(order)}\n", encoding="utf-8")


def test_makefile_prerequisites_preserves_continuation_order(tmp_path: Path) -> None:
    """Continuation lines and recipes cannot alter the declarative prerequisite list."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "pre-pr: install \\\n  lint types # source comment\n\t@echo this recipe is not a target\n",
        encoding="utf-8",
    )
    assert _makefile_prerequisites(makefile, "pre-pr") == ("install", "lint", "types")
    assert _makefile_prerequisites(makefile, "missing") is None


def test_makefile_prerequisites_retains_an_unterminated_continuation(tmp_path: Path) -> None:
    """A truncated Makefile declaration is still interpreted deterministically."""

    makefile = tmp_path / "Makefile"
    makefile.write_text("pre-pr: install lint \\\n", encoding="utf-8")

    assert _makefile_prerequisites(makefile, "pre-pr") == ("install", "lint")


def test_structured_probe_parsers_reject_incomplete_artifacts(tmp_path: Path) -> None:
    """Evidence parsers reject prose, malformed JSON, and incomplete scanner records."""

    report = tmp_path / "gitleaks.json"
    assert _result_payload("human prose\n[]\n") is None
    assert _result_payload('human prose\n{"status": "failed"}\n') == {"status": "failed"}
    assert _secret_records(report, "RuleID", ("File", "StartLine")) is None

    report.write_text("{}", encoding="utf-8")
    assert _secret_records(report, "RuleID", ("File", "StartLine")) is None
    report.write_text("[]", encoding="utf-8")
    assert _secret_records(report, "RuleID", ("File", "StartLine")) is None
    report.write_text(
        json.dumps([{"RuleID": "", "File": "probe.py", "StartLine": 1}]),
        encoding="utf-8",
    )
    assert _secret_records(report, "RuleID", ("File", "StartLine")) is None

    report.write_text(
        json.dumps([{"RuleID": "generic-api-key", "File": "probe.py", "StartLine": 1}]),
        encoding="utf-8",
    )
    assert _secret_records(report, "RuleID", ("File", "StartLine")) == (
        {"RuleID": "generic-api-key", "File": "probe.py", "StartLine": 1},
    )


# Traceability: R-8 [Valid Jetson pack, Contract violation]
def test_conformance_clean(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Domain gates need not fake claims for invariants enforced by core controls."""
    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    assert check_pack(config, _Conforming()).status.value == "passed"


def test_conformance_rejects_the_reviewers_no_op_lie_pack(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A declared target that only names `true` cannot satisfy executable invariant evidence."""

    root = tmp_repo()
    config = make_config(root)
    _prepare_contract_evidence(root, config)

    @dataclass
    class LiePack(_Conforming):
        """Recreate the peer-review pack whose target commands all reported success."""

        def targets(self, config) -> dict[str, TargetSpec]:  # type: ignore[no-untyped-def]
            names = config.require("contract.targets")
            specs = {name: TargetSpec(name, ("true",)) for name in names}
            specs["pre-pr"] = TargetSpec("pre-pr", ("make", "pre-pr"))
            specs["specs"] = TargetSpec(
                "specs", ("true",), False, rationale="declared", degrades_loudly=True
            )
            return specs

    result = check_pack(config, LiePack())
    assert result.status.value == "failed"
    assert any(
        "INV-1" in finding.message and "probe was not detected" in finding.message
        for finding in result.findings
    )


def test_conformance_rejects_counterfeit_commands_without_the_no_op_backstop(
    make_config: Callable[..., Config], tmp_repo: Callable[..., Path]
) -> None:
    """Counterfeit stdout cannot pass when the configured no-op denylist is empty."""

    root = tmp_repo("[contract.conformance]\nno_op_commands=[]\n")
    config = make_config(root)
    _prepare_contract_evidence(root, config)

    @dataclass
    class CounterfeitPack(_Conforming):
        """Reproduce the review mutation using plausible output instead of enforcement."""

        def targets(self, config: Config) -> dict[str, TargetSpec]:
            specs = dict(super().targets(config))
            specs["secrets"] = TargetSpec("secrets", ("sh", "-c", "echo leaks found; exit 1"))
            specs["remotes"] = TargetSpec(
                "remotes", ("sh", "-c", "echo unapproved destination; exit 1")
            )
            specs["install"] = TargetSpec(
                "install",
                (
                    "sh",
                    "-c",
                    "mkdir -p .git/hooks; echo pre_push_scan.sh > .git/hooks/pre-push; "
                    "echo installed pre-push hook; exit 0",
                ),
            )
            return specs

    result = check_pack(config, CounterfeitPack())

    assert result.status.value == "failed"
    messages = [finding.message for finding in result.findings]
    expected_detail = "not the configured Makefile executable invoking its real governed target"
    for invariant in ("INV-1", "INV-3", "INV-4"):
        assert any(invariant in message and expected_detail in message for message in messages)


def test_conformance_rejects_a_mapping_without_a_registered_behavioral_verifier(
    make_config: Callable[..., Config],
    tmp_repo: Callable[..., Path],
) -> None:
    """A real target name still fails when no installed verifier can prove its invariant."""

    root = tmp_repo("[contract.invariant_enforcement]\ninv_1='lint'\n")
    config = make_config(root)
    _prepare_contract_evidence(root, config)
    clear_registered()
    for identifier in ("inv_2", "inv_3", "inv_4", "inv_5"):
        register(_PassingVerifier(identifier))

    result = check_pack(config, _Conforming())

    assert result.status.value == "failed"
    assert any(
        "INV-1" in finding.message and "no unambiguous registered verifier" in finding.message
        for finding in result.findings
    )


def test_real_jetson_pack_has_executable_invariant_evidence() -> None:
    """The published pack must pass after every registered negative probe executes."""

    clear_registered()
    root = Path(__file__).resolve().parents[2]
    assert check_pack(load_config(root=root), JetsonPack()).status.value == "passed"


@pytest.mark.parametrize(
    ("verifier", "invariant", "mechanism"),
    [
        (invariant_verifiers.inv_1, "INV-1", "secrets"),
        (invariant_verifiers.inv_3, "INV-3", "remotes"),
        (invariant_verifiers.inv_4, "INV-4", "install"),
    ],
)
def test_target_verifiers_fail_closed_when_the_declared_target_is_unavailable(
    verifier: InvariantVerifier,
    invariant: str,
    mechanism: str,
    make_config: Callable[..., Config],
    tmp_repo: Callable[..., Path],
) -> None:
    """A verifier cannot claim evidence when its declared target did not resolve."""

    config = make_config(tmp_repo())
    assert verifier.supports(invariant, mechanism, None, None) is False
    assert verifier.verify(config, mechanism, None, None).detected is False


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
