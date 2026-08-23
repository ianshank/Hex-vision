"""Black-box regression probes for release controls that previously gave false greens."""

from __future__ import annotations

import random
import shutil
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import hexvision
from hexvision import scanner_identity
from hexvision.config import Config, load_config
from hexvision.conformance import check_pack
from hexvision.errors import ExitCode, GateBlockedError
from hexvision.gates.base import Gate, run_gate
from hexvision.gates.model import GateResult, GateStatus
from hexvision.gates.publication import PublicationGate
from hexvision.packs.base import Pack, PackMeta, TargetSpec
from tests.conftest import assert_subject_under_test_is_this_checkout
from tests.support.process import run_process

REPO_ROOT = Path(__file__).resolve().parents[2]
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"


def _secret() -> str:
    """Create a deterministic credential-shaped probe only at test execution time."""

    alphabet = string.ascii_letters + string.digits
    generator = random.Random(82)  # noqa: S311 - deterministic synthetic security probe.
    return "ghp_" + "".join(generator.choice(alphabet) for _ in range(36))


def _decision_log(root: Path, contents: str) -> None:
    """Write publication authority evidence into an isolated repository fixture."""

    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "decision-log.md").write_text(contents, encoding="utf-8")


# Incident PR-02 / original zero-rule secret scanner false green.
def test_aqa_planted_credential_is_detected_by_a_loaded_rule_set(tmp_path: Path) -> None:
    """A real scanner must emit a concrete RuleID and failing process result for a planted token."""

    scanner = shutil.which("gitleaks")
    assert scanner is not None, "gitleaks is required; a missing scanner is not a skip"
    probe = tmp_path / "credential.txt"
    probe.write_text(f"token = {_secret()}\n", encoding="utf-8")
    report = tmp_path / "report.json"

    completed = run_process(
        [
            scanner,
            "dir",
            str(tmp_path),
            "--config",
            str(GITLEAKS_CONFIG),
            "--report-format",
            "json",
            "--report-path",
            str(report),
            "--redact",
            "--no-banner",
        ],
        cwd=tmp_path,
    )

    assert completed.returncode == int(ExitCode.FAILED), completed.stderr
    assert '"RuleID":"github-pat"' in report.read_text(encoding="utf-8").replace(" ", "")


