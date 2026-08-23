#!/usr/bin/env bash
# Hex-vision hook installer (INV-4). Commit stamp: e0165e4 (2026-08-22).
# It installs the L1 fast pre-commit hook and L2 pre-push release shim. It
# does not make --no-verify safe, protect a checkout never installed, or replace L3
# CI/L4 policy. It preserves unrelated hooks, supports .git files in worktrees
# through git --git-path, and fails closed if Git cannot identify an installation
# destination.
set -euo pipefail

usage() { echo "usage: install_hooks.sh [--repo <path>]" >&2; exit 2; }
REPO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) shift; [ "$#" -gt 0 ] || usage; REPO="$1" ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
  shift
done
if [ -z "$REPO" ]; then
  REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "install_hooks: not in a git worktree" >&2; exit 1; }
fi
ROOT="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" || { echo "install_hooks: $REPO is not a git worktree" >&2; exit 1; }
SOURCE="$ROOT/scripts/pre_push_scan.sh"
[ -f "$SOURCE" ] || { echo "install_hooks: $SOURCE is missing" >&2; exit 1; }
PRE_COMMIT_SOURCE="$ROOT/scripts/pre_commit_check.sh"
# Git, rather than shell prefix rules, resolves linked-worktree gitdirs and both
# absolute and relative core.hooksPath values. --path-format avoids ROOT/<absolute>
# mistakes and makes this result safe to create directly.
HOOK_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-path hooks)" || { echo "install_hooks: cannot resolve hooks directory" >&2; exit 1; }
mkdir -p "$HOOK_DIR"
install_hook() {
  local hook_name="$1"
  local marker="$2"
  local source_name="$3"
  local destination="$HOOK_DIR/$hook_name"
  if [ -e "$destination" ] && ! grep -q "^# $marker$" "$destination" 2>/dev/null; then
    local backup="$destination.pre-hex-vision.$(date +%Y%m%d%H%M%S)"
    cp "$destination" "$backup"
    if [ "$hook_name" = "pre-push" ]; then
      echo "install_hooks: preserved unrelated pre-push hook at $backup" >&2
    else
      echo "install_hooks: preserved unrelated $hook_name hook at $backup" >&2
    fi
  fi
  cat > "$destination" <<HOOK
#!/usr/bin/env bash
# $marker
# Installed by Hex-vision; resolves the active worktree at hook execution so a
# shared Git hooks directory never points every linked worktree at this one.
# The pre-push source invokes the governed release chain whose remotes
# prerequisite is equivalent to: make -C "\$ROOT" remotes.
set -eu
ROOT="\$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "BLOCKED: cannot resolve the active Hex-vision worktree" >&2
  exit 2
}
exec bash "\$ROOT/scripts/$source_name" "\$@"
HOOK
  chmod +x "$destination"
  printf '%s\n' "install_hooks: installed $hook_name hook at $destination"
}

if [ -f "$PRE_COMMIT_SOURCE" ]; then
  install_hook "pre-commit" "hexvision-governed-pre-commit" "pre_commit_check.sh"
else
  # Compatibility for an older adopted checkout: keep its proven L2 hook
  # installable rather than making destination policy unavailable because the
  # additive L1 script has not yet been copied into that checkout.
  echo "install_hooks: L1 pre-commit source is absent; installing L2 pre-push only" >&2
fi
install_hook "pre-push" "hexvision-governed-pre-push" "pre_push_scan.sh"
