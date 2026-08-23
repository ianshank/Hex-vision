"""The one shared verifier that turns a decision-log record into usable authority.

Three independent call sites re-implemented "does a decision authorize this
exception" and each was wrong differently (DEC-016): release aggregation trusted
any non-empty string, hardware-in-the-loop matched a runner name as a substring
of a whole record row, and agent validation passed on an empty discovery set.
This module is the corrective action: every consumer resolves authority through
:func:`verify_authority`, which returns a typed :class:`VerifiedAuthority` no
gate constructs itself, and conformance rejects any construction site outside
this file.

Two honesty notes are deliberate parts of the contract. First, the construction
guard defends against *accidental* re-implementation — the defect class that
actually recurred — not against adversarial forgery: Python permits
``object.__new__`` bypasses, which the conformance AST heuristic flags in its
direct spelling but cannot see through an assignment alias, and which the
runtime cannot prevent. Second, verification failure is a typed denial while an
unreadable or misconfigured ledger *raises*: a verifier that could not look must
surface as BLOCKED at its caller, never as a quiet "not authorized".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from hexvision.config import Config
from hexvision.decision_log import (
    DecisionLogRecord,
    DecisionLogSchema,
    load_decision_log_schema,
    read_decision_log,
)
from hexvision.observability import get_logger

__all__ = [
    "AuthorityDenial",
    "DenialReason",
    "VerifiedAuthority",
    "verify_authority",
]

_LOG: Final = get_logger(__name__)
#: Private construction capability. Not exported; the conformance suite rejects
#: any ``VerifiedAuthority(...)`` call site outside this module, and this token
#: turns an accidental in-process construction into an immediate TypeError.
_CONSTRUCTION_TOKEN: Final = object()


class DenialReason(Enum):
    """Why a subject failed verification, as data an aggregate can act on."""

    NOT_FOUND = "not-found"
    MALFORMED_ID = "malformed-id"
    INACTIVE_STATUS = "inactive-status"
    SUPERSEDED = "superseded"
    AMBIGUOUS = "ambiguous"
    LOG_INVALID = "log-invalid"


@dataclass(frozen=True, slots=True)
class VerifiedAuthority:
    """A decision-log authorization that has actually been verified.

    Instances exist only as :func:`verify_authority` return values. The private
    token makes direct construction a TypeError, and the conformance gate
    rejects any construction call site outside this module, so a gate cannot
    hand itself an authority the ledger never granted.
    """

    decision_id: str
    subject: str
    clause: str | None
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Refuse construction that did not come from verify_authority.

        The token is scrubbed immediately after validation so a holder of a
        real instance cannot mint an altered copy through ``dataclasses.replace``
        (or ``copy.replace``), which would otherwise carry the live token back
        into ``__init__``. Pickle and deepcopy of a real instance still work,
        because slots-dataclass copying bypasses ``__init__`` entirely.
        """
        if self._token is not _CONSTRUCTION_TOKEN:
            raise TypeError(
                "VerifiedAuthority is created only by hexvision.authority.verify_authority; "
                "call the verifier instead of constructing authority directly"
            )
        object.__setattr__(self, "_token", None)


@dataclass(frozen=True, slots=True)
class AuthorityDenial:
    """A verification that ran to completion and found no live authority."""

    subject: str
    reason: DenialReason
    detail: str


