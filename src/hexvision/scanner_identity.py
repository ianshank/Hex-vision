"""Resolve and verify security scanner artifacts before a Makefile scan runs.

Version output is self-reported by the executable and therefore proves nothing
about the bytes that will scan a repository.  This module obtains scanner
policy from the layered configuration, resolves the configured executable to
its canonical absolute path, and compares the bytes at that path with the
platform-specific SHA-256 pin immediately before Make invokes the scanner.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shlex
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hexvision.config import Config, load_config
from hexvision.errors import GateBlockedError
from hexvision.observability import get_logger

__all__ = ["main", "resolve_verified_scanner"]

_LOG = get_logger(__name__)


def _require_text(mapping: Mapping[str, Any], key: str, *, tool: str) -> str:
    """Read a non-empty textual scanner-policy value or block the affected gate."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GateBlockedError(
            f"scanner identity BLOCKED: configured scanner {tool!r} has no usable {key!r} value",
            clause="INV-1",
        )
    return value


def _platform_policy(policy: Mapping[str, Any], *, tool: str) -> Mapping[str, Any]:
    """Select the configured digest table for the host's real platform and architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    platforms = policy.get("platforms")
    if not isinstance(platforms, Mapping):
        raise GateBlockedError(
            f"scanner identity BLOCKED: configured scanner {tool!r} has no platforms table",
            clause="INV-1",
        )
    by_system = platforms.get(system)
    if not isinstance(by_system, Mapping):
        raise GateBlockedError(
            f"scanner identity BLOCKED: {tool} has no configured digest for platform "
            f"{system}/{machine}",
            clause="INV-1",
        )
    values = by_system.get(machine)
    if not isinstance(values, Mapping):
        raise GateBlockedError(
            f"scanner identity BLOCKED: {tool} has no configured digest for platform "
            f"{system}/{machine}",
            clause="INV-1",
        )
    return values


def _scanner_policy(tool: str, config: Config) -> tuple[str, str, Mapping[str, Any]]:
    """Read one scanner's configured executable, version label, and host pin."""
    policy = config.section(f"scanners.{tool}")
    if not policy:
        raise GateBlockedError(
            f"scanner identity BLOCKED: scanner {tool!r} is not configured", clause="INV-1"
        )
    return (
        _require_text(policy, "executable", tool=tool),
        _require_text(policy, "version", tool=tool),
        _platform_policy(policy, tool=tool),
    )


def _digest(path: Path, *, tool: str) -> str:
    """Hash an opened scanner artifact, blocking rather than treating an I/O error as clean."""
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise GateBlockedError(
            f"scanner identity BLOCKED: cannot compute SHA-256 digest for {tool} at {path}: {exc}",
            clause="INV-1",
        ) from exc


def resolve_verified_scanner(tool: str, config: Config | None = None) -> Path:
    """Return a configured scanner's verified canonical absolute path.

    The digest is checked for every call rather than cached.  Make calls this
    immediately before each scan so a replacement after a preceding scan cannot
    inherit trust from an earlier verification.
    """
    resolved_config = load_config() if config is None else config
    executable, version, host_policy = _scanner_policy(tool, resolved_config)
    expected = _require_text(host_policy, "artifact_sha256", tool=tool)
    located = shutil.which(executable)
    if located is None:
        raise GateBlockedError(
            f"scanner identity BLOCKED: {tool} version {version} is not found on PATH",
            clause="INV-1",
        )
    try:
        artifact = Path(located).resolve(strict=True)
    except OSError as exc:
        raise GateBlockedError(
            f"scanner identity BLOCKED: cannot resolve {tool} executable {located}: {exc}",
            clause="INV-1",
        ) from exc
    actual = _digest(artifact, tool=tool)
    if actual.casefold() != expected.casefold():
        system = platform.system().lower()
        machine = platform.machine().lower()
        raise GateBlockedError(
            f"scanner identity BLOCKED: {tool} SHA-256 digest mismatch for {system}/{machine}: "
            f"expected {expected}, observed {actual}",
            clause="INV-1",
        )
    _LOG.debug(
        "scanner artifact verified",
        extra={"tool": tool, "path": str(artifact), "version": version},
    )
    return artifact


def _install_shell_values(tool: str, config: Config) -> str:
    """Render quoted platform install values for the backwards-compatible Make installers."""
    executable, version, host_policy = _scanner_policy(tool, config)
    values = {
        "executable": executable,
        "version": version,
        "go_module": _require_text(config.section(f"scanners.{tool}"), "go_module", tool=tool),
        "asset": _require_text(host_policy, "asset", tool=tool),
        "download_url": _require_text(host_policy, "download_url", tool=tool),
        "release_sha256": _require_text(host_policy, "release_sha256", tool=tool),
        "archive_kind": _require_text(host_policy, "archive_kind", tool=tool),
        "archive_member": _require_text(host_policy, "archive_member", tool=tool),
    }
    return " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())


def _parser() -> argparse.ArgumentParser:
    """Build the small command surface used exclusively by Makefile targets."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("verify", "install-shell"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("tool")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Verify a scanner or print config-derived installer values for the Makefile."""
    parsed = _parser().parse_args(arguments)
    try:
        config = load_config()
        if parsed.command == "verify":
            print(resolve_verified_scanner(parsed.tool, config))
        else:
            print(_install_shell_values(parsed.tool, config))
    except GateBlockedError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
