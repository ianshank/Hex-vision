#!/usr/bin/env bash
# Hex-vision L2 native pre-push body. Commit stamp: e0165e4 (2026-08-22).
# It is fast feedback only: `git push --no-verify`, an uninstalled hook, and
# destination changes outside the checkout are not caught here. L3 CI and L4
# required workflow are authoritative. It never parses remote URLs: it binds the
# exact Git-supplied URL into a temporary Git config and asks the one Python
# normalizer to inspect it. Runner chain: project venv, then uv, then BLOCK (2).
set -u

block() {
  echo "BLOCKED (INV-3): $1" >&2
  echo "Remediation: restore the Python normalizer and repository policy, then retry." >&2
  exit 2
}

[ "$#" -ge 2 ] || block "pre-push invocation is missing <remote-name> <remote-url>"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || block "cannot resolve repository root"
REMOTE_URL="$2"
[ -n "$REMOTE_URL" ] || block "Git supplied an empty push destination"

run_normalizer_for_url() {
  local destination="$1"
  local config_count="${GIT_CONFIG_COUNT:-0}"
  # The normalizer's public CLI checks configured Git URLs. Add the exact URL as
  # a synthetic remote, rather than parsing it in Bash or trusting list-mode 0.
  # Existing per-command Git config is preserved at higher indexes.
  (
    cd "$ROOT" || exit 127
    env \
      "GIT_CONFIG_COUNT=$((config_count + 1))" \
      "GIT_CONFIG_KEY_$config_count=remote.hexvision_guard.pushurl" \
      "GIT_CONFIG_VALUE_$config_count=$destination" \
      "${PY[@]}" -m hexvision.cli remotes --json
  )
}

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY=("$ROOT/.venv/bin/python")
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY=("$ROOT/.venv/Scripts/python.exe")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --project "$ROOT" python)
else
  block "no project Python or uv runner is available for the shared normalizer"
fi

NORMALIZER_OUTPUT="$(run_normalizer_for_url "$REMOTE_URL" 2>&1)"
NORMALIZER_RC=$?
if [ "$NORMALIZER_RC" -ne 0 ]; then
  [ -n "$NORMALIZER_OUTPUT" ] && printf '%s\n' "$NORMALIZER_OUTPUT" >&2
  block "shared normalizer denied or could not inspect the supplied push URL (exit $NORMALIZER_RC)"
fi

printf '%s\n' "pre-push scan: shared normalizer allowed Git's supplied destination" >&2
exit 0
