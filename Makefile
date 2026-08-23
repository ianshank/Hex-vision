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
# Scanner versions and per-platform digests are frozen configuration.  This
# helper resolves a canonical absolute path and verifies its artifact digest.
# Make then invokes that exact path immediately after verification.
override SCANNER_IDENTITY := $(RUN) python -m hexvision.scanner_identity
# INSTALL_DIR and INSTALL_METHOD affect only the explicit installer targets.
INSTALL_DIR ?= $(HOME)/.local/bin
# CI selects `release` because it exports INSTALL_DIR to later steps. Local
# `auto` preserves the existing Go installer when Go is available.
INSTALL_METHOD ?= auto
PKG ?= hexvision
# Pack under test for `make conformance`. Overridable because the whole point
# of the pack registry is that this list is not fixed in the harness.
PACK ?= jetson

.PHONY: help install format lint types test cov secrets specs audit remotes agent-validation \
        projections traceability conformance domain-gates publication guard-probe pre-pr clean \
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
# Erase first, always. A coverage gate that inherits whatever data files happen
# to be lying in the working tree is not a measurement, it is a coincidence.
# Stale parallel data (from an interrupted run, a different branch, or a
# subprocess that recorded statement-only data because it started in a temp
# directory and could not see this config) either crashes the combine step or,
# far worse, silently credits the current tree with coverage it never earned.
	$(RUN) coverage erase
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
# The scanner is resolved to an absolute path whose digest is verified against the
# pinned value first (R2-04): a version string a binary prints about itself is not
# an identity. GITLEAKS_REPORT, when set, additionally emits machine-readable
# findings, which is how the conformance probe proves INV-1 enforcement from a rule
# id rather than from stdout prose (R2-03).
	@tool_path="$$( $(SCANNER_IDENTITY) verify gitleaks)"; \
	  "$$tool_path" dir $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner \
	    $(if $(GITLEAKS_REPORT),--report-format json --report-path $(GITLEAKS_REPORT))
	@tool_path="$$( $(SCANNER_IDENTITY) verify gitleaks)"; \
	  "$$tool_path" git $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner

secrets-install: ## Install pinned gitleaks (Go when available, verified release binary otherwise)
	@eval "$$($(SCANNER_IDENTITY) install-shell gitleaks)"; \
	if test "$(INSTALL_METHOD)" = "go" || { test "$(INSTALL_METHOD)" = "auto" && command -v go >/dev/null 2>&1; }; then \
	  command -v go >/dev/null 2>&1 || { echo "go was requested but is not installed" >&2; exit 1; }; \
	  go install "$$go_module@$$version"; \
	elif test "$(INSTALL_METHOD)" = "auto" || test "$(INSTALL_METHOD)" = "release"; then \
	  command -v curl >/dev/null 2>&1 || { echo "curl is required to download gitleaks" >&2; exit 1; }; \
	  workdir="$$(mktemp -d)"; trap 'rm -rf "$$workdir"' EXIT; \
	  archive="$$workdir/$$asset"; \
	  curl -fsSL -o "$$archive" "$$download_url"; \
	  if command -v sha256sum >/dev/null 2>&1; then actual="$$(sha256sum "$$archive" | awk '{print $$1}')"; \
	  elif command -v shasum >/dev/null 2>&1; then actual="$$(shasum -a 256 "$$archive" | awk '{print $$1}')"; \
	  else echo "no SHA-256 utility found; refusing to install unverified gitleaks" >&2; exit 1; fi; \
	  test "$$actual" = "$$release_sha256" || { echo "gitleaks checksum mismatch; refusing to install" >&2; exit 1; }; \
	  mkdir -p "$(INSTALL_DIR)"; tar -xzf "$$archive" -C "$$workdir"; \
	  install -m 0755 "$$workdir/$$archive_member" "$(INSTALL_DIR)/$$executable"; \
	  echo "installed gitleaks $$version to $(INSTALL_DIR)/$$executable"; \
	else echo "unknown INSTALL_METHOD=$(INSTALL_METHOD); expected auto, go, or release" >&2; exit 1; fi

specs: ## Strict spec validation (wrapper falls back to structural validator)
	bash $(ROOT)/scripts/validate_specs.sh

