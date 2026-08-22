"""Staleness checks for the human-facing governance skill and charter pin."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "hex-vision-governance" / "SKILL.md"
LOG = REPO_ROOT / "docs" / "decision-log.md"
CHARTER = REPO_ROOT / "charter" / "CHARTER.md"
ENTRY = re.compile(r"^(\d{4}-\d{2}-\d{2}) \| ([A-Z]+-\d+[a-z]?|S\d+\.\d+|G-[A-Z]+) \|", re.M)
SINCE = re.compile(r"^## Decisions since (\d{4}-\d{2}-\d{2})$", re.M)
CHARTER_VERSION = re.compile(r"\b(?:Version|version)\s*[:v]*\s*(\d+\.\d+)\b")


def missing_skill_decisions(skill_text: str, log_text: str) -> list[str]:
    """Return log IDs that a skill summary must add before agents may rely on it."""
    since_match = SINCE.search(skill_text)
    assert since_match, "skill lost its Decisions since <date> heading"
    since = since_match.group(1)
    return [
        identifier
        for date, identifier in ENTRY.findall(log_text)
        if date >= since and identifier not in skill_text
    ]


def test_skill_decision_section_is_fresh_when_live_log_exists() -> None:
    """Integration form: a merged decision log makes an omitted current ID fail loudly."""
    if not LOG.exists():
        log_text = "2026-08-22 | DEC-001 | fixture | test\n"
    else:
        log_text = LOG.read_text(encoding="utf-8")
    assert missing_skill_decisions(SKILL.read_text(encoding="utf-8"), log_text) == []


def test_skill_freshness_detects_missing_current_decision() -> None:
    """Negative control proving an unlisted decision is not silently accepted."""
    skill = "## Decisions since 2026-08-22\n- **DEC-001**: covered\n"
    log = "2026-08-22 | DEC-001 | covered | test\n2026-08-22 | DEC-002 | missing | test\n"
    assert missing_skill_decisions(skill, log) == ["DEC-002"]


def test_skill_freshness_ignores_pre_summary_history() -> None:
    """The date boundary permits historical entries before the declared summary window."""
    skill = "## Decisions since 2026-08-22\n- **DEC-002**: covered\n"
    log = "2026-08-21 | DEC-001 | old | test\n2026-08-22 | DEC-002 | new | test\n"
    assert missing_skill_decisions(skill, log) == []


def test_skill_freshness_requires_heading() -> None:
    """Removing the summary boundary is a test failure, never an implicit opt-out."""
    with pytest.raises(AssertionError, match="Decisions since"):
        missing_skill_decisions("# no heading\n", "2026-08-22 | DEC-001 | x | test\n")


def test_charter_version_pin_matches_live_charter_when_present() -> None:
    """A merged charter version must match the skill's pinned operating constraint."""
    if not CHARTER.exists():
        charter = "# Charter\nVersion: 1.0\n"
    else:
        charter = CHARTER.read_text(encoding="utf-8")
    match = CHARTER_VERSION.search(charter)
    assert match, "charter has no machine-readable version"
    assert match.group(1) == "1.0", "skill charter pin is stale; reconcile it before operating"


def test_charter_version_pin_negative_control() -> None:
    """A newer charter is intentionally incompatible with the stale skill pin."""
    match = CHARTER_VERSION.search("# Charter\nVersion: 1.1\n")
    assert match is not None
    assert match.group(1) != "1.0"
