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
# Security scanners and all of their identity pins are deliberately immune to
# environment and command-line Make assignments. A caller-controlled executable
# can acknowledge any scan without reading the repository, which is no scan.
override GITLEAKS := gitleaks
override GITLEAKS_VERSION := v8.28.0
GITLEAKS_RELEASE_VERSION := $(patsubst v%,%,$(GITLEAKS_VERSION))
override GITLEAKS_LINUX_X64_SHA256 := a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb
override GITLEAKS_LINUX_ARM64_SHA256 := eff65261156100e5d94a6b3dec313d532fddfe19ae1590bf7a2b4f2699128356
override GITLEAKS_DARWIN_X64_SHA256 := edf5a507008b0d2ef4959575772772770586409c1f6f74dabf19cbe7ec341ced
override GITLEAKS_DARWIN_ARM64_SHA256 := d942f3ad147250c9edbaab3fed9e482f98d3b59ba10ae97b8d75647e3ade492c
override OSV := osv-scanner
override OSV_VERSION := v2.2.4
OSV_RELEASE_VERSION := $(patsubst v%,%,$(OSV_VERSION))
override OSV_LINUX_X64_SHA256 := 7702cd1e5d9f5059dd9570f4ad967f27d3c5f5391b371ec937b384c238177f55
override OSV_LINUX_ARM64_SHA256 := 94d1c520b30a7e28b0189b2a1dd24c7b08f41887186e8ae3f811067ec9ed7043
override OSV_DARWIN_X64_SHA256 := 589e673d8d6585fecf4384fa4d85cb9fa5aa7f6ff6a8c4e5ef1472e8217d5875
override OSV_DARWIN_ARM64_SHA256 := bd964925a27037db3a0426ac411a6599cd18781bb2bd72ce02adf4a6a1fe9058
# INSTALL_DIR and INSTALL_METHOD affect only the explicit installer targets;
# secrets and audit select only the protected executable names above.
INSTALL_DIR ?= $(HOME)/.local/bin
# CI selects `release` because it exports INSTALL_DIR to later steps. Local
# `auto` preserves the existing Go installer when Go is available.
INSTALL_METHOD ?= auto
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
	@tool_path="$$(command -v "$(GITLEAKS)" 2>/dev/null)" || { \
	  echo "gitleaks not found. A security gate that silently skips is worse"; \
	  echo "than no gate, so this fails closed. Install it with:"; \
	  echo "    make secrets-install"; \
	  exit 1; }; \
	  observed="$$( "$$tool_path" version 2>&1 || true)"; \
	  test "$$observed" = "$(GITLEAKS_RELEASE_VERSION)" || { \
	    printf 'gitleaks identity verification failed: expected version %s, observed %s\n' \
	      "$(GITLEAKS_RELEASE_VERSION)" "$${observed:-<no version output>}"; \
	    exit 1; }
	$(GITLEAKS) dir $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner
	$(GITLEAKS) git $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner

secrets-install: ## Install pinned gitleaks (Go when available, verified release binary otherwise)
	@if test "$(INSTALL_METHOD)" = "go" || { test "$(INSTALL_METHOD)" = "auto" && command -v go >/dev/null 2>&1; }; then \
	  command -v go >/dev/null 2>&1 || { echo "go was requested but is not installed" >&2; exit 1; }; \
	  go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION); \
	elif test "$(INSTALL_METHOD)" = "auto" || test "$(INSTALL_METHOD)" = "release"; then \
	  case "$$(uname -s):$$(uname -m)" in \
	    Linux:x86_64) asset="gitleaks_$(GITLEAKS_RELEASE_VERSION)_linux_x64.tar.gz"; expected="$(GITLEAKS_LINUX_X64_SHA256)" ;; \
	    Linux:aarch64|Linux:arm64) asset="gitleaks_$(GITLEAKS_RELEASE_VERSION)_linux_arm64.tar.gz"; expected="$(GITLEAKS_LINUX_ARM64_SHA256)" ;; \
	    Darwin:x86_64) asset="gitleaks_$(GITLEAKS_RELEASE_VERSION)_darwin_x64.tar.gz"; expected="$(GITLEAKS_DARWIN_X64_SHA256)" ;; \
	    Darwin:arm64) asset="gitleaks_$(GITLEAKS_RELEASE_VERSION)_darwin_arm64.tar.gz"; expected="$(GITLEAKS_DARWIN_ARM64_SHA256)" ;; \
	    *) echo "unsupported platform for gitleaks release install: $$(uname -s)/$$(uname -m)" >&2; exit 1 ;; \
	  esac; \
	  command -v curl >/dev/null 2>&1 || { echo "curl is required to download gitleaks" >&2; exit 1; }; \
	  workdir="$$(mktemp -d)"; trap 'rm -rf "$$workdir"' EXIT; \
	  archive="$$workdir/$$asset"; \
	  curl -fsSL -o "$$archive" "https://github.com/gitleaks/gitleaks/releases/download/$(GITLEAKS_VERSION)/$$asset"; \
	  if command -v sha256sum >/dev/null 2>&1; then actual="$$(sha256sum "$$archive" | awk '{print $$1}')"; \
	  elif command -v shasum >/dev/null 2>&1; then actual="$$(shasum -a 256 "$$archive" | awk '{print $$1}')"; \
	  else echo "no SHA-256 utility found; refusing to install unverified gitleaks" >&2; exit 1; fi; \
	  test "$$actual" = "$$expected" || { echo "gitleaks checksum mismatch; refusing to install" >&2; exit 1; }; \
	  mkdir -p "$(INSTALL_DIR)"; tar -xzf "$$archive" -C "$$workdir"; \
	  install -m 0755 "$$workdir/gitleaks" "$(INSTALL_DIR)/gitleaks"; \
	  echo "installed gitleaks $(GITLEAKS_VERSION) to $(INSTALL_DIR)/gitleaks"; \
	else echo "unknown INSTALL_METHOD=$(INSTALL_METHOD); expected auto, go, or release" >&2; exit 1; fi

