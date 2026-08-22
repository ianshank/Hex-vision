#!/usr/bin/env bash
# Hex-vision hook installer (INV-4). Commit stamp: e0165e4 (2026-08-22).
# It installs only the L2 fast-feedback shim; it does NOT make --no-verify safe,
# protect a checkout never installed, or replace L3 CI/L4 policy. It preserves an
# unrelated hook, supports .git files in worktrees through git --git-path, and fails
# closed if Git cannot identify an installation destination.
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
# Git, rather than shell prefix rules, resolves linked-worktree gitdirs and both
# absolute and relative core.hooksPath values. --path-format avoids ROOT/<absolute>
# mistakes and makes this result safe to create directly.
HOOK_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-path hooks)" || { echo "install_hooks: cannot resolve hooks directory" >&2; exit 1; }
mkdir -p "$HOOK_DIR"
DESTINATION="$HOOK_DIR/pre-push"
if [ -e "$DESTINATION" ] && ! grep -q 'scripts/pre_push_scan.sh' "$DESTINATION" 2>/dev/null; then
  BACKUP="$DESTINATION.pre-hex-vision.$(date +%Y%m%d%H%M%S)"
  cp "$DESTINATION" "$BACKUP"
  echo "install_hooks: preserved unrelated pre-push hook at $BACKUP" >&2
fi
cat > "$DESTINATION" <<HOOK
#!/usr/bin/env bash
# Installed by Hex-vision; edit scripts/pre_push_scan.sh in the worktree.
set -u
exec bash "$ROOT/scripts/pre_push_scan.sh" "\$@"
HOOK
chmod +x "$DESTINATION"
printf '%s\n' "install_hooks: installed pre-push hook at $DESTINATION"
