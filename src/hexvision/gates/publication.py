"""Control public publication with the shared destination policy and a recorded authority.

Release-time publication is distinct from ordinary pull-request validation: the
destination may be safe yet the organization may not have authorized a release.
This gate therefore composes the shared remote control with a decision-log check
without reimplementing URL parsing or weakening the remote allowlist.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from hexvision.config import Config
from hexvision.decision_log import (
    DecisionLogParseResult,
    DecisionLogSchema,
    load_decision_log_schema,
    read_decision_log,
)
from hexvision.errors import HexVisionError
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, GateStatus
from hexvision.observability import get_logger
from hexvision.remotes import check_remotes, normalize_remote_url

__all__ = ["PublicationGate"]

_CLAUSE: Final = "R-17"
_LOG: Final = get_logger(__name__)


class PublicationGate(Gate):
    """Permit publication only after shared destination policy and logged authority agree."""

    def __init__(self, destination: str | None = None) -> None:
        """Retain an explicit target while allowing the release target to use reviewed config."""
        self._destination = destination

    @property
    def name(self) -> str:
        """Return the release-time Makefile target name used in result output."""
        return "publication"

    @property
    def clause(self) -> str:
        """Return the authoritative requirement implemented by this control."""
        return _CLAUSE

    def check(self, config: Config) -> GateResult:
        """Evaluate destination policy before confirming a real publication authorization entry."""
        try:
            policy = _policy(config)
            destination = _destination(self._destination, policy)
        except (HexVisionError, TypeError, ValueError, re.error) as exc:
            return GateResult.blocked(
                self.name,
                summary="publication policy is unavailable",
                reason=str(exc),
                clause=self.clause,
            )

        normalized = normalize_remote_url(destination)
        remote_result = check_remotes(config, (destination,))
        measurements: dict[str, Any] = {
            "destination": normalized.destination,
            "remote_policy_status": remote_result.status.value,
        }
        if remote_result.status is GateStatus.BLOCKED:
            return GateResult.blocked(
                self.name,
                summary="publication destination policy is unavailable",
                reason=remote_result.findings[0].message,
                clause=self.clause,
                measurements=measurements,
            )
        if remote_result.status is GateStatus.FAILED:
            return GateResult.failed(
                self.name,
                summary="publication destination violates shared remote policy",
                findings=_publication_findings(remote_result.findings),
                clause=self.clause,
                measurements=measurements,
            )

        try:
            authorization = _authorization(config, policy)
        except OSError as exc:
            return GateResult.blocked(
                self.name,
                summary="publication authorization cannot be read",
                reason=f"cannot read {policy['decision_log_path']}: {exc}",
                clause=self.clause,
                measurements=measurements,
            )
        if not authorization[0]:
            return GateResult.blocked(
                self.name,
                summary="publication authorization is absent",
                reason=authorization[1],
                clause=self.clause,
                remediation=(
                    "Record a real G-PUB decision-log entry before attempting public publication."
                ),
                measurements=measurements,
            )
        _LOG.info("publication authorized", extra={"destination": normalized.destination})
        return GateResult.passed(
            self.name,
            summary="publication destination is approved and authorized",
            clause=self.clause,
            measurements=measurements,
        )


def _policy(config: Config) -> dict[str, Any]:
    """Resolve publication inputs and validate its ID with the shared decision-ID grammar."""
    policy = {
        "authorization_id": config.require("publication.authorization_id", clause=_CLAUSE),
        "decision_log_path": config.require("publication.decision_log_path", clause=_CLAUSE),
        "default_destination": config.require("publication.default_destination", clause=_CLAUSE),
        "decision_id_patterns": config.require("traceability.decision_id_patterns", clause=_CLAUSE),
        "decision_log_schema": load_decision_log_schema(config, clause=_CLAUSE),
    }
    if not all(
        isinstance(policy[key], str) and policy[key].strip()
        for key in ("authorization_id", "decision_log_path", "default_destination")
    ):
        raise ValueError(
            "publication authorization ID, decision-log path, and destination must be strings"
        )
    patterns = policy["decision_id_patterns"]
    if (
        not isinstance(patterns, list)
        or not patterns
        or not all(isinstance(item, str) for item in patterns)
    ):
        raise ValueError("traceability decision-id patterns must be non-empty strings")
    if not any(re.fullmatch(pattern, policy["authorization_id"]) for pattern in patterns):
        raise ValueError(
            "publication authorization ID must match an existing traceability decision-id pattern"
        )
    return policy


def _destination(explicit: str | None, policy: Mapping[str, Any]) -> str:
    """Select the explicit destination or the reviewed default without guessing a value."""
    destination = explicit if explicit is not None else policy["default_destination"]
    if not isinstance(destination, str):
        raise TypeError("publication destination must be a string")
    return destination


def _authorization(config: Config, policy: Mapping[str, Any]) -> tuple[bool, str]:
    """Require an actual configured record and retain why a pseudo-record was rejected."""
    path = config.root / str(policy["decision_log_path"])
    schema = policy["decision_log_schema"]
    if not isinstance(schema, DecisionLogSchema):
        raise TypeError("publication decision-log schema is invalid")
    parsed = read_decision_log(path, schema)
    authorization_id = str(policy["authorization_id"])
    if parsed.record(schema, authorization_id) is not None:
        return True, ""
    return False, _absent_authorization_reason(
        parsed, authorization_id, str(policy["decision_log_path"])
    )


def _absent_authorization_reason(
    parsed: DecisionLogParseResult, authorization_id: str, decision_log_path: str
) -> str:
    """Name an invalid candidate without treating generic explanatory prose as authorization."""
    rejection = parsed.rejection_for(authorization_id)
    if rejection is None:
        return (
            f"required publication authorization gate {authorization_id!r} "
            f"has no decision-log entry in {decision_log_path}"
        )
    return (
        f"required publication authorization gate {authorization_id!r} has no valid decision-log "
        f"entry in {decision_log_path} (line {rejection.line_number}): {rejection.reason}"
    )


def _publication_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Retain shared-policy evidence while assigning it to the publication requirement."""
    return tuple(
        Finding(
            id=f"PUB-{finding.id}",
            severity=finding.severity,
            message=finding.message,
            location=finding.location,
            clause=_CLAUSE,
            disposition=finding.disposition,
            context=finding.context,
        )
        for finding in findings
    )