specs: ## Strict spec validation (wrapper falls back to structural validator)
	bash $(ROOT)/scripts/validate_specs.sh

# osv-scanner over the lockfile rather than a severity-cut tool: every ignored
# advisory must be a named line with an owner, a reason and an expiry, which
# `pip-audit --ignore-vuln` and `npm audit --audit-level` cannot express.
audit: ## Dependency vulnerability scan. Ignore ONLY named, documented advisories.
	@tool_path="$$(command -v "$(OSV)" 2>/dev/null)" || { \
	  echo "osv-scanner not found. This gate fails closed rather than skip."; \
	  echo "Install it with:"; \
	  echo "    make audit-install"; \
	  exit 1; }; \
	  observed="$$( "$$tool_path" --version 2>&1 || true)"; \
	  case "$$observed" in *"osv-scanner version: $(OSV_RELEASE_VERSION)"*) ;; *) \
	    printf 'osv-scanner identity verification failed: expected version %s, observed %s\n' \
	      "$(OSV_RELEASE_VERSION)" "$${observed:-<no version output>}"; \
	    exit 1 ;; esac
	@test -f $(ROOT)/uv.lock || { \
	  echo "uv.lock is absent, so there is nothing pinned to audit."; \
	  echo "This fails closed rather than report a clean scan of nothing."; \
	  echo "Generate it with:  $(PM) lock"; \
	  exit 1; }
	$(OSV) scan --lockfile=$(ROOT)/uv.lock --config=$(ROOT)/osv-scanner.toml

audit-install: ## Install pinned osv-scanner (Go when available, verified release binary otherwise)
	@if test "$(INSTALL_METHOD)" = "go" || { test "$(INSTALL_METHOD)" = "auto" && command -v go >/dev/null 2>&1; }; then \
	  command -v go >/dev/null 2>&1 || { echo "go was requested but is not installed" >&2; exit 1; }; \
	  go install github.com/google/osv-scanner/v2/cmd/osv-scanner@$(OSV_VERSION); \
	elif test "$(INSTALL_METHOD)" = "auto" || test "$(INSTALL_METHOD)" = "release"; then \
	  case "$$(uname -s):$$(uname -m)" in \
	    Linux:x86_64) asset="osv-scanner_linux_amd64"; expected="$(OSV_LINUX_X64_SHA256)" ;; \
	    Linux:aarch64|Linux:arm64) asset="osv-scanner_linux_arm64"; expected="$(OSV_LINUX_ARM64_SHA256)" ;; \
	    Darwin:x86_64) asset="osv-scanner_darwin_amd64"; expected="$(OSV_DARWIN_X64_SHA256)" ;; \
	    Darwin:arm64) asset="osv-scanner_darwin_arm64"; expected="$(OSV_DARWIN_ARM64_SHA256)" ;; \
	    *) echo "unsupported platform for osv-scanner release install: $$(uname -s)/$$(uname -m)" >&2; exit 1 ;; \
	  esac; \
	  command -v curl >/dev/null 2>&1 || { echo "curl is required to download osv-scanner" >&2; exit 1; }; \
	  workdir="$$(mktemp -d)"; trap 'rm -rf "$$workdir"' EXIT; \
	  binary="$$workdir/$$asset"; \
	  curl -fsSL -o "$$binary" "https://github.com/google/osv-scanner/releases/download/$(OSV_VERSION)/$$asset"; \
	  if command -v sha256sum >/dev/null 2>&1; then actual="$$(sha256sum "$$binary" | awk '{print $$1}')"; \
	  elif command -v shasum >/dev/null 2>&1; then actual="$$(shasum -a 256 "$$binary" | awk '{print $$1}')"; \
	  else echo "no SHA-256 utility found; refusing to install unverified osv-scanner" >&2; exit 1; fi; \
	  test "$$actual" = "$$expected" || { echo "osv-scanner checksum mismatch; refusing to install" >&2; exit 1; }; \
	  mkdir -p "$(INSTALL_DIR)"; install -m 0755 "$$binary" "$(INSTALL_DIR)/osv-scanner"; \
	  echo "installed osv-scanner $(OSV_VERSION) to $(INSTALL_DIR)/osv-scanner"; \
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
