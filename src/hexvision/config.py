"""Layered configuration with provenance and frozen quality bars.

The harness has one rule about values: **no operational value is written in
Python source.** Thresholds, allowlists, latency budgets, safety bounds and file
globs all resolve through this module, which merges four layers and records where
each key came from.

Layer order, later winning:

======== =====================================================================
Layer    Source
======== =====================================================================
packaged ``hexvision/defaults/hex-vision.toml`` inside the wheel. Always present.
repo     ``hex-vision.toml`` at the repository root. What an adopting team edits.
pyproject ``[tool.hexvision]`` in ``pyproject.toml``. Where gate thresholds live,
         because the contract requires a single home for them next to the tool
         config that enforces them.
env      ``HEXVISION_`` variables, ``__`` separating path segments.
override Explicit values passed by a caller, normally from a CLI flag.
======== =====================================================================

Frozen keys — coverage floors, safety envelopes and the contract itself — accept
the first three layers and REFUSE the last two. A quality bar an operator can
lower from a shell is not a bar, and an override that leaves no diff behind
cannot be reviewed. The refusal is an error, never a silent ignore, because
silently ignoring an override means the operator believes a value is in force
that is not.

Provenance is not a debugging nicety. ``hexvision config explain
robotics.latency.budgets.tensorrt`` answers "why is this bound 33ms and who set
it" from the tool, which is the difference between a policy and a folk memory.
"""

from __future__ import annotations

import copy
import os
import tomllib
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from hexvision.errors import ConfigError, FrozenKeyOverrideError, MissingKeyError
from hexvision.observability import get_logger

__all__ = [
    "REPO_CONFIG_FILENAME",
    "Config",
    "ConfigLayer",
    "Provenance",
    "find_repo_root",
    "load_config",
]

_LOG: Final = get_logger(__name__)

#: Filename of the repository-level overlay. Not configurable: a config file
#: whose own location is configurable cannot be found by a fresh checkout.
REPO_CONFIG_FILENAME: Final = "hex-vision.toml"

#: Marker files that identify a repository root, most specific first. Searched
#: upward from a starting directory so the CLI works from any subdirectory and
#: from inside a git worktree.
_ROOT_MARKERS: Final = (REPO_CONFIG_FILENAME, "pyproject.toml", ".git")

_PACKAGED_DEFAULTS: Final = Path(__file__).parent / "defaults" / REPO_CONFIG_FILENAME
_PYPROJECT_FILENAME: Final = "pyproject.toml"
_PYPROJECT_TABLE: Final = ("tool", "hexvision")
_ENV_PATH_SEPARATOR: Final = "__"
_DEFAULT_ENV_PREFIX: Final = "HEXVISION_"
#: Environment variables consumed elsewhere that are not configuration keys.
#: Without this exclusion, `HEXVISION_LOG_LEVEL` would resolve to a bogus
#: `log.level` key and pollute `config dump`.
_ENV_RESERVED_SUFFIXES: Final = frozenset({"LOG_LEVEL", "LOG_FORMAT", "CONFIG"})


class ConfigLayer:
    """Names of the resolution layers.

    A class of constants rather than string literals at call sites: a typo'd
    layer name would otherwise produce a provenance record that reads plausibly
    and is wrong.
    """

    PACKAGED: Final = "packaged"
    REPO: Final = "repo"
    PYPROJECT: Final = "pyproject"
    ENV: Final = "env"
    OVERRIDE: Final = "override"

    #: Layers that may set a frozen key. Kept here beside the names so the two
    #: cannot drift apart.
    FROZEN_WRITABLE: Final = frozenset({PACKAGED, REPO, PYPROJECT})


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a resolved value came from.

    Attributes:
        key: Dotted key path.
        value: The value in force.
        layer: Winning layer name, one of :class:`ConfigLayer`.
        source: Human-readable origin — a file path, or ``"environment"``, or
            ``"cli override"``.
        shadowed: Values from lower-precedence layers, most recent first. Present
            so ``explain`` can show what the winning layer overrode rather than
            only what won.
    """

    key: str
    value: Any
    layer: str
    source: str
    shadowed: tuple[tuple[str, Any], ...] = ()


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking upward for a marker file.

    Args:
        start: Directory to search from. Defaults to the process working
            directory.

    Returns:
        The first ancestor containing a marker, or ``start`` itself when none is
        found. Returning ``start`` rather than raising keeps the library usable
        on a bare directory; callers that require a real repository check for
        the artifacts they need and fail with their own message.
    """
    origin = (Path.cwd() if start is None else start).resolve()
    candidates = [origin, *origin.parents] if origin.is_dir() else list(origin.parents)
    for candidate in candidates:
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            _LOG.debug("repo root resolved", extra={"root": str(candidate), "from": str(origin)})
            return candidate
    _LOG.debug("no repo marker found; using origin", extra={"origin": str(origin)})
    return origin


