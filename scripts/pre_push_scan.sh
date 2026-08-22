#!/usr/bin/env bash
# Hex-vision L2 native pre-push body. Commit stamp: 10b37dd (2026-08-22).
# It is fast feedback only: `git push --no-verify`, an uninstalled hook, and
# destination changes outside the checkout are not caught here. L3 CI and L4
# required workflow are authoritative. It never parses remote URLs: its verdict
# comes only from `python -m hexvision.cli remotes --json`, via .venv then uv;
# absent runners and every non-pass verdict end in BLOCK (exit 2).
set -u

block() {
  echo "BLOCKED (INV-3): $1" >&2
  echo "Remediation: restore the Python normalizer and repository policy, then retry." >&2
  exit 2
}

[ "$#" -ge 2 ] || block "pre-push invocation is missing <remote-name> <remote-url>"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || block "cannot resolve repository root"

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
  block "shared normalizer did not allow this push (exit $NORMALIZER_RC)"
fi

printf '%s\n' "pre-push scan: shared normalizer allowed the configured push destination" >&2
exit 0
