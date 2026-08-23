"""Tests for the one shared decision-log authority verifier (DEC-016, R-20)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hexvision.authority import (
    AuthorityDenial,
    DenialReason,
    VerifiedAuthority,
    verify_authority,
)
from hexvision.config import load_config


def _log(root: Path, *rows: str) -> None:
    """Write an isolated decision log using the packaged 7-column grammar."""
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "decision-log.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _row(
    identifier: str,
    subject: str,
    *,
    status: str = "active",
    supersedes: str = "-",
    decision: str = "recorded decision text",
) -> str:
    """Render one grammar-valid record row without duplicating cell order in tests."""
    return (
        f"2026-08-23 | {identifier} | {decision} | reviewer | {subject} | {status} | {supersedes}"
    )


# Traceability: R-20 [Nonexistent decision subject]
def test_no_record_for_subject_is_denied_not_found(tmp_repo: Any) -> None:
    """A subject no record names is denied rather than matched approximately."""
    root = tmp_repo()
    _log(root, _row("DEC-1", "hardware-in-loop:other_runner"))

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.NOT_FOUND
    assert result.subject == "hardware-in-loop:alpha"


# Traceability: R-20 [Unrelated subject text collision]
def test_prose_and_substring_collisions_never_authorize(tmp_repo: Any) -> None:
    """Neither prose containing the subject nor a superstring subject cell matches."""
    root = tmp_repo()
    _log(
        root,
        _row("DEC-201", "-", decision="alpha_beta subsystem is unrelated to the alpha runner"),
        _row("DEC-202", "hardware-in-loop:alpha_beta"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.NOT_FOUND


# Traceability: R-20 [Withdrawn or superseded decision]
def test_superseded_record_is_denied_regardless_of_its_own_status_cell(tmp_repo: Any) -> None:
    """A later supersedes reference withdraws a record whose own cell still says active."""
    root = tmp_repo()
    _log(
        root,
        _row("DEC-1", "hardware-in-loop:alpha"),
        _row("DEC-2", "-", supersedes="DEC-1", decision="DEC-1 is withdrawn; alpha must run"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.SUPERSEDED


def test_reconfirmation_chain_resolves_to_the_live_record(tmp_repo: Any) -> None:
    """A superseding record with the same subject becomes the single live authority."""
    root = tmp_repo()
    _log(
        root,
        _row("DEC-1", "hardware-in-loop:alpha"),
        _row("DEC-2", "hardware-in-loop:alpha", supersedes="DEC-1"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, VerifiedAuthority)
    assert result.decision_id == "DEC-2"
    assert result.subject == "hardware-in-loop:alpha"


def test_supersession_is_not_transitively_revived(tmp_repo: Any) -> None:
    """Superseding the superseder never revives the first record."""
    root = tmp_repo()
    _log(
        root,
        _row("DEC-1", "hardware-in-loop:alpha"),
        _row("DEC-2", "hardware-in-loop:alpha", supersedes="DEC-1"),
        _row("DEC-3", "hardware-in-loop:alpha", supersedes="DEC-2"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, VerifiedAuthority)
    assert result.decision_id == "DEC-3"


def test_inactive_status_cell_is_denied(tmp_repo: Any) -> None:
    """Any status other than the configured active value is non-authoritative."""
    root = tmp_repo()
    _log(root, _row("DEC-1", "hardware-in-loop:alpha", status="withdrawn"))

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.INACTIVE_STATUS


def test_two_live_records_for_one_subject_are_ambiguous_not_picked(tmp_repo: Any) -> None:
    """Competing live authority is denied instead of silently choosing one record."""
    root = tmp_repo()
    _log(
        root,
        _row("DEC-1", "hardware-in-loop:alpha"),
        _row("DEC-2", "hardware-in-loop:alpha"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.AMBIGUOUS


def test_identifier_outside_configured_grammar_is_denied_malformed(tmp_repo: Any) -> None:
    """A live record whose id fails every configured pattern cannot authorize."""
    root = tmp_repo()
    _log(root, _row("NOTREAL-9", "hardware-in-loop:alpha"))

    result = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.MALFORMED_ID


@pytest.mark.parametrize(
    "rows",
    [
        ("2026-08-23 | DEC-1 | text | r | s | active | DEC-1",),  # self-reference
        ("2026-08-23 | DEC-1 | text | r | s | active | DEC-9",),  # dangling reference
        (
            "2026-08-23 | DEC-1 | text | r | s | active | DEC-2",
            "2026-08-23 | DEC-2 | text | r | s2 | active | DEC-1",
        ),  # mutual reference
    ],
    ids=("self", "dangling", "mutual"),
)
def test_invalid_supersedes_graph_fails_closed_for_every_query(
    tmp_repo: Any, rows: tuple[str, ...]
) -> None:
    """A ledger whose withdrawal graph is inconsistent authorizes nothing at all."""
    root = tmp_repo()
    _log(root, _row("DEC-77", "unrelated:subject"), *rows)

    result = verify_authority(load_config(root=root, env={}), subject="unrelated:subject")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.LOG_INVALID


@pytest.mark.parametrize("subject", ["", "   ", "-", "n/a", "TBD"])
def test_blank_or_placeholder_caller_subject_is_rejected_not_matched(
    tmp_repo: Any, subject: str
) -> None:
    """A blank query can never equality-match a blank record cell; it is a caller error."""
    root = tmp_repo()
    _log(root, _row("DEC-1", "-"))

    with pytest.raises(ValueError, match="non-empty, non-placeholder"):
        verify_authority(load_config(root=root, env={}), subject=subject)


def test_unreadable_log_raises_for_caller_blocking_not_denial(tmp_repo: Any) -> None:
    """A missing ledger is an evidence failure the caller must surface as BLOCKED."""
    root = tmp_repo()

    with pytest.raises(FileNotFoundError, match="decision-log"):
        verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")


def test_lifecycle_columns_absent_from_adopter_schema_raise(tmp_repo: Any) -> None:
    """An adopter schema without the lifecycle columns cannot silently half-verify."""
    root = tmp_repo(
        '[decision_log]\ncolumns = ["date", "id", "decision", "recorded-by"]\n'
        'required_columns = ["date", "id", "decision", "recorded-by"]\n'
    )
    _log(root, "2026-08-23 | DEC-1 | text | reviewer")

    with pytest.raises(ValueError, match="must be configured columns"):
        verify_authority(load_config(root=root, env={}), subject="any:subject")


def test_verified_authority_cannot_be_constructed_outside_the_module() -> None:
    """Direct construction is refused so authority values only come from the verifier."""
    with pytest.raises(TypeError, match="verify_authority"):
        VerifiedAuthority(decision_id="DEC-1", subject="s", clause=None)


def test_dataclasses_replace_cannot_mint_altered_authority(tmp_repo: Any) -> None:
    """A holder of real authority cannot rewrite its fields through replace().

    The construction token is scrubbed after validation, so replace() carries
    None back into __init__ and the forgery raises instead of minting.
    """
    import dataclasses

    root = tmp_repo()
    _log(root, _row("DEC-1", "hardware-in-loop:alpha"))
    real = verify_authority(load_config(root=root, env={}), subject="hardware-in-loop:alpha")
    assert isinstance(real, VerifiedAuthority)

    with pytest.raises(TypeError, match="verify_authority"):
        dataclasses.replace(real, decision_id="DEC-FORGED", subject="release:anything")


def test_duplicate_record_ids_fail_closed_for_every_query(tmp_repo: Any) -> None:
    """Duplicate ids make the withdrawal graph unanswerable, including hidden cycles.

    Keyed edges would let a second row sharing an id overwrite the first row's
    supersedes edge, hiding a genuine cycle. Duplicates therefore invalidate the
    ledger outright rather than being resolved by position.
    """
    root = tmp_repo()
    _log(
        root,
        _row("DEC-77", "unrelated:subject"),
        "2026-08-23 | DEC-1 | text | r | s | active | DEC-2",
        "2026-08-23 | DEC-1 | text | r | s2 | active | DEC-3",
        "2026-08-23 | DEC-2 | text | r | s3 | active | DEC-1",
        _row("DEC-3", "-"),
    )

    result = verify_authority(load_config(root=root, env={}), subject="unrelated:subject")

    assert isinstance(result, AuthorityDenial)
    assert result.reason is DenialReason.LOG_INVALID
    assert "duplicate record id" in result.detail


def test_clause_is_diagnostic_context_only_never_a_record_filter(tmp_repo: Any) -> None:
    """The clause parameter labels config lookups; it must not filter records."""
    root = tmp_repo()
    _log(root, _row("DEC-1", "hardware-in-loop:alpha"))

    result = verify_authority(
        load_config(root=root, env={}), subject="hardware-in-loop:alpha", clause="R-HIL"
    )

    assert isinstance(result, VerifiedAuthority)
    assert result.decision_id == "DEC-1"
    assert result.clause == "R-HIL"