def _read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, converting every failure into a BLOCKED ConfigError.

    An unreadable or malformed configuration file must never degrade to "use the
    defaults": the operator wrote that file expecting it to take effect.
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:  # pragma: no cover - guarded by callers
        raise ConfigError(f"configuration file disappeared while reading: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid TOML ({exc}). This fails closed rather than "
            "falling back to defaults, because a file you wrote must either take "
            "effect or be reported."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def _nested_get(data: Mapping[str, Any], path: Sequence[str]) -> Any | None:
    """Return a nested value by path segments, or ``None`` if absent."""
    cursor: Any = data
    for segment in path:
        if not isinstance(cursor, Mapping) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor


def _deep_merge(base: MutableMapping[str, Any], incoming: Mapping[str, Any]) -> None:
    """Recursively merge ``incoming`` into ``base`` in place.

    Tables merge key-by-key; every other type replaces wholesale. Lists
    deliberately REPLACE rather than concatenate: an allowlist an overlay cannot
    shorten is not an allowlist, and a team narrowing ``allowed_runtimes`` must
    not silently inherit the entries they removed.
    """
    for key, value in incoming.items():
        existing = base.get(key)
        if isinstance(value, Mapping) and isinstance(existing, MutableMapping):
            _deep_merge(existing, value)
        else:
            base[key] = copy.deepcopy(value) if isinstance(value, Mapping | list) else value


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(dotted_key, value)`` for every leaf and every table.

    Tables are yielded as well as their leaves so that ``get("robotics.latency")``
    returns the whole table and provenance can be reported at table granularity.
    """
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        yield dotted, value
        if isinstance(value, Mapping):
            yield from _flatten(value, prefix=f"{dotted}.")


def _assert_supported_keys(
    data: Mapping[str, Any],
    *,
    supported_keys: frozenset[str],
    extensible_tables: tuple[str, ...],
    source: str,
) -> None:
    """Reject unsupported keys, allowing only shipped, explicitly extensible maps."""
    for key, _ in _flatten(data):
        is_dynamic_member = any(key.startswith(f"{table}.") for table in extensible_tables)
        if key not in supported_keys and not is_dynamic_member:
            raise ConfigError(
                f"unsupported configuration key {key!r} in {source}. "
                "Declare only keys shipped by the packaged configuration contract."
            )


def _parse_env_value(raw: str) -> Any:
    """Type an environment string by parsing it as a TOML value.

    ``HEXVISION_ROBOTICS__LATENCY__PERCENTILE=95`` must yield the integer ``95``,
    not the string ``"95"``, or a numeric comparison downstream compares a string
    to a float and raises. Reusing the TOML parser means the environment obeys
    exactly the same syntax as the files, including arrays and booleans, instead
    of a bespoke coercion ladder that disagrees with them at the edges.

    A value that is not valid TOML is treated as a bare string, which is what an
    operator writing ``HEXVISION_ROBOTICS__ARTIFACT_ROOTS=models`` means.
    """
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def _env_layer(env: Mapping[str, str], prefix: str) -> dict[str, Any]:
    """Build a nested mapping from ``PREFIX``-scoped environment variables.

    ``__`` separates path segments and single underscores are preserved, so
    ``HEXVISION_ROBOTICS__LATENCY__PERCENTILE`` becomes
    ``robotics.latency.percentile`` while ``artifact_roots`` keeps its underscore.
    """
    layer: dict[str, Any] = {}
    for name, raw in env.items():
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix) :]
        if not suffix or suffix in _ENV_RESERVED_SUFFIXES:
            continue
        segments = [part.lower() for part in suffix.split(_ENV_PATH_SEPARATOR) if part]
        if not segments:
            continue
        cursor = layer
        for segment in segments[:-1]:
            nested = cursor.setdefault(segment, {})
            if not isinstance(nested, dict):
                raise ConfigError(
                    f"environment variable {name} treats {segment!r} as a table, but "
                    f"another variable already set it to a scalar. Rename one of them."
                )
            cursor = nested
        cursor[segments[-1]] = _parse_env_value(raw)
    return layer


class Config:
    """An immutable, resolved configuration with per-key provenance.

    Instances are produced by :func:`load_config`. The mapping is not exposed for
    mutation: a gate that could rewrite configuration mid-run would make its own
    verdict unreproducible.
    """

    def __init__(
        self,
        resolved: Mapping[str, Any],
        provenance: Mapping[str, Provenance],
        *,
        root: Path,
        frozen_prefixes: Sequence[str],
    ) -> None:
        """Store the resolved tree. Prefer :func:`load_config` over calling this."""
        self._resolved: dict[str, Any] = copy.deepcopy(dict(resolved))
        self._provenance: dict[str, Provenance] = dict(provenance)
        self._root = root
        self._frozen_prefixes = tuple(frozen_prefixes)

    @property
    def root(self) -> Path:
        """Repository root every relative path in the configuration is anchored to."""
        return self._root

    @property
    def frozen_prefixes(self) -> tuple[str, ...]:
        """Key prefixes that refuse environment and CLI overrides."""
        return self._frozen_prefixes

    def is_frozen(self, key: str) -> bool:
        """Return whether ``key`` sits under a frozen prefix.

        Matching is on whole path segments, so a prefix of ``contract`` freezes
        ``contract.targets`` but not a hypothetical ``contractor`` key.
        """
        return any(
            key == prefix or key.startswith(f"{prefix}.") for prefix in self._frozen_prefixes
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value at a dotted key, or ``default`` when absent.

        Returns a deep copy of tables and lists so a caller cannot mutate shared
        state and change another gate's view of policy.
        """
        value = _nested_get(self._resolved, key.split("."))
        if value is None:
            return default
        return copy.deepcopy(value) if isinstance(value, Mapping | list) else value

    def require(self, key: str, *, clause: str | None = None) -> Any:
        """Return the value at a dotted key or raise.

        Used for every value a gate cannot sensibly default. Guessing a latency
        budget or a coverage floor is worse than refusing to run, because the
        guess produces a green tick.

        Raises:
            MissingKeyError: If no layer defines the key.
        """
        value = self.get(key, default=None)
        if value is None:
            raise MissingKeyError(
                f"required configuration key {key!r} is not set in any layer. "
                f"Add it to {REPO_CONFIG_FILENAME} at {self._root}.",
                clause=clause,
            )
        return value

    def section(self, key: str) -> dict[str, Any]:
        """Return a configuration table.

        Raises:
            ConfigError: If the key exists but is not a table. A gate expecting a
                table and receiving a scalar should say so rather than raise an
                attribute error three frames later.
        """
        value = self.get(key, default={})
        if not isinstance(value, Mapping):
            raise ConfigError(f"configuration key {key!r} is {type(value).__name__}, not a table")
        return dict(value)

    def resolve_path(self, key: str, *, clause: str | None = None) -> Path:
        """Return a configured relative path resolved against the repository root.

        Configuration holds repository-relative paths so that the same file works
        in a checkout, a container and a git worktree. An absolute value is
        honoured unchanged, which is what a CI runner pointing at a mounted
        artifact directory needs.
        """
        raw = Path(str(self.require(key, clause=clause)))
        return raw if raw.is_absolute() else self._root / raw

    def explain(self, key: str) -> Provenance:
        """Return the provenance record for a key.

        Raises:
            MissingKeyError: If the key is not defined in any layer.
        """
        record = self._provenance.get(key)
        if record is None:
            raise MissingKeyError(f"no configuration key {key!r} in any layer")
        return record

    def keys(self) -> tuple[str, ...]:
        """Return every dotted key, tables included, in sorted order."""
        return tuple(sorted(self._provenance))

    def as_dict(self) -> dict[str, Any]:
        """Return a deep copy of the resolved tree, safe for the caller to mutate."""
        return copy.deepcopy(self._resolved)


def _layer_sources(root: Path, config_path: Path | None) -> list[tuple[str, Path]]:
    """Return the file-backed layers that exist, in resolution order."""
    sources: list[tuple[str, Path]] = [(ConfigLayer.PACKAGED, _PACKAGED_DEFAULTS)]
    repo_config = config_path if config_path is not None else root / REPO_CONFIG_FILENAME
    if repo_config.exists():
        sources.append((ConfigLayer.REPO, repo_config))
    elif config_path is not None:
        # An explicitly-named file that does not exist is an operator error, not
        # an invitation to fall back silently.
        raise ConfigError(f"configuration file not found: {config_path}")
    pyproject = root / _PYPROJECT_FILENAME
    if pyproject.exists() and _nested_get(_read_toml(pyproject), _PYPROJECT_TABLE) is not None:
        sources.append((ConfigLayer.PYPROJECT, pyproject))
    return sources


def _assert_no_frozen_writes(
    layer: str, data: Mapping[str, Any], frozen_prefixes: Sequence[str], source: str
) -> None:
    """Refuse a frozen-key write from a non-authoritative layer.

    Raises:
        FrozenKeyOverrideError: naming the key, the layer and where the value is
            legitimately configured, so the operator's next action is obvious.
    """
    if layer in ConfigLayer.FROZEN_WRITABLE:
        return
    for key, _ in _flatten(data):
        if any(key == p or key.startswith(f"{p}.") for p in frozen_prefixes):
            raise FrozenKeyOverrideError(
                f"{key!r} is a frozen key and cannot be set from {source}. "
                f"Frozen keys are quality and safety bars: an override from a shell "
                f"leaves no reviewable diff. Change it in {REPO_CONFIG_FILENAME} or "
                f"{_PYPROJECT_FILENAME} and record the change in the decision log.",
                clause="C-FROZEN",
            )


def load_config(
    *,
    root: Path | None = None,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Config:
    """Resolve configuration from every layer and return it with provenance.

    Args:
        root: Repository root. Discovered from the working directory when omitted.
        config_path: Explicit overlay file, replacing the default
            ``hex-vision.toml`` lookup. Used by tests and by CI jobs that check a
            candidate config before it is committed.
        env: Environment mapping. Injected rather than read from ``os.environ``
            directly so tests never mutate process state.
        overrides: Nested mapping of explicit values, normally from CLI flags.

    Returns:
        The resolved :class:`Config`.

    Raises:
        ConfigError: If a layer is unreadable or malformed.
        FrozenKeyOverrideError: If the environment or an override targets a
            frozen key.
    """
    resolved_root = find_repo_root() if root is None else root.resolve()
    resolved_env = os.environ if env is None else env

    merged: dict[str, Any] = {}
    provenance: dict[str, Provenance] = {}

    def apply(layer: str, data: Mapping[str, Any], source: str) -> None:
        """Merge one layer and record provenance for every key it sets."""
        for key, value in _flatten(data):
            previous = provenance.get(key)
            shadowed = ((previous.layer, previous.value), *previous.shadowed) if previous else ()
            provenance[key] = Provenance(
                key=key, value=value, layer=layer, source=source, shadowed=shadowed
            )
        _deep_merge(merged, data)
        _LOG.debug("config layer applied", extra={"layer": layer, "source": source})

    packaged_defaults = _read_toml(_PACKAGED_DEFAULTS)
    supported_keys = frozenset(key for key, _ in _flatten(packaged_defaults))
    extensible_tables = tuple(
        str(table)
        for table in (_nested_get(packaged_defaults, ("meta", "extensible_tables")) or ())
    )
    file_layers = _layer_sources(resolved_root, config_path)
    for layer, path in file_layers:
        data = _read_toml(path)
        if layer == ConfigLayer.PYPROJECT:
            data = dict(_nested_get(data, _PYPROJECT_TABLE) or {})
        if layer != ConfigLayer.PACKAGED:
            _assert_supported_keys(
                data,
                supported_keys=supported_keys,
                extensible_tables=extensible_tables,
                source=str(path),
            )
        apply(layer, data, str(path))

    # Frozen prefixes come from the merged file layers, so a repository can
    # freeze additional keys of its own — a team with a certification obligation
    # can freeze more than the harness ships with, never less at run time.
    frozen_prefixes = tuple(_nested_get(merged, ("meta", "frozen", "prefixes")) or ())
    env_prefix = str(_nested_get(merged, ("meta", "env_prefix")) or _DEFAULT_ENV_PREFIX)

    env_data = _env_layer(resolved_env, env_prefix)
    if env_data:
        _assert_supported_keys(
            env_data,
            supported_keys=supported_keys,
            extensible_tables=extensible_tables,
            source=f"the environment ({env_prefix}*)",
        )
        _assert_no_frozen_writes(
            ConfigLayer.ENV, env_data, frozen_prefixes, f"the environment ({env_prefix}*)"
        )
        apply(ConfigLayer.ENV, env_data, "environment")

    if overrides:
        _assert_supported_keys(
            overrides,
            supported_keys=supported_keys,
            extensible_tables=extensible_tables,
            source="a command-line override",
        )
        _assert_no_frozen_writes(
            ConfigLayer.OVERRIDE, overrides, frozen_prefixes, "a command-line override"
        )
        apply(ConfigLayer.OVERRIDE, overrides, "cli override")

    _LOG.debug(
        "config resolved",
        extra={
            "root": str(resolved_root),
            "layers": [layer for layer, _ in file_layers],
            "keys": len(provenance),
        },
    )
    return Config(merged, provenance, root=resolved_root, frozen_prefixes=frozen_prefixes)
