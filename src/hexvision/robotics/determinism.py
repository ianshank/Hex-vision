"""Verify repeatable evaluation records for perception models.

A matching metric from differently seeded runs is evidence of coincidence, not
of determinism. The gate therefore validates both the observed metric spread and
identical recorded seeds before treating evaluation as reproducible.
"""

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger
from hexvision.robotics.filesystem import trusted_regular_file
from hexvision.robotics.model_card import load_model_cards

__all__ = ["DeterminismGate"]

_LOG: Final = get_logger(__name__)


class DeterminismGate(Gate):
    """Require identically seeded, low-spread evaluation records for every model card.

    Eval-run record schema (JSON or TOML): a top-level configured schema-version
    field, configured model-name field, and configured list-of-runs field. Each
    run contains the configured metric field and every configured seed field.
    The schema is versioned so record readers do not silently reinterpret old
    evidence when new metadata is added.
    """

    @property
    def name(self) -> str:
        """Return the stable determinism gate name used in audit output."""
        return "determinism"

    @property
    def clause(self) -> str:
        """Return the reproducibility clause this check implements."""
        return "R-DET"

    def check(self, config: Config) -> GateResult:
        """Parse and assess every configured evaluation record, failing closed on absence."""
        try:
            policy = _policy(config, self.clause)
            records = self._records(config, policy["record_globs"], policy["toml_suffix"])
            cards = load_model_cards(config)
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            tomllib.TOMLDecodeError,
        ) as exc:
            return GateResult.blocked(
                self.name,
                summary="determinism evidence could not be read",
                reason=str(exc),
                clause=self.clause,
            )
        record_by_model: dict[str, tuple[Path, Mapping[str, Any]]] = {}
        for path, record in records:
            model_name = record.get(policy["model_name_field"])
            if not isinstance(model_name, str) or not model_name:
                return GateResult.blocked(
                    self.name,
                    summary="determinism record has no usable model name",
                    reason=(
                        f"{path} omits configured model-name field {policy['model_name_field']!r}"
                    ),
                    clause=self.clause,
                )
            if model_name in record_by_model:
                return GateResult.blocked(
                    self.name,
                    summary="determinism records are ambiguous",
                    reason=f"multiple evaluation records name model {model_name!r}",
                    clause=self.clause,
                )
            record_by_model[model_name] = (path, record)

        findings: list[Finding] = []
        spreads: dict[str, float] = {}
        for index, card in enumerate(cards, 1):
            model_name = card.fields.get(policy["card_model_name_field"])
            if not isinstance(model_name, str) or model_name not in record_by_model:
                return GateResult.blocked(
                    self.name,
                    summary="a model has no evaluation-run record",
                    reason=f"model card {card.path} has no matching configured eval-run record",
                    clause=self.clause,
                )
            path, record = record_by_model[model_name]
            record_findings, spread = self._check_record(record, path, index, policy, config.root)
            findings.extend(record_findings)
            if spread is not None:
                spreads[model_name] = spread
        measurements: dict[str, Any] = {
            "spread": spreads,
            "records": len(records),
            "models": len(cards),
        }
        _LOG.info(
            "determinism records assessed",
            extra={"records": len(records), "findings": len(findings)},
        )
        if findings:
            return GateResult.failed(
                self.name,
                summary="evaluation-run records are not deterministic",
                findings=findings,
                clause=self.clause,
                measurements=measurements,
            )
        return GateResult.passed(
            self.name,
            summary="all evaluation runs use identical seeds and agree within tolerance",
            clause=self.clause,
            measurements=measurements,
        )

    def _records(
        self, config: Config, globs: tuple[str, ...], toml_suffix: str
    ) -> tuple[tuple[Path, Mapping[str, Any]], ...]:
        """Read configured JSON/TOML records, rejecting extensions not declared by policy."""
        paths: set[Path] = set()
        for pattern in globs:
            paths.update(path for path in config.root.glob(pattern) if path.is_file())
        records: list[tuple[Path, Mapping[str, Any]]] = []
        for path in sorted(paths):
            try:
                trusted_regular_file(config.root, path, "evaluation record")
                if path.suffix == toml_suffix:
                    with path.open("rb") as handle:
                        document = tomllib.load(handle)
                else:
                    document = json.loads(path.read_text(encoding="utf-8"))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                tomllib.TOMLDecodeError,
            ) as exc:
                raise ValueError(f"cannot parse evaluation record {path}: {exc}") from exc
            if not isinstance(document, Mapping):
                raise TypeError(f"evaluation record {path} must contain a top-level object")
            records.append((path, document))
        return tuple(records)

    def _check_record(
        self,
        record: Mapping[str, Any],
        path: Path,
        index: int,
        policy: Mapping[str, Any],
        root: Path,
    ) -> tuple[list[Finding], float | None]:
        """Validate one versioned run record and distinguish missing evidence from a bad result."""
        location = str(path.relative_to(root))
        if record.get(policy["schema_version_field"]) != policy["schema_version"]:
            return [
                _finding(
                    f"DET-{index}-SCHEMA",
                    Severity.BLOCKER,
                    "evaluation-run record schema version is unsupported",
                    location,
                    self.clause,
                    "Write the record using the configured schema version.",
                )
            ], None
        runs = record.get(policy["runs_field"])
        if not isinstance(runs, list) or len(runs) < policy["required_runs"]:
            return [
                _finding(
                    f"DET-{index}-RUNS",
                    Severity.BLOCKER,
                    "evaluation-run record has fewer than the required runs",
                    location,
                    self.clause,
                    "Record the configured number of completed evaluation runs.",
                )
            ], None
        if not all(isinstance(run, Mapping) for run in runs):
            return [
                _finding(
                    f"DET-{index}-RUN-SHAPE",
                    Severity.BLOCKER,
                    "evaluation-run entries must be objects",
                    location,
                    self.clause,
                    "Record each evaluation run as a structured object.",
                )
            ], None
        metrics = [run.get(policy["metric_field"]) for run in runs]
        if not all(_numeric(metric) for metric in metrics):
            return [
                _finding(
                    f"DET-{index}-METRIC",
                    Severity.BLOCKER,
                    "every evaluation run needs a finite numeric metric",
                    location,
                    self.clause,
                    "Record a finite numeric metric for every run.",
                )
            ], None
        values = [float(metric) for metric in metrics]
        if not all(math.isfinite(metric) for metric in values):
            return [
                _finding(
                    f"DET-{index}-FINITE",
                    Severity.BLOCKER,
                    "evaluation metrics must be finite",
                    location,
                    self.clause,
                    "Record finite numeric metrics for every run.",
                )
            ], None
        spread = max(values) - min(values)
        findings: list[Finding] = []
        if spread > policy["metric_tolerance"]:
            findings.append(
                _finding(
                    f"DET-{index}-SPREAD",
                    Severity.MAJOR,
                    f"evaluation metric spread {spread} exceeds the configured tolerance",
                    location,
                    self.clause,
                    "Investigate nondeterminism or record an approved tolerance change.",
                )
            )
        for seed_field in policy["seed_fields"]:
            seeds = [run.get(seed_field) for run in runs]
            if any(seed is None or seed == "" for seed in seeds):
                findings.append(
                    _finding(
                        f"DET-{index}-{seed_field.upper()}-MISSING",
                        Severity.BLOCKER,
                        f"every run must record seed field {seed_field!r}",
                        location,
                        self.clause,
                        "Record the seed used by every evaluation run.",
                    )
                )
            elif any(seed != seeds[0] for seed in seeds[1:]):
                findings.append(
                    _finding(
                        f"DET-{index}-{seed_field.upper()}-DIFFERS",
                        Severity.BLOCKER,
                        f"seed field {seed_field!r} differs across runs",
                        location,
                        self.clause,
                        "Use and record the identical seed for every determinism run.",
                    )
                )
        return findings, spread


