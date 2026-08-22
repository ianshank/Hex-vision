"""Adversarial behavioral tests for runtime skip enforcement and coverage scope."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from coverage import Coverage


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
    shutil.copy(Path(__file__).parents[1] / "conftest.py", root / "conftest.py")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    if decision_log is not None:
        (root / "docs").mkdir()
        (root / "docs" / "decision-log.md").write_text(decision_log, encoding="utf-8")
    (root / "test_guard.py").write_text(test_source, encoding="utf-8")
    environment = dict(os.environ)
    for key in ("COV_CORE_CONFIG", "COV_CORE_DATAFILE", "COV_CORE_SOURCE", "COV_CORE_BRANCH"):
        environment.pop(key, None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
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
