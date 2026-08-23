"""Regression: the CLI, not Make, is the authority for the four-state exit contract.

Incident this guards
--------------------
The harness advertises four distinct verdicts with distinct process exit codes:
0 OK, 1 FAILED (looked and found a problem), 2 BLOCKED (could not look), 3 USAGE.
The distinction between FAILED and BLOCKED is the project's central claim, because
a check that could not run must never be mistaken for a check that ran cleanly.

During the third review pass the harness was found to be running every gate
through ``make`` in both the local workflow and all nine CI jobs. GNU Make exits
2 for any failed recipe regardless of what the recipe's own exit code was, so a
gate reporting FAILED (1) reached the shell, CI, and any automated consumer as 2,
which is this project's code for BLOCKED. The four-state contract was therefore
unobservable through the interface the project told operators to use, and CI could
not have told a real failure apart from an unavailable scanner.

Make is kept as the convenience runner because it encodes the ordering authority,
but it is not the verdict authority. These tests pin both halves of that split so
neither can drift: Make's collapsing is asserted as a known property rather than
relied upon, and the CLI is asserted to carry the real codes.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from hexvision.gates.model import GateStatus
from tests.support.process import run_process

_MAKE_FAILURE_EXIT = 2
_GATE_FAILED_EXIT = 1


def _make() -> str:
    resolved = shutil.which("make")
    assert resolved is not None, "make must be present to assert its exit behaviour"
    return resolved


def test_make_cannot_convey_a_failed_verdict(tmp_path: Path) -> None:
    """GNU Make reports 2 for a recipe that exited 1, erasing FAILED.

    This is asserted against a synthetic Makefile rather than a real gate so the
    property is attributed to Make itself and stays true when gate behaviour
    changes.
    """
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "failed:\n\t@sh -c 'exit 1'\nblocked:\n\t@sh -c 'exit 2'\n",
        encoding="utf-8",
    )
    failed = run_process([_make(), "-C", str(tmp_path), "failed"], cwd=tmp_path)
    blocked = run_process([_make(), "-C", str(tmp_path), "blocked"], cwd=tmp_path)
    assert failed.returncode == _MAKE_FAILURE_EXIT
    assert blocked.returncode == _MAKE_FAILURE_EXIT
    assert failed.returncode == blocked.returncode, (
        "Make flattens 1 and 2 to the same code, so a Make exit status must never "
        "be read as a Hex-vision verdict"
    )


def test_cli_preserves_the_distinction_make_erases(tmp_path: Path) -> None:
    """The CLI returns the gate's own code, so FAILED and BLOCKED stay separable."""
    usage = run_process([sys.executable, "-m", "hexvision.cli", "no-such-command"], cwd=tmp_path)
    assert usage.returncode not in {0, _GATE_FAILED_EXIT}, (
        "a usage error must not be reported as OK or as a gate failure"
    )
    blocked = run_process(
        [sys.executable, "-m", "hexvision.cli", "gate", "coverage", "--report", "absent.json"],
        cwd=tmp_path,
    )
    assert blocked.returncode == GateStatus.BLOCKED.exit_code, (
        "an unreadable coverage report means the gate could not look, which is "
        "BLOCKED, and the CLI must say so in its exit status"
    )


def test_every_status_maps_to_a_distinct_documented_exit_code() -> None:
    """No two non-clean verdicts may share an exit code."""
    codes = {status: status.exit_code for status in GateStatus}
    assert codes[GateStatus.PASSED] == 0
    assert codes[GateStatus.FAILED] == _GATE_FAILED_EXIT
    assert codes[GateStatus.BLOCKED] == _MAKE_FAILURE_EXIT
    assert codes[GateStatus.FAILED] != codes[GateStatus.BLOCKED], (
        "collapsing FAILED into BLOCKED, or the reverse, destroys the distinction "
        "between a gate that found a problem and a gate that never ran"
    )
