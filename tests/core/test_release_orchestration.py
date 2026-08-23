"""Integration coverage for active-pack domain-gate release orchestration."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from hexvision import cli
from hexvision.authority import VerifiedAuthority, verify_authority
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


def _minted_authority(root: Path, subject: str, *rows: str) -> VerifiedAuthority:
    """Record decisions in the isolated ledger and mint authority for one subject."""
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "decision-log.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    authority = verify_authority(load_config(root=root, env={}), subject=subject)
    assert isinstance(authority, VerifiedAuthority)
    return authority


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


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_authorised_declared_absence_passes_but_stays_visible(tmp_repo: Any) -> None:
    """A declared absence with verifier-minted authority passes, and names it.

    GateStatus.SKIPPED_DECLARED maps to the FAILED exit code by default, and that
    mapping documents that the authorising decision-log entry is what converts it
    to a pass, in the gate rather than in the mapping. If the aggregate stayed red
    for an authorised absence, the decision-log mechanism would be decorative: no
    release could ever go green while a documented, owned exception existed.

    Visibility is the other half of the contract and is asserted here too. The
    absence is not swallowed: it is counted in the summary and each skip is listed
    against the decision that authorises it, so a reader cannot mistake this run
    for one where every gate actually ran. The typed authority itself stays out
    of the serialised gate result: JSON output carries the derived id string only.
    """
    calls: list[str] = []
    root = tmp_repo('[orchestration]\nactive_packs = ["declared-pack"]\n')
    authority = _minted_authority(
        root,
        "declared-gap:runner",
        "2026-08-23 | DEC-777 | runner absence accepted | reviewer "
        "| declared-gap:runner | active | -",
    )
    skipped = GateResult.skipped_declared(
        "declared-gap",
        summary="approved runner absence",
        reason="runner is unavailable under DEC-777",
        authority={"runner": authority},
        clause="R-19",
    )
    pack = _TestPack("declared-pack", (_RecordingGate("declared-gap", skipped, calls),))
    registry.register(pack)

    result = run_active_domain_gates(load_config(root=root, env={}))

    assert calls == ["declared-gap"]
    assert result.status is GateStatus.PASSED
    assert result.exit_code == 0
    assert result.measurements["authorised_declared_skips"] == {
        "declared-pack/declared-gap": "DEC-777"
    }
    assert "1 declared unavailable under recorded decisions" in result.summary
    serialised = result.measurements["gate_results"][0]["result"]
    assert serialised["measurements"]["decision_id"] == "DEC-777"
    assert "declared_skip_authority" not in serialised
    json.dumps(result.measurements["gate_results"])


# Traceability: R-19 [Unavailable domain gate evidence]
def test_unauthorised_declared_absence_fails_and_names_the_gate(tmp_repo: Any) -> None:
    """A declared skip carrying no decision is red, and says which gate it was.

    Producing gates now report an unowned absence as BLOCKED, so this aggregate
    branch is a defence against a future gate that forgets to resolve authority.
    It must not degrade into a bare non-zero exit that an operator has to guess at.
    """
    calls: list[str] = []
    skipped = GateResult.skipped_declared(
        "unowned-gap",
        summary="unowned runner absence",
        reason="runner is unavailable and nobody accepted that",
        decision_id=None,
        clause="R-19",
    )
    pack = _TestPack("unowned-pack", (_RecordingGate("unowned-gap", skipped, calls),))
    registry.register(pack)

    result = run_active_domain_gates(_config(tmp_repo, pack.name))

    assert calls == ["unowned-gap"]
    assert result.status is GateStatus.FAILED
    assert result.exit_code == 1
    assert result.measurements["unauthorised_declared_skips"] == ["unowned-pack/unowned-gap"]


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_forged_decision_id_string_no_longer_authorises_a_skip(tmp_repo: Any) -> None:
    """The literal PEER-REVIEW-3 exploit: a bare decision_id string is not authority.

    Before DEC-016's corrective action, aggregation trusted any non-empty
    ``decision_id`` measurement, so ``decision_id="nonsense"`` turned an absent
    runner green without any ledger record existing. Authority is now only the
    typed value minted by the shared verifier; the same forged string must fail
    the release verdict and name the gate that carried it.
    """
    skipped = GateResult.skipped_declared(
        "forged-gap",
        summary="forged runner absence",
        reason="runner absent with an invented id",
        decision_id="nonsense",
        clause="R-19",
    )
    pack = _TestPack("forged-pack", (_RecordingGate("forged-gap", skipped, []),))
    registry.register(pack)

    result = run_active_domain_gates(_config(tmp_repo, pack.name))

    assert result.status is GateStatus.FAILED
    assert result.exit_code == 1
    assert result.measurements["unauthorised_declared_skips"] == ["forged-pack/forged-gap"]
    finding = result.findings[0]
    assert finding.id == "FORGED-PACK-FORGED-GAP-UNVERIFIED-SKIP"
    assert finding.severity is Severity.BLOCKER
    assert "no verified authority" in finding.message


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_borrowed_authority_for_another_gate_does_not_transfer(tmp_repo: Any) -> None:
    """Real authority recorded for one gate cannot authorise a different gate's skip.

    The subject's gate segment — everything before the first separator — must
    equal the producing gate's name, so a decision accepting one gate's absence
    is not a bearer token any declared skip can spend.
    """
    root = tmp_repo('[orchestration]\nactive_packs = ["borrowed-pack"]\n')
    authority = _minted_authority(
        root,
        "other-gate:runner",
        "2026-08-23 | DEC-31 | other-gate absence accepted | reviewer "
        "| other-gate:runner | active | -",
    )
    skipped = GateResult.skipped_declared(
        "borrowed-gap",
        summary="absence borrowing an unrelated decision",
        reason="runner absent",
        authority={"runner": authority},
        clause="R-19",
    )
    pack = _TestPack("borrowed-pack", (_RecordingGate("borrowed-gap", skipped, []),))
    registry.register(pack)

    result = run_active_domain_gates(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.measurements["unauthorised_declared_skips"] == ["borrowed-pack/borrowed-gap"]
    assert "does not name this gate and runner" in result.findings[0].message
    assert "other-gate:runner" in result.findings[0].message


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_gate_name_containing_the_subject_separator_fails_closed(tmp_repo: Any) -> None:
    """A separator-bearing gate name can never have its declared skips authorised.

    The gate segment of a subject is everything before the first separator, so a
    gate named with a ``:`` cannot be named by any subject. The invariant is
    enforced fail-closed rather than left as a naming convention.
    """
    root = tmp_repo('[orchestration]\nactive_packs = ["colon-pack"]\n')
    authority = _minted_authority(
        root,
        "odd:gate:runner",
        "2026-08-23 | DEC-42 | odd gate absence accepted | reviewer | odd:gate:runner | active | -",
    )
    skipped = GateResult.skipped_declared(
        "odd:gate",
        summary="absence for a gate whose name contains the separator",
        reason="runner absent",
        authority={"runner": authority},
        clause="R-19",
    )
    pack = _TestPack("colon-pack", (_RecordingGate("odd:gate", skipped, []),))
    registry.register(pack)

    result = run_active_domain_gates(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.measurements["unauthorised_declared_skips"] == ["colon-pack/odd:gate"]
    assert "contains the subject separator" in result.findings[0].message


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_whole_gate_subject_is_not_a_wildcard(tmp_repo: Any) -> None:
    """A subject naming only the gate cannot authorize every runner of that gate.

    The subject must exactly equal the gate name, the separator, and the runner
    key the authority is attached under — a runnerless subject would otherwise
    be one ledger record spendable for any absence the gate ever declares.
    """
    root = tmp_repo('[orchestration]\nactive_packs = ["wildcard-pack"]\n')
    authority = _minted_authority(
        root,
        "wildcard-gap",
        "2026-08-23 | DEC-55 | whole-gate absence accepted | reviewer | wildcard-gap | active | -",
    )
    skipped = GateResult.skipped_declared(
        "wildcard-gap",
        summary="absence claiming a runnerless subject",
        reason="runner absent",
        authority={"runner": authority},
        clause="R-19",
    )
    pack = _TestPack("wildcard-pack", (_RecordingGate("wildcard-gap", skipped, []),))
    registry.register(pack)

    result = run_active_domain_gates(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.measurements["unauthorised_declared_skips"] == ["wildcard-pack/wildcard-gap"]
    assert "does not name this gate and runner" in result.findings[0].message


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_hand_built_fake_authority_value_is_named_not_crashed_on(tmp_repo: Any) -> None:
    """A non-verifier value smuggled into the typed mapping is a named failure.

    ``skipped_declared`` refuses fakes at construction, so the only route here
    is a hand-built result. Aggregation must still name the problem instead of
    tripping over the fake and degrading into a generic crash BLOCK.
    """
    forged = GateResult(
        gate="fake-gap",
        status=GateStatus.SKIPPED_DECLARED,
        clause="R-19",
        summary="hand-built skip with a counterfeit authority value",
        measurements={"decision_id": "DEC-1", "reason": "runner absent"},
        declared_skip_authority={"runner": cast(VerifiedAuthority, object())},
    )
    pack = _TestPack("fake-pack", (_RecordingGate("fake-gap", forged, []),))
    registry.register(pack)

    result = run_active_domain_gates(_config(tmp_repo, pack.name))

    assert result.status is GateStatus.FAILED
    assert result.measurements["unauthorised_declared_skips"] == ["fake-pack/fake-gap"]
    assert "not verifier-minted" in result.findings[0].message


# Traceability: R-19 [Declared skip trusts only verified authority]
def test_blocking_finding_on_a_declared_skip_is_not_converted_to_a_pass(tmp_repo: Any) -> None:
    """Authorised absence converts the skip, not the failure evidence around it.

    A gate can report a declared absence for one runner while another, present
    runner failed. The authority owns only the absence; a Major finding riding
    on the same result must fail the release verdict rather than survive only
    inside nested measurements of a green aggregate.
    """
    root = tmp_repo('[orchestration]\nactive_packs = ["degraded-pack"]\n')
    authority = _minted_authority(
        root,
        "degraded-gap:runner",
        "2026-08-23 | DEC-66 | runner absence accepted | reviewer "
        "| degraded-gap:runner | active | -",
    )
    base = GateResult.skipped_declared(
        "degraded-gap",
        summary="absence owned, but a present runner failed",
        reason="one runner absent, one failed",
        authority={"runner": authority},
        clause="R-19",
    )
    failed_alongside = dataclasses.replace(
        base,
        findings=(
            Finding(
                "DEGRADED-RUNNER-FAILED",
                Severity.MAJOR,
                "present runner exited non-zero",
                clause="R-19",
                disposition="Fix the failing runner scenario.",
            ),
        ),
    )
    pack = _TestPack("degraded-pack", (_RecordingGate("degraded-gap", failed_alongside, []),))
    registry.register(pack)

    result = run_active_domain_gates(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.measurements["degraded_declared_skips"] == ["degraded-pack/degraded-gap"]
    assert result.findings[0].id == "DEGRADED-PACK-DEGRADED-RUNNER-FAILED"


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
