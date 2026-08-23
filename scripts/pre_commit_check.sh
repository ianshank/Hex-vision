#!/usr/bin/env bash
# Hex-vision L1 native pre-commit feedback loop. Commit stamp: v3-infra (2026-08-22).
#
# This is intentionally narrower than pre-push: it checks changed work quickly
# (Ruff plus the staged content secret scan) and leaves coverage, history,
# specifications, dependencies, projections, traceability, pack execution, and
# conformance to the L2/L3 release chain. Bypassing it with --no-verify changes
# no authoritative verdict; it does not catch the full release sequence.
set -euo pipefail

block() {
  echo "BLOCKED (L1 pre-commit): $1" >&2
  exit 2
}

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || block "cannot resolve repository root"
cd "$ROOT"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON=("$ROOT/.venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run --project "$ROOT" python)
else
  block "no project Python or uv runner is available"
fi

"${PYTHON[@]}" -m ruff check src tests planning
"${PYTHON[@]}" -m ruff format --check src tests planning

tool_path="$("${PYTHON[@]}" -m hexvision.scanner_identity verify gitleaks)" \
  || block "verified gitleaks is unavailable"
"$tool_path" protect --staged --config "$ROOT/.gitleaks.toml" --redact --no-banner

echo "pre-commit: fast lint, format, and staged-secret checks passed" >&2
