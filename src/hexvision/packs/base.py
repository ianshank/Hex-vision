"""The stack-pack interface: how a new stack or domain joins the estate.

A **pack** is the unit of modularity in Hex-vision. It answers three questions
for one stack — ROS 2 Python, PX4 C++, a Rust flight controller, a Jetson
inference service — and nothing else:

1. **How is each of the 15 contract targets invoked here?** ``lint`` means
   ``ruff check`` in one pack and ``colcon test --ament-lint`` in another. The
   name never changes; the command always does.
2. **Which domain gates does this stack add?** A Jetson pack adds model-card,
   latency-budget and determinism gates. A generic web service adds none. These
   are ordinary :class:`~hexvision.gates.base.Gate` objects, so the runner,
   result model and JSON output are shared.
3. **What does it claim to conform to?** Every pack is checked against the same
   contract clauses; a pack that cannot state its claims cannot be audited.

Packs are discovered through entry points, never through an import list in the
core. Adding a stack is installing a package — the core does not change, which is
the backwards-compatibility property that lets an estate adopt a new pack without
re-releasing the harness.

The base class supplies no default commands. A pack that forgets to map a target
fails conformance with the target named, rather than inheriting a Python command
that silently does the wrong thing in a C++ repository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hexvision.config import Config
from hexvision.gates.base import Gate

__all__ = ["Pack", "PackMeta", "TargetSpec"]


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """How one contract target is implemented in a pack.

    Attributes:
        target: One of the 15 contract target names.
        command: Argument vector, already split. A string would have to be
            re-split by a shell, and shell-splitting a command containing a path
            with a space is a class of bug this type exists to remove.
        fail_closed_on_missing_tool: Whether the absence of the underlying tool
            must fail. Defaults to ``True``: opting out is a deliberate,
            reviewable act, and the contract names the small set of gates that
            legitimately degrade instead.
        tool: Executable whose presence is probed for the fail-closed check.
            Defaults to the first element of ``command``.
        degrades_loudly: Whether the pack has a real degraded mode for this
            target that prints its own absence on stderr every run. Only
            meaningful when ``fail_closed_on_missing_tool`` is ``False``.
        rationale: Why this implementation, in one line. Required for any target
            that opts out of fail-closed, because an unexplained exception is
            indistinguishable from a mistake.
    """

    target: str
    command: tuple[str, ...]
    fail_closed_on_missing_tool: bool = True
    tool: str | None = None
    degrades_loudly: bool = False
    rationale: str | None = None

    def __post_init__(self) -> None:
        """Reject a spec that cannot be enforced or explained.

        Raises:
            ValueError: On an empty command, or on a fail-open target with no
                stated rationale.
        """
        if not self.command:
            raise ValueError(f"target {self.target!r} declares an empty command")
        if not self.fail_closed_on_missing_tool and not self.rationale:
            raise ValueError(
                f"target {self.target!r} opts out of fail-closed behaviour without a "
                f"rationale; an unexplained exception is indistinguishable from a mistake"
            )

    @property
    def probe_tool(self) -> str:
        """Executable whose presence determines the fail-closed verdict."""
        return self.tool or self.command[0]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "target": self.target,
            "command": list(self.command),
            "tool": self.probe_tool,
            "fail_closed_on_missing_tool": self.fail_closed_on_missing_tool,
            "degrades_loudly": self.degrades_loudly,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class PackMeta:
    """Static descriptive metadata for a pack."""

    name: str
    stack: str
    summary: str
    reference_docs: tuple[str, ...] = field(default_factory=tuple)


class Pack(ABC):
    """Base class for a stack pack.

    Subclasses implement :meth:`meta`, :meth:`targets` and :meth:`domain_gates`.
    Everything else — conformance checking, JSON rendering, gate execution — is
    shared, so a new pack is a declaration plus its domain gates, not a fork of
    the harness.
    """

    @property
    @abstractmethod
    def meta(self) -> PackMeta:
        """Descriptive metadata: name, stack, one-line summary, reference docs."""

    @abstractmethod
    def targets(self, config: Config) -> Mapping[str, TargetSpec]:
        """Return the target-name to implementation mapping.

        Takes ``config`` so that a pack can build its commands from configured
        values — the package manager, the test runner, the artifact roots — rather
        than embedding them. A pack with hard-coded paths is a pack that works in
        exactly one repository.

        Every one of the 15 contract targets must appear. Conformance names any
        that are missing.
        """

    @abstractmethod
    def domain_gates(self, config: Config) -> Sequence[Gate]:
        """Return the stack-specific gates this pack contributes.

        May be empty for a stack with no domain concerns. The robotics packs are
        where this earns its place: model-card completeness, inference latency
        budgets, eval determinism and mission safety-envelope bounds are checks a
        generic software harness has no reason to know about.
        """

    @property
    def name(self) -> str:
        """Short pack name used on the command line and in entry points."""
        return self.meta.name

    def describe(self, config: Config) -> dict[str, Any]:
        """Return a full JSON-serialisable description of the pack.

        Used by ``hexvision pack show`` and by the published dataset card, which
        is generated from this rather than hand-written — a hand-written pack
        table is a table that disagrees with the code within one release.
        """
        gates = self.domain_gates(config)
        return {
            "name": self.meta.name,
            "stack": self.meta.stack,
            "summary": self.meta.summary,
            "reference_docs": list(self.meta.reference_docs),
            "targets": {
                target: spec.to_dict() for target, spec in sorted(self.targets(config).items())
            },
            "domain_gates": [
                {"name": gate.name, "clause": gate.clause, "description": gate.description}
                for gate in gates
            ],
        }