# Incident R2-01 / comment-shaped publication authority forgery.
def test_aqa_comment_shaped_publication_authority_is_blocked(tmp_repo: Any) -> None:
    """A pseudo-row was inspected but cannot authorize release, so it remains BLOCKED."""

    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _decision_log(root, "# 2026-08-22 | G-PUB | illustrative only | reviewer\n")

    result = PublicationGate("https://github.com/acme/release.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.BLOCKED
    assert result.exit_code is ExitCode.BLOCKED
    assert result.findings[0].id == "PUBLICATION-BLOCKED"
    assert "has no valid decision-log entry" in result.findings[0].message
    assert "date cell does not match" in result.findings[0].message


@pytest.mark.parametrize(
    ("suffix", "reason"),
    [
        ("?redirect=https://evil.example", "remote URL contains a query component"),
        ("#@evil.example", "remote URL contains a fragment component"),
    ],
)
# Incident R2-02 / remote query or fragment silently discarded.
def test_aqa_publication_destination_preserves_rejected_components(
    tmp_repo: Any, suffix: str, reason: str
) -> None:
    """Rejected components retain their exact reason, finding identity, and failure exit."""

    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _decision_log(root, "2026-08-22 | G-PUB | approved | reviewer\n")
    destination = f"https://github.com/acme/release.git{suffix}"

    result = PublicationGate(destination).check(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    assert result.findings[0].id == "PUB-REMOTE-001"
    assert result.findings[0].message.endswith(reason)


@dataclass
class _CounterfeitPack(Pack):
    """Pack whose plausible prose is deliberately not a governed implementation."""

    @property
    def meta(self) -> PackMeta:
        """Describe the test pack using the same discovery interface as real packs."""

        return PackMeta("counterfeit", "AQA probe", "AQA")

    def targets(self, config: Config) -> dict[str, TargetSpec]:
        """Claim valid target names while replacing one implementation with counterfeit prose."""

        specs = {
            name: TargetSpec(name, ("make", name)) for name in config.require("contract.targets")
        }
        specs["pre-pr"] = TargetSpec("pre-pr", ("make", "pre-pr"))
        specs["specs"] = TargetSpec(
            "specs",
            ("make", "specs"),
            False,
            rationale="configured degraded mode",
            degrades_loudly=True,
        )
        specs["secrets"] = TargetSpec("secrets", ("sh", "-c", "echo leaks found; exit 1"))
        return specs

    def domain_gates(self, config: Config) -> tuple[Gate, ...]:
        """Keep the probe focused on invariant evidence rather than domain-gate metadata."""

        del config
        return ()


# Incident R2-03 / conformance accepted a counterfeit command that printed expected prose.
def test_aqa_counterfeit_conformance_command_fails_with_governed_implementation_reason(
    tmp_repo: Any,
) -> None:
    """Plausible output cannot substitute for controlled Makefile evidence."""

    root = tmp_repo()
    config = load_config(root=root, env={})
    (root / "src").mkdir()
    (root / "src" / "remote.py").write_text(
        "def normalize_remote_url(raw):\n    return raw\n", encoding="utf-8"
    )
    targets = "\n".join(
        f"{target}:" for target in config.require("contract.targets") if target != "pre-pr"
    )
    (root / "Makefile").write_text(
        f"{targets}\npre-pr: {' '.join(config.require('contract.pre_pr_order'))}\n",
        encoding="utf-8",
    )

    result = check_pack(config, _CounterfeitPack())

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    assert any(
        finding.id.startswith("CONFORMANCE-")
        and "INV-1" in finding.message
        and "not the configured Makefile executable" in finding.message
        for finding in result.findings
    )


# Incident R2-04 / a PATH shadow scanner spoofed only its version string.
def test_aqa_path_shadow_scanner_is_blocked_by_digest_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-named executable with plausible version behavior is BLOCKED before it can scan."""

    shadow = tmp_path / "gitleaks"
    shadow.write_text(
        '#!/bin/sh\nif [ "$1" = version ]; then echo 8.28.0; fi\nexit 0\n', encoding="utf-8"
    )
    shadow.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path(shutil.which('sh') or '/bin/sh').parent}")

    with pytest.raises(GateBlockedError) as blocked:
        scanner_identity.resolve_verified_scanner("gitleaks", load_config(root=REPO_ROOT))

    assert blocked.value.exit_code is ExitCode.BLOCKED
    assert "scanner identity BLOCKED" in str(blocked.value)
    assert "SHA-256 digest mismatch" in str(blocked.value)


# Incident R2-05 / importorskip bypassed zero-skip at collection time.
def test_aqa_importorskip_collection_bypass_is_a_failed_child_run(tmp_path: Path) -> None:
    """Collection-time non-execution returns a failed pytest process with the terminal reason."""

    test_root = REPO_ROOT / "tests"
    shutil.copy(test_root / "conftest.py", tmp_path / "conftest.py")
    support = tmp_path / "tests"
    support.mkdir()
    shutil.copy(test_root / "__init__.py", support / "__init__.py")
    shutil.copytree(test_root / "support", support / "support")
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "test_collection.py").write_text(
        'import pytest\npytest.importorskip("aqa_missing_dependency")\n', encoding="utf-8"
    )

    completed = run_process([sys.executable, "-m", "pytest", "-q"], cwd=tmp_path)

    assert completed.returncode == int(ExitCode.FAILED), completed.stdout + completed.stderr
    output = completed.stdout + completed.stderr
    assert "zero-skip terminal accounting failure: collection skip recorded" in output


# Incident R2-06 / traceability was Green for collection rather than scenario fidelity.
def test_aqa_traceability_marker_requires_the_cited_node_not_another_test(
    tmp_repo: Any,
) -> None:
    """Scenario evidence fails with its exact marker finding when only unrelated prose is cited."""

    root = tmp_repo()
    (root / "traceability").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    specs = root / "openspec" / "changes" / "aqa" / "specs"
    specs.mkdir(parents=True)
    (specs / "requirement.md").write_text(
        "### Requirement: R-1 — fidelity\n\n"
        "#### Scenario: cited behavior\n- **WHEN** x\n- **THEN** y\n",
        encoding="utf-8",
    )
    (root / "docs" / "decision-log.md").write_text("", encoding="utf-8")
    (root / "traceability" / "REQUIREMENT-TRACEABILITY.md").write_text(
        (
            "| requirement id | statement | status | test node id | "
            "inherits-from | decision ref | notes |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| R-1 | fidelity | Green | tests/test_claim.py::test_claim | | | |\n"
        ),
        encoding="utf-8",
    )
    (root / "tests" / "test_claim.py").write_text(
        "# Traceability: R-2 [cited behavior]\n\ndef test_claim() -> None:\n    assert True\n",
        encoding="utf-8",
    )

    from hexvision.traceability import check_traceability

    result = check_traceability(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    assert any(
        finding.id == "TRACE-R-1-MARKER"
        and "lacks exact Traceability marker for 'R-1'" in finding.message
        for finding in result.findings
    )


class _UninspectableGate(Gate):
    """Minimal gate that reproduces an inspection prerequisite failure."""

    @property
    def name(self) -> str:
        """Name the probe for its structured finding identifier."""

        return "aqa-inspection"

    @property
    def clause(self) -> str:
        """Bind the probe to the four-state contract."""

        return "AQA"

    def check(self, config: Config) -> GateResult:
        """Raise an unavailable-input error that the common runner must retain as BLOCKED."""

        del config
        raise OSError("evidence source unavailable")


# Incident shared-rules four-state regression / BLOCKED was collapsed into FAILED.
def test_aqa_could_not_look_remains_blocked_with_its_distinct_exit_and_finding() -> None:
    """A runner error preserves 'could not look' rather than claiming a discovered problem."""

    result = run_gate(_UninspectableGate(), load_config(root=REPO_ROOT))

    assert result.status is GateStatus.BLOCKED
    assert result.exit_code is ExitCode.BLOCKED
    assert result.findings[0].id == "AQA-INSPECTION-BLOCKED"
    assert "unexpected OSError: evidence source unavailable" in result.findings[0].message


# Incident shared-virtualenv false green / sibling checkout source was imported.
def test_aqa_shared_virtualenv_source_guard_names_the_foreign_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling editable-install path is rejected before any test can report a false pass."""

    checkout = tmp_path / "checkout"
    (checkout / "src" / "hexvision").mkdir(parents=True)
    (checkout / "src" / "hexvision" / "__init__.py").write_text("", encoding="utf-8")
    foreign = tmp_path / "foreign" / "hexvision" / "__init__.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("", encoding="utf-8")
    monkeypatch.setattr(hexvision, "__file__", str(foreign))

    with pytest.raises(RuntimeError, match="does not belong to the checkout under test"):
        assert_subject_under_test_is_this_checkout(checkout)
