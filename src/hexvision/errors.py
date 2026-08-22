"""Error taxonomy for the harness.

Every failure an operator can cause has its own type, and every type carries the
governance clause it violated. A gate that fails with a bare ``ValueError`` tells
the operator that something is wrong; a gate that fails with
``FrozenKeyOverrideError`` tells them which bar they tried to lower and where the
bar is defined. The difference is whether the failure is actionable at 2am.

Exit codes are part of the contract, because CI, the pre-push hook and the
PreToolUse guard all branch on them:

==== ==========================================================================
Code Meaning
==== ==========================================================================
0    The check passed.
1    The check ran and FAILED (a real finding).
2    BLOCK — the check refused to run and must be treated as a failure. This is
     the fail-closed code: a missing scanner, an unreadable allowlist, an empty
     allowlist, or a crash. It is distinct from 1 so that "we found a problem"
     and "we could not look" are never conflated in an audit narrative.
3    Usage error — the operator invoked the tool wrongly. Never a pass.
==== ==========================================================================
"""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "ConfigError",
    "ConformanceError",
    "ExitCode",
    "FrozenKeyOverrideError",
    "GateBlockedError",
    "GateFailure",
    "HexVisionError",
    "MissingKeyError",
    "PackError",
    "UsageError",
]


class ExitCode(IntEnum):
    """Process exit codes. See the module docstring for the contract."""

    OK = 0
    FAILED = 1
    BLOCKED = 2
    USAGE = 3


class HexVisionError(Exception):
    """Base class for every harness error.

    ``exit_code`` defaults to :attr:`ExitCode.FAILED` rather than
    :attr:`ExitCode.OK`, so a subclass that forgets to declare one still fails
    the build. Defaulting to success is how fail-open bugs are born.
    """

    exit_code: ExitCode = ExitCode.FAILED

    def __init__(self, message: str, *, clause: str | None = None) -> None:
        """Record the failure message and, when known, the clause it violated.

        Args:
            message: What went wrong, phrased so the operator can act on it.
            clause: The contract clause or invariant id (for example ``INV-3``)
                this failure belongs to. Included in ``str()`` when present so
                that a log line is self-describing without the reader holding
                the contract open beside it.
        """
        self.clause = clause
        self.message = message
        super().__init__(f"[{clause}] {message}" if clause else message)


class ConfigError(HexVisionError):
    """Configuration could not be read, parsed or reconciled."""

    exit_code = ExitCode.BLOCKED


class MissingKeyError(ConfigError):
    """A required configuration key is absent from every layer.

    This is BLOCKED rather than FAILED: the harness could not determine what the
    policy is, which is not the same as determining that the policy was broken.
    """


class FrozenKeyOverrideError(ConfigError):
    """An attempt was made to override a frozen key from the environment or CLI.

    Frozen keys are quality and safety bars. Honouring a shell-level override
    would mean the bar is whatever the last invocation said it was, and would
    leave no reviewable diff behind.
    """


class PackError(HexVisionError):
    """A stack pack is missing, unloadable, or declares an invalid contract."""

    exit_code = ExitCode.BLOCKED


class GateFailure(HexVisionError):
    """A gate ran to completion and found a real problem."""

    exit_code = ExitCode.FAILED


class GateBlockedError(HexVisionError):
    """A gate could not run and therefore must not report a pass.

    Raised when a required tool is absent, an input is unreadable, or an
    allowlist is empty. The distinction from :class:`GateFailure` is the whole
    of the fail-closed policy.
    """

    exit_code = ExitCode.BLOCKED


class ConformanceError(HexVisionError):
    """A pack violates a clause of the Gate Harness Contract."""

    exit_code = ExitCode.FAILED


class UsageError(HexVisionError):
    """The operator invoked the CLI incorrectly."""

    exit_code = ExitCode.USAGE
