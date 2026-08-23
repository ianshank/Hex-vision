"""Validate model-card provenance before an edge model is promoted.

A model artifact is executable behaviour in a safety-relevant system. This gate
requires a deliberately small, strict front-matter dialect so provenance data is
machine-checkable without treating malformed YAML as trustworthy metadata.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger
from hexvision.robotics.filesystem import trusted_regular_file

__all__ = ["ModelCard", "ModelCardGate", "load_model_cards", "parse_front_matter"]

_LOG: Final = get_logger(__name__)
_FULL_SHA: Final = re.compile(r"^[0-9a-fA-F]{40}$")
_ABBREVIATED_SHA: Final = re.compile(r"^[0-9a-fA-F]+$")
_MIN_QUOTED_SCALAR_LENGTH: Final = 2


@dataclass(frozen=True, slots=True)
class ModelCard:
    """A parsed card with its source path.

    Keeping the source path next to the metadata lets sibling gates reuse this
    documented loading interface without independently inventing card discovery
    and thereby disagreeing about which deployed model they checked.
    """

    path: Path
    fields: Mapping[str, object]


def parse_front_matter(text: str) -> dict[str, object]:
    """Parse the supported YAML-style front matter without guessing at YAML.

    The subset accepts top-level ``key: scalar`` pairs and indented scalar lists.
    Rejecting anchors, nested maps and malformed quoting is intentional: a card
    that cannot be parsed exactly is not evidence of model provenance.

    Raises:
        ValueError: If delimiters, indentation, keys, or scalar syntax are not
            in the strict portable subset.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("model card must begin with a front-matter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("model card front matter has no closing delimiter") from exc

    parsed: dict[str, object] = {}
    active_list: list[object] | None = None
    active_key: str | None = None
    key_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    for line_number, raw_line in enumerate(lines[1:end], 2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith((" ", "\t")):
            stripped = raw_line.strip()
            if active_list is None or not stripped.startswith("- "):
                raise ValueError(f"unsupported indentation at model card line {line_number}")
            active_list.append(_parse_scalar(stripped[2:], line_number))
            continue
        active_list = None
        active_key = None
        if ":" not in raw_line:
            raise ValueError(f"missing ':' at model card line {line_number}")
        key, raw_value = raw_line.split(":", 1)
        if not key_pattern.fullmatch(key):
            raise ValueError(f"invalid front-matter key {key!r} at line {line_number}")
        if key in parsed:
            raise ValueError(f"duplicate front-matter key {key!r} at line {line_number}")
        value = raw_value.strip()
        if not value:
            active_key = key
            active_list = []
            parsed[key] = active_list
            continue
        parsed[key] = _parse_scalar(value, line_number)
    if active_key is not None and not parsed[active_key]:
        raise ValueError(f"empty list value for {active_key!r}")
    return parsed


def _parse_scalar(value: str, line_number: int) -> object:
    """Parse an intentionally limited scalar while rejecting ambiguous YAML."""
    if value.startswith(("&", "*", "{", "|", ">")):
        raise ValueError(f"unsupported YAML construct at model card line {line_number}")
    if value.startswith(("'", '"')):
        quote = value[0]
        if len(value) < _MIN_QUOTED_SCALAR_LENGTH or not value.endswith(quote):
            raise ValueError(f"unclosed quoted scalar at model card line {line_number}")
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        contents = value[1:-1].strip()
        if not contents:
            return []
        return [_parse_scalar(item.strip(), line_number) for item in contents.split(",")]
    if value.startswith("[") or value.endswith("]") or ": " in value:
        raise ValueError(f"unsupported scalar syntax at model card line {line_number}")
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return (
            float(value) if any(marker in value.casefold() for marker in (".", "e")) else int(value)
        )
    except ValueError:
        return value


def load_model_cards(config: Config) -> tuple[ModelCard, ...]:
    """Load all configured cards through the package's shared card interface.

    A sibling gate uses this rather than its own glob and parser so latency and
    determinism assess the same set of models that provenance assessed.

    Raises:
        ValueError: If configured cards cannot be read or parsed.
    """
    card_glob = str(config.require("robotics.model_card.card_glob", clause="R-MC"))
    try:
        paths = tuple(sorted(config.root.glob(card_glob)))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot expand configured model-card glob {card_glob!r}: {exc}") from exc
    cards: list[ModelCard] = []
    for path in paths:
        if not path.is_file():
            continue
        trusted_regular_file(config.root, path, "model card")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read model card {path}: {exc}") from exc
        try:
            fields = parse_front_matter(text)
        except ValueError as exc:
            raise ValueError(f"cannot parse model card {path}: {exc}") from exc
        cards.append(ModelCard(path=path, fields=fields))
    _LOG.info("model cards loaded", extra={"count": len(cards), "glob": card_glob})
    return tuple(cards)


def _nonempty(value: object) -> bool:
    """Return whether a metadata value records an actual declared value."""
    return value is not None and (not isinstance(value, str) or bool(value.strip())) and value != []


def _location(root: Path, path: Path) -> str:
    """Make finding locations portable by reporting paths relative to the repository."""
    return str(path.relative_to(root))


class ModelCardGate(Gate):
    """Require complete and paired provenance for every deployed model artifact."""

    @property
    def name(self) -> str:
        """Return the stable robotics gate name used in audit output."""
        return "model-card"

    @property
    def clause(self) -> str:
        """Return the provenance clause this check implements."""
        return "R-MC"

    def check(self, config: Config) -> GateResult:
        """Validate configured cards and their artifact-to-card correspondence."""
        try:
            cards = load_model_cards(config)
            artifact_paths = self._artifact_paths(config)
            required_fields = _strings(
                config.require("robotics.model_card.required_fields", clause=self.clause)
            )
            allowed_precisions = set(
                _strings(
                    config.require("robotics.model_card.allowed_precisions", clause=self.clause)
                )
            )
            allowed_runtimes = set(
                _strings(config.require("robotics.model_card.allowed_runtimes", clause=self.clause))
            )
            policy = _field_policy(config, self.clause)
        except (OSError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="model-card provenance could not be read",
                reason=str(exc),
                clause=self.clause,
            )

        findings: list[Finding] = []
        artifact_field = policy["artifact_field"]
        for index, card in enumerate(cards, 1):
            findings.extend(
                self._card_findings(
                    card,
                    index,
                    required_fields,
                    allowed_precisions,
                    allowed_runtimes,
                    policy,
                )
            )

        declared_artifacts = {
            config.root / str(card.fields[artifact_field])
            for card in cards
            if _nonempty(card.fields.get(artifact_field))
        }
        for index, artifact in enumerate(sorted(artifact_paths - declared_artifacts), 1):
            findings.append(
                _finding(
                    f"MC-ARTIFACT-{index}",
                    Severity.BLOCKER,
                    f"artifact {_location(config.root, artifact)} has no corresponding model card",
                    _location(config.root, artifact),
                    self.clause,
                    "Add a reviewed card that names this artifact path.",
                )
            )
        for index, artifact in enumerate(sorted(declared_artifacts - artifact_paths), 1):
            findings.append(
                _finding(
                    f"MC-ORPHAN-{index}",
                    Severity.BLOCKER,
                    f"model card declares artifact {_location(config.root, artifact)} "
                    "that is not present",
                    _location(config.root, artifact),
                    self.clause,
                    "Restore the artifact or correct the reviewed artifact path.",
                )
            )
        measurements = {"cards": len(cards), "artifacts": len(artifact_paths)}
        if findings:
            return GateResult.failed(
                self.name,
                summary="model-card provenance findings require attention",
                findings=findings,
                clause=self.clause,
                measurements=measurements,
            )
        return GateResult.passed(
            self.name,
            summary="all configured model artifacts have complete reviewed cards",
            clause=self.clause,
            measurements=measurements,
        )

    def _artifact_paths(self, config: Config) -> set[Path]:
        """Discover only configured artifact patterns, never guessed file extensions."""
        patterns = _strings(
            config.require("robotics.model_card.artifact_globs", clause=self.clause)
        )
        roots = _strings(config.require("robotics.artifact_roots", clause=self.clause))
        artifacts: set[Path] = set()
        for root in roots:
            for pattern in patterns:
                try:
                    artifacts.update(
                        trusted_regular_file(config.root, path, "model artifact")
                        for path in (config.root / root).glob(pattern)
                        if path.is_file()
                    )
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        f"cannot expand configured artifact glob {pattern!r} under {root!r}: {exc}"
                    ) from exc
        return artifacts

    def _card_findings(  # noqa: PLR0913 - inputs are separate reviewed card-policy dimensions.
        self,
        card: ModelCard,
        index: int,
        required_fields: Sequence[str],
        allowed_precisions: set[str],
        allowed_runtimes: set[str],
        policy: Mapping[str, str],
    ) -> list[Finding]:
        """Produce all field findings for one card so a reviewer fixes it in one cycle."""
        location = str(card.path)
        findings: list[Finding] = []
        for field in required_fields:
            if not _nonempty(card.fields.get(field)):
                severity = (
                    Severity.BLOCKER
                    if field == policy["provenance_license_field"]
                    else Severity.MAJOR
                )
                findings.append(
                    _finding(
                        f"MC-{index}-{field.upper()}",
                        severity,
                        f"required model-card field {field!r} is absent or empty",
                        location,
                        self.clause,
                        "Record the reviewed provenance value in the model card.",
                    )
                )
        precision = card.fields.get(policy["precision_field"])
        if _nonempty(precision) and str(precision) not in allowed_precisions:
            findings.append(
                _finding(
                    f"MC-{index}-PRECISION",
                    Severity.MAJOR,
                    "model precision is not an allowed precision",
                    location,
                    self.clause,
                    "Use a configured precision or update the reviewed allowlist.",
                )
            )
        runtime = card.fields.get(policy["runtime_field"])
        if _nonempty(runtime) and str(runtime) not in allowed_runtimes:
            findings.append(
                _finding(
                    f"MC-{index}-RUNTIME",
                    Severity.MAJOR,
                    "target runtime is not an allowed runtime",
                    location,
                    self.clause,
                    "Use a configured runtime or add its reviewed budget.",
                )
            )
        commit = card.fields.get(policy["provenance_commit_field"])
        if _nonempty(commit) and not _FULL_SHA.fullmatch(str(commit)):
            severity = Severity.MINOR if _ABBREVIATED_SHA.fullmatch(str(commit)) else Severity.MAJOR
            findings.append(
                _finding(
                    f"MC-{index}-COMMIT",
                    severity,
                    f"{policy['provenance_commit_field']} is not a full 40-hex commit SHA",
                    location,
                    self.clause,
                    "Record the immutable full training commit SHA.",
                )
            )
        eval_value_field = policy["eval_value_field"]
        if _nonempty(card.fields.get(eval_value_field)) and not _number(
            card.fields[eval_value_field]
        ):
            findings.append(
                _finding(
                    f"MC-{index}-EVAL-VALUE",
                    Severity.MAJOR,
                    f"{eval_value_field} is not numeric",
                    location,
                    self.clause,
                    "Record a numeric evaluation result.",
                )
            )
        failure_modes_field = policy["failure_modes_field"]
        if not _nonempty(card.fields.get(failure_modes_field)):
            findings.append(
                _finding(
                    f"MC-{index}-FAILURE-MODES",
                    Severity.MAJOR,
                    f"{failure_modes_field} must state what was assessed, including "
                    "'None known' when appropriate",
                    location,
                    self.clause,
                    "Record known failure modes or explicitly state None known.",
                )
            )
        artifact = card.fields.get(policy["artifact_field"])
        if _nonempty(artifact) and not isinstance(artifact, str):
            findings.append(
                _finding(
                    f"MC-{index}-ARTIFACT",
                    Severity.MAJOR,
                    "artifact path must be a string",
                    location,
                    self.clause,
                    "Record the repository-relative artifact path as text.",
                )
            )
        return findings


def _strings(value: object) -> tuple[str, ...]:
    """Convert a configured list to strings while making malformed policy visible."""
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError("configured policy list must contain non-empty strings")
    return tuple(value)


def _field_policy(config: Config, clause: str) -> dict[str, str]:
    """Read retargetable card schema identities from reviewed configuration."""
    keys = {
        "artifact_field": "robotics.model_card.artifact_field",
        "model_name_field": "robotics.model_card.model_name_field",
        "precision_field": "robotics.model_card.precision_field",
        "runtime_field": "robotics.model_card.runtime_field",
        "device_field": "robotics.model_card.device_field",
        "provenance_license_field": "robotics.model_card.provenance_license_field",
        "provenance_commit_field": "robotics.model_card.provenance_commit_field",
        "eval_value_field": "robotics.model_card.eval_value_field",
        "failure_modes_field": "robotics.model_card.failure_modes_field",
    }
    policy = {name: config.require(key, clause=clause) for name, key in keys.items()}
    if not all(isinstance(value, str) and value for value in policy.values()):
        raise ValueError("model-card field identities must be non-empty strings")
    return {name: str(value) for name, value in policy.items()}


def _number(value: object) -> bool:
    """Accept finite numeric metadata while excluding booleans, which are integers in Python."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _finding(  # noqa: PLR0913 - Finding fields stay explicit for audit readability.
    identifier: str,
    severity: Severity,
    message: str,
    location: str,
    clause: str,
    disposition: str,
) -> Finding:
    """Create consistently actionable model-card findings."""
    return Finding(
        id=identifier,
        severity=severity,
        message=message,
        location=location,
        clause=clause,
        disposition=disposition,
    )
