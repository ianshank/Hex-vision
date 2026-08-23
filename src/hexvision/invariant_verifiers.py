"""Discover and run behavioral evidence verifiers for contract invariants.

An invariant mapping is a claim, not evidence.  Verifiers are independently
installable entry points so a stack with a different enforcement mechanism can
prove it without teaching the conformance coordinator about that stack.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final, Protocol, cast

from hexvision.config import Config
from hexvision.gates.contract import MakefileAuthorityGate, ZeroSkipAuditGate
from hexvision.gates.model import GateResult
from hexvision.packs.base import TargetSpec

__all__ = [
    "InvariantVerifier",
    "ProbeEvidence",
    "available",
    "clear_registered",
    "load_all",
    "register",
]

_GROUP: Final = "hexvision.invariant_verifiers"
_REGISTERED: dict[str, InvariantVerifier] = {}
_PROBE_FILENAME: Final = "conformance-probe.txt"


@dataclass(frozen=True, slots=True)
class ProbeEvidence:
    """Record what an invariant probe observed so a pass remains auditable."""

    probe: str
    detected: bool
    outcome: str
    reason: str


class InvariantVerifier(Protocol):
    """Prove one invariant's declared mechanism blocks a synthetic violation."""

    @property
    def name(self) -> str:
        """Return the registry key used to replace this verifier in isolated tests."""

    def supports(
        self,
        invariant: str,
        mechanism: str,
        target: TargetSpec | None,
        gate: object | None,
    ) -> bool:
        """Return whether this verifier understands the declared enforcement mechanism."""

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Run a negative probe and return its observed mechanism outcome."""


def register(verifier: InvariantVerifier) -> None:
    """Register an in-process verifier, allowing tests and embedders to replace one proof."""

    _REGISTERED[verifier.name] = verifier


def clear_registered() -> None:
    """Clear in-process verifier replacements so one proof cannot leak into another."""

    _REGISTERED.clear()


def _entry_points() -> dict[str, metadata.EntryPoint]:
    """Resolve verifier entry points using the same dynamic contract as stack packs."""

    points = metadata.entry_points()
    selected = (
        points.select(group=_GROUP)
        if hasattr(points, "select")
        else cast("dict[str, metadata.EntryPoints]", points).get(_GROUP, metadata.EntryPoints(()))
    )
    return {point.name: point for point in selected}


def available() -> tuple[str, ...]:
    """Return installed and in-process verifier names in deterministic order."""

    return tuple(sorted(set(_entry_points()) | set(_REGISTERED)))


def _load(name: str) -> InvariantVerifier:
    """Load one verifier and reject entry points that do not implement its protocol."""

    if name in _REGISTERED:
        return _REGISTERED[name]
    entry = _entry_points()[name]
    try:
        candidate = entry.load()
        verifier = candidate() if isinstance(candidate, type) else candidate
    except Exception as exc:
        raise RuntimeError(
            f"failed to load invariant verifier {name!r}: {type(exc).__name__}: {exc}"
        ) from exc
    if not all(hasattr(verifier, attribute) for attribute in ("name", "supports", "verify")):
        raise RuntimeError(f"invariant verifier entry point {name!r} has an invalid interface")
    return cast(InvariantVerifier, verifier)


def load_all() -> tuple[InvariantVerifier, ...]:
    """Load every verifier so a broken installed proof cannot silently disappear."""

    return tuple(_load(name) for name in available())


def _run(
    arguments: tuple[str, ...], *, cwd: Path, environment: Mapping[str, str] | None = None
) -> str:
    """Run a declared target and retain both streams as the mechanism's reason evidence."""

    env = None if environment is None else {**os.environ, **environment}
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        return f"unable to execute declared mechanism: {exc}"
    return f"exit={completed.returncode}\n{completed.stdout}{completed.stderr}"


