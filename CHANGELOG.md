# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). No version has been released or tagged yet; the entries below are reconstructed from the `main` branch history and remain under **Unreleased**.

## [Unreleased]

### Added

- Added the layered, provenance-preserving configuration engine; immutable result model; pack interface and dynamic entry-point registries.
- Added Gate Harness Contract conformance, invariant negative probes, traceability linting, deterministic roadmap/backlog projections, and the Jetson reference pack with repository-evidence gates.
- Added guarded public-publication assessment, a structured decision-log parser, and GitHub/Hugging Face publication assets.
- Added native pre-commit and pre-push feedback loops, a reproducible container image definition, C4 architecture documentation, and quality-loop operating guidance.

### Changed

- Made Makefile target invocation the local and CI orchestration authority, with CI jobs sequenced through target dependencies.
- Made scanner installation and invocation release-binary based where Go is unavailable, with scanner identity verified from frozen configuration.
- Made traceability evidence depend on source requirements, collected test nodes, and matching executable test markers rather than matrix prose alone.

### Fixed

- Refused tests that import Hex-vision from a different checkout, preventing false-green worktree results.
- Preserved the four-state gate model in CLI reporting so `BLOCKED` is not reported as `FAILED` or as success.
- Enforced decision-log semantic validity and remote URL component validation for publication checks.
- Corrected coverage isolation and contract integration behavior.

### Security

- Restored the gitleaks default rule extension after the rule-loading failure that could leave a scanner with zero active detection rules.
- Verified the runnable scanner artifact by SHA-256 before use, removing the PATH-shadowable scanner route.
- Required structured, real decision-log authority for publication, preventing forgeable publication authorization from prose or malformed records.
- Counted collection-time skips and terminal skip accounting as non-passing, closing the skip-control bypass.
- Required collected tests and source markers for Green traceability rows, preventing fabricated traceability greens.
- Required secret-scan evidence for both the working tree and Git history, including a meaningful negative probe.
