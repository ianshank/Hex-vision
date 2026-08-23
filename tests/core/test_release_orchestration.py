"""Integration coverage for active-pack domain-gate release orchestration."""

from __future__ import annotations

import json
import re
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from hexvision import cli
from hexvision.config import Config, load_config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.orchestration import run_active_domain_gates
from hexvision.packs import registry
from hexvision.packs.base import Pack, PackMeta, TargetSpec

REPO_ROOT = Path(__file__).resolve().parents[2]


class _RecordingGate(Gate):
    """Test gate that records every actual runner invocation."""

    def __init__(self, name: str, result: GateResult, calls: list[str]) -> None:
        self._name = name
        self._result = result
        self._calls = calls

    @property
    def name(self) -> str:
        return self._name

    @property
    def clause(self) -> str:
        return "R-19"

    def check(self, config: Config) -> GateResult:
        del config
        self._calls.append(self.name)
        return self._result


@dataclass
class _TestPack(Pack):
    """Pack seam that exposes real domain gates without an entry-point wheel."""

    pack_name: str
    gates: Sequence[Gate] = field(default_factory=tuple)
    gate_error: Exception | None = None

    @property
    def meta(self) -> PackMeta:
        return PackMeta(self.pack_name, "test", "release orchestration test pack")

    def targets(self, config: Config) -> Mapping[str, TargetSpec]:
        del config
        return {}

    def domain_gates(self, config: Config) -> Sequence[Gate]:
        del config
        if self.gate_error is not None:
            raise self.gate_error
        return self.gates


@pytest.fixture(autouse=True)
def _clear_pack_registrations() -> Generator[None, None, None]:
    """Keep the process-local registry isolated between active-pack scenarios."""
    registry.clear_registered()
    yield
    registry.clear_registered()


def _config(tmp_repo: Any, active: str) -> Config:
    """Create a reviewed repository overlay selecting exactly one test pack."""
    root = tmp_repo(f'[orchestration]\nactive_packs = ["{active}"]\n')
    return load_config(root=root, env={})


def _failed(gate: str, finding_id: str, reason: str) -> GateResult:
    """Create a domain failure with an assertion-worthy ID and reason."""
    return GateResult.failed(
        gate,
        summary="evidence was evaluated and rejected",
        clause="R-19",
        findings=(
            Finding(
                finding_id,
                Severity.MAJOR,
                reason,
                clause="R-19",
                disposition="Correct the rejected evidence.",
            ),
        ),
    )