def verify_authority(  # noqa: PLR0911 - each denial reason reports independently.
    config: Config, *, subject: str, clause: str | None = None
) -> VerifiedAuthority | AuthorityDenial:
    """Resolve one subject against the configured decision log, exactly.

    Matching is equality on the configured subject column — never substring,
    prose, or pattern matching — and a record is live only when its status cell
    equals the configured active value AND no other record names it in a
    supersedes cell. The supersession check deliberately ignores the superseded
    record's own status cell, because the ledger is append-only: a withdrawn
    record's cells are never edited, so only the later reference can kill it.

    Args:
        config: Resolved repository configuration.
        subject: Exact subject string to authorize, e.g. ``"hardware-in-loop:hil_smoke"``.
        clause: Diagnostic context recorded on config lookups and the returned
            value. It never filters records; two callers passing different
            clauses for the same subject see the same verdict.

    Returns:
        A :class:`VerifiedAuthority` for the single live, well-formed record
        naming ``subject``, or an :class:`AuthorityDenial` naming why none
        qualifies.

    Raises:
        ValueError: If ``subject`` is blank or a configured placeholder (a
            caller error, not a ledger verdict), or the lifecycle columns are
            not part of the configured schema.
        OSError: If the configured ledger cannot be read, including a ledger
            that is not valid UTF-8. Callers must surface this as BLOCKED, not
            as a denial.
    """
    schema = load_decision_log_schema(config, clause=clause)
    subject_column = _lifecycle_column(
        schema,
        config.require("decision_log.subject_column", clause=clause),
        "decision_log.subject_column",
    )
    status_column = _lifecycle_column(
        schema,
        config.require("decision_log.status_column", clause=clause),
        "decision_log.status_column",
    )
    supersedes_column = _lifecycle_column(
        schema,
        config.require("decision_log.supersedes_column", clause=clause),
        "decision_log.supersedes_column",
    )
    active_value = _non_empty(
        config.require("decision_log.active_status_value", clause=clause),
        "decision_log.active_status_value",
    )
    patterns = _identifier_patterns(config, clause)
    normalized_subject = subject.strip()
    if not normalized_subject or normalized_subject.casefold() in schema.placeholder_values:
        raise ValueError(
            f"authority subject must be a non-empty, non-placeholder string; got {subject!r}"
        )
    path = config.resolve_path("decision_log.path", clause=clause)
    try:
        records = read_decision_log(path, schema).records
    except UnicodeDecodeError as exc:
        # Keep the documented raise contract exact: an undecodable ledger is the
        # same "could not look" condition as an unreadable one, so callers can
        # catch OSError alone and still surface every evidence failure as BLOCKED.
        raise OSError(f"decision log at {path} is not valid UTF-8: {exc}") from exc
    graph_problem = _supersedes_graph_problem(records, schema, supersedes_column)
    if graph_problem is not None:
        _LOG.error(
            "decision-log supersedes graph is invalid",
            extra={"subject": normalized_subject, "problem": graph_problem},
        )
        return AuthorityDenial(
            subject=normalized_subject,
            reason=DenialReason.LOG_INVALID,
            detail=graph_problem,
        )
    superseded = _superseded_identifiers(records, schema, supersedes_column)
    candidates = [
        record for record in records if record.value(schema, subject_column) == normalized_subject
    ]
    if not candidates:
        return _denial(
            normalized_subject,
            DenialReason.NOT_FOUND,
            "no record's subject cell exactly equals the queried subject",
        )
    live = [
        record
        for record in candidates
        if record.value(schema, status_column).strip().casefold() == active_value.casefold()
        and record.value(schema, schema.identifier_column) not in superseded
    ]
    if not live:
        if any(
            record.value(schema, schema.identifier_column) in superseded for record in candidates
        ):
            return _denial(
                normalized_subject,
                DenialReason.SUPERSEDED,
                "no matching record is both active and un-superseded; at least one "
                "is named in a later record's supersedes cell",
            )
        return _denial(
            normalized_subject,
            DenialReason.INACTIVE_STATUS,
            f"no matching record carries the configured active status {active_value!r}",
        )
    if len(live) > 1:
        identifiers = ", ".join(record.value(schema, schema.identifier_column) for record in live)
        return _denial(
            normalized_subject,
            DenialReason.AMBIGUOUS,
            f"multiple live records claim this subject: {identifiers}",
        )
    identifier = live[0].value(schema, schema.identifier_column)
    if not any(re.fullmatch(pattern, identifier) for pattern in patterns):
        return _denial(
            normalized_subject,
            DenialReason.MALFORMED_ID,
            f"identifier {identifier!r} matches no configured decision-id pattern",
        )
    _LOG.info(
        "authority verified",
        extra={"subject": normalized_subject, "decision_id": identifier, "clause": clause},
    )
    return VerifiedAuthority(
        decision_id=identifier,
        subject=normalized_subject,
        clause=clause,
        _token=_CONSTRUCTION_TOKEN,
    )


def _denial(subject: str, reason: DenialReason, detail: str) -> AuthorityDenial:
    """Log and build one completed-but-unauthorized verdict."""
    _LOG.info(
        "authority denied", extra={"subject": subject, "reason": reason.value, "detail": detail}
    )
    return AuthorityDenial(subject=subject, reason=reason, detail=detail)


def _lifecycle_column(schema: DecisionLogSchema, value: object, key: str) -> str:
    """Validate a configured lifecycle column and require it in the record grammar."""
    column = _non_empty(value, key)
    if column not in schema.columns:
        raise ValueError(
            f"authority lifecycle columns must be configured columns: {column!r} "
            f"(from {key}) is not in the decision-log schema"
        )
    return column


def _identifier_patterns(config: Config, clause: str | None) -> tuple[str, ...]:
    """Read the shared decision-id grammar without inventing a second one here."""
    configured = config.require("traceability.decision_id_patterns", clause=clause)
    if (
        not isinstance(configured, list)
        or not configured
        or not all(isinstance(item, str) and item.strip() for item in configured)
    ):
        raise ValueError("traceability decision-id patterns must be non-empty strings")
    return tuple(configured)


def _non_empty(value: object, key: str) -> str:
    """Require one non-empty configured string before it changes authority semantics."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _supersedes_graph_problem(
    records: tuple[DecisionLogRecord, ...],
    schema: DecisionLogSchema,
    supersedes_column: str,
) -> str | None:
    """Return why the withdrawal graph cannot be trusted, or None when it can.

    A self reference, a reference to an id no record carries, or a reference
    cycle each make "which records are withdrawn" unanswerable. The ledger then
    authorizes nothing at all: a typo in a withdrawal must fail closed rather
    than silently leave the record it meant to kill alive.
    """
    all_ids = [record.value(schema, schema.identifier_column) for record in records]
    identifiers = set(all_ids)
    if len(identifiers) != len(all_ids):
        duplicates = sorted({name for name in identifiers if all_ids.count(name) > 1})
        return f"duplicate record id(s): {', '.join(duplicates)}"
    edges: dict[str, str] = {}
    for record in records:
        target = record.value(schema, supersedes_column).strip()
        if not target or target.casefold() in schema.placeholder_values:
            continue
        source = record.value(schema, schema.identifier_column)
        if target == source:
            return f"record {source!r} supersedes itself"
        if target not in identifiers:
            return f"record {source!r} supersedes unknown id {target!r}"
        edges[source] = target
    for start in edges:
        seen = {start}
        current = start
        while current in edges:
            current = edges[current]
            if current in seen:
                return f"supersedes references form a cycle involving {current!r}"
            seen.add(current)
    return None


def _superseded_identifiers(
    records: tuple[DecisionLogRecord, ...],
    schema: DecisionLogSchema,
    supersedes_column: str,
) -> frozenset[str]:
    """Return every id any record names in its supersedes cell."""
    return frozenset(
        target
        for record in records
        if (target := record.value(schema, supersedes_column).strip())
        and target.casefold() not in schema.placeholder_values
    )
