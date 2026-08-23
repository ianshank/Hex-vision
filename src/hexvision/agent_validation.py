"""Validate governed subagent and skill definitions as deterministic gate inputs.

Agent and skill Markdown files influence implementation and release decisions.
They therefore need the same deterministic, fail-closed treatment as a regular
gate: their schema is policy, their references are checked against the checked
out repository, and every verdict is canonically serialisable for CI evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from hexvision.config import Config, load_config
from hexvision.gates.base import Gate
from hexvision.gates.model import Finding, GateResult, Severity
from hexvision.observability import get_logger

__all__ = [
    "AgentDefinitionValidationGate",
    "DefinitionPolicy",
    "canonical_serialization",
    "load_definition_policy",
    "main",
    "validate_definitions",
]

_LOG: Final = get_logger(__name__)
_POLICY_PATH: Final = Path(__file__).parent / "defaults" / "agent-validation.toml"
_MINIMUM_FRONTMATTER_LINES: Final = 3


@dataclass(frozen=True, slots=True)
class DefinitionPolicy:
    """Configuration that defines valid governed definition artifacts."""

    gate_name: str
    clause: str
    agent_directory: str
    skill_directory: str
    skill_filename: str
    definition_suffix: str
    frontmatter_delimiter: str
    makefile_path: str
    cli_source_path: str
    description_min_length: int
    description_max_length: int
    name_pattern: str
    inline_code_pattern: str
    path_reference_pattern: str
    make_command_pattern: str
    cli_command_pattern: str
    agent_reference_pattern: str
    skill_reference_pattern: str
    schemas: Mapping[str, Mapping[str, str]]
    finding_ids: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _Definition:
    """A discovered definition plus parsed frontmatter and source text."""

    kind: str
    path: Path
    name: str
    fields: Mapping[str, object]
    body: str
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class _AvailableReferences:
    """Existing governed references available to every definition body."""

    make_targets: frozenset[str]
    cli_commands: frozenset[str]
    agents: frozenset[str]
    skills: frozenset[str]


def load_definition_policy(path: Path | None = None) -> DefinitionPolicy:
    """Load the versioned policy file, rejecting malformed policy before inspection."""

    source = _POLICY_PATH if path is None else path
    try:
        with source.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"agent definition policy cannot be read at {source}: {exc}") from exc
    section = payload.get("agent_validation")
    if not isinstance(section, dict):
        raise TypeError("agent definition policy lacks [agent_validation]")
    schemas = section.get("schemas")
    findings = section.get("findings")
    if not isinstance(schemas, dict) or not isinstance(findings, dict):
        raise TypeError("agent definition policy lacks schemas or finding IDs")
    strings = (
        "gate_name",
        "clause",
        "agent_directory",
        "skill_directory",
        "skill_filename",
        "definition_suffix",
        "frontmatter_delimiter",
        "makefile_path",
        "cli_source_path",
        "name_pattern",
        "inline_code_pattern",
        "path_reference_pattern",
        "make_command_pattern",
        "cli_command_pattern",
        "agent_reference_pattern",
        "skill_reference_pattern",
    )
    values = {key: _non_empty_text(section.get(key), key) for key in strings}
    minimum = _positive_integer(section.get("description_min_length"), "description_min_length")
    maximum = _positive_integer(section.get("description_max_length"), "description_max_length")
    if minimum > maximum:
        raise ValueError("description_min_length must not exceed description_max_length")
    typed_schemas: dict[str, Mapping[str, str]] = {}
    for kind, schema in schemas.items():
        if not isinstance(kind, str) or not isinstance(schema, dict):
            raise TypeError("definition schemas must be named tables")
        required = schema.get("required_fields")
        if not isinstance(required, dict) or not required:
            raise ValueError(f"schema {kind!r} lacks required_fields")
        typed_schemas[kind] = {
            _non_empty_text(field, f"schema {kind} field"): _non_empty_text(
                field_type, f"schema {kind} type"
            )
            for field, field_type in required.items()
        }
    return DefinitionPolicy(
        **values,
        description_min_length=minimum,
        description_max_length=maximum,
        schemas=typed_schemas,
        finding_ids={
            _non_empty_text(key, "finding key"): _non_empty_text(value, "finding ID")
            for key, value in findings.items()
        },
    )


def canonical_serialization(result: GateResult) -> bytes:
    """Return stable, locale-independent bytes for deterministic CI comparison."""

    return json.dumps(
        result.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def validate_definitions(
    root: Path,
    policy: DefinitionPolicy | None = None,
    *,
    discovery_order: Sequence[Path] | None = None,
) -> GateResult:
    """Validate all dynamically discovered definitions under ``root``.

    ``discovery_order`` exists solely for deterministic validation probes: callers
    can provide a shuffled list and receive the same canonical result as natural
    discovery. It never acts as an allowlist; every expected artifact must still
    appear exactly once.
    """

    resolved_policy = load_definition_policy() if policy is None else policy
    try:
        definitions, discovery_measurement = _discover(root, resolved_policy, discovery_order)
        make_targets = _make_targets(root / resolved_policy.makefile_path)
        cli_commands = _cli_commands(root / resolved_policy.cli_source_path)
    except (OSError, TypeError, UnicodeDecodeError, ValueError, SyntaxError) as exc:
        return GateResult.blocked(
            resolved_policy.gate_name,
            summary="agent and skill definitions cannot be inspected",
            reason=str(exc),
            clause=resolved_policy.clause,
        )

    findings: list[Finding] = []
    names: dict[str, list[_Definition]] = {}
    for definition in definitions:
        names.setdefault(definition.name, []).append(definition)
        findings.extend(_definition_findings(definition, root, resolved_policy))
    available = _AvailableReferences(
        make_targets=frozenset(make_targets),
        cli_commands=frozenset(cli_commands),
        agents=frozenset(item.name for item in definitions if item.kind == "agent"),
        skills=frozenset(item.name for item in definitions if item.kind == "skill"),
    )
    for definition in definitions:
        findings.extend(_reference_findings(definition, root, resolved_policy, available))
    for name, group in sorted(names.items()):
        if len(group) > 1:
            locations = ", ".join(
                _location(item.path, root)
                for item in sorted(group, key=lambda item: _path_key(item.path))
            )
            findings.append(
                _finding(
                    resolved_policy,
                    "duplicate",
                    f"definition name {name!r} is duplicated across {locations}",
                    locations,
                    "Rename definitions so every agent and skill name is globally unique.",
                )
            )
    findings.sort(key=lambda finding: (finding.id, finding.location or "", finding.message))
    measurements = {
        "definitions": len(definitions),
        "agents": sum(item.kind == "agent" for item in definitions),
        "skills": sum(item.kind == "skill" for item in definitions),
        "make_targets": len(make_targets),
        "cli_commands": len(cli_commands),
        "discovery": discovery_measurement,
    }
    if findings:
        _LOG.error("agent definition validation failed", extra={"findings": len(findings)})
        return GateResult.failed(
            resolved_policy.gate_name,
            summary="agent and skill definitions have governed-artifact findings",
            findings=findings,
            clause=resolved_policy.clause,
            measurements=measurements,
        )
    _LOG.info("agent definition validation passed", extra=measurements)
    return GateResult.passed(
        resolved_policy.gate_name,
        summary="agent and skill definitions are structurally valid",
        clause=resolved_policy.clause,
        measurements=measurements,
    )


class AgentDefinitionValidationGate(Gate):
    """Run governed agent/skill definition validation through the common gate model."""

    def __init__(self, policy_path: Path | None = None) -> None:
        """Allow an explicit policy only for hermetic embedding and test fixtures."""

        self._policy_path = policy_path

    @property
    def name(self) -> str:
        """Return the configured gate identity without duplicating policy in code."""

        return load_definition_policy(self._policy_path).gate_name

    @property
    def clause(self) -> str:
        """Return the configured requirement clause for common gate rendering."""

        return load_definition_policy(self._policy_path).clause

    def check(self, config: Config) -> GateResult:
        """Inspect definitions rooted at the resolved repository configuration."""

        policy = load_definition_policy(self._policy_path)
        return validate_definitions(config.root, policy)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the gate as a standalone Makefile target without editing the main CLI surface.

    The parent integration can later register the gate in ``hexvision.cli``.  A
    module entry point keeps the artifact independently executable immediately,
    while returning the common process exit codes and emitting canonical JSON.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)
    result = AgentDefinitionValidationGate().check(load_config())
    print(canonical_serialization(result).decode("ascii"))
    return int(result.exit_code)


def _discover(
    root: Path, policy: DefinitionPolicy, discovery_order: Sequence[Path] | None
) -> tuple[tuple[_Definition, ...], list[str]]:
    """Discover definitions dynamically while normalising arbitrary enumeration order."""

    expected = _expected_paths(root, policy)
    supplied = tuple(discovery_order) if discovery_order is not None else expected
    if set(supplied) != set(expected):
        raise ValueError(
            "definition discovery order does not contain exactly the discovered definition paths"
        )
    definitions = tuple(
        sorted(
            (_read_definition(root, path, policy) for path in supplied),
            key=_definition_key,
        )
    )
    return definitions, [_location(path, root) for path in sorted(expected, key=_path_key)]


def _expected_paths(root: Path, policy: DefinitionPolicy) -> tuple[Path, ...]:
    """Return every configured agent and skill artifact without filesystem-order dependence."""

    agent_root = root / policy.agent_directory
    skill_root = root / policy.skill_directory
    if not agent_root.is_dir() or not skill_root.is_dir():
        raise ValueError(
            "configured definition directories must exist: "
            f"{policy.agent_directory}, {policy.skill_directory}"
        )
    agents = sorted(agent_root.glob(f"*{policy.definition_suffix}"), key=_path_key)
    skills = sorted(skill_root.glob(f"*/{policy.skill_filename}"), key=_path_key)
    return (*agents, *skills)


def _read_definition(root: Path, path: Path, policy: DefinitionPolicy) -> _Definition:
    """Parse one small YAML-compatible frontmatter block without a runtime dependency."""

    kind = "agent" if path.parent == root / policy.agent_directory else "skill"
    text = path.read_text(encoding="utf-8")
    parse_error: str | None
    try:
        fields, body = _frontmatter(text, policy.frontmatter_delimiter)
    except ValueError as exc:
        fields, body = {}, text
        parse_error = str(exc)
    else:
        parse_error = None
    expected_name = path.stem if kind == "agent" else path.parent.name
    name = fields.get("name") if isinstance(fields.get("name"), str) else expected_name
    return _Definition(
        kind=kind,
        path=path,
        name=str(name),
        fields=fields,
        body=body,
        parse_error=parse_error,
    )


def _frontmatter(text: str, delimiter: str) -> tuple[dict[str, object], str]:
    """Read scalar YAML frontmatter; non-scalar policy fields are intentionally rejected."""

    lines = text.splitlines()
    if len(lines) < _MINIMUM_FRONTMATTER_LINES or lines[0] != delimiter:
        raise ValueError("definition has no opening frontmatter delimiter")
    try:
        end = lines.index(delimiter, 1)
    except ValueError as exc:
        raise ValueError("definition has no closing frontmatter delimiter") from exc
    fields: dict[str, object] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ValueError(f"invalid frontmatter line {line!r}")
        raw_value = value.strip()
        parsed: object = raw_value
        if raw_value.casefold() in {"true", "false"}:
            parsed = raw_value.casefold() == "true"
        elif raw_value.isdecimal():
            parsed = int(raw_value)
        fields[key.strip()] = parsed
    return fields, "\n".join(lines[end + 1 :])


def _definition_findings(
    definition: _Definition, root: Path, policy: DefinitionPolicy
) -> list[Finding]:
    """Apply configured schema, naming, and prose constraints to one definition."""

    findings: list[Finding] = []
    location = _location(definition.path, root)
    if definition.parse_error is not None:
        findings.append(
            _finding(
                policy,
                "frontmatter",
                f"invalid definition frontmatter: {definition.parse_error}",
                location,
                "Restore a complete configured frontmatter block.",
            )
        )
    schema = policy.schemas.get(definition.kind)
    if schema is None:
        findings.append(
            _finding(
                policy,
                "schema",
                f"definition kind {definition.kind!r} has no configured schema",
                location,
                "Add a schema for this discovered definition kind.",
            )
        )
        return findings
    for field, expected_type in sorted(schema.items()):
        actual = definition.fields.get(field)
        if actual is None or not _matches_type(actual, expected_type):
            findings.append(
                _finding(
                    policy,
                    "schema",
                    f"{definition.kind} definition lacks {field!r} with configured type "
                    f"{expected_type!r}",
                    location,
                    "Add the required frontmatter field with the configured type.",
                )
            )
    expected_name = (
        definition.path.stem if definition.kind == "agent" else definition.path.parent.name
    )
    name = definition.fields.get("name")
    if isinstance(name, str) and (
        name != expected_name or re.fullmatch(policy.name_pattern, name) is None
    ):
        findings.append(
            _finding(
                policy,
                "name",
                f"definition name {name!r} must match filename/directory "
                f"{expected_name!r} and configured pattern",
                location,
                "Rename the frontmatter value or its artifact path to the same valid name.",
            )
        )
    description = definition.fields.get("description")
    if isinstance(description, str) and not (
        policy.description_min_length <= len(description) <= policy.description_max_length
    ):
        findings.append(
            _finding(
                policy,
                "description",
                (
                    f"description length {len(description)} is outside configured range "
                    f"{policy.description_min_length}..{policy.description_max_length}"
                ),
                location,
                "Write a non-empty description within the configured length range.",
            )
        )
    return findings


def _reference_findings(
    definition: _Definition,
    root: Path,
    policy: DefinitionPolicy,
    available: _AvailableReferences,
) -> list[Finding]:
    """Resolve configured inline-code, command, and explicit cross-reference forms."""

    findings: list[Finding] = []
    location = _location(definition.path, root)
    inline = re.compile(policy.inline_code_pattern)
    path_pattern = re.compile(policy.path_reference_pattern)
    make_pattern = re.compile(policy.make_command_pattern)
    cli_pattern = re.compile(policy.cli_command_pattern)
    for match in inline.finditer(definition.body):
        value = match.group("reference").strip()
        if path_pattern.fullmatch(value) and not (root / value).exists():
            findings.append(
                _finding(
                    policy,
                    "path",
                    f"dangling file reference {value!r}",
                    location,
                    "Update the definition to an existing repository path.",
                )
            )
        make_match = make_pattern.fullmatch(value)
        if make_match and make_match.group("target") not in available.make_targets:
            target = make_match.group("target")
            findings.append(
                _finding(
                    policy,
                    "make_target",
                    f"dangling Make target {target!r}",
                    location,
                    "Reference a target declared by the configured Makefile.",
                )
            )
        cli_match = cli_pattern.fullmatch(value)
        if cli_match and cli_match.group("command") not in available.cli_commands:
            command = cli_match.group("command")
            findings.append(
                _finding(
                    policy,
                    "cli_command",
                    f"dangling CLI command {command!r}",
                    location,
                    "Reference a command registered by the configured CLI parser.",
                )
            )
    for pattern, known, kind, key in (
        (policy.agent_reference_pattern, available.agents, "agent", "agent_reference"),
        (policy.skill_reference_pattern, available.skills, "skill", "skill_reference"),
    ):
        for match in re.finditer(pattern, definition.body):
            reference = match.group("reference")
            if reference not in known:
                findings.append(
                    _finding(
                        policy,
                        key,
                        f"dangling {kind} reference {reference!r}",
                        location,
                        f"Reference an existing {kind} definition or remove the cross-reference.",
                    )
                )
    return findings


def _make_targets(path: Path) -> set[str]:
    """Read declared Make targets, ignoring recipe lines and preserving no shell state."""

    source = path.read_text(encoding="utf-8")
    return {
        line.partition(":")[0].strip()
        for line in source.splitlines()
        if line
        and not line[0].isspace()
        and ":" in line
        and re.fullmatch(r"[A-Za-z0-9_.-]+", line.partition(":")[0].strip()) is not None
    }


def _cli_commands(path: Path) -> set[str]:
    """Discover argparse subcommands from parser registration rather than a copied list."""

    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.args[0].value
        for node in ast.walk(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _finding(
    policy: DefinitionPolicy, key: str, message: str, location: str, disposition: str
) -> Finding:
    """Build policy-named findings so identifiers also remain configuration-owned."""

    identifier = policy.finding_ids.get(key)
    if identifier is None:
        raise ValueError(f"agent definition policy has no finding ID for {key!r}")
    return Finding(
        id=identifier,
        severity=Severity.MAJOR,
        message=message,
        location=location,
        clause=policy.clause,
        disposition=disposition,
    )


def _matches_type(value: object, expected: str) -> bool:
    """Validate configured scalar frontmatter types without accepting bool as integer."""

    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(expected, False)


def _non_empty_text(value: object, name: str) -> str:
    """Require a non-empty configured string before it affects validation."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"agent definition policy {name!r} must be a non-empty string")
    return value


def _positive_integer(value: object, name: str) -> int:
    """Require positive configuration limits with no bool-as-int ambiguity."""

    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"agent definition policy {name!r} must be a positive integer")
    return value


def _path_key(path: Path) -> str:
    """Return a deterministic portable sort key without locale-sensitive collation."""

    return path.as_posix()


def _definition_key(definition: _Definition) -> tuple[str, str]:
    """Sort definitions by kind and path to make every aggregate repeatable."""

    return definition.kind, _path_key(definition.path)


def _location(path: Path, root: Path) -> str:
    """Render repository-relative locations whenever the artifact is under root."""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
