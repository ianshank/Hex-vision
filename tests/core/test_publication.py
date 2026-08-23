"""Tests for the release-time control governing public publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from hexvision.cli import main
from hexvision.config import load_config
from hexvision.gates.model import GateStatus
from hexvision.gates.publication import PublicationGate


def _publication_repo(root: Path, decision_log: str = "") -> None:
    """Create the decision-log input consumed by an isolated publication gate."""
    docs = root / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(decision_log, encoding="utf-8")


# Traceability: R-17 [Publication gate absent, Publication gate and allowlist present]
def test_publication_blocks_without_g_pub_authorization(tmp_repo: Any) -> None:
    """An approved destination still cannot publish before its named gate is recorded."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | G-PUB | | reviewer\n")

    result = PublicationGate("https://github.com/acme/release.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].message == (
        "required publication authorization gate 'G-PUB' has no valid decision-log entry "
        "in docs/decision-log.md: line 1 required cell 'decision' is blank or a configured "
        "placeholder"
    )


# Traceability: R-17 [Publication gate and allowlist present]
def test_publication_rejects_unallowlisted_destination_despite_g_pub(tmp_repo: Any) -> None:
    """Decision authority cannot override the shared destination allowlist."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | G-PUB | authorized release | reviewer\n")

    result = PublicationGate("https://github.com/acme/other.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.FAILED
    assert result.findings[0].message == (
        "remote 'https://github.com/acme/other.git' resolves to unapproved destination "
        "'github.com/acme/other'"
    )


# Traceability: R-17 [Publication gate and allowlist present]
def test_publication_rejects_credential_destination_with_normalizer_reason(tmp_repo: Any) -> None:
    """Credentials cannot be discarded before the shared normalizer records their reason."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | G-PUB | authorized release | reviewer\n")

    result = PublicationGate("https://user:token@github.com/acme/release").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.FAILED
    assert result.findings[0].message == (
        "remote 'https://user:token@github.com/acme/release' is unsafe or unparseable: "
        "remote URL contains userinfo with a password or token"
    )


# Traceability: R-17 [Publication gate and allowlist present]
def test_publication_permits_normalized_allowlisted_destination_with_g_pub(tmp_repo: Any) -> None:
    """Publication proceeds only when both independently governed conditions hold."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | G-PUB | authorized release | reviewer\n")

    result = PublicationGate("git@github.com:Acme/Release.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.PASSED
    assert result.measurements["destination"] == "github.com/acme/release"


@pytest.mark.parametrize(
    ("decision_log", "line_number", "reason"),
    [
        (
            "# 2026-08-22 | G-PUB | approved release | reviewer\n",
            1,
            "date cell does not match configured format '%Y-%m-%d'",
        ),
        (
            "The release is not authorized by G-PUB until a decision is recorded.\n",
            1,
            "line is not a decision-log table row",
        ),
        (
            "```\n2026-08-22 | G-PUB | approved release | reviewer\n```\n",
            2,
            "line is inside a fenced code block",
        ),
        (
            "<!--\n2026-08-22 | G-PUB | approved release | reviewer\n-->\n",
            2,
            "line is inside an HTML comment",
        ),
        (
            "    2026-08-22 | G-PUB | approved release | reviewer\n",
            1,
            "line is indented and cannot be a top-level decision-log row",
        ),
        (
            "| --- | --- | --- | --- |\n",
            1,
            None,
        ),
        (
            "2026-08-22 | G-PUB | approved release\n",
            1,
            "row has 3 cells; configured schema requires 4",
        ),
        (
            "2026-08-22 | G-PUB | approved release | reviewer | extra\n",
            1,
            "row has 5 cells; configured schema requires 4",
        ),
        (
            "2026-8-22 | G-PUB | approved release | reviewer\n",
            1,
            "date cell does not match configured format '%Y-%m-%d'",
        ),
        (
            "2026-08-22 | G-PUB |  | reviewer\n",
            1,
            "required cell 'decision' is blank or a configured placeholder",
        ),
        (
            "2026-08-22 | G-PUB | TBD | reviewer\n",
            1,
            "required cell 'decision' is blank or a configured placeholder",
        ),
        (
            "2026-08-22 | G-PUB | - | reviewer\n",
            1,
            "required cell 'decision' is blank or a configured placeholder",
        ),
        (
            "2026-08-22 | G-PUB | N/A | reviewer\n",
            1,
            "required cell 'decision' is blank or a configured placeholder",
        ),
    ],
)
# Traceability: R-17
def test_publication_rejects_invalid_g_pub_pseudo_records(
    tmp_repo: Any, decision_log: str, line_number: int, reason: str | None
) -> None:
    """Every pseudo-record fails with its grammar reason rather than gaining authority."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, decision_log)

    result = PublicationGate("https://github.com/acme/release.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.BLOCKED
    expected = (
        "required publication authorization gate 'G-PUB' has no decision-log entry "
        "in docs/decision-log.md"
        if reason is None
        else (
            "required publication authorization gate 'G-PUB' has no valid decision-log entry "
            f"in docs/decision-log.md: line {line_number} {reason}"
        )
    )
    assert result.findings[0].message == expected


# Traceability: R-17
def test_publication_rejects_record_for_a_different_gate_id(tmp_repo: Any) -> None:
    """A well-formed decision for another gate cannot be substituted for G-PUB."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | DEC-001 | approved release | reviewer\n")

    result = PublicationGate("https://github.com/acme/release.git").check(
        load_config(root=root, env={})
    )

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].message == (
        "required publication authorization gate 'G-PUB' has no decision-log entry "
        "in docs/decision-log.md"
    )


@pytest.mark.parametrize(
    ("destination", "reason"),
    [
        (
            "https://github.com/acme/release.git?branch=release",
            "remote URL contains a query component",
        ),
        (
            "https://github.com/acme/release.git#release",
            "remote URL contains a fragment component",
        ),
        (
            "https://github.com/acme/release.git?redirect=https://evil.example",
            "remote URL contains a query component",
        ),
        (
            "https://github.com/acme/release.git?redirect=https://evil.example#@evil.example",
            "remote URL contains query and fragment components",
        ),
    ],
)
# Traceability: R-17
def test_publication_rejects_destination_query_and_fragment_components(
    tmp_repo: Any, destination: str, reason: str
) -> None:
    """Git destinations reject components whose semantics would otherwise be discarded."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')
    _publication_repo(root, "2026-08-22 | G-PUB | approved release | reviewer\n")

    result = PublicationGate(destination).check(load_config(root=root, env={}))

    assert result.status is GateStatus.FAILED
    assert result.findings[0].message == (
        f"remote {destination!r} is unsafe or unparseable: {reason}"
    )


def test_publication_blocks_when_shared_remote_policy_is_unavailable(tmp_repo: Any) -> None:
    """An empty shared allowlist is unavailable policy rather than a release authorization."""
    root = tmp_repo("[remotes]\nallowlist=[]\n")
    _publication_repo(root, "2026-08-22 | G-PUB | authorized release | reviewer\n")

    result = PublicationGate("github.com/acme/release").check(load_config(root=root, env={}))

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].message == (
        "remotes.allowlist must contain at least one approved destination"
    )


