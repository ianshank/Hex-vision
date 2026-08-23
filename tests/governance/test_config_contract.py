"""Dynamic controls that keep shipped configuration honest and enforceable."""

from __future__ import annotations

import ast
import subprocess
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from hexvision.config import load_config
from hexvision.errors import ConfigError
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.safety_envelope import SafetyEnvelopeGate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = REPO_ROOT / "src" / "hexvision" / "defaults" / "hex-vision.toml"
SOURCE_ROOT = REPO_ROOT / "src" / "hexvision"
_READER_METHODS = frozenset({"get", "require", "resolve_path", "section"})


def _leaf_paths(value: object, prefix: str = "") -> Iterable[str]:
    """Yield each leaf from a nested TOML object using its dotted policy path."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            yield from _leaf_paths(child, dotted)
    else:
        yield prefix


def _string_value(node: ast.expr) -> str | None:
    """Return a literal string or the fixed prefix of an f-string argument."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        prefix = "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
        return f"{prefix}*" if prefix else None
    return None


def _mapping_paths(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, set[str]]:
    """Collect literal dotted paths held in local mapping policy declarations."""
    paths: dict[str, set[str]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Dict):
            continue
        values = {
            value.value
            for value in node.value.values
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and "." in value.value
        }
        if values:
            paths[target.id] = values
    return paths


def _function_read_paths(tree: ast.Module) -> set[str]:  # noqa: PLR0912 - AST reader cases are explicit.
    """Infer configuration reader paths, including delegated parameter readers."""
    reads: set[str] = set()
    delegated: dict[str, set[int]] = {}
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    parameter_names = {
        function.name: [
            *(argument.arg for argument in function.args.args),
            *(argument.arg for argument in function.args.kwonlyargs),
        ]
        for function in functions
    }
    for function in functions:
        parameters = parameter_names[function.name]
        mapping_paths = _mapping_paths(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                node.func.attr not in _READER_METHODS
                or not isinstance(node.func.value, ast.Name)
                or node.func.value.id != "config"
                or not node.args
            ):
                continue
            value = _string_value(node.args[0])
            if value is not None:
                reads.add(value)
            elif isinstance(node.args[0], ast.Name):
                name = node.args[0].id
                reads.update(mapping_paths.get(name, set()))
                if name not in mapping_paths:
                    reads.update(path for paths in mapping_paths.values() for path in paths)
                if name in parameters:
                    delegated.setdefault(function.name, set()).add(parameters.index(name))
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            for index in delegated.get(node.func.id, set()):
                argument: ast.expr | None
                if index < len(node.args):
                    argument = node.args[index]
                else:
                    argument = None
                    for keyword in node.keywords:
                        if keyword.arg == parameter_names[node.func.id][index]:
                            argument = keyword.value
                            break
                if argument is not None:
                    value = _string_value(argument)
                    if value is not None:
                        reads.add(value)
                    elif isinstance(argument, ast.Name) and argument.id in parameters:
                        delegated.setdefault(function.name, set()).add(
                            parameters.index(argument.id)
                        )
    return reads


