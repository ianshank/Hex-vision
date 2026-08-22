# Hex-vision — Python task runner for the robotics / edge-AI governance harness.
#
# This file is the SINGLE SOURCE OF TRUTH for how every gate is invoked.
# .github/workflows/ci.yml calls these targets rather than repeating the
# commands, so a gate cannot pass locally and differ in CI. A meta-test
# (tests/governance/test_governance_meta.py) asserts CI keeps using them.
#
# TARGET-NAME CONTRACT (Gate Harness Contract v1.1) — identical across every
# stack in the estate:
#   install format lint types test cov secrets specs audit remotes projections
#   traceability guard-probe pre-pr clean
# The implementations differ per stack; the names never do.
#
# No absolute paths and no machine-specific values: every tool is reached
# through $(RUN), and paths derive from this file's own location.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

# PM/RUN are overridable so a team can use uv, pip+venv or poetry without
# forking this file. Whatever it is, it must be lockfile-driven so a gate
# tool version cannot float between local and CI.
PM ?= uv
RUN ?= $(PM) run --
GITLEAKS ?= gitleaks
GITLEAKS_VERSION ?= v8.28.0
OSV ?= osv-scanner
OSV_VERSION ?= v2.2.4
PKG ?= hexvision
# Pack under test for `make conformance`. Overridable because the whole point
# of the pack registry is that this list is not fixed in the harness.
PACK ?= jetson

.PHONY: help install format lint types test cov secrets specs audit remotes \
        projections traceability conformance guard-probe pre-pr clean \
        secrets-install audit-install

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create/refresh the dev environment AND install the git hooks
	$(PM) sync --extra dev
	@bash $(ROOT)/scripts/install_hooks.sh

# --- gates ---------------------------------------------------------------

test: ## Run the suite (zero skipped, mechanically enforced by the conftest guard)
	$(RUN) pytest

cov: ## Run the suite against the coverage floors in pyproject.toml
	$(RUN) pytest --cov --cov-report=term-missing --cov-report=json:$(ROOT)/coverage.json
	$(RUN) python -m $(PKG).cli gate coverage --report $(ROOT)/coverage.json
# NOTE: deliberately no --cov-fail-under flag here. The project floor lives ONLY
# in [tool.coverage.report] and the per-file floor ONLY in [tool.hexvision.coverage].
# A CLI override would shadow the config and silently re-narrow the gate the
# moment a subpackage is added. The second command exists because coverage.py
# has no native per-file threshold — a project floor alone lets twenty
# well-tested modules subsidise one untested one.

lint: ## Ruff rules + formatting + dead code
	$(RUN) ruff check $(ROOT)
	$(RUN) ruff format --check $(ROOT)
	$(RUN) vulture

format: ## Apply ruff formatting
	$(RUN) ruff format $(ROOT)

types: ## Static types (config in pyproject.toml; strict mode, whole project)
	$(RUN) mypy

# Two passes, because they catch different things and neither subsumes the
# other: `dir` scans the WORKING TREE (the secret you are about to commit),
# `git` scans COMMITTED HISTORY (a secret added and later deleted still lives
# in the objects).
secrets: ## Secret scan of working tree AND history. Fails closed if gitleaks is absent.
	@command -v $(GITLEAKS) >/dev/null 2>&1 || { \
	  echo "gitleaks not found. A security gate that silently skips is worse"; \
	  echo "than no gate, so this fails closed. Install it with:"; \
	  echo "    make secrets-install"; \
	  exit 1; }
	$(GITLEAKS) dir $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner
	$(GITLEAKS) git $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner

secrets-install: ## Install the pinned gitleaks binary via go
	go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION)

specs: ## Strict spec validation (wrapper falls back to structural validator)
	bash $(ROOT)/scripts/validate_specs.sh

# osv-scanner over the lockfile rather than a severity-cut tool: every ignored
# advisory must be a named line with an owner, a reason and an expiry, which
# `pip-audit --ignore-vuln` and `npm audit --audit-level` cannot express.
audit: ## Dependency vulnerability scan. Ignore ONLY named, documented advisories.
	@command -v $(OSV) >/dev/null 2>&1 || { \
	  echo "osv-scanner not found. This gate fails closed rather than skip."; \
	  echo "Install it with:"; \
	  echo "    make audit-install"; \
	  exit 1; }
	@test -f $(ROOT)/uv.lock || { \
	  echo "uv.lock is absent, so there is nothing pinned to audit."; \
	  echo "This fails closed rather than report a clean scan of nothing."; \
	  echo "Generate it with:  $(PM) lock"; \
	  exit 1; }
	$(OSV) scan --lockfile=$(ROOT)/uv.lock --config=$(ROOT)/osv-scanner.toml

audit-install: ## Install the pinned osv-scanner binary via go
	go install github.com/google/osv-scanner/v2/cmd/osv-scanner@$(OSV_VERSION)

# --- governance checks (the CI guard job) --------------------------------

remotes: ## Destination allowlist check via the shared normalizer (INV-3)
	$(RUN) python -m $(PKG).cli remotes --json

projections: ## Generated-projection drift check (roadmap + backlog CSV byte-match the data source)
	$(RUN) python -m $(PKG).cli projections --check --json

traceability: ## Requirement-traceability lint
	$(RUN) python -m $(PKG).cli traceability --json

conformance: ## Assert PACK satisfies every clause of the Gate Harness Contract
	$(RUN) python -m $(PKG).cli conformance --pack $(PACK) --json

guard-probe: ## Show the PreToolUse guard's verdict for CMD, with tracing
	@test -n "$(CMD)" || { echo 'usage: make guard-probe CMD="<command>"'; exit 2; }
	@printf '%s' "$(CMD)" | python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.stdin.read()}}))' \
	  | GUARD_DEBUG=1 CLAUDE_PROJECT_DIR=$(ROOT) bash $(ROOT)/scripts/pretooluse_guard.sh; \
	  rc=$$?; test $$rc -eq 2 && echo "verdict: BLOCK" || echo "verdict: ALLOW (rc=$$rc)"

# --- the pre-PR gate ------------------------------------------------------

pre-pr: install lint types cov secrets specs audit remotes projections traceability ## Everything CI runs, in CI order
	@echo
	@echo "pre-PR validation complete — every gate CI runs has passed locally."

clean: ## Remove build/test caches (never touches tracked files)
	rm -rf $(ROOT)/.pytest_cache $(ROOT)/.mypy_cache $(ROOT)/.ruff_cache \
	       $(ROOT)/htmlcov $(ROOT)/coverage.json $(ROOT)/.coverage $(ROOT)/dist
	find $(ROOT)/src $(ROOT)/tests -type d -name '__pycache__' -prune -exec rm -rf {} +
