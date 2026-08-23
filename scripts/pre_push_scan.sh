#!/usr/bin/env bash
# Hex-vision L2 native pre-push release loop. Commit stamp: v3-infra (2026-08-22).
# It validates Git's exact destination through the shared normalizer, then runs
# the authoritative local release chain (`make pre-pr`). `git push --no-verify`,
# an uninstalled hook, and checks a server does not require remain possible
# bypasses, so L3 CI / required workflow remains authoritative. It never parses
# remote URLs: it binds the exact Git-supplied URL into a temporary Git config
# and asks the one Python normalizer to inspect it. Runner chain: project venv,
# then uv, then BLOCK (2).
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
if [ ! -f "$ROOT/Makefile" ]; then
  # This source is also exercised in isolated normalizer fixtures that do not
  # contain a governed Makefile. A governed repository must have one; otherwise
  # no local release chain is available to run.
  printf '%s\n' "pre-push scan: no governed Makefile found; destination check complete" >&2
  exit 0
fi
make -C "$ROOT" -n pre-pr >/dev/null 2>&1 \
  || block "governed Makefile does not provide the required pre-pr release target"
printf '%s\n' "pre-push scan: starting authoritative local release chain (make pre-pr)" >&2
exec make -C "$ROOT" pre-pr
