"""Normalize Git destinations once so every remote policy consumer agrees.

Git accepts several URL spellings for one destination. Keeping canonicalisation in
this module prevents a hook, CI job, and interactive CLI from disagreeing about
whether a push is allowed, which would make INV-3 unenforceable.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from hexvision.config import Config
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger

__all__ = ["NormalizedRemote", "check_remotes", "normalize_remote_url", "read_git_remotes"]

_LOG: Final = get_logger(__name__)
_CLAUSE: Final = "INV-3"
_REMOTE_FIELDS_MINIMUM: Final = 2
_HOST_ONLY: Final = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class NormalizedRemote:
    """A remote URL plus its comparison form or a fail-closed rejection reason.

    ``original`` is intentionally retained: policy comparisons use a lower-cased
    destination while remediation needs to quote the exact value an operator put
    in Git configuration.
    """

    original: str
    destination: str | None
    blocked_reason: str | None = None

    @property
    def is_blocked(self) -> bool:
        """Return whether parsing refused to discard a security-relevant input."""
        return self.blocked_reason is not None


def _blocked(original: str, reason: str) -> NormalizedRemote:
    """Make a rejected result instead of throwing away evidence in an exception."""
    return NormalizedRemote(original=original, destination=None, blocked_reason=reason)


def _is_known_host_allowlist_entry(value: object, known_hosts: set[str]) -> bool:
    """Allow a configured known host to authorize all repository paths on that host.

    A host-only policy entry is intentionally narrower than accepting a host-only
    Git remote: repository remotes still require a path, while an approved model
    registry host can govern many repository paths without repeating each one.
    """
    host = str(value).strip().casefold()
    return bool(_HOST_ONLY.fullmatch(host)) and host in known_hosts


def normalize_remote_url(  # noqa: PLR0911, PLR0912 - each rejection preserves a distinct security reason.
    raw: str,
) -> NormalizedRemote:
    """Return the canonical ``host/path`` form for a Git remote.

    The parser accepts only Git spellings modelled by configured policy consumers.
    In particular, a password-bearing userinfo component is blocked rather than
    normalised away, because silently removing a token would hide it from the
    secret control that must see it.
    """
    original = raw
    value = raw.strip()
    if not value:
        return _blocked(original, "remote URL is empty")
    if "://" not in value and "//" in value:
        return _blocked(original, "remote URL contains an invalid empty path segment")

    parsed = None
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"ssh", "https", "http", "git"}:
            return _blocked(original, f"unsupported remote scheme {parsed.scheme!r}")
        if not parsed.hostname:
            return _blocked(original, "remote URL has no host")
        if parsed.username == "":
            return _blocked(original, "remote URL contains an empty username")
        if parsed.password is not None:
            return _blocked(original, "remote URL contains userinfo with a password or token")
        if parsed.query and parsed.fragment:
            return _blocked(original, "remote URL contains query and fragment components")
        if parsed.query:
            return _blocked(original, "remote URL contains a query component")
        if parsed.fragment:
            return _blocked(original, "remote URL contains a fragment component")
        host = parsed.hostname
        path = parsed.path
    elif "@" in value and ":" in value:
        user_host, path = value.split(":", maxsplit=1)
        if "@" not in user_host:
            return _blocked(original, "unparseable SCP-style remote URL")
        user, host = user_host.rsplit("@", maxsplit=1)
        if not user or not host or ":" in user:
            return _blocked(original, "remote URL contains invalid userinfo")
    elif ":" in value:
        host, path = value.split(":", maxsplit=1)
    elif "/" in value:
        host, path = value.split("/", maxsplit=1)
    else:
        return _blocked(original, "unparseable remote URL")

    clean_host = host.casefold().strip()
    if "//" in path:
        return _blocked(original, "remote URL contains an invalid empty path segment")
    clean_path = path.strip().strip("/")
    if clean_path.casefold().endswith(".git"):
        clean_path = clean_path[:-4]
    clean_path = clean_path.strip("/")
    if not clean_host or not clean_path:
        return _blocked(original, "remote URL must include both host and repository path")
    if any(part in {"", ".", ".."} for part in clean_path.split("/")):
        return _blocked(original, "remote URL contains an invalid repository path")
    destination = f"{clean_host}/{clean_path.casefold()}"
    _LOG.debug("remote normalized", extra={"original": original, "destination": destination})
    return NormalizedRemote(original=original, destination=destination)


def read_git_remotes(config: Config, repository: str | None = None) -> tuple[str, ...] | GateResult:
    """Read configured Git remotes without shell interpretation.

    Returning a blocked result makes tool absence and command failure auditable
    rather than converting them into an empty set that could accidentally pass.
    """
    executable = str(config.require("remotes.git_executable", clause=_CLAUSE))
    cwd = config.root if repository is None else config.root / repository

    def execute(arguments: list[str]) -> subprocess.CompletedProcess[str] | GateResult:
        """Run one configured Git query without a shell or unstructured fallback."""
        try:
            return subprocess.run(
                [executable, *arguments],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, OSError) as exc:
            return GateResult.blocked(
                "remotes",
                summary="remote inspection could not start",
                reason=f"cannot execute configured git command {executable!r}: {exc}",
                clause=_CLAUSE,
            )

    listed = execute(["remote", "-v"])
    if isinstance(listed, GateResult):
        return listed
    configured = execute(["config", "--get-regexp", r"^remote\..*\.(url|pushurl)$"])
    if isinstance(configured, GateResult):
        return configured
    if listed.returncode != 0:
        return GateResult.blocked(
            "remotes",
            summary="remote inspection failed",
            reason=listed.stderr.strip() or "git remote -v returned a non-zero exit status",
            clause=_CLAUSE,
        )
    if configured.returncode not in {0, 1}:
        return GateResult.blocked(
            "remotes",
            summary="remote inspection failed",
            reason=(
                configured.stderr.strip()
                or "git config could not enumerate remote URL and pushurl values"
            ),
            clause=_CLAUSE,
        )
    urls: list[str] = []
    for line in listed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= _REMOTE_FIELDS_MINIMUM:
            urls.append(fields[1])
    if configured.returncode == 0:
        for line in configured.stdout.splitlines():
            key, separator, url = line.partition(" ")
            if separator and key and url.strip():
                urls.append(url.strip())
    unique_urls = tuple(dict.fromkeys(urls))
    if not unique_urls:
        return GateResult.blocked(
            "remotes",
            summary="no configured remote URLs were found",
            reason=(
                "git remote -v and remote.*.(url|pushurl) configuration contained no "
                "resolvable destination; refusing an allowlist-only pass"
            ),
            clause=_CLAUSE,
        )
    return unique_urls


def check_remotes(config: Config, remotes: Iterable[str] | None = None) -> GateResult:
    """Verify every remote resolves to the configured allowlist, failing closed.

    An empty allowlist means policy is unknown, not that every destination is
    permitted. This explicit block prevents a broken configuration overlay from
    turning the remote control into an allow-all control.
    """
    try:
        raw_allowlist = config.require("remotes.allowlist", clause=_CLAUSE)
        known_hosts = {
            str(host).strip().casefold()
            for host in config.require("remotes.known_hosts", clause=_CLAUSE)
        }
    except Exception as exc:
        return GateResult.blocked(
            "remotes", summary="remote policy unavailable", reason=str(exc), clause=_CLAUSE
        )
    if not isinstance(raw_allowlist, list) or not raw_allowlist:
        return GateResult.blocked(
            "remotes",
            summary="remote allowlist is empty",
            reason="remotes.allowlist must contain at least one approved destination",
            clause=_CLAUSE,
        )
    allowed: set[str] = set()
    allowed_hosts: set[str] = set()
    for item in raw_allowlist:
        normal = normalize_remote_url(str(item))
        if normal.is_blocked or normal.destination is None:
            if _is_known_host_allowlist_entry(item, known_hosts):
                allowed_hosts.add(str(item).strip().casefold())
                continue
            return GateResult.blocked(
                "remotes",
                summary="remote allowlist is invalid",
                reason=(
                    f"configured allowlist entry {item!r} cannot be normalized: "
                    f"{normal.blocked_reason}"
                ),
                clause=_CLAUSE,
            )
        allowed.add(normal.destination)
    values: Iterable[str]
    if remotes is None:
        observed = read_git_remotes(config)
        if isinstance(observed, GateResult):
            return observed
        values = observed
    else:
        values = remotes
    findings: list[Finding] = []
    for index, raw in enumerate(values, start=1):
        normal = normalize_remote_url(raw)
        destination = normal.destination or ""
        if normal.is_blocked:
            findings.append(
                Finding(
                    id=f"REMOTE-{index:03d}",
                    severity=Severity.BLOCKER,
                    message=f"remote {raw!r} is unsafe or unparseable: {normal.blocked_reason}",
                    clause=_CLAUSE,
                    disposition="Replace the remote with an approved credential-free URL.",
                )
            )
        elif (
            destination not in allowed
            and destination.split("/", maxsplit=1)[0] not in allowed_hosts
        ):
            findings.append(
                Finding(
                    id=f"REMOTE-{index:03d}",
                    severity=Severity.BLOCKER,
                    message=(
                        f"remote {raw!r} resolves to unapproved destination {normal.destination!r}"
                    ),
                    clause=_CLAUSE,
                    disposition="Use a destination listed in remotes.allowlist.",
                )
            )
    if findings:
        return GateResult.failed(
            "remotes",
            summary="one or more remotes violate policy",
            findings=findings,
            clause=_CLAUSE,
        )
    return GateResult.passed(
        "remotes",
        summary="all remotes are approved",
        clause=_CLAUSE,
        measurements={
            "allowlist_size": len(allowed) + len(allowed_hosts),
            "host_allowlist": sorted(allowed_hosts),
        },
    )
