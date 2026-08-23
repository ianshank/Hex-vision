"""Direct coverage of the configuration-driven scanner artifact verifier."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hexvision import scanner_identity
from hexvision.config import load_config
from hexvision.errors import GateBlockedError

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_verified_gitleaks_resolves_to_its_canonical_absolute_path() -> None:
    """The real configured artifact verifies and is returned as a canonical path."""
    config = load_config(root=REPO_ROOT)
    executable = str(config.require("scanners.gitleaks.executable"))
    located = shutil.which(executable)
    assert located is not None
    assert scanner_identity.resolve_verified_scanner("gitleaks", config) == Path(located).resolve()


def test_verifier_blocks_an_absent_configured_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing tool is BLOCKED, with a reason distinct from a clean scan."""
    monkeypatch.setattr("hexvision.scanner_identity.shutil.which", lambda _executable: None)
    with pytest.raises(GateBlockedError, match="gitleaks version 8.28.0 is not found on PATH"):
        scanner_identity.resolve_verified_scanner("gitleaks", load_config(root=REPO_ROOT))


def test_verifier_blocks_a_digest_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An arbitrary same-named executable cannot satisfy the configured digest pin."""
    impostor = tmp_path / "gitleaks"
    impostor.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    impostor.chmod(0o755)
    monkeypatch.setattr(
        "hexvision.scanner_identity.shutil.which", lambda _executable: str(impostor)
    )
    with pytest.raises(GateBlockedError, match="gitleaks SHA-256 digest mismatch"):
        scanner_identity.resolve_verified_scanner("gitleaks", load_config(root=REPO_ROOT))


def test_verifier_blocks_a_platform_without_a_pinned_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dynamic platform lookup refuses to guess a digest for a platform without one."""
    monkeypatch.setattr("hexvision.scanner_identity.platform.system", lambda: "Unsupported")
    monkeypatch.setattr("hexvision.scanner_identity.platform.machine", lambda: "architecture")
    with pytest.raises(
        GateBlockedError, match="no configured digest for platform unsupported/architecture"
    ):
        scanner_identity.resolve_verified_scanner("gitleaks", load_config(root=REPO_ROOT))


def test_verifier_blocks_an_unreadable_artifact() -> None:
    """Digest I/O failures remain BLOCKED rather than being mistaken for a mismatch pass."""
    with pytest.raises(GateBlockedError, match="cannot compute SHA-256 digest for gitleaks"):
        scanner_identity._digest(REPO_ROOT / "not-a-scanner", tool="gitleaks")


@pytest.mark.parametrize(
    ("policy", "reason"),
    [
        ({}, "has no platforms table"),
        ({"platforms": {}}, "no configured digest for platform linux/x86_64"),
        ({"platforms": {"linux": {}}}, "no configured digest for platform linux/x86_64"),
    ],
)
def test_platform_policy_blocks_every_malformed_or_missing_host_mapping(
    policy: dict[str, object], reason: str
) -> None:
    """Malformed scanner policy cannot make a platform resolve to an unreviewed digest."""
    with pytest.raises(GateBlockedError, match=reason):
        scanner_identity._platform_policy(policy, tool="gitleaks")


def test_policy_text_values_must_be_nonempty() -> None:
    """A blank executable or digest configuration is BLOCKED rather than silently accepted."""
    with pytest.raises(GateBlockedError, match="no usable 'artifact_sha256' value"):
        scanner_identity._require_text({"artifact_sha256": ""}, "artifact_sha256", tool="gitleaks")


def test_install_values_come_from_the_host_platform_configuration() -> None:
    """The legacy installer receives only shell-quoted policy values from configuration."""
    values = scanner_identity._install_shell_values("gitleaks", load_config(root=REPO_ROOT))
    assert "version=8.28.0" in values
    assert "asset=gitleaks_8.28.0_linux_x64.tar.gz" in values
    assert "release_sha256=" in values


def test_cli_verifies_and_renders_installer_values(capsys: pytest.CaptureFixture[str]) -> None:
    """Both Makefile-facing commands return their policy-derived stdout contracts."""
    assert scanner_identity.main(["verify", "gitleaks"]) == 0
    assert Path(capsys.readouterr().out.strip()).is_absolute()
    assert scanner_identity.main(["install-shell", "osv-scanner"]) == 0
    assert "executable=osv-scanner" in capsys.readouterr().out


def test_cli_returns_blocked_exit_and_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI failures retain the scanner-specific BLOCKED reason and the required exit code."""

    def blocked(tool: str, config: object) -> Path:
        del tool, config
        raise GateBlockedError("scanner identity BLOCKED: deliberate test failure", clause="INV-1")

    monkeypatch.setattr(scanner_identity, "resolve_verified_scanner", blocked)
    assert scanner_identity.main(["verify", "gitleaks"]) == 2
    assert "scanner identity BLOCKED: deliberate test failure" in capsys.readouterr().err
