"""Hermetic child-process execution for behavioral test fixtures."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

COVERAGE_CONTROL_ENVIRONMENT_KEYS: Final = (
    "COV_CORE_CONFIG",
    "COV_CORE_DATAFILE",
    "COV_CORE_SOURCE",
    "COV_CORE_BRANCH",
)


@contextmanager
def coverage_controls_sanitized() -> Generator[None, None, None]:
    """Temporarily remove pytest-cov controls while a fixture causes a child to start.

    A fixture can exercise production code that starts a process itself instead
    of calling :func:`run_process`. Removing controls from the test process for
    that short interval protects those indirect children as well, while the
    ``finally`` block preserves the parent branch measurement afterward.
    """
    removed_controls = {
        key: os.environ.pop(key) for key in COVERAGE_CONTROL_ENVIRONMENT_KEYS if key in os.environ
    }
    try:
        yield
    finally:
        os.environ.update(removed_controls)


def run_process(
    arguments: list[str], *, cwd: Path, input_text: str = "", env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a black-box fixture without contaminating the parent's branch coverage.

    pytest-cov starts coverage in inherited Python children through ``COV_CORE_*``
    variables. These children are behavioral fixtures, so their statement-only
    data is both irrelevant to and incompatible with the parent's branch
    measurement; removing the control variables prevents invalid parallel data.
    """
    with coverage_controls_sanitized():
        merged_env = os.environ.copy()
        if env is not None:
            merged_env.update(env)
        for key in COVERAGE_CONTROL_ENVIRONMENT_KEYS:
            merged_env.pop(key, None)
        return subprocess.run(
            arguments,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=merged_env,
        )