def test_publication_blocks_when_decision_log_cannot_be_read(tmp_repo: Any) -> None:
    """Missing authorization evidence blocks instead of being interpreted as an empty approval."""
    root = tmp_repo('[remotes]\nallowlist=["github.com/acme/release"]\n')

    result = PublicationGate("github.com/acme/release").check(load_config(root=root, env={}))

    assert result.status is GateStatus.BLOCKED
    assert result.summary == "publication authorization cannot be read"


@pytest.mark.parametrize(
    "overlay, reason",
    [
        (
            "[publication]\ndefault_destination=1\n",
            "publication authorization ID, decision-log path, and destination must be strings",
        ),
        (
            "[traceability]\ndecision_id_patterns=[]\n",
            "traceability decision-id patterns must be non-empty strings",
        ),
        (
            '[publication]\nauthorization_id="PUB-1"\n',
            "publication authorization ID must match an existing traceability decision-id pattern",
        ),
    ],
)
def test_publication_blocks_invalid_configured_policy(
    tmp_repo: Any, overlay: str, reason: str
) -> None:
    """Misconfigured inputs cannot make a release control appear to have run."""
    result = PublicationGate().check(load_config(root=tmp_repo(overlay), env={}))

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].message == reason


def test_publication_blocks_non_string_explicit_destination(tmp_repo: Any) -> None:
    """Programmatic callers receive the same fail-closed handling as the CLI."""
    result = PublicationGate(cast(str, 7)).check(load_config(root=tmp_repo(), env={}))

    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].message == "publication destination must be a string"


def test_publication_cli_accepts_destination_and_uses_config_default(
    monkeypatch: pytest.MonkeyPatch, tmp_repo: Any
) -> None:
    """The release target may use reviewed config while operators may name a destination."""
    root = tmp_repo(
        '[remotes]\nallowlist=["github.com/acme/release"]\n'
        "\n[publication]\n"
        'default_destination="github.com/acme/release"\n'
    )
    _publication_repo(root, "2026-08-22 | G-PUB | authorized release | reviewer\n")
    monkeypatch.chdir(root)

    assert main(["publication"]) == 0
    assert main(["publication", "https://github.com/acme/release.git"]) == 0
