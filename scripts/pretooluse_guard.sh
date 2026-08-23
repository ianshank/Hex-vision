#!/usr/bin/env bash
# Hex-vision L1 PreToolUse first-pass filter. Commit stamp: e0165e4 (2026-08-22).
# It does NOT model shell aliases, command substitutions, environment-supplied Git
# configuration, or shell syntax Python's shlex rejects. It splits plain command
# segments on ;, &&, ||, pipes, and newlines; every push-shaped segment it cannot
# resolve BLOCKS. L2/L3 independently run the same normalizer; L3 CI is authority.
# This script never parses a URL: project venv -> uv -> BLOCK is its only runner chain.
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
')" || block "unanalyzable PreToolUse payload; refusing a possible push-shaped command"

# Python does shell-token awareness only; it does not normalize a remote URL.
SEGMENT_ANALYZER="$(cat <<'PYTHON_ANALYZER'
from __future__ import annotations
import re
import shlex
import sys

raw = sys.stdin.read()
segments: list[str] = []
buffer: list[str] = []
quote = ""
escaped = False
i = 0
while i < len(raw):
    char = raw[i]
    if escaped:
        buffer.append(char)
        escaped = False
    elif char == "\\" and quote != "'":
        buffer.append(char)
        escaped = True
    elif char in "'\"":
        if not quote:
            quote = char
        elif quote == char:
            quote = ""
        buffer.append(char)
    elif not quote and char in ";|\n":
        segments.append("".join(buffer))
        buffer = []
        if char == "|" and i + 1 < len(raw) and raw[i + 1] == "|":
            i += 1
    elif not quote and char == "&" and i + 1 < len(raw) and raw[i + 1] == "&":
        segments.append("".join(buffer))
        buffer = []
        i += 1
    else:
        buffer.append(char)
    i += 1
segments.append("".join(buffer))
if quote or escaped:
    print("UNRESOLVED\tunterminated shell syntax")
    raise SystemExit(0)

for segment in segments:
    if not re.search(r"\bgit\b[\s\S]*\bpush\b", segment):
        continue
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        print("UNRESOLVED\tshlex rejected a push-shaped segment")
        continue
    try:
        git_at = tokens.index("git")
        push_at = tokens.index("push", git_at + 1)
    except ValueError:
        print("UNRESOLVED\tcannot attribute git push tokens")
        continue
    between = tokens[git_at + 1 : push_at]
    if any(token in {"-c", "-C", "--git-dir", "--work-tree"} or token.startswith("-c") for token in between):
        print("UNRESOLVED\tgit globals before push are not safely attributable")
        continue
    remaining = tokens[push_at + 1 :]
    remote = ""
    for token in remaining:
        if token == "--":
            continue
        if token.startswith("-"):
            continue
        remote = token
        break
    print(f"PUSH\t{remote or '<default>'}")
PYTHON_ANALYZER
)"
ANALYSIS="$(printf '%s' "$CMD" | python3 -c "$SEGMENT_ANALYZER" 2>&1)" || block "command segmentation failed for a push-shaped command"

[ -n "$ANALYSIS" ] || exit 0
ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || block "cannot resolve project root for push-shaped command"
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY=("$ROOT/.venv/bin/python")
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY=("$ROOT/.venv/Scripts/python.exe")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --project "$ROOT" python)
else
  block "no project Python or uv runner is available for the shared normalizer"
fi

resolve_default_remote() {
  local current branch remote
  remote="$(git -C "$ROOT" config --get remote.pushDefault 2>/dev/null || true)"
  if [ -z "$remote" ]; then
    branch="$(git -C "$ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    [ -n "$branch" ] && remote="$(git -C "$ROOT" config --get "branch.$branch.remote" 2>/dev/null || true)"
  fi
  printf '%s' "${remote:-origin}"
}

run_normalizer_for_url() {
  local destination="$1"
  local config_count="${GIT_CONFIG_COUNT:-0}"
  (
    cd "$ROOT" || exit 127
    env \
      "GIT_CONFIG_COUNT=$((config_count + 1))" \
      "GIT_CONFIG_KEY_$config_count=remote.hexvision_guard.pushurl" \
      "GIT_CONFIG_VALUE_$config_count=$destination" \
      "${PY[@]}" -m hexvision.cli remotes --json
  )
}

while IFS=$'\t' read -r kind value; do
  [ "$kind" = "PUSH" ] || block "cannot resolve push-shaped segment: $value"
  candidate="$value"
  if [ "$candidate" = "<default>" ]; then
    candidate="$(resolve_default_remote)"
  fi
  destination="$(git -C "$ROOT" remote get-url --push "$candidate" 2>/dev/null || true)"
  # A direct URL is not parsed here. It is passed untouched to the normalizer;
  # an unknown remote name is likewise fail-closed as an invalid destination.
  [ -n "$destination" ] || destination="$candidate"
  [ -n "$destination" ] || block "push-shaped segment has no resolvable destination"
  NORMALIZER_OUTPUT="$(run_normalizer_for_url "$destination" 2>&1)"
  NORMALIZER_RC=$?
  if [ "$NORMALIZER_RC" -ne 0 ]; then
    [ -n "$NORMALIZER_OUTPUT" ] && printf '%s\n' "$NORMALIZER_OUTPUT" >&2
    block "shared normalizer denied or could not inspect push destination (exit $NORMALIZER_RC)"
  fi
done <<EOF_ANALYSIS
$ANALYSIS
EOF_ANALYSIS

exit 0