def _runtime_reader_paths() -> set[str]:
    """Discover all configuration paths runtime source actively reads."""
    reads: set[str] = set()
    for source in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        reads.update(_function_read_paths(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "_nested_get" or len(node.args) < 2:
                continue
            path = node.args[1]
            if isinstance(path, ast.Tuple):
                values = [_string_value(item) for item in path.elts]
                if all(value is not None for value in values):
                    reads.add(".".join(value for value in values if value is not None))
    return reads


def _is_covered(leaf: str, readers: set[str]) -> bool:
    """Return whether a concrete leaf lies under an active reader path."""
    return any(
        leaf == reader
        or leaf.startswith(f"{reader}.")
        or (reader.endswith("*") and leaf.startswith(reader.removesuffix("*")))
        for reader in readers
    )


def _discarded_config_reads() -> list[str]:
    """Find a config read used only as an expression or assigned to `_`."""
    discarded: list[str] = []
    for source in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                node.func.attr not in _READER_METHODS
                or not isinstance(node.func.value, ast.Name)
                or node.func.value.id != "config"
            ):
                continue
            parent = parents.get(node)
            if isinstance(parent, ast.Expr):
                discarded.append(f"{source.relative_to(REPO_ROOT)}:{node.lineno}")
            if isinstance(parent, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_" for target in parent.targets
            ):
                discarded.append(f"{source.relative_to(REPO_ROOT)}:{node.lineno}")
    return discarded


def test_every_shipped_default_leaf_has_an_active_runtime_reader() -> None:
    """Walk defaults dynamically and fail with every declared-but-unread key."""
    defaults = tomllib.loads(DEFAULTS.read_text(encoding="utf-8"))
    readers = _runtime_reader_paths()
    unread = sorted(path for path in _leaf_paths(defaults) if not _is_covered(path, readers))
    assert not unread, f"declared-but-unread configuration keys: {', '.join(unread)}"
    assert not _discarded_config_reads(), "discard-only config reads: " + ", ".join(
        _discarded_config_reads()
    )


@pytest.mark.parametrize(
    ("overlay", "key"),
    [
        ("[remotes]\nnot_a_policy = true\n", "remotes.not_a_policy"),
        (
            "[remotes]\nblock_userinfo_with_password = false\n",
            "remotes.block_userinfo_with_password",
        ),
        (
            "[robotics.hardware_in_loop]\nabsence_requires_decision = false\n",
            "robotics.hardware_in_loop.absence_requires_decision",
        ),
        ("[packs.jetson]\nrunner = 'unexpected'\n", "packs.jetson.runner"),
    ],
)
def test_unknown_or_unsupported_overlay_keys_are_rejected(
    tmp_path: Path, overlay: str, key: str
) -> None:
    """Configuration must reject a declared setting with no supported runtime behavior."""
    (tmp_path / "hex-vision.toml").write_text(overlay, encoding="utf-8")
    with pytest.raises(ConfigError, match=key):
        load_config(root=tmp_path, env={})


def test_declared_extensible_invariant_maps_remain_supported(tmp_path: Path) -> None:
    """The two contract maps deliberately consume reviewed, dynamically named IDs."""
    (tmp_path / "hex-vision.toml").write_text(
        "[contract.invariants]\ninv_99 = 'A reviewed local invariant.'\n",
        encoding="utf-8",
    )
    config = load_config(root=tmp_path, env={})
    assert config.require("contract.invariants.inv_99") == "A reviewed local invariant."


def test_each_supported_policy_flag_changes_the_safety_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flipping the sole supported policy flag changes widening-review behavior."""
    mission_dir = tmp_path / "missions"
    mission_dir.mkdir()
    (mission_dir / "patrol.toml").write_text(
        "\n".join(
            [
                "max_altitude_m = 81",
                "max_horizontal_speed_ms = 8",
                "max_tilt_deg = 25",
                "geofence_radius_m = 250",
                "rtl_battery_percent = 30",
                'failsafe_action = "rtl"',
            ]
        ),
        encoding="utf-8",
    )
    baseline = "\n".join(
        [
            "max_altitude_m = 80",
            "max_horizontal_speed_ms = 8",
            "max_tilt_deg = 25",
            "geofence_radius_m = 250",
            "rtl_battery_percent = 30",
            'failsafe_action = "rtl"',
        ]
    )
    baseline_calls: list[object] = []

    def baseline_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        baseline_calls.append(object())
        return subprocess.CompletedProcess(["git"], 0, stdout=baseline, stderr="")

    monkeypatch.setattr("hexvision.robotics.safety_envelope.subprocess.run", baseline_run)
    gate = SafetyEnvelopeGate()
    widening_required = gate.check(load_config(root=tmp_path, env={}))
    assert widening_required.status is GateStatus.FAILED
    assert any(
        finding.id.endswith("WIDENING") and finding.severity is Severity.BLOCKER
        for finding in widening_required.findings
    )
    assert baseline_calls

    baseline_calls.clear()
    (tmp_path / "hex-vision.toml").write_text(
        "[robotics.safety_envelope]\nwidening_requires_decision = false\n",
        encoding="utf-8",
    )
    widening_not_required = gate.check(load_config(root=tmp_path, env={}))
    assert widening_not_required.status is GateStatus.PASSED
    assert not baseline_calls
