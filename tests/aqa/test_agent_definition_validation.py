"""Behavioral tests for deterministic governed agent and skill definition validation."""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from hexvision import agent_validation
from hexvision.agent_validation import (
    AgentDefinitionValidationGate,
    canonical_serialization,
    load_definition_policy,
    main,
    validate_definitions,
)
from hexvision.config import load_config
from hexvision.errors import ExitCode
from hexvision.gates.model import GateStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_SOURCE = REPO_ROOT / "src" / "hexvision" / "defaults" / "agent-validation.toml"


def _definition(name: str, *, tools: bool = False, body: str = "") -> str:
    """Build one schema-valid definition fixture with a configurable governed body."""

    tools_line = "tools: Read, Grep\n" if tools else ""
    return (
        "---\n"
        f"name: {name}\n"
        "description: A governed definition with enough descriptive detail.\n"
        f"{tools_line}"
        "---\n"
        f"{body}\n"
    )


def _root(tmp_path: Path) -> Path:
    """Create the smallest repository that exposes real Make and CLI declarations."""

    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "release-skill").mkdir(parents=True)
    (tmp_path / "src" / "hexvision").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[tool.hexvision]\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("pre-pr:\nconformance:\n", encoding="utf-8")
    (tmp_path / "src" / "hexvision" / "cli.py").write_text(
        'commands.add_parser("conformance")\n', encoding="utf-8"
    )
    (tmp_path / ".claude" / "agents" / "release-agent.md").write_text(
        _definition("release-agent", tools=True, body="Use `make pre-pr`."), encoding="utf-8"
    )
    (tmp_path / ".claude" / "skills" / "release-skill" / "SKILL.md").write_text(
        _definition("release-skill", body="Use `hexvision conformance`."), encoding="utf-8"
    )
    return tmp_path


def test_validator_is_byte_deterministic_across_repeated_and_shuffled_discovery(
    tmp_path: Path,
) -> None:
    """Enterprise proof: a shuffled discovery order cannot alter canonical gate evidence."""

    root = _root(tmp_path)
    policy = load_definition_policy(POLICY_SOURCE)
    paths = [
        *sorted((root / ".claude" / "agents").glob("*.md")),
        *sorted((root / ".claude" / "skills").glob("*/SKILL.md")),
    ]
    shuffled = list(paths)
    random.Random(7).shuffle(shuffled)  # noqa: S311 - fixed deterministic shuffle probe.

    first = canonical_serialization(validate_definitions(root, policy))
    second = canonical_serialization(validate_definitions(root, policy))
    reordered = canonical_serialization(
        validate_definitions(root, policy, discovery_order=shuffled)
    )

    assert first == second == reordered
    assert b'"status":"passed"' in first
    assert b'"exit_code":0' in first


def test_validator_reports_every_dangling_governed_reference_with_finding_and_exit_code(
    tmp_path: Path,
) -> None:
    """Definitions are release inputs: stale path, command, and cross-references fail loudly."""

    root = _root(tmp_path)
    agent = root / ".claude" / "agents" / "release-agent.md"
    agent.write_text(
        _definition(
            "release-agent",
            tools=True,
            body=(
                "`src/missing.py` `make vanished` `hexvision vanished` "
                "@agent:vanished @skill:vanished"
            ),
        ),
        encoding="utf-8",
    )

    result = validate_definitions(root, load_definition_policy(POLICY_SOURCE))

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    findings = {finding.id: finding.message for finding in result.findings}
    assert findings["AQA-DEF-PATH"] == "dangling file reference 'src/missing.py'"
    assert findings["AQA-DEF-MAKE"] == "dangling Make target 'vanished'"
    assert findings["AQA-DEF-CLI"] == "dangling CLI command 'vanished'"
    assert findings["AQA-DEF-AGENT-REF"] == "dangling agent reference 'vanished'"
    assert findings["AQA-DEF-SKILL-REF"] == "dangling skill reference 'vanished'"


def test_validator_treats_malformed_definition_as_failed_not_blocked(tmp_path: Path) -> None:
    """A readable broken definition was inspected, so it is a FAILED finding, not BLOCKED."""

    root = _root(tmp_path)
    (root / ".claude" / "agents" / "release-agent.md").write_text(
        "name: release-agent\n", encoding="utf-8"
    )

    result = validate_definitions(root, load_definition_policy(POLICY_SOURCE))

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    assert any(
        finding.id == "AQA-DEF-FRONTMATTER" and "opening frontmatter delimiter" in finding.message
        for finding in result.findings
    )