# osv-scanner over the lockfile rather than a severity-cut tool: every ignored
# advisory must be a named line with an owner, a reason and an expiry, which
# `pip-audit --ignore-vuln` and `npm audit --audit-level` cannot express.
audit: ## Dependency vulnerability scan. Ignore ONLY named, documented advisories.
	@test -f $(ROOT)/uv.lock || { \
	  echo "uv.lock is absent, so there is nothing pinned to audit."; \
	  echo "This fails closed rather than report a clean scan of nothing."; \
	  echo "Generate it with:  $(PM) lock"; \
	  exit 1; }
	@tool_path="$$( $(SCANNER_IDENTITY) verify osv-scanner)"; \
	  "$$tool_path" scan --lockfile=$(ROOT)/uv.lock --config=$(ROOT)/osv-scanner.toml

audit-install: ## Install pinned osv-scanner (Go when available, verified release binary otherwise)
	@eval "$$($(SCANNER_IDENTITY) install-shell osv-scanner)"; \
	if test "$(INSTALL_METHOD)" = "go" || { test "$(INSTALL_METHOD)" = "auto" && command -v go >/dev/null 2>&1; }; then \
	  command -v go >/dev/null 2>&1 || { echo "go was requested but is not installed" >&2; exit 1; }; \
	  go install "$$go_module@$$version"; \
	elif test "$(INSTALL_METHOD)" = "auto" || test "$(INSTALL_METHOD)" = "release"; then \
	  command -v curl >/dev/null 2>&1 || { echo "curl is required to download osv-scanner" >&2; exit 1; }; \
	  workdir="$$(mktemp -d)"; trap 'rm -rf "$$workdir"' EXIT; \
	  binary="$$workdir/$$asset"; \
	  curl -fsSL -o "$$binary" "$$download_url"; \
	  if command -v sha256sum >/dev/null 2>&1; then actual="$$(sha256sum "$$binary" | awk '{print $$1}')"; \
	  elif command -v shasum >/dev/null 2>&1; then actual="$$(shasum -a 256 "$$binary" | awk '{print $$1}')"; \
	  else echo "no SHA-256 utility found; refusing to install unverified osv-scanner" >&2; exit 1; fi; \
	  test "$$actual" = "$$release_sha256" || { echo "osv-scanner checksum mismatch; refusing to install" >&2; exit 1; }; \
	  mkdir -p "$(INSTALL_DIR)"; install -m 0755 "$$binary" "$(INSTALL_DIR)/$$executable"; \
	  echo "installed osv-scanner $$version to $(INSTALL_DIR)/$$executable"; \
	else echo "unknown INSTALL_METHOD=$(INSTALL_METHOD); expected auto, go, or release" >&2; exit 1; fi

# --- governance checks (the CI guard job) --------------------------------

remotes: ## Destination allowlist check via the shared normalizer (INV-3)
	$(RUN) python -m $(PKG).cli remotes --json

projections: ## Generated-projection drift check (roadmap + backlog CSV byte-match the data source)
	$(RUN) python -m $(PKG).cli projections --check --json

traceability: ## Requirement-traceability lint
	$(RUN) python -m $(PKG).cli traceability --json

conformance: ## Assert PACK satisfies every clause of the Gate Harness Contract
	$(RUN) python -m $(PKG).cli conformance --pack $(PACK) --json

agent-validation: ## Validate governed agent and skill definitions deterministically
	$(RUN) python -m $(PKG).agent_validation

domain-gates: ## Execute every registered domain gate for each configured active pack
	$(RUN) python -m $(PKG).cli pack gates --all-active --json

publication: ## Release-time public destination and G-PUB authorization control
	$(RUN) python -m $(PKG).cli publication --json

guard-probe: ## Show the PreToolUse guard's verdict for CMD, with tracing
	@test -n "$(CMD)" || { echo 'usage: make guard-probe CMD="<command>"'; exit 2; }
	@printf '%s' "$(CMD)" | python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.stdin.read()}}))' \
	  | GUARD_DEBUG=1 CLAUDE_PROJECT_DIR=$(ROOT) bash $(ROOT)/scripts/pretooluse_guard.sh; \
	  rc=$$?; test $$rc -eq 2 && echo "verdict: BLOCK" || echo "verdict: ALLOW (rc=$$rc)"

# --- the pre-PR gate ------------------------------------------------------

pre-pr: install lint types cov secrets specs audit remotes projections agent-validation traceability conformance domain-gates ## Every configured CI gate, in CI order
	@echo
	@echo "pre-PR validation complete — every configured CI gate has passed locally."

clean: ## Remove build/test caches (never touches tracked files)
	rm -rf $(ROOT)/.pytest_cache $(ROOT)/.mypy_cache $(ROOT)/.ruff_cache \
	       $(ROOT)/htmlcov $(ROOT)/coverage.json $(ROOT)/.coverage $(ROOT)/dist
	find $(ROOT)/src $(ROOT)/tests -type d -name '__pycache__' -prune -exec rm -rf {} +
