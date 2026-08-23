"""Dynamic stack-pack discovery with explicit failure reporting.

Entry points make packs independently installable. Discovery errors are surfaced
rather than silently omitted because an absent pack would otherwise remove its
gates while preserving a misleadingly green core run.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import metadata
from typing import Final, cast

from hexvision.errors import PackError
from hexvision.packs.base import Pack

__all__ = ["available", "clear_registered", "load", "load_all", "register"]

_GROUP: Final = "hexvision.packs"
_REGISTERED: dict[str, Pack] = {}


def register(pack: Pack) -> None:
    """Register an in-process pack for embedding and isolated tests.

    This opt-in path avoids manufacturing package metadata in tests while still
    applying the same duplicate-name protection as installed entry points.
    """
    if pack.name in _REGISTERED:
        raise PackError(f"pack {pack.name!r} is already registered")
    _REGISTERED[pack.name] = pack


def clear_registered() -> None:
    """Clear test registrations so independent callers cannot leak policy state."""
    _REGISTERED.clear()


def _entry_points() -> dict[str, metadata.EntryPoint]:
    """Resolve the current importlib metadata API into a name-indexed mapping."""
    points = metadata.entry_points()
    selected = (
        points.select(group=_GROUP)
        if hasattr(points, "select")
        else cast("dict[str, metadata.EntryPoints]", points).get(_GROUP, metadata.EntryPoints(()))
    )
    return {point.name: point for point in selected}


def available() -> tuple[str, ...]:
    """Return all installed and in-process pack names in stable order."""
    return tuple(sorted(set(_entry_points()) | set(_REGISTERED)))


def load(name: str) -> Pack:
    """Load one named pack or raise a cause-preserving :class:`PackError`."""
    if name in _REGISTERED:
        return _REGISTERED[name]
    entry = _entry_points().get(name)
    if entry is None:
        raise PackError(
            f"pack {name!r} is not registered; available packs: {', '.join(available()) or 'none'}"
        )
    try:
        candidate = entry.load()
        pack = candidate() if isinstance(candidate, type) else candidate
    except Exception as exc:
        raise PackError(f"failed to load pack {name!r}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(pack, Pack):
        raise PackError(f"entry point for pack {name!r} did not return a Pack instance")
    return pack


def load_all(names: Sequence[str] | None = None) -> tuple[Pack, ...]:
    """Load every pack, or an explicit reviewed subset, without partial discovery.

    ``names`` lets release orchestration obtain its candidate list from reviewed
    configuration while discovery continues to come from entry points.  Names
    absent from discovery are errors; silently omitting an allowlisted pack
    would make a missing control look like a clean run.
    """
    discovered = available()
    selected = discovered if names is None else tuple(names)
    missing = tuple(name for name in selected if name not in discovered)
    if missing:
        raise PackError(
            "configured active pack(s) are not registered: "
            f"{', '.join(missing)}; available packs: {', '.join(discovered) or 'none'}"
        )
    return tuple(load(name) for name in selected)
