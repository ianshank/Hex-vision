# Next steps after the remediation pass

**Audience:** project owner, release engineers, and workstream leads
**Classification:** remediation plan

This document is deliberately forward-looking. It does not mark an item complete merely because an artifact exists; each item names the remaining deliverable, sequence, size, and milestone. The authoritative detailed scope remains the OpenSpec task list and generated planning projections.

## Sequence

| Order | Milestone | Remaining work | Size | Exit evidence |
| ---: | --- | --- | --- | --- |
| 1 | M1 / release orchestration | Land all-active-pack execution, an explicit `active_packs` allowlist, and a pack-domain-gate CLI command; wire it into `contract.pre_pr_order`, `make pre-pr`, and CI. | L (2 PRs, 16–24 h) | A deliberately failing registered gate blocks the local chain and CI; an unconfigured external pack is ignored. |
| 2 | M4 / safety correctness | Classify unavailable, timed-out, malformed, and unreadable safety baselines as `BLOCKED` with redacted diagnostics; retain a separately reviewed new-mission policy. | M (1–2 PRs, 12–16 h) | Tests assert status, finding ID, reason, measurement, and bounded diagnostics for every unavailable-baseline case. |
| 3 | M1 / tool provenance | Remove or make authoritative the unused remote-password and HIL-absence configuration leaves; eliminate discard-only pack launcher reads and arbitrary strict-validator environment replacement. | M (1–2 PRs, 12–18 h) | A configuration-contract inventory maps every policy leaf to a real runtime reader; no environment tool substitution can claim strict validation. |
| 4 | M3–M4 / boundary QA | Add hermetic symlink, permission-denied, Unicode/non-UTF-8, oversized-input, concurrent-change, and timeout fixtures across repository-evidence gates. | M (2 PRs, 16–24 h) | Each gate has semantic failure assertions, not status-only assertions, and the fixture suite remains parallel-safe. |
| 5 | M5 / governed release loop | Merge the quality-loop wiring in [QUALITY-LOOPS.md](QUALITY-LOOPS.md), require the CI workflow in branch protection, and validate pre-push behavior in a disposable clone. | S (1 PR, 4–8 h) | Required CI covers the same configured chain as `make pre-pr`; hook bypass is documented and CI remains authoritative. |
| 6 | M5 / planning truth | After items 1–4 have merged, reconcile OpenSpec checkboxes and `planning/roadmap_data.py` against collected traceability evidence; regenerate projections in the same change. | S (1 PR, 4–6 h) | `hexvision projections --write`, `make projections`, and `make traceability` are green with no completed work left marked open. |
| 7 | Post-M5 hardening | Trial Ruff `ANN`, `PT`, and `TID` incrementally; then consider stricter MyPy `Any` controls at configuration and gate boundaries. | M (2–3 PRs, 12–20 h) | Each rule family is enabled with typed fixtures and no blanket exclusions. |

## Deferred by design

- **Publication remains blocked.** `G-PUB` is intentionally absent. Adding it is a named-human release-authority decision, not remediation work.
- **Airworthiness and flight readiness are outside this harness.** The gates evaluate repository evidence only; they cannot authorize operation or command hardware.
- **Container history scanning is not claimed.** The image excludes `.git` by design. Run the Git-history secret scan in a checkout/CI job with a full clone.
- **Multi-platform container execution needs a CI runner.** The Dockerfile supports `amd64` and `arm64`; a daemon-backed build matrix is still needed to demonstrate both images.

## Ownership notes

The release-orchestration, safety, configuration-provenance, and filesystem-boundary workstreams own the implementation portions of the first four rows. This infrastructure/documentation workstream supplies the hooks, container policy, C4 set, and the exact Make/CI wiring contract; it does not overwrite their concurrent source or test changes.
