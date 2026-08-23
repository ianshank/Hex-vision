"""Adversarial behavioral tests for runtime skip enforcement and coverage scope."""

from __future__ import annotations

import ast
import json
import os
import runpy
import shutil
import sys
from pathlib import Path
from typing import Final, TypeAlias

import pytest
from coverage import Coverage

from hexvision.gates.contract import CoverageFloorGate
from tests.support.process import run_process

TEST_ROOT: Final = Path(__file__).resolve().parents[1]
# This module owns the one actual child-process call; all other tests delegate to it.
ALLOWED_DIRECT_PROCESS_MODULE: Final = TEST_ROOT / "support" / "process.py"
DIRECT_PROCESS_METHODS: Final = frozenset({"run", "Popen", "call", "check_call", "check_output"})
SkipScenario: TypeAlias = tuple[str, str | None, str, int, str]


def _direct_subprocess_call_lines(source: str) -> tuple[int, ...]:
    """Return direct stdlib subprocess call lines without treating patch targets as calls."""
    tree = ast.parse(source)
    subprocess_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "subprocess"
    }
    return tuple(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in subprocess_names
        and node.func.attr in DIRECT_PROCESS_METHODS
    )


def test_every_test_subprocess_spawn_uses_the_shared_hermetic_helper() -> None:
    """No test may bypass the helper and leak irrelevant child coverage data."""
    violations = {
        path.relative_to(TEST_ROOT).as_posix(): _direct_subprocess_call_lines(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(TEST_ROOT.rglob("*.py"))
        if path != ALLOWED_DIRECT_PROCESS_MODULE
        and _direct_subprocess_call_lines(path.read_text(encoding="utf-8"))
    }
    assert violations == {}


def test_subprocess_spawn_meta_guard_rejects_a_direct_call() -> None:
    """The AST guard must reject an actual direct subprocess invocation."""
    source = "import subprocess\nsubprocess.run(['fixture'])\n"
    assert _direct_subprocess_call_lines(source) == (2,)


def test_subprocess_spawn_meta_guard_allows_string_patch_targets() -> None:
    """Patch-target strings mentioning subprocess calls are not process execution."""
    source = 'monkeypatch.setattr("hexvision.robotics.hardware_in_loop.subprocess.run", fake)\n'
    assert _direct_subprocess_call_lines(source) == ()


def test_shared_process_helper_removes_coverage_control_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Python fixture cannot create parallel coverage data after its controls are removed."""
    for key in (
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COV_CORE_SOURCE",
        "COV_CORE_BRANCH",
    ):
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    result = run_process(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "print(','.join(str(key in os.environ) for key in "
                "('COV_CORE_CONFIG', 'COV_CORE_DATAFILE', 'COV_CORE_SOURCE', 'COV_CORE_BRANCH')))"
            ),
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False,False,False,False"
    assert all(
        key in os.environ
        for key in ("COV_CORE_CONFIG", "COV_CORE_DATAFILE", "COV_CORE_SOURCE", "COV_CORE_BRANCH")
    )
    assert not tuple(tmp_path.glob(".coverage.*")), (
        "the helper removed pytest-cov controls, so the behavioral child could not "
        "write incompatible statement-only parallel coverage data"
    )


@pytest.mark.parametrize(
    "scenario",
    [
        (
            "forged",
            "2026-08-22 | DEC-1 | approved | reviewer\n",
            (
                "# @governance-skip: DEC-999 forged\n"
                "import pytest\n# @governance-skip: DEC-999 forged\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
            "has no valid @governance-skip decision",
        ),
        (
            "stale",
            "2026-08-22 | DEC-2 | approved | reviewer\n",
            (
                "# @governance-skip: DEC-1 stale\n"
                "import pytest\n# @governance-skip: DEC-1 stale\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
            "has no valid @governance-skip decision",
        ),
        (
            "no_reason",
            "2026-08-22 | DEC-1 | approved | reviewer\n",
            "import pytest\n# @governance-skip: DEC-1\n@pytest.mark.skip\ndef test_x(): pass\n",
            1,
            "has no valid @governance-skip decision",
        ),
        (
            "unrelated",
            "2026-08-22 | DEC-1 | approved | reviewer\n",
            (
                "# @governance-skip: DEC-1 unrelated\nVALUE = 1\n"
                "import pytest\n@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
            "has no valid @governance-skip decision",
        ),
        (
            "unreadable",
            None,
            (
                "# @governance-skip: DEC-1 approved\n"
                "import pytest\n# @governance-skip: DEC-1 approved\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
            "has no valid @governance-skip decision",
        ),
        (
            "authorized",
            "2026-08-22 | DEC-1 | approved | reviewer\n",
            (
                "# @governance-skip: DEC-1 hardware unavailable\n"
                "import pytest\n# @governance-skip: DEC-1 hardware unavailable\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
            "cites authorized @governance-skip decision DEC-1",
        ),
    ],
)
# Traceability: R-9 [Unresolvable authorization]
def test_runtime_skip_guard_resolves_test_local_decisions(
    tmp_path: Path,
    scenario: SkipScenario,
) -> None:
    """A miniature pytest run proves each authorization bypass is rejected behaviorally."""
    _, decision_log, test_source, expected, reason = scenario
    root = tmp_path
    test_root = Path(__file__).parents[1]
    shutil.copy(test_root / "conftest.py", root / "conftest.py")
    support_root = root / "tests"
    support_root.mkdir()
    shutil.copy(test_root / "__init__.py", support_root / "__init__.py")
    shutil.copytree(test_root / "support", support_root / "support")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    if decision_log is not None:
        (root / "docs").mkdir()
        (root / "docs" / "decision-log.md").write_text(decision_log, encoding="utf-8")
    (root / "test_guard.py").write_text(test_source, encoding="utf-8")
    completed = run_process(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    assert reason in completed.stdout + completed.stderr


def _run_zero_skip_child(
    root: Path, source: str, arguments: list[str] | None = None
) -> tuple[int, str]:
    """Run a pytest child whose only zero-skip plugin is this repository's conftest."""
    test_root = Path(__file__).parents[1]
    shutil.copy(test_root / "conftest.py", root / "conftest.py")
    support_root = root / "tests"
    support_root.mkdir()
    shutil.copy(test_root / "__init__.py", support_root / "__init__.py")
    shutil.copytree(test_root / "support", support_root / "support")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "test_terminal_accounting.py").write_text(source, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", *(arguments or [])]
    completed = run_process(command, cwd=root)
    return completed.returncode, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (
            'import pytest\npytest.importorskip("terminal_accounting_missing_dependency")\n',
            "collection skip recorded",
        ),
        (
            'import pytest\npytest.skip("collection stop", allow_module_level=True)\n',
            "collection skip recorded",
        ),
        (
            (
                "import pytest\n"
                '@pytest.mark.parametrize("value", [])\n'
                "def test_empty(value):\n"
                "    assert value\n"
            ),
            "runtime skip recorded",
        ),
        (
            "import pytest\n\ndef test_runtime_skip():\n    pytest.skip('runtime stop')\n",
            "runtime skip recorded",
        ),
        (
            (
                "import pytest\n"
                "@pytest.mark.skipif(True, reason='conditional stop')\n"
                "def test_conditional_skip():\n"
                "    assert True\n"
            ),
            "runtime skip recorded",
        ),
        (
            (
                "import pytest\n"
                "@pytest.mark.xfail(reason='expected stop')\n"
                "def test_expected_failure():\n"
                "    assert False\n"
            ),
            "XFAIL recorded",
        ),
        (
            (
                "import pytest\n"
                "@pytest.mark.xfail(reason='unexpected success')\n"
                "def test_unexpected_success():\n"
                "    assert True\n"
            ),
            "XPASS recorded",
        ),
        (
            (
                "import pytest\n"
                "def test_dynamic_skip_bypasses_static_ast_name_check():\n"
                "    getattr(pytest, 'skip')('dynamic stop')\n"
            ),
            "runtime skip recorded",
        ),
    ],
    ids=(
        "importorskip-collection",
        "module-skip-collection",
        "empty-parametrize",
        "runtime-skip",
        "skipif",
        "xfail",
        "xpass",
        "dynamic-ast-bypass",
    ),
)
# Traceability: R-9 [Unapproved skip]
def test_terminal_accounting_rejects_every_skip_route(
    tmp_path: Path, source: str, reason: str
) -> None:
    """Pytest reports reject collection and runtime routes, including an AST bypass."""
    returncode, output = _run_zero_skip_child(tmp_path, source)
    assert returncode == 1, output
    assert f"zero-skip terminal accounting failure: {reason}" in output
    if reason == "runtime skip recorded" and "parametrize" in source:
        assert "collected 1 test(s) but executed 0 test body/bodies" in output


