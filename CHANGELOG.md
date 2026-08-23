# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). No version has been released or tagged yet; the entries below are reconstructed from the `main` branch history and remain under **Unreleased**.

## [Unreleased]

### Added

- Added the layered, provenance-preserving configuration engine; immutable result model; pack interface and dynamic entry-point registries.
- Added Gate Harness Contract conformance, invariant negative probes, traceability linting, deterministic roadmap/backlog projections, and the Jetson reference pack with repository-evidence gates.
- Added guarded public-publication assessment, a structured decision-log parser, and GitHub/Hugging Face publication assets.
- Added native pre-commit and pre-push feedback loops, a reproducible container image definition, C4 architecture documentation, and quality-loop operating guidance.
- Added release orchestration that executes every registered domain gate for each configured active pack, exposed as `hexvision pack gates --all-active` and `make domain-gates`, closing the gap where domain gates existed but no local or CI path invoked them.
- Added deterministic validation of governed agent and skill definitions, wired as `make agent-validation`, a step in the configured release order, and its own CI job so the local and CI gate sets cannot drift.
- Added a test asserting which interface owns the four-state verdict, pinning GNU make's collapsing of every recipe failure into its own exit status and naming the CLI as the authority.

### Changed

- Made Makefile target invocation the local and CI orchestration authority, with CI jobs sequenced through target dependencies.
- Made scanner installation and invocation release-binary based where Go is unavailable, with scanner identity verified from frozen configuration.
- Made traceability evidence depend on source requirements, collected test nodes, and matching executable test markers rather than matrix prose alone.
- Changed release aggregation so an authorised declared skip passes while remaining visible through a counted summary and a listing of each skip against its authorising decision, replacing a red exit that made the decision log decorative. An absence with no recorded authority fails and names its gate. Recorded as DEC-015.
- Widened the decision-log record schema from 4 columns to 7, adding `subject`, `status`, and `supersedes` for the shared authority verifier required by DEC-016. All 13 pre-existing records were migrated with their first four cells preserved byte-for-byte, mechanically verified before merge; two (DEC-013, DEC-014) were additionally reconfirmed under the widened schema via new records that supersede them (DEC-019, DEC-020). Recorded as DEC-018.

### Fixed

- Refused tests that import Hex-vision from a different checkout, preventing false-green worktree results.
- Preserved the four-state gate model in CLI reporting so `BLOCKED` is not reported as `FAILED` or as success.
- Enforced decision-log semantic validity and remote URL component validation for publication checks.
- Corrected coverage isolation and contract integration behavior.
- Reported an absent hardware runner with no authorising decision as `BLOCKED` rather than as a declared skip, closing a path where an unowned absence presented itself as an approved one.
- Repaired the shared Git pre-commit hook, which invoked a script present on only one branch and therefore blocked commits in every other worktree.

### Security

- Restored the gitleaks default rule extension after the rule-loading failure that could leave a scanner with zero active detection rules.
- Verified the runnable scanner artifact by SHA-256 before use, removing the PATH-shadowable scanner route.
- Required structured, real decision-log authority for publication, preventing forgeable publication authorization from prose or malformed records.
- Counted collection-time skips and terminal skip accounting as non-passing, closing the skip-control bypass.
- Required collected tests and source markers for Green traceability rows, preventing fabricated traceability greens.
- Required secret-scan evidence for both the working tree and Git history, including a meaningful negative probe.
