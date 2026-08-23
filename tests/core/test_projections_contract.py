"""Tests for deterministic projections and concrete invariant gates."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hexvision.config import Config
from hexvision.gates.contract import (
    CoverageFloorGate,
    MakefileAuthorityGate,
    ZeroSkipAuditGate,
    _branch_percentage,
)
from hexvision.projections import check_projections, render_projections


def _module(root) -> None:  # type: ignore[no-untyped-def]
    (root / "fake_data.py").write_text(
        (
            "def data():\n"
            " return {'change_id':'x','generated_from':'fake_data.py',"
            "'milestones':[{'id':'M0','name':'Start','exit_criteria':'done',"
            "'budget_prs':1,'budget_hours':1,'tasks':[{'id':'1','title':'A',"
            "'requirement_ids':['R-1'],'status':'todo','estimate_hours':1,"
            "'depends_on':[]}]}],'requirements':[{'id':'R-1','statement':'s',"
            "'milestone':'M0'}]}\n"
        ),
        encoding="utf-8",
    )


# Traceability: R-7
def test_projection_write_check_and_drift(make_config, tmp_repo, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Generated files round-trip and an edit is detected byte-for-byte."""
    root = tmp_repo(
        "[projections]\ndata_module='fake_data'\n[[projections.outputs]]\nname='one'\npath='out.md'\nrenderer='markdown_roadmap'\n"
    )
    _module(root)
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("fake_data", None)
    config = make_config(root)
    assert check_projections(config, write=True).status.value == "passed"
    assert check_projections(config).status.value == "passed"
    (root / "out.md").write_text("drift", encoding="utf-8")
    result = check_projections(config)
    assert result.status.value == "failed"
    assert "diff" in result.findings[0].context


def test_projection_render_is_deterministic(make_config, tmp_repo, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Two renders of the same source have exactly identical bytes."""
    root = tmp_repo(
        "[projections]\ndata_module='fake_data'\n[[projections.outputs]]\nname='one'\npath='out.csv'\nrenderer='jira_csv'\n"
    )
    _module(root)
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("fake_data", None)
    config = make_config(root)
    assert render_projections(config) == render_projections(config)


def test_projection_loads_repo_data_module_without_pythonpath(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """The console command can load its configured repository planning module directly."""
    root = tmp_repo(
        "[projections]\ndata_module='fake_data'\n[[projections.outputs]]\n"
        "name='one'\npath='out.csv'\nrenderer='jira_csv'\n"
    )
    _module(root)
    sys.modules.pop("fake_data", None)
    assert check_projections(make_config(root), write=True).status.value == "passed"


# Traceability: R-18
def test_coverage_gate_reports_each_floor(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Line and branch deficits are both reported rather than stopping at one file."""
    root = tmp_repo()
    (root / "src").mkdir()
    (root / "coverage.json").write_text(
        json.dumps(
            {
                "files": {
                    "low.py": {
                        "summary": {
                            "num_statements": 100,
                            "percent_covered": 80,
                            "percent_covered_branches": 70,
                        }
                    },
                    "high.py": {
                        "summary": {
                            "num_statements": 100,
                            "percent_covered": 100,
                            "percent_covered_branches": 100,
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    result = CoverageFloorGate().check(make_config(root, None))
    assert result.status.value == "failed"
    assert len(result.findings) == 2


def test_branch_percentage_supports_current_and_legacy_coverage_json() -> None:
    """A no-branch file is fully covered; current and legacy JSON schemas agree."""
    assert _branch_percentage({"num_branches": 0, "covered_branches": 0}) == 100
    assert _branch_percentage({"num_branches": 4, "covered_branches": 3}) == 75
    assert _branch_percentage({"percent_covered_branches": 75}) == 75


def test_coverage_gate_blocks_missing_report(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Coverage evidence absence is distinct from a measured quality failure."""
    assert CoverageFloorGate().check(make_config(tmp_repo(), None)).status.value == "blocked"


def test_coverage_gate_blocks_a_missing_configured_source_root(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """Coverage cannot claim a quality result when its declared source scope is absent."""
    root = tmp_repo()
    (root / "coverage.json").write_text('{"files": {}}', encoding="utf-8")
    result = CoverageFloorGate().check(make_config(root, None))
    assert result.status.value == "blocked"
    assert result.summary == "coverage source root is unavailable"


# Traceability: R-9
def test_zero_skip_and_makefile_authority(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """AST skip audit and workflow authority both reject explicit bypasses."""
    root = tmp_repo()
    (root / "tests").mkdir()
    (root / "tests" / "test_bad.py").write_text(
        "import pytest\ndef test_x():\n pytest.skip('no')\n", encoding="utf-8"
    )
    (root / "docs").mkdir()
    (root / "docs" / "decision-log.md").write_text("DEC-1", encoding="utf-8")
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    workflow.joinpath("ci.yml").write_text("ruff check\n", encoding="utf-8")
    config = make_config(root)
    assert ZeroSkipAuditGate().check(config).status.value == "failed"
    assert MakefileAuthorityGate().check(config).status.value == "failed"


def test_zero_skip_gate_rejects_an_authorized_annotation(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A logged decision remains visible in a failure but cannot authorize a pytest skip."""
    root = tmp_repo()
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_authorized.py").write_text(
        (
            "import pytest\n"
            "# @governance-skip: DEC-1 hardware unavailable\n"
            "@pytest.mark.skip\n"
            "def test_x(): pass\n"
        ),
        encoding="utf-8",
    )
    docs = root / "docs"
    docs.mkdir()
    (docs / "decision-log.md").write_text(
        "2026-08-22 | DEC-1 | approved | reviewer\n", encoding="utf-8"
    )
    result = ZeroSkipAuditGate().check(make_config(root))
    assert result.status.value == "failed"
    assert "authorized @governance-skip decision DEC-1" in result.findings[0].message


def test_projections_block_unknown_renderer_and_malformed_data(
    make_config: Callable[[Path, dict[str, Any] | None], Config],
    tmp_repo: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown renderers and malformed data modules are blocked rather than guessed."""
    root = tmp_repo(
        "[projections]\ndata_module='bad_data'\n[[projections.outputs]]\n"
        "name='one'\npath='out.md'\nrenderer='missing'\n"
    )
    (root / "bad_data.py").write_text("def data():\n return {}\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("bad_data", None)
    assert check_projections(make_config(root, None)).status.value == "blocked"
    (root / "bad_data.py").write_text(
        "def data():\n return {\n"
        "  'change_id':'x','generated_from':'x','milestones':[],'requirements':[]\n"
        " }\n",
        encoding="utf-8",
    )
    sys.modules.pop("bad_data", None)
    assert check_projections(make_config(root, None)).status.value == "blocked"