def test_terminal_accounting_allows_a_clean_child_suite(tmp_path: Path) -> None:
    """A clean child suite proves terminal enforcement is not a blanket failure."""
    returncode, output = _run_zero_skip_child(
        tmp_path, "def test_clean_execution():\n    assert True\n"
    )
    assert returncode == 0, output
    assert "1 passed" in output


def test_terminal_accounting_rejects_deselection(tmp_path: Path) -> None:
    """Selection filters cannot omit a collected test without a terminal policy failure."""
    returncode, output = _run_zero_skip_child(
        tmp_path,
        ("def test_run():\n    assert True\n\ndef test_omitted():\n    assert True\n"),
        arguments=["-k", "run"],
    )
    assert returncode == 1, output
    assert "zero-skip terminal accounting failure: 1 deselected test(s) recorded" in output


# Traceability: R-18 [Untested source file]
def test_coverage_report_includes_unimported_source_file(tmp_path: Path) -> None:
    """Coverage's denominator includes source files that tests never import."""
    source = tmp_path / "source"
    source.mkdir()
    imported = source / "imported.py"
    unimported = source / "unimported.py"
    imported.write_text("value = 1\n", encoding="utf-8")
    unimported.write_text("value = 2\n", encoding="utf-8")
    report = tmp_path / "coverage.json"
    coverage = Coverage(source=[str(source)], data_file=str(tmp_path / ".coverage"))
    coverage.start()
    runpy.run_path(str(imported))
    coverage.stop()
    coverage.save()
    coverage.json_report(outfile=str(report))
    files = json.loads(report.read_text(encoding="utf-8"))["files"]
    assert any(Path(filename).name == "unimported.py" for filename in files)


def test_coverage_gate_rejects_a_pragma_excluded_source_file(make_config, tmp_repo) -> None:  # type: ignore[no-untyped-def]
    """A source-level pragma cannot make untested executable code look covered."""
    root = tmp_repo()
    source = root / "src" / "untested.py"
    source.parent.mkdir()
    source.write_text(
        "def operationally_untested():  # pragma: no cover\n    return 1\n", encoding="utf-8"
    )
    (root / "coverage.json").write_text(
        json.dumps(
            {
                "files": {
                    "src/untested.py": {
                        "summary": {
                            "num_statements": 0,
                            "percent_covered": 100,
                            "percent_covered_branches": 100,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = CoverageFloorGate().check(make_config(root, None))
    assert result.status.value == "failed"
    assert any(finding.id == "COVERAGE-PRAGMA-src/untested.py-1" for finding in result.findings)
    assert any("coverage pragma" in finding.message for finding in result.findings)
