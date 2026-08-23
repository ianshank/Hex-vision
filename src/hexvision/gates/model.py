"""The result model every gate returns.

One shape for every verdict, across every stack pack and every domain gate. This
matters more than it looks: the CI job, the pre-push hook, the ``--json`` output
and the audit narrative all consume gate results, and a per-gate ad-hoc dict
means each consumer grows its own special cases until none of them agree on what
"passed" meant.

Three distinctions are encoded deliberately, because collapsing any of them is
how a governance harness becomes decorative:

**Passed vs blocked.** :attr:`GateStatus.FAILED` means the gate looked and found
a problem. :attr:`GateStatus.BLOCKED` means the gate could not look — a missing
scanner, an unreadable allowlist, an empty allowlist. Both are non-zero exits,
and neither is a pass, but an audit that cannot tell them apart cannot answer
"was this control ever actually running".

**Skipped is not a status.** There is no ``SKIPPED`` member. A gate that cannot
run is BLOCKED. The one legitimate exception — a hardware-in-the-loop gate on a
runner with no hardware — is :attr:`GateStatus.SKIPPED_DECLARED`, which requires
a decision-log entry naming it and is counted as a failure without one.

**Severity is bounded and ordered.** Findings carry a fixed severity enum, so
"Major findings block completion" is a machine-checkable statement rather than a
convention that erodes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from hexvision.authority import VerifiedAuthority, joined_decision_ids
from hexvision.errors import ExitCode

__all__ = ["Finding", "GateResult", "GateStatus", "Severity"]


class Severity(Enum):
    """Finding severity, ordered by how much it blocks.

    The ordering is explicit rather than relying on declaration order, so a
    comparison in a gate cannot be changed by reordering the members.
    """

    BLOCKER = ("Blocker", 40)
    MAJOR = ("Major", 30)
    MINOR = ("Minor", 20)
    INFO = ("Info", 10)

    def __init__(self, label: str, rank: int) -> None:
        """Store the human label and the blocking rank."""
        self.label = label
        self.rank = rank

    @property
    def blocks_completion(self) -> bool:
        """Whether a finding at this severity prevents a task being marked done.

        Major and above block. This threshold is the one place it is defined; a
        gate comparing severities by hand would let the rule drift per gate.
        """
        return self.rank >= Severity.MAJOR.rank

    @classmethod
    def from_label(cls, label: str) -> Severity:
        """Parse a severity from its label, case-insensitively.

        Raises:
            ValueError: On an unknown label. Findings arrive from documents and
                subagent output as well as code, and an unrecognised severity
                must fail loudly rather than default to ``INFO`` and disappear.
        """
        wanted = label.strip().casefold()
        for member in cls:
            if member.label.casefold() == wanted:
                return member
        valid = ", ".join(member.label for member in cls)
        raise ValueError(f"unknown severity {label!r}; expected one of: {valid}")


class GateStatus(Enum):
    """Terminal status of a gate run.

    There is deliberately no plain ``SKIPPED``. See the module docstring.
    """

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED_DECLARED = "skipped-declared"

    @property
    def exit_code(self) -> ExitCode:
        """Process exit code for this status.

        ``SKIPPED_DECLARED`` maps to :attr:`ExitCode.FAILED`, not ``OK``. The
        authorising decision-log entry is what converts it to a pass, and that
        check lives in the gate that produced it — never in this mapping, so the
        default for an unauthorised declared skip is red.
        """
        return {
            GateStatus.PASSED: ExitCode.OK,
            GateStatus.FAILED: ExitCode.FAILED,
            GateStatus.BLOCKED: ExitCode.BLOCKED,
            GateStatus.SKIPPED_DECLARED: ExitCode.FAILED,
        }[self]

    @property
    def is_pass(self) -> bool:
        """Whether this status may be reported as green."""
        return self is GateStatus.PASSED


@dataclass(frozen=True, slots=True)
class Finding:
    """A single thing wrong, addressed to whoever has to fix it.

    Attributes:
        id: Stable identifier, unique within a gate run (for example ``MC-003``).
            Stable ids let a review cycle say "the same Major finding recurred",
            which is what the fix-cycle cap counts.
        severity: How much this blocks.
        message: What is wrong, in operator-actionable terms.
        location: Where — a repository-relative path, optionally with ``:line``,
            or a dotted config key. ``None`` only when genuinely repository-wide.
        clause: Contract clause, invariant or requirement id this violates.
        disposition: What must happen for the finding to clear. A finding with no
            required disposition is a complaint, not a review output.
        context: Structured detail for machine consumers — measured values,
            thresholds, commit stamps.
    """

    id: str
    severity: Severity
    message: str
    location: str | None = None
    clause: str | None = None
    disposition: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "id": self.id,
            "severity": self.severity.label,
            "message": self.message,
            "location": self.location,
            "clause": self.clause,
            "disposition": self.disposition,
            "context": dict(self.context),
        }


_MEASUREMENT_REQUIRED_NOTE: Final = (
    "every factual claim is either mechanically measured here or absent"
)


@dataclass(frozen=True, slots=True)
class GateResult:
    """The outcome of one gate.

    Construct through :meth:`passed`, :meth:`failed`, :meth:`blocked` or
    :meth:`skipped_declared` rather than directly; the constructors keep status
    and findings consistent, which a hand-built instance does not.

    Attributes:
        gate: Target name, matching the Makefile target that invokes it.
        status: Terminal status.
        clause: The contract clause or invariant the gate enforces.
        summary: One line an operator can read in a CI log tail.
        findings: Every finding, worst first.
        measurements: Values the gate measured, for the audit trail. A gate that
            asserts a threshold was met without recording what it measured
            cannot be re-examined later.
        declared_skip_authority: Verifier-minted authority per absent runner,
            present only on declared-skip results. This is the value release
            aggregation trusts; the ``decision_id`` measurement derived from it
            is display only. Deliberately excluded from :meth:`to_dict`:
            :class:`~hexvision.authority.VerifiedAuthority` is process-local
            trust, and a JSON round-trip would launder it back into forgeable
            string data.
    """

    gate: str
    status: GateStatus
    clause: str | None
    summary: str
    findings: tuple[Finding, ...] = ()
    measurements: Mapping[str, Any] = field(default_factory=dict)
    declared_skip_authority: Mapping[str, VerifiedAuthority] | None = None

    def __post_init__(self) -> None:
        """Reject internally inconsistent results.

        A PASSED result carrying a blocking finding is the exact shape of a
        fail-open bug, so it is refused at construction rather than being
        reported and believed.
        """
        if self.status.is_pass and self.blocking_findings:
            raise ValueError(
                f"gate {self.gate!r} reported PASSED while carrying "
                f"{len(self.blocking_findings)} blocking finding(s); a passing gate "
                f"with Major+ findings is a fail-open bug, not a warning"
            )

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        """Findings at Major severity or above."""
        return tuple(f for f in self.findings if f.severity.blocks_completion)

    @property
    def exit_code(self) -> ExitCode:
        """Process exit code for this result."""
        return self.status.exit_code

    @classmethod
    def _sorted(cls, findings: Sequence[Finding]) -> tuple[Finding, ...]:
        """Return findings worst-first, ties broken by id for stable output.

        Stable ordering is what makes gate output diffable between runs; an
        unstable order turns every re-run into a spurious change.
        """
        return tuple(sorted(findings, key=lambda f: (-f.severity.rank, f.id)))

    @classmethod
    def passed(
        cls,
        gate: str,
        *,
        summary: str,
        clause: str | None = None,
        measurements: Mapping[str, Any] | None = None,
        findings: Sequence[Finding] = (),
    ) -> GateResult:
        """Build a passing result.

        Non-blocking (Minor/Info) findings are allowed on a pass — that is how a
        gate reports an observation without failing the build. Blocking findings
        are rejected by :meth:`__post_init__`.
        """
        return cls(
            gate=gate,
            status=GateStatus.PASSED,
            clause=clause,
            summary=summary,
            findings=cls._sorted(findings),
            measurements=dict(measurements or {}),
        )

    @classmethod
    def failed(
        cls,
        gate: str,
        *,
        summary: str,
        findings: Sequence[Finding],
        clause: str | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> GateResult:
        """Build a failing result.

        Raises:
            ValueError: If no findings are supplied. A failure with no finding
                gives the operator nothing to fix and cannot be reviewed.
        """
        if not findings:
            raise ValueError(
                f"gate {gate!r} failed without recording a finding; {_MEASUREMENT_REQUIRED_NOTE}"
            )
        return cls(
            gate=gate,
            status=GateStatus.FAILED,
            clause=clause,
            summary=summary,
            findings=cls._sorted(findings),
            measurements=dict(measurements or {}),
        )

    @classmethod
    def blocked(  # noqa: PLR0913 - keyword-only descriptive fields; see note below.
        cls,
        gate: str,
        *,
        summary: str,
        reason: str,
        clause: str | None = None,
        remediation: str | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> GateResult:
        """Build a BLOCKED result: the gate could not look.

        Args:
            gate: Target name.
            summary: One-line operator-facing summary.
            reason: Why the gate could not run — the missing tool, the unreadable
                file, the empty allowlist.
            clause: Clause being enforced.
            remediation: The command or action that unblocks it. Supplied
                separately from ``reason`` so the JSON consumer can surface a
                fix without string-parsing prose.
            measurements: Anything measured before the block.

        Note:
            The argument-count lint is suppressed here deliberately. Every
            parameter past ``gate`` is keyword-only, so there is no positional
            call site to confuse, and the fields exist because a BLOCKED result
            is the one an operator has to act on without further context:
            collapsing ``reason`` and ``remediation`` into one string would
            force the JSON consumer to parse prose to find the fix.
        """
        return cls(
            gate=gate,
            status=GateStatus.BLOCKED,
            clause=clause,
            summary=summary,
            findings=(
                Finding(
                    id=f"{gate.upper()}-BLOCKED",
                    severity=Severity.BLOCKER,
                    message=reason,
                    clause=clause,
                    disposition=remediation
                    or "Restore the gate's preconditions; this gate fails closed by design.",
                ),
            ),
            measurements=dict(measurements or {}),
        )

    @classmethod
    def skipped_declared(  # noqa: PLR0913 - keyword-only fields; see blocked()'s note.
        cls,
        gate: str,
        *,
        summary: str,
        reason: str,
        decision_id: str | None = None,
        authority: Mapping[str, VerifiedAuthority] | None = None,
        clause: str | None = None,
    ) -> GateResult:
        """Build a declared-skip result for a gate whose runner is absent.

        Args:
            decision_id: Display-only identifier for an absence that has NOT
                been resolved through the shared verifier. It never authorises:
                release aggregation trusts only ``authority``, so a result built
                with a bare id fails the release verdict — the PEER-REVIEW-3
                forged-string exploit. When both this and ``authority`` are
                absent the result carries a Blocker finding, because an
                unauthorised skip is the failure mode this status exists to make
                visible rather than to excuse.
            authority: Verifier-minted authority per absent runner. The
                ``decision_id`` measurement is derived from it here — the single
                reconciliation point between the typed mapping and the joined
                display string — so the two shapes can never disagree. Mutually
                exclusive with ``decision_id`` for the same reason.

        Raises:
            ValueError: If both ``decision_id`` and ``authority`` are supplied,
                or ``authority`` is an empty mapping.
            TypeError: If any ``authority`` value is not a verifier-minted
                :class:`~hexvision.authority.VerifiedAuthority`.
        """
        if authority is not None:
            if decision_id is not None:
                raise ValueError(
                    f"gate {gate!r} passed both a bare decision_id and verified "
                    "authority; pass one, never both — the display id is derived "
                    "from the authority so the two shapes cannot disagree"
                )
            if not authority:
                raise ValueError(
                    f"gate {gate!r} attached an empty authority mapping; an empty "
                    "mapping authorises nothing and must be passed as None"
                )
            fakes = sorted(
                key for key, value in authority.items() if not isinstance(value, VerifiedAuthority)
            )
            if fakes:
                raise TypeError(
                    f"gate {gate!r} attached authority that is not verifier-minted "
                    f"for: {', '.join(fakes)}"
                )
        effective_id = joined_decision_ids(authority) if authority else decision_id
        findings = (
            ()
            if effective_id
            else (
                Finding(
                    id=f"{gate.upper()}-UNDECLARED-SKIP",
                    severity=Severity.BLOCKER,
                    message=(
                        f"{reason} — and no decision-log entry authorises this absence. "
                        f"A skip with no owner is a gate that quietly stopped running."
                    ),
                    clause=clause,
                    disposition=(
                        "Log a decision naming this gate and the runner it needs, "
                        "or provide the runner."
                    ),
                ),
            )
        )
        return cls(
            gate=gate,
            status=GateStatus.SKIPPED_DECLARED,
            clause=clause,
            summary=summary,
            findings=findings,
            measurements={"decision_id": effective_id, "reason": reason},
            declared_skip_authority=dict(authority) if authority else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation for ``--json`` output."""
        return {
            "gate": self.gate,
            "status": self.status.value,
            "clause": self.clause,
            "summary": self.summary,
            "exit_code": int(self.exit_code),
            "findings": [finding.to_dict() for finding in self.findings],
            "measurements": dict(self.measurements),
        }
