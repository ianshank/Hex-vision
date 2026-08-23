"""The stdlib-only command-line front door for Hex-vision governance checks.

All commands serialize the same result model so people receive readable output
and CI receives one stable JSON object without diagnostics contaminating stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from hexvision.config import Config, load_config
from hexvision.conformance import check_pack
from hexvision.errors import ExitCode, HexVisionError
from hexvision.gates.base import run_gate
from hexvision.gates.contract import CoverageFloorGate, MakefileAuthorityGate, ZeroSkipAuditGate
from hexvision.gates.model import GateResult
from hexvision.gates.publication import PublicationGate
from hexvision.orchestration import run_active_domain_gates
from hexvision.packs.registry import available, load
from hexvision.projections import check_projections
from hexvision.remotes import check_remotes
from hexvision.traceability import check_traceability

__all__ = ["build_parser", "main"]

_JSON_HELP: Final = "emit exactly one JSON object to stdout"


def _json_argument(parser: argparse.ArgumentParser) -> None:
    """Add the identical output contract to every executable subcommand."""
    parser.add_argument("--json", action="store_true", dest="as_json", help=_JSON_HELP)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser without executing work, which keeps CLI dispatch testable."""
    parser = argparse.ArgumentParser(prog="hexvision")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("remotes", "traceability"):
        child = sub.add_parser(name)
        _json_argument(child)
    publication = sub.add_parser("publication")
    publication.add_argument(
        "destination",
        nargs="?",
        help="publication destination; defaults to publication.default_destination",
    )
    _json_argument(publication)
    projections = sub.add_parser("projections")
    mode = projections.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    _json_argument(projections)
    conformance = sub.add_parser("conformance")
    conformance.add_argument("--pack", required=True)
    _json_argument(conformance)
    gate = sub.add_parser("gate")
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)
    coverage = gate_sub.add_parser("coverage")
    coverage.add_argument("--report", type=Path)
    _json_argument(coverage)
    for name in ("zero-skip", "makefile-authority"):
        child = gate_sub.add_parser(name)
        _json_argument(child)
    pack = sub.add_parser("pack")
    pack_sub = pack.add_subparsers(dest="pack_command", required=True)
    list_parser = pack_sub.add_parser("list")
    _json_argument(list_parser)
    show = pack_sub.add_parser("show")
    show.add_argument("name")
    _json_argument(show)
    gates = pack_sub.add_parser("gates")
    gates.add_argument("--all-active", action="store_true", required=True)
    _json_argument(gates)
    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    dump = config_sub.add_parser("dump")
    _json_argument(dump)
    explain = config_sub.add_parser("explain")
    explain.add_argument("key")
    _json_argument(explain)
    return parser


def _render_result(result: GateResult, as_json: bool) -> None:
    """Write only result data to stdout; error diagnostics remain the runner's job."""
    if as_json:
        print(json.dumps(result.to_dict(), sort_keys=True))
        return
    print(f"{result.gate}: {result.status.value} — {result.summary}")
    for finding in result.findings:
        location = f" ({finding.location})" if finding.location else ""
        print(f"{finding.severity.label} {finding.id}{location}: {finding.message}")


def _data_result(name: str, data: Any) -> GateResult:
    """Wrap non-gate CLI output in the normal result shape for uniform exit behavior."""
    return GateResult.passed(name, summary=f"{name} completed", measurements={"data": data})


def _dispatch(  # noqa: PLR0911 - each explicit branch is a public CLI route.
    args: argparse.Namespace, config: Config
) -> GateResult:
    """Map parsed command state to one auditable result-producing operation."""
    if args.command == "remotes":
        return check_remotes(config)
    if args.command == "traceability":
        return check_traceability(config)
    if args.command == "publication":
        return run_gate(PublicationGate(args.destination), config)
    if args.command == "projections":
        return check_projections(config, write=bool(args.write))
    if args.command == "conformance":
        return check_pack(config, load(args.pack))
    if args.command == "gate":
        if args.gate_command == "coverage":
            return run_gate(CoverageFloorGate(args.report), config)
        if args.gate_command == "zero-skip":
            return run_gate(ZeroSkipAuditGate(), config)
        return run_gate(MakefileAuthorityGate(), config)
    if args.command == "pack":
        if args.pack_command == "list":
            return _data_result("pack-list", list(available()))
        if args.pack_command == "show":
            return _data_result("pack-show", load(args.name).describe(config))
        return run_active_domain_gates(config)
    if args.config_command == "dump":
        return _data_result("config-dump", config.as_dict())
    explanation = config.explain(args.key)
    return _data_result(
        "config-explain",
        {
            "key": explanation.key,
            "value": explanation.value,
            "layer": explanation.layer,
            "source": explanation.source,
            "shadowed": list(explanation.shadowed),
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI command and return the contract exit code instead of exiting.

    Returning an integer lets embedding callers and tests own process lifetime;
    the console script wrapper still converts it to a conventional process code.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        config = load_config()
        result = _dispatch(args, config)
    except HexVisionError as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
    except SystemExit as exc:
        # argparse raises SystemExit for two different situations and they must
        # not collapse into one code. A malformed invocation carries a non-zero
        # code and becomes USAGE, which prevents a no-argument direct call from
        # looking like a successful no-op. But --help and --version also raise
        # SystemExit, with code 0, and those are successful requests: reporting
        # a failure for `hexvision --help` would make the CLI unusable inside a
        # shell that checks exit status.
        if exc.code in (0, None):
            return int(ExitCode.OK)
        return int(ExitCode.USAGE)
    except Exception as exc:
        print(f"hexvision blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        return int(ExitCode.BLOCKED)
    _render_result(result, bool(getattr(args, "as_json", False)))
    return int(result.exit_code)


if __name__ == "__main__":  # pragma: no cover - console entry point delegates to main.
    raise SystemExit(main())
