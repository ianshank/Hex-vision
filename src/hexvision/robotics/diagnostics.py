"""Safe, bounded diagnostics for robotics evidence commands.

External evidence runners frequently put the useful error on stderr.  Keeping a
small, redacted excerpt makes a blocked gate actionable without turning its
findings or structured logs into a secret sink.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


def diagnostic_policy(config: Any, clause: str) -> dict[str, Any]:
    """Resolve and validate the shared external-command diagnostic policy."""
    keys = {
        "excerpt_max_chars": "robotics.diagnostics.stderr_excerpt_max_chars",
        "secret_patterns": "robotics.diagnostics.secret_patterns",
        "redaction": "robotics.diagnostics.redaction",
        "encoding": "robotics.diagnostics.command_encoding",
        "decode_errors": "robotics.diagnostics.command_decode_errors",
    }
    policy = {name: config.require(key, clause=clause) for name, key in keys.items()}
    if not isinstance(policy["excerpt_max_chars"], int) or policy["excerpt_max_chars"] < 1:
        raise ValueError("stderr diagnostic excerpt length must be a positive integer")
    if (
        not isinstance(policy["secret_patterns"], list)
        or not policy["secret_patterns"]
        or not all(isinstance(pattern, str) and pattern for pattern in policy["secret_patterns"])
    ):
        raise ValueError("diagnostic secret patterns must be non-empty strings")
    if not isinstance(policy["redaction"], str) or not policy["redaction"]:
        raise ValueError("diagnostic redaction marker must be a non-empty string")
    if not isinstance(policy["encoding"], str) or not policy["encoding"]:
        raise ValueError("external-command encoding must be a non-empty string")
    if not isinstance(policy["decode_errors"], str) or not policy["decode_errors"]:
        raise ValueError("external-command decode error policy must be a non-empty string")
    try:
        tuple(re.compile(pattern) for pattern in policy["secret_patterns"])
    except re.error as exc:
        raise ValueError(f"diagnostic secret pattern is invalid: {exc}") from exc
    return policy


def redacted_excerpt(value: object, policy: Mapping[str, Any]) -> str:
    """Return a bounded secret-redacted diagnostic string."""
    excerpt = str(value)
    for pattern in policy["secret_patterns"]:
        excerpt = re.sub(str(pattern), str(policy["redaction"]), excerpt)
    return excerpt[: int(policy["excerpt_max_chars"])]


def command_identity(command: Sequence[object], policy: Mapping[str, Any]) -> str:
    """Return the configured command identity without exposing secret-like arguments."""
    return redacted_excerpt(" ".join(str(part) for part in command), policy)
