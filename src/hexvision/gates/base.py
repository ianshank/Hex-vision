"""The gate interface, and the runner that enforces fail-closed semantics.

A gate is a named check that takes resolved configuration and returns a
:class:`~hexvision.gates.model.GateResult`. Two properties are enforced here
rather than trusted to each implementation:

1. **An unexpected exception is a BLOCK, not a crash and not a pass.** Every gate
   runs inside :func:`run_gate`, which converts an escaped exception into a
   BLOCKED result. A traceback that reaches the operator loses the audit record;
   worse, a gate wrapped in a bare ``try/except`` at the call site could be made
   to look green.
2. **A gate declares the clause it enforces.** ``clause`` is abstract, so a gate
   cannot be written without stating what it is for. This is what lets the
   conformance suite check that every invariant has at least one gate behind it.

Gates are deliberately not given a filesystem or a subprocess helper by the base
class. Each gate takes exactly the inputs it needs from configuration, which is
what keeps them unit-testable without a repository on disk.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Final

from hexvision.config import Config
from hexvision.errors import HexVisionError
from hexvision.gates.model import Finding, GateResult, GateStatus, Severity
from hexvision.observability import get_logger, log_verdict

__all__ = ["Gate", "run_gate", "run_gates"]

_LOG: Final = get_logger(__name__)


class Gate(ABC):
    """Base class for every check the harness can run.

    Subclasses implement :meth:`name`, :meth:`clause` and :meth:`check`. They do
    not implement error handling or logging: :func:`run_gate` owns both so that
    behaviour is identical across gates and cannot be forgotten in a new one.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Target name this gate answers to.

        For a contract gate this matches the Makefile target exactly, so a log
        line and a CI step name are the same string. For a domain gate it is the
        dotted name the pack registers it under.
        """

    @property
    @abstractmethod
    def clause(self) -> str:
        """Contract clause, invariant or requirement id this gate enforces.

        Abstract on purpose: a gate that cannot name what it enforces cannot be
        traced to a requirement, and an untraceable gate is one nobody can decide
        to remove.
        """

    @property
    def description(self) -> str:
        """One-line human description. Defaults to the subclass docstring's first line."""
        doc = (type(self).__doc__ or "").strip()
        return doc.splitlines()[0] if doc else self.name

    @property
    def requires_repository(self) -> bool:
        """Whether this gate reads files from the repository tree.

        Used by the CLI to give a precise BLOCKED message when run outside a
        repository, instead of a confusing file-not-found from deep inside a gate.
        """
        return True

    @abstractmethod
    def check(self, config: Config) -> GateResult:
        """Run the check and return its result.

        Implementations must return a result for every outcome they anticipate,
        including their own fail-closed cases (a missing tool, an unreadable
        input). Raising is reserved for genuinely unanticipated states, which
        :func:`run_gate` converts into a BLOCK.
        """


def run_gate(gate: Gate, config: Config) -> GateResult:
    """Run one gate with fail-closed exception handling and verdict logging.

    Every path out of a gate produces a :class:`GateResult`:

    - The gate returns a result: used as-is, with duration recorded.
    - The gate raises a :class:`~hexvision.errors.HexVisionError`: converted to a
      result at the status its exit code implies, preserving the clause.
    - The gate raises anything else: converted to BLOCKED. Never to a pass, and
      never re-raised, because a traceback that escapes has no audit record.

    Args:
        gate: The gate to run.
        config: Resolved configuration.

    Returns:
        The gate's result, always with a ``duration_ms`` measurement.
    """
    started = time.monotonic()

    def elapsed() -> dict[str, float]:
        return {"duration_ms": round((time.monotonic() - started) * 1000, 3)}

    try:
        result = gate.check(config)
    except HexVisionError as exc:
        status = (
            GateStatus.FAILED
            if exc.exit_code == GateStatus.FAILED.exit_code
            else GateStatus.BLOCKED
        )
        _LOG.error(
            "gate raised a governance error",
            extra={"gate": gate.name, "clause": exc.clause or gate.clause, "error": str(exc)},
        )
        result = (
            GateResult.blocked(
                gate.name,
                summary=f"{gate.name} could not run",
                reason=str(exc),
                clause=exc.clause or gate.clause,
                measurements=elapsed(),
            )
            if status is GateStatus.BLOCKED
            else GateResult.failed(
                gate.name,
                summary=f"{gate.name} failed",
                clause=exc.clause or gate.clause,
                findings=(
                    _finding_from_error(gate, exc),
                ),
                measurements=elapsed(),
            )
        )
    except Exception as exc:  # noqa: BLE001 - deliberate: an escaped exception must BLOCK.
        # Broad by design. The alternative is a traceback that exits non-zero
        # with no structured record, which is indistinguishable in CI from an
        # infrastructure failure and gets retried until it passes.
        _LOG.exception("gate raised an unexpected exception", extra={"gate": gate.name})
        result = GateResult.blocked(
            gate.name,
            summary=f"{gate.name} crashed",
            reason=(
                f"unexpected {type(exc).__name__}: {exc}. This is reported as BLOCKED "
                f"rather than re-raised so the failure keeps an audit record."
            ),
            clause=gate.clause,
            remediation="Fix the gate; a crashing gate is not a passing gate.",
            measurements=elapsed(),
        )
    else:
        result = GateResult(
            gate=result.gate,
            status=result.status,
            clause=result.clause or gate.clause,
            summary=result.summary,
            findings=result.findings,
            measurements={**dict(result.measurements), **elapsed()},
        )

    log_verdict(
        _LOG,
        gate=result.gate,
        passed=result.status.is_pass,
        clause=result.clause,
        status=result.status.value,
        findings=len(result.findings),
        **{k: v for k, v in result.measurements.items() if k == "duration_ms"},
    )
    return result


def _finding_from_error(gate: Gate, exc: HexVisionError) -> Finding:
    """Build a blocking finding from a governance error raised by a gate."""
    return Finding(
        id=f"{gate.name.upper()}-ERROR",
        severity=Severity.MAJOR,
        message=exc.message,
        clause=exc.clause or gate.clause,
        disposition="Resolve the reported condition and re-run the gate.",
    )


def run_gates(gates: tuple[Gate, ...], config: Config) -> tuple[GateResult, ...]:
    """Run every gate and return all results.

    Runs all gates rather than stopping at the first failure: an operator fixing
    a robotics repository wants the full list of what is wrong in one pass, and a
    fail-fast runner hides the second finding behind the first for as many cycles
    as there are findings.
    """
    return tuple(run_gate(gate, config) for gate in gates)
