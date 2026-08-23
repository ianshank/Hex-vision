"""Exercise command dispatch and entry-point failure behavior as real operations."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import cast

import pytest

from hexvision import cli
from hexvision.config import Config
from hexvision.errors import PackError
from hexvision.gates.model import GateResult
from hexvision.packs import registry


@pytest.mark.parametrize(
    ("args", "attribute"),
    [
        (SimpleNamespace(command="remotes"), "check_remotes"),
        (SimpleNamespace(command="traceability"), "check_traceability"),
        (SimpleNamespace(command="projections", write=False), "check_projections"),
    ],
)
def test_dispatches_top_level_gate_commands(
    monkeypatch: pytest.MonkeyPatch, args: SimpleNamespace, attribute: str
) -> None:
    """Each top-level route invokes the corresponding behavioral implementation."""
    result = GateResult.passed("x", summary="ok")
    monkeypatch.setattr(cli, attribute, lambda *_unused, **_kwargs: result)
    assert cli._dispatch(cast(argparse.Namespace, args), cast(Config, SimpleNamespace())) is result


def test_dispatches_publication_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The release-time route constructs a normal gate rather than special-casing exits."""
    result = GateResult.passed("publication", summary="ok")
    monkeypatch.setattr(cli, "run_gate", lambda _gate, _config: result)
    args = SimpleNamespace(command="publication", destination="github.com/acme/release")

    assert cli._dispatch(cast(argparse.Namespace, args), cast(Config, SimpleNamespace())) is result


def test_dispatches_pack_and_config_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pack and configuration routes serialize their actual discovered data."""
    monkeypatch.setattr(cli, "available", lambda: ("fake",))
    listed = cli._dispatch(
        cast(argparse.Namespace, SimpleNamespace(command="pack", pack_command="list")),
        cast(Config, SimpleNamespace()),
    )
    assert listed.measurements["data"] == ["fake"]
    explanation = SimpleNamespace(key="x", value=1, layer="repo", source="file", shadowed=())
    config = SimpleNamespace(explain=lambda _unused: explanation)
    explained = cli._dispatch(
        cast(
            argparse.Namespace, SimpleNamespace(command="config", config_command="explain", key="x")
        ),
        cast(Config, config),
    )
    assert explained.measurements["data"]["key"] == "x"


def test_dispatches_all_contract_gate_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coverage, zero-skip, and Makefile paths instantiate the intended gate."""
    expected = GateResult.passed("x", summary="ok")
    monkeypatch.setattr(cli, "run_gate", lambda _gate, _config: expected)
    config = SimpleNamespace()
    assert (
        cli._dispatch(
            cast(
                argparse.Namespace,
                SimpleNamespace(command="gate", gate_command="coverage", report=None),
            ),
            cast(Config, config),
        )
        is expected
    )
    assert (
        cli._dispatch(
            cast(argparse.Namespace, SimpleNamespace(command="gate", gate_command="zero-skip")),
            cast(Config, config),
        )
        is expected
    )
    assert (
        cli._dispatch(
            cast(
                argparse.Namespace,
                SimpleNamespace(command="gate", gate_command="makefile-authority"),
            ),
            cast(Config, config),
        )
        is expected
    )


class _BrokenEntry:
    """Entry point fake that proves import failures cannot be silently omitted."""

    def load(self) -> object:
        raise ImportError("broken")


def test_registry_wraps_broken_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """An advertised pack that fails import produces a cause-preserving PackError."""
    registry.clear_registered()
    monkeypatch.setattr(registry, "_entry_points", lambda: {"broken": _BrokenEntry()})
    with pytest.raises(PackError, match="broken"):
        registry.load("broken")


def test_registry_rejects_non_pack_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin returning an arbitrary object cannot masquerade as a pack."""

    class NonPackEntry:
        def load(self) -> object:
            return object()

    monkeypatch.setattr(registry, "_entry_points", lambda: {"bad": NonPackEntry()})
    with pytest.raises(PackError, match="did not return"):
        registry.load("bad")
