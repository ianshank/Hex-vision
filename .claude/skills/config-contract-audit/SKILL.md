---
name: config-contract-audit
description: Audits Hex-vision configuration leaves against their runtime readers, policy effects, environment boundaries, and external-tool identity checks.
---

# Configuration-contract audit

Configuration is a contract only when a reviewed leaf has one authoritative runtime reader and an observable, tested effect. A `config.require(...)` whose value is discarded is evidence of a broken contract, not proof of configurability.

## Required inventory

1. Read `src/hexvision/defaults/hex-vision.toml`, `src/hexvision/config.py`, `pyproject.toml`, `Makefile`, scripts, CLI modules, and every module that calls `Config.require`, `Config.get`, `Config.section`, `Config.resolve_path`, or reads a relevant environment variable.
2. Produce a leaf-level table: `config path | default | frozen prefix? | runtime reader(s) | effective behavior | test/probe | environment/CLI override path | verdict`. Expand nested TOML tables to leaves; comments and a declaration alone are not readers.
3. For every leaf, classify it as **authoritative**, **derived**, **deprecated/remove**, or **unread**. A policy leaf that has no reader, a reader whose result is discarded, or a shell/Make value that overrides it without provenance is a Major finding.
4. Trace environment values separately. Verify frozen prefixes reject environment and explicit overrides; identify every non-frozen `HEXVISION_` reader and every direct environment variable such as `SPEC_VALIDATOR`, `PATH`, `RUN`, or package-manager selection. A successful arbitrary executable is not strict tool validation.
5. For each external tool, identify the configured name, version, platform artifact digest, resolution path, executable invoked, and meaningful probe. Reject PATH-only identity, self-reported version-only identity, unaudited command strings, and a tool substitution that can report a control as executed when it was not.

## Required probes

- Flip each supported non-frozen policy leaf in a temporary repository/configuration and observe the documented behavior change.
- Attempt to override each frozen leaf through `HEXVISION_` and explicit caller overrides; assert the frozen-key error and the named key.
- For every candidate discard-only reader, mutate the leaf and show whether the invoked command, threshold, path, allowlist, or verdict changes. If it does not, classify it unread.
- Replace an external tool with a benign successful executable and confirm the harness blocks or reports degraded mode rather than claiming strict success.
- Resolve a PATH-shadow candidate before and after scanner/tool verification; assert the verified absolute executable and digest, not only its version text.

## Review standards

- Do not solve a misleading security invariant by making an insecure `false` setting available. Prefer removing the false promise or keep the invariant unconditional with explicit documentation.
- Do not duplicate policy authority in TOML, Make, and environment variables. Select one reviewed authority and demonstrate how callers inherit it.
- Preserve the four-state gate model. An unavailable configuration, policy, binary, or evidence input must not create a passing result.
- When remediation adds a leaf, require an exact test that changes it and a documentation update naming its operational effect.

Output: a leaf inventory, then findings in `ID | Severity | Config contract failure | Evidence | Required disposition` format, followed by exact probe commands and observed reasons. Do not mark an inventory complete merely because every key is declared.
