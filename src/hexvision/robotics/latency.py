"""Enforce device-specific inference latency budgets from reviewed model cards.

Recording the percentile, device and headroom together prevents a nominally fast
model on one Jetson SKU from being represented as safe for every deployment.
"""

from __future__ import annotations

import math
from typing import Any, Final, TypeGuard

from hexvision.config import Config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger
from hexvision.robotics.model_card import ModelCard, load_model_cards

__all__ = ["LatencyBudgetGate"]

_LOG: Final = get_logger(__name__)


class LatencyBudgetGate(Gate):
    """Compare every reviewed model's stated percentile latency to its runtime budget."""

    @property
    def name(self) -> str:
        """Return the stable latency gate name used in audit output."""
        return "latency-budget"

    @property
    def clause(self) -> str:
        """Return the runtime-performance clause this check implements."""
        return "R-LAT"

    def check(self, config: Config) -> GateResult:
        """Check configured cards and record headroom for every comparable model."""
        try:
            cards = load_model_cards(config)
        except ValueError as exc:
            return GateResult.blocked(
                self.name,
                summary="latency inputs could not be read",
                reason=str(exc),
                clause=self.clause,
            )
        try:
            measurement_field = str(
                config.require("robotics.latency.measurement_field", clause=self.clause)
            )
            percentile_field = str(
                config.require("robotics.latency.percentile_field", clause=self.clause)
            )
            expected_percentile = config.require("robotics.latency.percentile", clause=self.clause)
            budgets = config.section("robotics.latency.budgets")
            unit = str(config.require("robotics.latency.unit", clause=self.clause))
            runtime_field = str(
                config.require("robotics.latency.runtime_field", clause=self.clause)
            )
            device_field = str(config.require("robotics.latency.device_field", clause=self.clause))
        except (TypeError, ValueError) as exc:
            return GateResult.blocked(
                self.name,
                summary="latency policy is not usable",
                reason=str(exc),
                clause=self.clause,
            )
        if not _numeric(expected_percentile):
            return GateResult.blocked(
                self.name,
                summary="latency policy is not usable",
                reason="configured latency percentile must be numeric",
                clause=self.clause,
            )

        findings: list[Finding] = []
        headroom: dict[str, float] = {}
        for index, card in enumerate(cards, 1):
            card_findings, card_headroom = self._check_card(
                card,
                index,
                measurement_field,
                percentile_field,
                float(expected_percentile),
                budgets,
                unit,
                runtime_field,
                device_field,
                config.root,
            )
            findings.extend(card_findings)
            if card_headroom is not None:
                headroom[str(card.path.relative_to(config.root))] = card_headroom
        measurements: dict[str, Any] = {"headroom": headroom, "unit": unit, "models": len(cards)}
        _LOG.info(
            "latency budgets assessed", extra={"models": len(cards), "findings": len(findings)}
        )
        if findings:
            return GateResult.failed(
                self.name,
                summary="one or more model latency budgets were not satisfied",
                findings=findings,
                clause=self.clause,
                measurements=measurements,
            )
        return GateResult.passed(
            self.name,
            summary="all model latency measurements meet their configured budgets",
            clause=self.clause,
            measurements=measurements,
        )

    def _check_card(  # noqa: PLR0913 - card and each configured policy value remain explicit.
        self,
        card: ModelCard,
        index: int,
        measurement_field: str,
        percentile_field: str,
        expected_percentile: float,
        budgets: dict[str, Any],
        unit: str,
        runtime_field: str,
        device_field: str,
        root: Any,
    ) -> tuple[list[Finding], float | None]:
        """Validate one card while preserving headroom even for an over-budget result."""
        location = str(card.path.relative_to(root))
        runtime = card.fields.get(runtime_field)
        device = card.fields.get(device_field)
        measured = card.fields.get(measurement_field)
        recorded_percentile = card.fields.get(percentile_field)
        label = f"{runtime or 'unknown runtime'} on {device or 'unknown device'}"
        if not _numeric(measured):
            return [
                _finding(
                    f"LAT-{index}-MEASUREMENT",
                    Severity.BLOCKER,
                    f"{label} has no numeric {measurement_field} measurement",
                    location,
                    self.clause,
                    "Record the measured latency in the reviewed model card.",
                )
            ], None
        if not _numeric(recorded_percentile) or float(recorded_percentile) != expected_percentile:
            return [
                _finding(
                    f"LAT-{index}-PERCENTILE",
                    Severity.BLOCKER,
                    f"{label} has no matching recorded latency percentile",
                    location,
                    self.clause,
                    "Record the configured percentile beside the latency measurement.",
                )
            ], None
        budget = budgets.get(str(runtime))
        if not _numeric(budget):
            return [
                _finding(
                    f"LAT-{index}-BUDGET",
                    Severity.BLOCKER,
                    f"{label} has no configured latency budget",
                    location,
                    self.clause,
                    "Add a reviewed runtime budget before promoting this model.",
                )
            ], None
        numeric_measured = float(measured)
        numeric_budget = float(budget)
        if not math.isfinite(numeric_measured) or not math.isfinite(numeric_budget):
            return [
                _finding(
                    f"LAT-{index}-FINITE",
                    Severity.BLOCKER,
                    f"{label} has a non-finite latency measurement or budget",
                    location,
                    self.clause,
                    "Record finite numeric latency values.",
                )
            ], None
        remaining = numeric_budget - numeric_measured
        if remaining < 0:
            return [
                _finding(
                    f"LAT-{index}-OVER",
                    Severity.MAJOR,
                    f"{label} exceeds its latency budget by {abs(remaining)} {unit}",
                    location,
                    self.clause,
                    "Optimise the model or approve a changed budget through configuration review.",
                )
            ], remaining
        return [], remaining


def _numeric(value: Any) -> TypeGuard[int | float]:
    """Identify numeric policy values without allowing boolean metadata to pass as a number."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _finding(  # noqa: PLR0913 - Finding fields stay explicit for audit readability.
    identifier: str,
    severity: Severity,
    message: str,
    location: str,
    clause: str,
    disposition: str,
) -> Finding:
    """Create a consistent, device-actionable latency finding."""
    return Finding(
        id=identifier,
        severity=severity,
        message=message,
        location=location,
        clause=clause,
        disposition=disposition,
    )
