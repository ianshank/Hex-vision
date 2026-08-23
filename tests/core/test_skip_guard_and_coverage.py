"""Adversarial behavioral tests for runtime skip enforcement and coverage scope."""

from __future__ import annotations

import ast
import json
import os
import runpy
import shutil
import sys
from pathlib import Path
from typing import Final

import pytest
from coverage import Coverage

from tests.support.process import run_process

TEST_ROOT: Final = Path(__file__).resolve().parents[1]
# This module owns the one actual child-process call; all other tests delegate to it.
ALLOWED_DIRECT_PROCESS_MODULE: Final = TEST_ROOT / "support" / "process.py"
DIRECT_PROCESS_METHODS: Final = frozenset({"run", "Popen", "call", "check_call", "check_output"})


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
    ("name", "decision_log", "test_source", "expected"),
    [
        (
            "forged",
            "DEC-1 approved\n",
            (
                "# @governance-skip: DEC-999 forged\n"
                "import pytest\n# @governance-skip: DEC-999 forged\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
        ),
        (
            "stale",
            "DEC-2 approved\n",
            (
                "# @governance-skip: DEC-1 stale\n"
                "import pytest\n# @governance-skip: DEC-1 stale\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
        ),
        (
            "no_reason",
            "DEC-1 approved\n",
            "import pytest\n# @governance-skip: DEC-1\n@pytest.mark.skip\ndef test_x(): pass\n",
            1,
        ),
        (
            "unrelated",
            "DEC-1 approved\n",
            (
                "# @governance-skip: DEC-1 unrelated\nVALUE = 1\n"
                "import pytest\n@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            1,
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
        ),
        (
            "authorized",
            "DEC-1 approved\n",
            (
                "# @governance-skip: DEC-1 hardware unavailable\n"
                "import pytest\n# @governance-skip: DEC-1 hardware unavailable\n"
                "@pytest.mark.skip\ndef test_x(): pass\n"
            ),
            0,
        ),
    ],
)
def test_runtime_skip_guard_resolves_test_local_decisions(
    tmp_path: Path,
    name: str,
    decision_log: str | None,
    test_source: str,
    expected: int,
) -> None:
    """A miniature pytest run proves each authorization bypass is rejected behaviorally."""
    del name
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