def _result_payload(observed: str) -> dict[str, object] | None:
    """Read the final JSON result emitted by a governed CLI target, never its prose."""

    for line in reversed(observed.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _secret_records(
    path: Path, rule_id_field: str, location_fields: tuple[str, ...]
) -> tuple[dict[str, object], ...] | None:
    """Return scanner records only when every record has a rule id and location."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    records = tuple(record for record in payload if isinstance(record, dict))
    if not records or len(records) != len(payload):
        return None
    if any(
        not isinstance(record.get(rule_id_field), str)
        or not record[rule_id_field]
        or any(not record.get(field) for field in location_fields)
        for record in records
    ):
        return None
    return records


def _target_probe_root(config: Config, files: tuple[Path, ...]) -> tempfile.TemporaryDirectory[str]:
    """Copy only policy files needed by a target probe, avoiding mutable checkout state."""

    workspace = tempfile.TemporaryDirectory(prefix="hexvision-conformance-")
    root = Path(workspace.name)
    for source in files:
        destination = root / source.relative_to(config.root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return workspace


def _git(arguments: list[str], root: Path, executable: str) -> bool:
    """Create minimal Git evidence for targets that inspect repository configuration."""

    completed = subprocess.run(
        [executable, *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


@dataclass(frozen=True, slots=True)
class _SecretScanVerifier:
    """Prove a Makefile secrets target rejects a credential-shaped working-tree mutation."""

    name: str = "inv_1"

    def supports(
        self, invariant: str, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> bool:
        """Limit this built-in proof to the standard secrets target."""

        del gate
        return invariant == "INV-1" and mechanism == "secrets" and target is not None

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Plant a configured synthetic credential and run the declared target against it."""

        del mechanism, gate
        if target is None:
            return ProbeEvidence(
                "synthetic working-tree credential", False, "target unavailable", ""
            )
        settings = config.section("contract.conformance")
        policy = config.resolve_path("contract.conformance.secret_policy_path")
        makefile = config.resolve_path("contract.makefile_path")
        with _target_probe_root(config, (makefile, policy)) as workspace:
            root = Path(workspace)
            seed = int(settings["secret_probe_seed"])
            length = int(settings["secret_probe_length"])
            alphabet = string.ascii_letters + string.digits
            generator = random.Random(seed)  # noqa: S311 - deterministic synthetic probe fixture.
            secret = str(settings["secret_probe_prefix"]) + "".join(
                generator.choice(alphabet) for _ in range(length)
            )
            (root / _PROBE_FILENAME).write_text(f"token = {secret}\n", encoding="utf-8")
            report = root / str(settings["secret_report_path"])
            observed = _run(
                target.command,
                cwd=root,
                environment={"GITLEAKS_REPORT": str(report)},
            )
            records = _secret_records(
                report,
                str(settings["secret_report_rule_id_field"]),
                tuple(str(field) for field in settings["secret_report_location_fields"]),
            )
        return ProbeEvidence(
            probe="synthetic working-tree credential",
            detected="exit=0" not in observed and records is not None,
            outcome=observed,
            reason=json.dumps(records, sort_keys=True) if records is not None else "",
        )


@dataclass(frozen=True, slots=True)
class _RemoteVerifier:
    """Prove the declared remotes target rejects a configured unapproved destination."""

    name: str = "inv_3"

    def supports(
        self, invariant: str, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> bool:
        """Limit this built-in proof to the standard remotes Makefile target."""

        del gate
        return invariant == "INV-3" and mechanism == "remotes" and target is not None

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Add an unapproved remote and require the named target to reject it."""

        del mechanism, gate
        if target is None:
            return ProbeEvidence("unapproved Git remote", False, "target unavailable", "")
        makefile = config.resolve_path("contract.makefile_path")
        git_executable = str(config.require("remotes.git_executable"))
        with _target_probe_root(config, (makefile,)) as workspace:
            root = Path(workspace)
            initialized = _git(["init"], root, git_executable)
            arguments = [
                "remote",
                "add",
                "origin",
                str(config.require("contract.conformance.probe_remote")),
            ]
            added = initialized and _git(
                arguments,
                root,
                git_executable,
            )
            environment = {"RUN": f"uv run --project {config.root} --"}
            observed = (
                _run(target.command, cwd=root, environment=environment)
                if added
                else "unable to prepare synthetic unapproved remote"
            )
        payload = _result_payload(observed)
        detected = (
            added
            and payload is not None
            and payload.get("status") == "failed"
            and isinstance(payload.get("findings"), list)
            and bool(payload["findings"])
        )
        return ProbeEvidence(
            probe="unapproved Git remote",
            detected=detected,
            outcome=observed,
            reason=json.dumps(payload, sort_keys=True) if payload is not None else "",
        )


@dataclass(frozen=True, slots=True)
class _HookInstallerVerifier:
    """Prove the declared installer recreates a removed pre-push hook."""

    name: str = "inv_4"

    def supports(
        self, invariant: str, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> bool:
        """Limit this built-in proof to the standard install target."""

        del gate
        return invariant == "INV-4" and mechanism == "install" and target is not None

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Prepare a hookless repository and require the target to install the expected shim."""

        del mechanism, gate
        if target is None:
            return ProbeEvidence("missing pre-push hook", False, "target unavailable", "")
        makefile = config.resolve_path("contract.makefile_path")
        installer = config.resolve_path("contract.conformance.hook_installer_path")
        hook_source = config.resolve_path("contract.conformance.hook_source_path")
        governed_target = str(config.require("contract.conformance.hook_governed_target"))
        make_executable = str(config.require("contract.make_executable"))
        git_executable = str(config.require("remotes.git_executable"))
        with _target_probe_root(config, (makefile, installer, hook_source)) as workspace:
            root = Path(workspace)
            initialized = _git(["init"], root, git_executable)
            environment = {"PM": str(config.require("contract.conformance.probe_package_manager"))}
            observed = (
                _run(target.command, cwd=root, environment=environment)
                if initialized
                else "unable to prepare synthetic hookless repository"
            )
            hook = root / ".git" / "hooks" / "pre-push"
            content = hook.read_text(encoding="utf-8") if hook.is_file() else ""
            installed = (
                hook.is_file()
                and os.access(hook, os.X_OK)
                and f"{make_executable} -C" in content
                and f" {governed_target}" in content
            )
            hook_evidence = (
                json.dumps(
                    {
                        "hook": str(hook.relative_to(root)),
                        "executable": os.access(hook, os.X_OK),
                        "invokes": [make_executable, governed_target],
                    },
                    sort_keys=True,
                )
                if installed
                else ""
            )
        return ProbeEvidence(
            probe="missing pre-push hook",
            detected=initialized and installed and "exit=0" in observed,
            outcome=observed,
            reason=hook_evidence,
        )


@dataclass(frozen=True, slots=True)
class _ZeroSkipVerifier:
    """Prove the registered zero-skip gate reports a synthetic skipped test."""

    name: str = "inv_2"

    def supports(
        self, invariant: str, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> bool:
        """Bind this proof to the actual core gate clause rather than a target name."""

        return invariant == "INV-2" and mechanism == "INV-2" and target is None and gate is not None

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Give the core gate a skipped test and preserve its finding message as evidence."""

        del mechanism, target
        if not isinstance(gate, ZeroSkipAuditGate):
            return ProbeEvidence(
                "synthetic skipped test", False, "wrong gate type", "wrong gate type"
            )
        with tempfile.TemporaryDirectory(prefix="hexvision-conformance-") as workspace:
            root = Path(workspace)
            tests = root / str(config.require("traceability.tests_path"))
            tests.mkdir(parents=True)
            decision_log = root / str(config.require("traceability.decision_log_path"))
            decision_log.parent.mkdir(parents=True)
            decision_log.write_text("", encoding="utf-8")
            skipped_test = (
                "import pytest\n\n"
                "@pytest.mark.skip(reason='conformance probe')\n"
                "def test_probe():\n"
                "    pass\n"
            )
            (tests / "test_probe.py").write_text(
                skipped_test,
                encoding="utf-8",
            )
            from hexvision.config import load_config

            result = gate.check(load_config(root=root))
        return _gate_evidence("synthetic skipped test", result)


@dataclass(frozen=True, slots=True)
class _MakefileAuthorityVerifier:
    """Prove the Makefile-authority gate reports a raw CI command mutation."""

    name: str = "inv_5"

    def supports(
        self, invariant: str, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> bool:
        """Bind this proof to the actual core authority gate clause."""

        return invariant == "INV-5" and mechanism == "INV-5" and target is None and gate is not None

    def verify(
        self, config: Config, mechanism: str, target: TargetSpec | None, gate: object | None
    ) -> ProbeEvidence:
        """Add a configured raw command to a temporary workflow and retain its finding."""

        del mechanism, target
        if not isinstance(gate, MakefileAuthorityGate):
            return ProbeEvidence("raw CI command", False, "wrong gate type", "wrong gate type")
        with tempfile.TemporaryDirectory(prefix="hexvision-conformance-") as workspace:
            root = Path(workspace)
            workflow = root / str(config.require("makefile_authority.workflow_path"))
            workflow.parent.mkdir(parents=True)
            raw_pattern = str(config.require("makefile_authority.raw_command_patterns")[0])
            workflow.write_text(f"jobs:\n  probe:\n    run: {raw_pattern}\n", encoding="utf-8")
            from hexvision.config import load_config

            result = gate.check(load_config(root=root))
        return _gate_evidence("raw CI command", result)


def _gate_evidence(probe: str, result: GateResult) -> ProbeEvidence:
    """Translate a gate result into the invariant evidence record conformance evaluates."""

    reasons = "\n".join(finding.message for finding in result.findings)
    return ProbeEvidence(
        probe=probe,
        detected=result.status.value == "failed" and bool(reasons),
        outcome=json.dumps(result.to_dict(), sort_keys=True),
        reason=reasons,
    )


inv_1: Final = _SecretScanVerifier()
inv_2: Final = _ZeroSkipVerifier()
inv_3: Final = _RemoteVerifier()
inv_4: Final = _HookInstallerVerifier()
inv_5: Final = _MakefileAuthorityVerifier()
