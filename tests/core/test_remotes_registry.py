"""Tests for canonical remote identity and dynamic pack registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from hexvision.config import Config
from hexvision.errors import PackError
from hexvision.packs import registry
from hexvision.packs.base import Pack, PackMeta, TargetSpec
from hexvision.packs.registry import available, clear_registered, load, load_all, register
from hexvision.remotes import check_remotes, normalize_remote_url
from tests.support.process import coverage_controls_sanitized, run_process


@pytest.mark.parametrize(
    "raw",
    [
        "git@github.com:Org/Repo.git",
        "ssh://git@github.com:22/org/repo",
        "ssh://git@github.com/org/repo.git",
        "https://github.com/org/repo.git",
        "https://GitHub.com/Org/Repo/",
        "github.com:org/repo",
        "github.com/org/repo",
        "git@github.com:org/repo\r",
    ],
)
# Traceability: R-3 [Equivalent GitHub spellings, Credential-bearing remote]
def test_remote_spellings_normalize(raw: str) -> None:
    """All Git spellings compare as one policy destination."""
    result = normalize_remote_url(raw)
    assert result.destination == "github.com/org/repo"
    assert not result.is_blocked


@pytest.mark.parametrize(
    "raw", ["", "ftp://github.com/o/r", "https://u:secret@github.com/o/r", "abc"]
)
def test_unsafe_or_invalid_remote_blocks(raw: str) -> None:
    """Unmodelled and credential-bearing remote values retain a blocked state."""
    assert normalize_remote_url(raw).is_blocked


@pytest.mark.parametrize(
    "raw",
    [
        "github.com:",
        ":org/repo",
        "https://github.com",
        "https://github.com/",
        "ssh://github.com/",
        "github.com//repo",
        "github.com/org/../repo",
        "github.com/org/./repo",
        "ssh://@github.com/org/repo",
        "ssh://git@:22/org/repo",
        "ssh://git@/org/repo",
        "mailto:user@example.com",
        "file:///tmp/repo",
        "git://",
        "https://:token@github.com/org/repo",
        "https://user:token@github.com/org/repo",
        "HTTPS://USER:TOKEN@GITHUB.COM/ORG/REPO",
        "ftp://host/path",
        "gopher://host/path",
        "github.com",
        "host:",
        " @ : ",
        "https:///org/repo",
        "ssh:///org/repo",
        "git@github.com:",
        "github.com:/",
        "github.com/.",
        "github.com/..",
        "https://github.com//",
        "://github.com/org/repo",
    ],
)
def test_more_invalid_remote_forms_block(raw: str) -> None:
    """Malformed inputs fail closed rather than being guessed into a destination."""
    assert normalize_remote_url(raw).is_blocked


# Traceability: R-4 [Empty allowlist]
def test_remote_policy_empty_allowlist_blocks(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A missing destination policy must not become an allow-all rule."""
    config = make_config(tmp_repo("[remotes]\nallowlist=[]\n"))
    assert check_remotes(config, ["github.com/org/repo"]).status.value == "blocked"


# Traceability: R-4 [Unreadable remote inspection]
def test_remote_policy_blocks_when_git_cannot_be_invoked(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A configured but unavailable Git executable leaves remote evidence unreadable and blocked."""

    config = make_config(
        tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\ngit_executable='missing-git'\n")
    )
    result = check_remotes(config)
    assert result.status.value == "blocked"
    assert result.summary == "remote inspection could not start"
    assert "cannot execute configured git command" in result.findings[0].message


# Traceability: R-4 [Invalid remote destination]
def test_remote_policy_rejects_an_invalid_discovered_destination(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A malformed remote is a concrete failed check with the parser's precise reason."""

    config = make_config(tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n"))
    result = check_remotes(config, ["https://github.com"])
    assert result.status.value == "failed"
    assert result.findings[0].message.endswith(
        "remote URL must include both host and repository path"
    )


# Traceability: R-4 [Unallowlisted destination]
def test_remote_policy_rejects_a_normalized_unallowlisted_destination(
    make_config: Callable[..., Config], tmp_repo: Callable[..., Path]
) -> None:
    """A valid but unapproved destination cannot inherit approval from another remote."""

    config = make_config(tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n"))
    result = check_remotes(config, ["https://github.com/other/repo.git"])
    assert result.status.value == "failed"
    assert "github.com/other/repo" in result.findings[0].message


# Traceability: R-4 [Allowlisted destination]
def test_remote_policy_accepts_allowed(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A normal configured destination passes policy comparison."""
    config = make_config(tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n"))
    assert check_remotes(config, ["https://GitHub.com/Org/Repo.git"]).status.value == "passed"


def test_remote_policy_accepts_configured_registry_host(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A governed registry host may approve its repository paths without weakening Git parsing."""
    result = check_remotes(make_config(tmp_repo()), ["https://huggingface.co/owner/model.git"])
    assert result.status.value == "passed"
    assert result.measurements["host_allowlist"] == ["huggingface.co"]


@dataclass(frozen=True)
class _Pack(Pack):
    """Minimal installed-like pack for exercising registry interfaces."""

    _meta: ClassVar[PackMeta] = PackMeta("fake", "test", "test pack")

    @property
    def meta(self) -> PackMeta:
        return self._meta

    def targets(self, config):  # type: ignore[no-untyped-def]
        del config
        return {"test": TargetSpec("test", ("pytest",))}

    def domain_gates(self, config):  # type: ignore[no-untyped-def]
        del config
        return ()


def test_registry_registers_and_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process registration supports isolated consumers without package metadata."""
    clear_registered()
    monkeypatch.setattr(registry, "_entry_points", lambda: {})
    pack = _Pack()
    register(pack)
    assert "fake" in available()
    assert load("fake") is pack
    assert pack in load_all()
    clear_registered()


def test_registry_rejects_duplicate_and_unknown() -> None:
    """Duplicate or missing names fail loudly instead of changing discovery silently."""
    clear_registered()
    register(_Pack())
    with pytest.raises(PackError):
        register(_Pack())
    clear_registered()
    with pytest.raises(PackError):
        load("absent")


def test_scp_credentials_are_blocked() -> None:
    """SCP syntax cannot hide a token in the user component from the secret gate."""
    assert normalize_remote_url("user:token@github.com:org/repo").is_blocked
    assert normalize_remote_url("https://user:token@github.com/org/repo").is_blocked


def test_actual_remote_and_pushurl_are_enumerated(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """An off-allowlist pushurl fails even when the fetch URL is approved."""
    root = tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n")
    run_process(
        ["/usr/bin/git", "remote", "add", "origin", "https://github.com/org/repo.git"],
        cwd=root,
    ).check_returncode()
    run_process(
        ["/usr/bin/git", "remote", "set-url", "--push", "origin", "https://evil.example/x/y.git"],
        cwd=root,
    ).check_returncode()
    with coverage_controls_sanitized():
        result = check_remotes(make_config(root))
    assert result.status.value == "failed"
    assert any("evil.example/x/y" in finding.message for finding in result.findings)


def test_no_actual_remote_blocks_instead_of_allowlist_only_pass(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A configured allowlist alone never produces a remote-gate pass."""
    root = tmp_repo("[remotes]\nallowlist=['github.com/org/repo']\n")
    with coverage_controls_sanitized():
        assert check_remotes(make_config(root)).status.value == "blocked"
