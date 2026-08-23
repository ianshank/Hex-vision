"""Tests for the shared, configuration-derived decision-log authority grammar."""

from __future__ import annotations

from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.decision_log import decision_ids, load_decision_log_schema, parse_decision_log


def test_decision_log_accepts_bare_and_delimited_configured_rows(tmp_repo: Any) -> None:
    """Both Markdown row spellings retain exact configured field order and values."""
    config = load_config(root=tmp_repo(), env={})
    schema = load_decision_log_schema(config)

    parsed = parse_decision_log(
        "2026-08-22 | DEC-001 | approved | owner | - | active | -\n"
        "| 2026-08-23 | G-PUB | release | reviewer | - | active | - |\n",
        schema,
    )

    assert [record.value(schema, "id") for record in parsed.records] == ["DEC-001", "G-PUB"]
    assert not parsed.rejections


def test_decision_log_uses_an_adopter_configured_schema(tmp_repo: Any) -> None:
    """Authority remains configurable instead of inheriting this repository's column names."""
    root = tmp_repo(
        """
[decision_log]
columns = ["when", "gate", "justification", "owner", "ticket"]
date_column = "when"
identifier_column = "gate"
date_format = "%Y/%m/%d"
required_columns = ["when", "gate", "justification", "owner"]
"""
    )
    config = load_config(root=root, env={})
    schema = load_decision_log_schema(config)

    parsed = parse_decision_log("2026/08/22 | G-RELEASE | reviewed | owner | -\n", schema)

    assert parsed.record(schema, "G-RELEASE") is not None


@pytest.mark.parametrize(
    ("overlay", "reason"),
    [
        (
            '[decision_log]\ncolumns = ["date", "date", "id", "decision"]\n',
            "decision-log columns must be unique",
        ),
        (
            '[decision_log]\ndate_column = "when"\n',
            "decision-log date and identifier columns must be configured columns",
        ),
        (
            '[decision_log]\nrequired_columns = ["date", "id", "absent"]\n',
            "required decision-log columns must be configured columns",
        ),
        (
            '[decision_log]\nrequired_columns = ["id", "decision", "recorded-by"]\n',
            "decision-log date and identifier columns must be required",
        ),
        (
            '[decision_log]\nhtml_comment_delimiters = ["<!--"]\n',
            "decision-log HTML-comment delimiters must contain start and end values",
        ),
    ],
)
def test_decision_log_rejects_invalid_grammar_configuration(
    tmp_repo: Any, overlay: str, reason: str
) -> None:
    """A malformed grammar cannot degrade into a permissive hard-coded fallback."""
    config = load_config(root=tmp_repo(overlay), env={})

    with pytest.raises(ValueError, match=reason):
        load_decision_log_schema(config)


def test_decision_ids_excludes_invalid_and_retains_valid_records(tmp_repo: Any) -> None:
    """Shared consumers receive only IDs that occur in fully valid authority records."""
    root = tmp_repo()
    path = root / "decisions.md"
    path.write_text(
        "2026-08-22 | DEC-001 | approved | owner | - | active | -\n"
        "# 2026-08-22 | DEC-FAKE | comment | owner\n"
        "```\n2026-08-22 | G-PUB | example | owner\n```\n",
        encoding="utf-8",
    )

    assert decision_ids(load_config(root=root, env={}), path) == {"DEC-001"}


def test_decision_log_rejects_separator_rows_with_a_specific_grammar_reason(tmp_repo: Any) -> None:
    """A Markdown separator cannot be mistaken for a dated append-only decision record."""
    schema = load_decision_log_schema(load_config(root=tmp_repo(), env={}))

    parsed = parse_decision_log("| --- | --- | --- | --- | --- | --- | --- |\n", schema)

    assert not parsed.records
    assert parsed.rejections[0].reason == "date cell does not match configured format '%Y-%m-%d'"
