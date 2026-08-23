"""Parse decision-log authority records from one configured append-only grammar.

Decision records authorize consequential exceptions: publication, declared
hardware absence, and permissive safety changes.  A substring search is not an
authority check because prose, Markdown comments, and code examples can all
contain an identifier.  This module therefore defines the one record grammar
all authority consumers share and leaves the grammar itself in configuration so
adopting repositories can retain their own reviewed decision-log schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from hexvision.config import Config
from hexvision.observability import get_logger

__all__ = [
    "DecisionLogParseResult",
    "DecisionLogRecord",
    "DecisionLogRejection",
    "DecisionLogSchema",
    "decision_ids",
    "load_decision_log_schema",
    "parse_decision_log",
    "read_decision_log",
]

_LOG: Final = get_logger(__name__)
_HTML_COMMENT_DELIMITER_COUNT: Final = 2


@dataclass(frozen=True, slots=True)
class DecisionLogSchema:
    """A reviewed record grammar used to distinguish authority from document prose.

    ``columns`` retains the configured order so a record cannot move an ID into
    a different cell and still become authority.  The explicit ``date_column``
    and ``identifier_column`` make the parser reusable for organizations whose
    established log uses different names.
    """

    columns: tuple[str, ...]
    date_column: str
    identifier_column: str
    date_format: str
    required_columns: frozenset[str]
    placeholder_values: frozenset[str]
    delimiter: str
    fenced_code_markers: tuple[str, ...]
    html_comment_start: str
    html_comment_end: str


@dataclass(frozen=True, slots=True)
class DecisionLogRecord:
    """One validated authority record and its source line for audit diagnostics."""

    line_number: int
    cells: tuple[str, ...]

    def value(self, schema: DecisionLogSchema, column: str) -> str:
        """Return a configured field without duplicating position assumptions in callers."""
        return self.cells[schema.columns.index(column)]


@dataclass(frozen=True, slots=True)
class DecisionLogRejection:
    """A non-record line and the grammar reason it cannot grant authority."""

    line_number: int
    text: str
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionLogParseResult:
    """Validated records plus rejected non-records for precise authorization failures."""

    records: tuple[DecisionLogRecord, ...]
    rejections: tuple[DecisionLogRejection, ...]

    def record(self, schema: DecisionLogSchema, identifier: str) -> DecisionLogRecord | None:
        """Return the exact recorded identifier, never a prose or partial-text match."""
        return next(
            (
                record
                for record in self.records
                if record.value(schema, schema.identifier_column) == identifier
            ),
            None,
        )

    def rejection_for(self, identifier: str) -> DecisionLogRejection | None:
        """Return the first rejected line naming an identifier to explain a failed lookup."""
        return next(
            (rejection for rejection in self.rejections if identifier in rejection.text),
            None,
        )


def load_decision_log_schema(config: Config, *, clause: str | None = None) -> DecisionLogSchema:
    """Resolve and validate the configured grammar before any authority is read.

    A malformed grammar blocks its consumer rather than falling back to a
    built-in layout.  Falling back would let an unreviewed configuration change
    silently alter the meaning of an existing decision log.
    """
    columns = _string_list(
        config.require("decision_log.columns", clause=clause), "decision-log columns"
    )
    date_column = _non_empty_string(
        config.require("decision_log.date_column", clause=clause), "decision-log date column"
    )
    identifier_column = _non_empty_string(
        config.require("decision_log.identifier_column", clause=clause),
        "decision-log identifier column",
    )
    date_format = _non_empty_string(
        config.require("decision_log.date_format", clause=clause), "decision-log date format"
    )
    required_columns = frozenset(
        _string_list(
            config.require("decision_log.required_columns", clause=clause),
            "required decision-log columns",
        )
    )
    placeholder_values = frozenset(
        value.casefold()
        for value in _string_list(
            config.require("decision_log.placeholder_values", clause=clause),
            "decision-log placeholder values",
            allow_blank=True,
        )
    )
    delimiter = _non_empty_string(
        config.require("decision_log.delimiter", clause=clause), "decision-log delimiter"
    )
    fenced_code_markers = tuple(
        _string_list(
            config.require("decision_log.fenced_code_markers", clause=clause),
            "decision-log fenced-code markers",
        )
    )
    comment_delimiters = _string_list(
        config.require("decision_log.html_comment_delimiters", clause=clause),
        "decision-log HTML-comment delimiters",
    )
    if len(set(columns)) != len(columns):
        raise ValueError("decision-log columns must be unique")
    if date_column not in columns or identifier_column not in columns:
        raise ValueError("decision-log date and identifier columns must be configured columns")
    if not required_columns <= set(columns):
        raise ValueError("required decision-log columns must be configured columns")
    if {date_column, identifier_column} - required_columns:
        raise ValueError("decision-log date and identifier columns must be required")
    if len(comment_delimiters) != _HTML_COMMENT_DELIMITER_COUNT:
        raise ValueError("decision-log HTML-comment delimiters must contain start and end values")
    return DecisionLogSchema(
        columns=tuple(columns),
        date_column=date_column,
        identifier_column=identifier_column,
        date_format=date_format,
        required_columns=required_columns,
        placeholder_values=placeholder_values,
        delimiter=delimiter,
        fenced_code_markers=fenced_code_markers,
        html_comment_start=comment_delimiters[0],
        html_comment_end=comment_delimiters[1],
    )


def read_decision_log(path: Path, schema: DecisionLogSchema) -> DecisionLogParseResult:
    """Read and parse one configured log path without allowing partial-text authority."""
    result = parse_decision_log(path.read_text(encoding="utf-8"), schema)
    _LOG.debug(
        "decision log parsed",
        extra={
            "path": str(path),
            "records": len(result.records),
            "rejections": len(result.rejections),
        },
    )
    return result


def decision_ids(config: Config, path: Path, *, clause: str | None = None) -> set[str]:
    """Return only identifiers carried by fully valid records in a configured log."""
    schema = load_decision_log_schema(config, clause=clause)
    return {
        record.value(schema, schema.identifier_column)
        for record in read_decision_log(path, schema).records
    }


def parse_decision_log(text: str, schema: DecisionLogSchema) -> DecisionLogParseResult:
    """Parse top-level Markdown table rows while rejecting non-record document contexts.

    The parser intentionally never asks whether a line *looks like a comment*.
    Instead, it accepts only a complete, top-level record with the configured
    number, order, required values, and date format.  Fenced code and HTML
    comment state are tracked because a complete-looking row in either context
    is documentation, not an append-only decision.
    """
    records: list[DecisionLogRecord] = []
    rejections: list[DecisionLogRejection] = []
    in_fenced_code = False
    in_html_comment = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if in_html_comment:
            rejections.append(_rejection(line_number, line, "line is inside an HTML comment"))
            if schema.html_comment_end in stripped:
                in_html_comment = False
            continue
        if schema.html_comment_start in stripped:
            rejections.append(_rejection(line_number, line, "line is inside an HTML comment"))
            if schema.html_comment_end not in stripped:
                in_html_comment = True
            continue
        if in_fenced_code:
            rejections.append(_rejection(line_number, line, "line is inside a fenced code block"))
            if _is_fence(stripped, schema):
                in_fenced_code = False
            continue
        if _is_fence(stripped, schema):
            in_fenced_code = True
            rejections.append(
                _rejection(line_number, line, "line is a fenced code-block delimiter")
            )
            continue
        record, reason = _parse_record_line(line_number, line, schema)
        if record is None:
            rejections.append(_rejection(line_number, line, reason))
        else:
            records.append(record)
    return DecisionLogParseResult(records=tuple(records), rejections=tuple(rejections))


def _parse_record_line(
    line_number: int, line: str, schema: DecisionLogSchema
) -> tuple[DecisionLogRecord | None, str]:
    """Validate one top-level line against every configured record grammar rule."""
    if line[:1].isspace():
        return None, "line is indented and cannot be a top-level decision-log row"
    if schema.delimiter not in line:
        return None, "line is not a decision-log table row"
    cells = line.split(schema.delimiter)
    if cells and not cells[0]:
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    normalized_cells = tuple(cell.strip() for cell in cells)
    if len(normalized_cells) != len(schema.columns):
        return (
            None,
            (
                f"row has {len(normalized_cells)} cells; configured schema requires "
                f"{len(schema.columns)}"
            ),
        )
    by_column = dict(zip(schema.columns, normalized_cells, strict=True))
    date_value = by_column[schema.date_column]
    if not _matches_date_format(date_value, schema.date_format):
        return None, f"date cell does not match configured format {schema.date_format!r}"
    for column in schema.required_columns:
        value = by_column[column]
        if not value or value.casefold() in schema.placeholder_values:
            return None, f"required cell {column!r} is blank or a configured placeholder"
    return DecisionLogRecord(line_number=line_number, cells=normalized_cells), ""


def _string_list(value: object, name: str, *, allow_blank: bool = False) -> list[str]:
    """Validate a configured list without silently stringifying malformed policy."""
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a non-empty list of strings")
    if not allow_blank and not all(item.strip() for item in value):
        raise ValueError(f"{name} must not contain blank values")
    return [item.strip() for item in value]


def _non_empty_string(value: object, name: str) -> str:
    """Validate one scalar grammar value before it changes authority semantics."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _matches_date_format(value: str, date_format: str) -> bool:
    """Require both parsability and a round trip so ISO dates retain zero padding."""
    try:
        return datetime.strptime(value, date_format).strftime(date_format) == value
    except ValueError:
        return False


def _is_fence(value: str, schema: DecisionLogSchema) -> bool:
    """Recognize configured Markdown fence starts and ends without hardcoded marker syntax."""
    return any(value.startswith(marker) for marker in schema.fenced_code_markers)


def _rejection(line_number: int, text: str, reason: str) -> DecisionLogRejection:
    """Preserve a non-record's exact location for an actionable blocked verdict."""
    return DecisionLogRejection(line_number=line_number, text=text, reason=reason)
