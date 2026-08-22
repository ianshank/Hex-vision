"""Structured logging for the harness (module named `observability` deliberately:
 a package-local `logging.py` shadows the stdlib module name for readers and trips
 ruff A005, so the name states its role instead).

Two rules drive this module:

1. **A gate result must be reconstructable from the log alone.** When a build
   goes red three weeks later in an audit, the log is the only artifact left, so
   every gate emits its inputs, its verdict and the clause it was enforcing.
2. **The log is machine-readable on demand.** ``--json`` output goes to stdout
   for CI to parse; diagnostics go to stderr so that piping stdout into ``jq``
   never mixes the two. Any module that prints a diagnostic to stdout breaks the
   ``--json`` contract, so nothing here writes to stdout.

Verbosity is resolved from configuration and the environment rather than being
fixed in code, and the level name is validated so that a typo produces an error
instead of silently falling back to a level that hides findings.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from typing import Any, Final

__all__ = ["JsonFormatter", "configure_logging", "get_logger", "log_verdict"]

LOGGER_ROOT: Final = "hexvision"
_LEVEL_ENV_VAR: Final = "HEXVISION_LOG_LEVEL"
_FORMAT_ENV_VAR: Final = "HEXVISION_LOG_FORMAT"
_DEFAULT_LEVEL: Final = "INFO"
_DEFAULT_FORMAT: Final = "text"
_VALID_FORMATS: Final = frozenset({"text", "json"})
# Reserved LogRecord attributes; anything outside this set that a caller passes
# through `extra=` is treated as structured context and included in JSON output.
_RECORD_RESERVED: Final = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | frozenset({"message", "asctime", "taskName"})


class JsonFormatter(logging.Formatter):
    """Render a record as a single-line JSON object.

    Structured context passed via ``extra=`` is merged into the object rather
    than being interpolated into the message, so a downstream query can filter
    on ``clause`` or ``gate`` without parsing prose.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as compact JSON, including any extra context."""
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RECORD_RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str` rather than failing: a log call must never be the thing
        # that crashes a gate because a value was not JSON-serialisable.
        return json.dumps(payload, default=str, sort_keys=True)


def _resolve(env: Mapping[str, str], var: str, configured: str | None, fallback: str) -> str:
    """Resolve a setting from the environment, then configuration, then default.

    The environment wins for logging only. Verbosity is an observability choice,
    not a quality bar, so unlike the frozen configuration keys it is deliberately
    operator-controllable at run time.
    """
    value = env.get(var) or configured or fallback
    return value.strip()


def configure_logging(
    *,
    level: str | None = None,
    fmt: str | None = None,
    env: Mapping[str, str] | None = None,
    stream: Any | None = None,
) -> logging.Logger:
    """Configure and return the harness root logger.

    Args:
        level: Level name from configuration. Overridden by ``HEXVISION_LOG_LEVEL``.
        fmt: ``"text"`` or ``"json"``. Overridden by ``HEXVISION_LOG_FORMAT``.
        env: Environment mapping; injected so tests never mutate ``os.environ``.
        stream: Destination stream. Defaults to ``sys.stderr`` — never stdout,
            which belongs to ``--json`` gate output.

    Returns:
        The configured ``hexvision`` logger.

    Raises:
        ValueError: If the level or format name is not recognised. A typo'd
            level must not silently resolve to one that hides findings.
    """
    resolved_env = os.environ if env is None else env
    level_name = _resolve(resolved_env, _LEVEL_ENV_VAR, level, _DEFAULT_LEVEL).upper()
    format_name = _resolve(resolved_env, _FORMAT_ENV_VAR, fmt, _DEFAULT_FORMAT).lower()

    if level_name not in logging.getLevelNamesMapping():
        valid = ", ".join(sorted(logging.getLevelNamesMapping()))
        raise ValueError(f"unknown log level {level_name!r}; expected one of: {valid}")
    if format_name not in _VALID_FORMATS:
        valid = ", ".join(sorted(_VALID_FORMATS))
        raise ValueError(f"unknown log format {format_name!r}; expected one of: {valid}")

    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(level_name)
    # Replace rather than append: configure_logging is called from every CLI
    # entry point, and appending would duplicate every line per invocation.
    for existing in list(logger.handlers):
        logger.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    handler.setFormatter(
        JsonFormatter()
        if format_name == "json"
        else logging.Formatter("%(levelname)-8s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    # Do not propagate to the root logger: an adopting application's own
    # handlers would otherwise print every harness line a second time.
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the harness root.

    Args:
        name: Dotted suffix, conventionally the module name. A leading
            ``hexvision.`` is tolerated and not duplicated.
    """
    suffix = name.removeprefix(f"{LOGGER_ROOT}.")
    return logging.getLogger(LOGGER_ROOT if suffix == LOGGER_ROOT else f"{LOGGER_ROOT}.{suffix}")


def log_verdict(
    logger: logging.Logger,
    *,
    gate: str,
    passed: bool,
    clause: str | None = None,
    **context: Any,
) -> None:
    """Emit a gate verdict at a level that matches its severity.

    A passing gate logs at INFO and a failing gate at ERROR, so a CI log filtered
    to ERROR shows exactly the findings and nothing else.

    Args:
        logger: Logger to emit through.
        gate: Target name, matching the Makefile target that invoked it.
        passed: The verdict.
        clause: Contract clause or invariant id being enforced.
        **context: Structured detail included verbatim in JSON output.
    """
    logger.log(
        logging.INFO if passed else logging.ERROR,
        "gate %s: %s",
        gate,
        "PASS" if passed else "FAIL",
        extra={"gate": gate, "verdict": "pass" if passed else "fail", "clause": clause, **context},
    )