def test_validator_enforces_configured_schema_name_and_duplicate_constraints(
    tmp_path: Path,
) -> None:
    """Schema policy changes, not test branches, govern names, types, and duplicate prevention."""

    root = _root(tmp_path)
    (root / ".claude" / "agents" / "release-agent.md").write_text(
        _definition("different-name", body="no string tools field"), encoding="utf-8"
    )
    (root / ".claude" / "skills" / "release-skill" / "SKILL.md").write_text(
        _definition("different-name"), encoding="utf-8"
    )

    result = validate_definitions(root, load_definition_policy(POLICY_SOURCE))

    assert result.status is GateStatus.FAILED
    assert result.exit_code is ExitCode.FAILED
    assert {finding.id for finding in result.findings} >= {
        "AQA-DEF-SCHEMA",
        "AQA-DEF-NAME",
        "AQA-DEF-DUPLICATE",
    }
    assert any("configured type 'string'" in finding.message for finding in result.findings)


def test_gate_uses_configured_repository_root_not_process_working_directory(tmp_path: Path) -> None:
    """The gate validates the checkout represented by Config, preserving worktree isolation."""

    root = _root(tmp_path)
    shutil.copy(POLICY_SOURCE, tmp_path / "agent-validation.toml")

    result = AgentDefinitionValidationGate(tmp_path / "agent-validation.toml").check(
        load_config(root=root)
    )

    assert result.status is GateStatus.PASSED
    assert result.exit_code is ExitCode.OK
    assert result.measurements["definitions"] == 2


def test_standalone_target_returns_common_exit_and_canonical_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Makefile-facing entry point needs no main-CLI wiring to return gate evidence."""

    monkeypatch.chdir(REPO_ROOT)

    assert main([]) == int(ExitCode.OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == GateStatus.PASSED.value
    assert payload["exit_code"] == int(ExitCode.OK)


def test_policy_and_discovery_preconditions_fail_closed_with_precise_reasons(
    tmp_path: Path,
) -> None:
    """Unreadable policy and incomplete discovery are blocked before a definition can be trusted."""

    absent = tmp_path / "absent-policy.toml"
    with pytest.raises(ValueError, match="policy cannot be read"):
        load_definition_policy(absent)

    root = tmp_path / "incomplete"
    root.mkdir()
    result = validate_definitions(root, load_definition_policy(POLICY_SOURCE))

    assert result.status is GateStatus.BLOCKED
    assert result.exit_code is ExitCode.BLOCKED
    assert "configured definition directories must exist" in result.findings[0].message


def test_parser_and_policy_helpers_reject_malformed_governance_inputs(tmp_path: Path) -> None:
    """Malformed scalar grammar and invalid policy constraints cannot silently change validation."""

    with pytest.raises(ValueError, match="closing frontmatter delimiter"):
        agent_validation._frontmatter("---\nname: one\nbody\n", "---")
    with pytest.raises(ValueError, match="invalid frontmatter line"):
        agent_validation._frontmatter("---\ninvalid\n---\n", "---")
    fields, _ = agent_validation._frontmatter(
        "---\nname: one\nenabled: true\nlimit: 4\n---\n", "---"
    )
    assert fields == {"name": "one", "enabled": True, "limit": 4}
    assert agent_validation._matches_type(True, "integer") is False
    assert (
        agent_validation._location(tmp_path / "outside.md", tmp_path / "root")
        == (tmp_path / "outside.md").as_posix()
    )

    bad_policy = tmp_path / "bad-policy.toml"
    bad_policy.write_text("[agent_validation]\ndescription_min_length=2\n", encoding="utf-8")
    with pytest.raises(TypeError, match=r"lacks schemas or finding IDs"):
        load_definition_policy(bad_policy)


def test_policy_limits_schema_absence_and_discovery_tampering_are_explicit_findings(
    tmp_path: Path,
) -> None:
    """Policy grammar and discovery completeness are executable governance constraints."""

    root = _root(tmp_path)
    policy = load_definition_policy(POLICY_SOURCE)
    gate = AgentDefinitionValidationGate(POLICY_SOURCE)
    assert (gate.name, gate.clause) == ("agent-validation", "AQA-AGENT-VALIDATION")

    reversed_limits = tmp_path / "reversed-policy.toml"
    reversed_limits.write_text(
        POLICY_SOURCE.read_text(encoding="utf-8").replace(
            "description_min_length = 24", "description_min_length = 241"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not exceed"):
        load_definition_policy(reversed_limits)

    agent = root / ".claude" / "agents" / "release-agent.md"
    result = validate_definitions(root, policy, discovery_order=[agent])
    assert result.status is GateStatus.BLOCKED
    assert result.exit_code is ExitCode.BLOCKED
    assert "does not contain exactly" in result.findings[0].message

    no_agent_schema = replace(policy, schemas={"skill": policy.schemas["skill"]})
    result = validate_definitions(root, no_agent_schema)
    assert result.status is GateStatus.FAILED
    assert any(
        finding.id == "AQA-DEF-SCHEMA" and "has no configured schema" in finding.message
        for finding in result.findings
    )

    with pytest.raises(ValueError, match="no finding ID"):
        agent_validation._finding(replace(policy, finding_ids={}), "name", "x", "x", "x")
