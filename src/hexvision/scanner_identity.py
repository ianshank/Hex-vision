"""Resolve and verify configured tool artifacts before automation invokes them.

Version output is self-reported by the executable and therefore proves nothing
about the bytes that will run. This module obtains tool policy from the layered
configuration, resolves the configured executable to its canonical absolute
path, and compares the bytes at that path with the platform-specific SHA-256
pin immediately before automation invokes the tool.
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

__all__ = ["main", "resolve_verified_scanner", "resolve_verified_spec_validator"]

_LOG = get_logger(__name__)


def _require_text(
    mapping: Mapping[str, Any], key: str, *, tool: str, identity: str = "scanner"
) -> str:
    """Read a non-empty textual tool-policy value or block the affected gate."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GateBlockedError(
            f"{identity} identity BLOCKED: configured {identity} {tool!r} "
            f"has no usable {key!r} value",
            clause="INV-1",
        )
    return value


def _platform_policy(
    policy: Mapping[str, Any], *, tool: str, identity: str = "scanner"
) -> Mapping[str, Any]:
    """Select the configured digest table for the host's real platform and architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    platforms = policy.get("platforms")
    if not isinstance(platforms, Mapping):
        raise GateBlockedError(
            f"{identity} identity BLOCKED: configured {identity} {tool!r} has no platforms table",
            clause="INV-1",
        )
    by_system = platforms.get(system)
    if not isinstance(by_system, Mapping):
        raise GateBlockedError(
            f"{identity} identity BLOCKED: {tool} has no configured digest for platform "
            f"{system}/{machine}",
            clause="INV-1",
        )
    values = by_system.get(machine)
    if not isinstance(values, Mapping):
        raise GateBlockedError(
            f"{identity} identity BLOCKED: {tool} has no configured digest for platform "
            f"{system}/{machine}",
            clause="INV-1",
        )
    return values


def _tool_policy(
    tool: str, config: Config, *, policy_path: str, identity: str
) -> tuple[str, str, Mapping[str, Any]]:
    """Read one configured tool's executable, version label, and host pin."""
    policy = config.section(policy_path)
    if not policy:
        raise GateBlockedError(
            f"{identity} identity BLOCKED: {identity} {tool!r} is not configured", clause="INV-1"
        )
    return (
        _require_text(policy, "executable", tool=tool, identity=identity),
        _require_text(policy, "version", tool=tool, identity=identity),
        _platform_policy(policy, tool=tool, identity=identity),
    )


def _digest(path: Path, *, tool: str, identity: str = "scanner") -> str:
    """Hash an opened tool artifact, blocking rather than treating an I/O error as clean."""
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise GateBlockedError(
            f"{identity} identity BLOCKED: cannot compute SHA-256 digest for {tool} "
            f"at {path}: {exc}",
            clause="INV-1",
        ) from exc


def _resolve_verified_tool(tool: str, config: Config, *, policy_path: str, identity: str) -> Path:
    """Return one configured tool's verified canonical absolute path.

    The digest is checked for every call rather than cached. This prevents a
    replacement after a preceding run from inheriting trust from that run.
    """
    executable, version, host_policy = _tool_policy(
        tool, config, policy_path=policy_path, identity=identity
    )
    expected = _require_text(host_policy, "artifact_sha256", tool=tool, identity=identity)
    located = shutil.which(executable)
    if located is None:
        raise GateBlockedError(
            f"{identity} identity BLOCKED: {tool} version {version} is not found on PATH",
            clause="INV-1",
        )
    try:
        artifact = Path(located).resolve(strict=True)
    except OSError as exc:
        raise GateBlockedError(
            f"{identity} identity BLOCKED: cannot resolve {tool} executable {located}: {exc}",
            clause="INV-1",
        ) from exc
    actual = _digest(artifact, tool=tool, identity=identity)
    if actual.casefold() != expected.casefold():
        system = platform.system().lower()
        machine = platform.machine().lower()
        raise GateBlockedError(
            f"{identity} identity BLOCKED: {tool} SHA-256 digest mismatch for {system}/{machine}: "
            f"expected {expected}, observed {actual}",
            clause="INV-1",
        )
    _LOG.debug(
        "tool artifact verified",
        extra={"tool": tool, "identity": identity, "path": str(artifact), "version": version},
    )
    return artifact


def resolve_verified_scanner(tool: str, config: Config | None = None) -> Path:
    """Return a configured scanner's verified canonical absolute path."""
    resolved_config = load_config() if config is None else config
    return _resolve_verified_tool(
        tool, resolved_config, policy_path=f"scanners.{tool}", identity="scanner"
    )


def resolve_verified_spec_validator(config: Config | None = None) -> Path:
    """Return the configured strict OpenSpec validator after byte verification."""
    resolved_config = load_config() if config is None else config
    return _resolve_verified_tool(
        "openspec",
        resolved_config,
        policy_path="specification_validator",
        identity="specification validator",
    )


def _install_shell_values(tool: str, config: Config) -> str:
    """Render quoted platform install values for the backwards-compatible Make installers."""
    executable, version, host_policy = _tool_policy(
        tool, config, policy_path=f"scanners.{tool}", identity="scanner"
    )
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
    for command in ("verify", "install-shell", "verify-spec-validator"):
        command_parser = commands.add_parser(command)
        if command != "verify-spec-validator":
            command_parser.add_argument("tool")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Verify a scanner or print config-derived installer values for the Makefile."""
    parsed = _parser().parse_args(arguments)
    try:
        config = load_config()
        if parsed.command == "verify":
            print(resolve_verified_scanner(parsed.tool, config))
        elif parsed.command == "install-shell":
            print(_install_shell_values(parsed.tool, config))
        else:
            print(resolve_verified_spec_validator(config))
    except GateBlockedError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