def _policy(config: Config, clause: str) -> dict[str, Any]:
    """Read all variable determinism policy from config, never from source literals."""
    keys = {
        "record_globs": "robotics.determinism.record_globs",
        "toml_suffix": "robotics.determinism.toml_suffix",
        "schema_version_field": "robotics.determinism.schema_version_field",
        "schema_version": "robotics.determinism.schema_version",
        "model_name_field": "robotics.determinism.model_name_field",
        "card_model_name_field": "robotics.model_card.model_name_field",
        "runs_field": "robotics.determinism.runs_field",
        "metric_field": "robotics.determinism.metric_field",
        "required_runs": "robotics.determinism.required_runs",
        "metric_tolerance": "robotics.determinism.metric_tolerance",
        "seed_fields": "robotics.determinism.seed_fields",
    }
    policy = {name: config.require(key, clause=clause) for name, key in keys.items()}
    if (
        not isinstance(policy["record_globs"], list)
        or not policy["record_globs"]
        or not all(isinstance(glob, str) and glob for glob in policy["record_globs"])
    ):
        raise ValueError("determinism record globs must be non-empty strings")
    if (
        not isinstance(policy["seed_fields"], list)
        or not policy["seed_fields"]
        or not all(isinstance(field, str) and field for field in policy["seed_fields"])
    ):
        raise ValueError("determinism seed fields must be non-empty strings")
    if not isinstance(policy["required_runs"], int) or policy["required_runs"] < 1:
        raise ValueError("determinism required runs must be a positive integer")
    if not _numeric(policy["metric_tolerance"]) or float(policy["metric_tolerance"]) < 0:
        raise ValueError("determinism tolerance must be a non-negative number")
    return policy


def _numeric(value: Any) -> bool:
    """Identify numeric metrics without accepting booleans as integer values."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _finding(  # noqa: PLR0913 - Finding fields stay explicit for audit readability.
    identifier: str,
    severity: Severity,
    message: str,
    location: str,
    clause: str,
    disposition: str,
) -> Finding:
    """Create a consistently actionable determinism finding."""
    return Finding(
        id=identifier,
        severity=severity,
        message=message,
        location=location,
        clause=clause,
        disposition=disposition,
    )
