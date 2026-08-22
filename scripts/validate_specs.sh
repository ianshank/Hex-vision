#!/usr/bin/env bash
# Hex-vision SPECS gate. Commit stamp: 10b37dd (2026-08-22).
# This validates OpenSpec document structure. It does NOT validate semantic completeness, prose
# quality, or whether a scenario proves production behavior. Tier 1 strict tooling
# checks its own schema; Tier 2 always checks independent traceability structure.
# The strict tool may be absent only because Tier 2 still runs loudly; missing input
# trees, malformed documents, and failed assertions never degrade to a pass.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CHANGES_DIR="$ROOT/openspec/changes"
VALIDATOR="${SPEC_VALIDATOR:-openspec}"

[ -d "$CHANGES_DIR" ] || {
  echo "specs: $CHANGES_DIR does not exist; refusing to validate nothing" >&2
  exit 1
}

if command -v "$VALIDATOR" >/dev/null 2>&1; then
  echo "specs: strict validation via $VALIDATOR" >&2
  "$VALIDATOR" validate "$CHANGES_DIR" --strict
else
  echo "specs: WARNING — strict validator '$VALIDATOR' is not installed." >&2
  echo "specs: structural Tier 2 remains active; install it to close the schema gap." >&2
fi

python3 - "$CHANGES_DIR" <<'PY'
"""Tier 2, intentionally independent of the optional strict validator."""
from __future__ import annotations

import re
import sys
from pathlib import Path

changes_dir = Path(sys.argv[1])
requirement = re.compile(r"\b(R-[A-Za-z0-9][A-Za-z0-9.-]*)\b")
failures: list[str] = []
seen: dict[str, Path] = {}
changes = sorted(path for path in changes_dir.iterdir() if path.is_dir())
if not changes:
    failures.append("no change directories exist")

for change in changes:
    for required in ("proposal.md", "design.md", "tasks.md"):
        path = change / required
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            failures.append(f"{change.name}: missing or empty {required}")
    specs = sorted((change / "specs").glob("*.md")) if (change / "specs").is_dir() else []
    if not specs:
        failures.append(f"{change.name}: missing specs/*.md")
    for spec in specs:
        text = spec.read_text(encoding="utf-8")
        if "## Requirements" not in text:
            failures.append(f"{spec}: missing ## Requirements")
        if "## Acceptance criteria" not in text:
            failures.append(f"{spec}: missing ## Acceptance criteria")
        if not re.search(r"\bWHEN\b[\s\S]*?\bTHEN\b", text, flags=re.IGNORECASE):
            failures.append(f"{spec}: no WHEN/THEN scenario")
        for identifier in requirement.findall(text):
            prior = seen.get(identifier)
            if prior is not None and prior != spec:
                failures.append(f"duplicate requirement id {identifier}: {prior} and {spec}")
            seen[identifier] = spec

if failures:
    print("specs: structural validation FAILED", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    raise SystemExit(1)
print(f"specs: structural validation passed ({len(changes)} change(s), {len(seen)} requirement id(s))")
PY
