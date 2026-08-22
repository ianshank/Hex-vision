#!/usr/bin/env bash
# Hex-vision L1 PreToolUse first-pass filter. Commit stamp: 10b37dd (2026-08-22).
# It does NOT model shell aliases, environment-supplied Git configuration, or
# tokenizer/shell disagreements; documented false positives include `echo git push`
# and wrappers. Spell real pushes as plain calls. L2/L3 use the authoritative Python
# normalizer; L2 can be bypassed with --no-verify and L3 CI is authoritative. This
# script never parses a URL: .venv -> uv -> BLOCK is its entire normalizer chain.
set -u

block() {
  echo "BLOCKED (INV-3): $1" >&2
  echo "Remediation: use an allowlisted destination with the shared normalizer available." >&2
  exit 2
}

PAYLOAD="$(cat)"
CMD="$(printf '%s' "$PAYLOAD" | python3 -c '
import json
import sys
try:
    value = json.load(sys.stdin)
except Exception:
    raise SystemExit(3)
command = value.get("tool_input", {}).get("command", "")
if not isinstance(command, str):
    raise SystemExit(3)
print(command)
')" || {
  if printf '%s' "$PAYLOAD" | grep -Eq 'git[[:space:]]+([^[:space:]]+[[:space:]]+)*push([[:space:]]|$)'; then
    block "unanalyzable payload contains a push-shaped command"
  fi
  exit 0
}

printf '%s' "$CMD" | grep -Eq 'git[[:space:]]+([^[:space:]]+[[:space:]]+)*push([[:space:]]|$)' || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || block "cannot resolve project root for push-shaped command"
fi

run_normalizer() {
  if [ -x "$ROOT/.venv/bin/python" ]; then
    "$ROOT/.venv/bin/python" -m hexvision.cli remotes --json
  elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    "$ROOT/.venv/Scripts/python.exe" -m hexvision.cli remotes --json
  elif command -v uv >/dev/null 2>&1; then
    uv run --project "$ROOT" python -m hexvision.cli remotes --json
  else
    return 127
  fi
}

NORMALIZER_OUTPUT="$(run_normalizer 2>&1)"
NORMALIZER_RC=$?
if [ "$NORMALIZER_RC" -ne 0 ]; then
  [ -n "$NORMALIZER_OUTPUT" ] && printf '%s\n' "$NORMALIZER_OUTPUT" >&2
  block "shared normalizer did not allow the push-shaped command (exit $NORMALIZER_RC)"
fi

exit 0