# Traceability: R-19 [Registered gate failure blocks release orchestration]
def test_release_command_runs_every_registered_gate_and_a_failure_blocks(
    tmp_repo: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gate metadata does not count as execution; the CLI runs all registered controls."""
    calls: list[str] = []
    gates = (
        _RecordingGate(
            "first-gate", GateResult.passed("first-gate", summary="first passed"), calls
        ),
        _RecordingGate(
            "failing-gate",
            _failed("failing-gate", "DOMAIN-FAIL-001", "deliberately rejected evidence"),
            calls,
        ),
        _RecordingGate("last-gate", GateResult.passed("last-gate", summary="last passed"), calls),
    )
    pack = _TestPack("release-test", gates)
    registry.register(pack)
    config = _config(tmp_repo, pack.name)

    assert [gate["name"] for gate in pack.describe(config)["domain_gates"]] == [
        "first-gate",
        "failing-gate",
        "last-gate",
    ]
    assert calls == [], "describing gates is metadata-only and cannot satisfy release execution"

    monkeypatch.chdir(config.root)
    assert cli.main(["pack", "gates", "--all-active", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert calls == ["first-gate", "failing-gate", "last-gate"]
    assert payload["status"] == GateStatus.FAILED.value
    assert payload["exit_code"] == 1
    assert payload["findings"][0]["id"] == "RELEASE-TEST-DOMAIN-FAIL-001"
    assert payload["findings"][0]["message"] == (
        "[release-test/failing-gate] deliberately rejected evidence"
    )
    assert [item["result"]["gate"] for item in payload["measurements"]["gate_results"]] == [
        "first-gate",
        "failing-gate",
        "last-gate",
    ]


# Traceability: R-19 [Unavailable domain gate evidence]
def test_blocked_domain_gate_retains_blocked_exit_and_reason(
    tmp_repo: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing evidence path is BLOCKED with exit 2 rather than a generic failure."""
    calls: list[str] = []
    blocked = GateResult.blocked(
        "evidence-gate",
        summary="evidence cannot be read",
        reason="required telemetry artifact is unavailable",
        clause="R-19",
    )
    pack = _TestPack("blocked-pack", (_RecordingGate("evidence-gate", blocked, calls),))
    registry.register(pack)
    config = _config(tmp_repo, pack.name)

    monkeypatch.chdir(config.root)
    assert cli.main(["pack", "gates", "--all-active", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert calls == ["evidence-gate"]
    assert payload["status"] == GateStatus.BLOCKED.value
    assert payload["exit_code"] == 2
    assert payload["findings"][0]["id"] == "DOMAIN-GATES-BLOCKED"
    assert "blocked-pack/evidence-gate" in payload["findings"][0]["message"]
    assert "required telemetry artifact is unavailable" in payload["findings"][0]["message"]
    assert (
        payload["measurements"]["gate_results"][0]["result"]["status"] == GateStatus.BLOCKED.value
    )


class _UnloadedPlugin:
    """Entry-point double that must never load when absent from the allowlist."""

    loaded = False

    def load(self) -> object:
        type(self).loaded = True
        raise AssertionError("an unallowlisted plugin must not be loaded")


# Traceability: R-19 [Active allowlist admits only reviewed packs]
def test_active_allowlist_blocks_invalid_pack_and_ignores_unreviewed_plugin(
    tmp_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An allowlisted invalid pack blocks, while discovered-but-unreviewed code is ignored."""
    invalid = _TestPack("invalid-pack", gate_error=ValueError("temporary pack is invalid"))
    registry.register(invalid)
    monkeypatch.setattr(registry, "_entry_points", lambda: {"unreviewed-plugin": _UnloadedPlugin()})
    config = _config(tmp_repo, invalid.name)

    result = run_active_domain_gates(config)

    assert result.status is GateStatus.BLOCKED
    assert result.exit_code == 2
    assert result.findings[0].id == "DOMAIN-GATES-BLOCKED"
    assert "invalid-pack" in result.findings[0].message
    assert "temporary pack is invalid" in result.findings[0].message
    assert _UnloadedPlugin.loaded is False


@pytest.mark.parametrize(
    ("active_packs", "reason"),
    [
        ("[]", "must be a non-empty list"),
        ('["duplicate-pack", "duplicate-pack"]', "must not repeat"),
    ],
)
# Traceability: R-19 [Active allowlist admits only reviewed packs]
def test_active_allowlist_must_be_explicit_and_unique(
    tmp_repo: Any, active_packs: str, reason: str
) -> None:
    """Malformed review policy blocks before discovery can silently select a plugin."""
    config = load_config(root=tmp_repo(f"[orchestration]\nactive_packs = {active_packs}\n"), env={})

    result = run_active_domain_gates(config)

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "DOMAIN-GATES-BLOCKED"
    assert reason in result.findings[0].message


# Traceability: R-19 [Active allowlist admits only reviewed packs]
def test_active_pack_with_non_gate_registration_blocks(tmp_repo: Any) -> None:
    """A bad pack registration is a blocked orchestration outcome, never a pass."""
    invalid = _TestPack("non-gate-pack", cast(Sequence[Gate], (object(),)))
    registry.register(invalid)

    result = run_active_domain_gates(_config(tmp_repo, invalid.name))

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "DOMAIN-GATES-BLOCKED"
    assert "non-gate-pack" in result.findings[0].message
    assert "non-Gate domain control" in result.findings[0].message


# Traceability: R-19 [Registered gate failure blocks release orchestration]
def test_all_passing_active_domain_gates_produce_a_passing_release_verdict(tmp_repo: Any) -> None:
    """A green aggregate is possible only after the registered gate has actually run."""
    calls: list[str] = []
    gate = _RecordingGate("passing-gate", GateResult.passed("passing-gate", summary="ok"), calls)
    pack = _TestPack("passing-pack", (gate,))
    registry.register(pack)

    result = run_active_domain_gates(_config(tmp_repo, pack.name))

    assert calls == ["passing-gate"]
    assert result.status is GateStatus.PASSED
    assert result.exit_code == 0
    assert result.summary == "every active pack domain gate passed"


# Traceability: R-19 [Unavailable domain gate evidence]
def test_declared_domain_unavailability_remains_a_distinct_aggregate_status(tmp_repo: Any) -> None:
    """An authorised declared absence is visible and non-successful, not collapsed to FAILED."""
    calls: list[str] = []
    skipped = GateResult.skipped_declared(
        "declared-gap",
        summary="approved runner absence",
        reason="runner is unavailable under DEC-777",
        decision_id="DEC-777",
        clause="R-19",
    )
    pack = _TestPack("declared-pack", (_RecordingGate("declared-gap", skipped, calls),))
    registry.register(pack)

    result = run_active_domain_gates(_config(tmp_repo, pack.name))

    assert calls == ["declared-gap"]
    assert result.status is GateStatus.SKIPPED_DECLARED
    assert result.exit_code == 1
    assert result.findings == ()
    gate_measurements = result.measurements["gate_results"][0]["result"]["measurements"]
    assert gate_measurements["decision_id"] == "DEC-777"


# Traceability: R-19 [Configured release order]
def test_makefile_and_ci_follow_the_configured_release_order() -> None:
    """The new release target remains driven by the one configured order authority."""
    config = load_config(root=REPO_ROOT, env={})
    order = list(config.require("contract.pre_pr_order"))
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_pr = re.search(r"^pre-pr:\s*(.*?)\s*##", makefile, re.MULTILINE)
    assert pre_pr is not None
    assert pre_pr.group(1).split() == order

    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"^  (?P<name>[a-z][a-z0-9-]*):\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
            workflow.split("\njobs:\n", maxsplit=1)[1],
            re.MULTILINE | re.DOTALL,
        )
    }
    assert [name for name in jobs if name in order] == order
    for index, target in enumerate(order):
        assert f"run: make {target}" in jobs[target]
        if index:
            assert f"needs: {order[index - 1]}" in jobs[target]
