# Next steps after the remediation pass

**Audience:** project owner, release engineers, and workstream leads
**Classification:** remediation plan

This document is deliberately forward-looking. It does not mark an item complete merely because an artifact exists; each item names the remaining deliverable, sequence, size, and milestone. The authoritative detailed scope remains the OpenSpec task list and generated planning projections.

## Completed since the remediation plan was written

These rows are closed by merged work on `main`, verified by running the gates rather than by the presence of an artifact.

| Milestone | Landed | Evidence |
| --- | --- | --- |
| M1 / release orchestration | All-active-pack execution, a frozen `orchestration.active_packs` allowlist, `hexvision pack gates --all-active`, and `make domain-gates`, wired into `contract.pre_pr_order`, `make pre-pr`, and CI. | `make pre-pr` executes all five Jetson domain gates; a failing registered gate blocks the chain; an unconfigured external pack is ignored. |
| M4 / safety correctness | Unavailable, timed-out, malformed, and unreadable safety baselines classified `BLOCKED` with bounded redacted diagnostics. | Tests assert status, finding ID, reason, and measurement per case. |
| M1 / tool provenance | Unused policy leaves either removed or given real runtime readers; no environment substitution can claim strict validation. | `make specs` now reports degraded structural mode honestly instead of printing success. |
| M3-M4 / boundary QA | Hermetic symlink, permission-denied, non-UTF-8, oversized-input, and concurrent-change fixtures across repository-evidence gates. | Semantic failure assertions rather than status-only assertions. |
| AQA / agent governance | Deterministic agent and skill definition validation, wired as `make agent-validation`, a release-order step, and a CI job. | Six agents and three skills validated; order-authority tests fail if CI and the configured order diverge. |

## Sequence

| Order | Milestone | Remaining work | Size | Exit evidence |
| ---: | --- | --- | --- | --- |
| 0 | Release blocker / authority verification | Replace per-site authority checking with one verifier. Gates must not be able to construct their own authorisation: the verifier resolves a claim against the configured decision log and returns a typed verified value, aggregation accepts only that type, and the record schema gains explicit machine-readable subject and lifecycle fields so a subject match is exact and a withdrawn record stops authorising. Then require a non-empty reviewed inventory for agent and skill discovery. See PEER-REVIEW-3 findings 1-3 and DEC-016. | L (2-3 PRs, 20-32 h) | Negative tests prove a nonexistent, malformed, unrelated-subject, and withdrawn decision each fail the release aggregate; a substring-colliding subject fails hardware-in-loop; empty definition directories fail agent validation. |
| 1 | M5 / governed release loop | Push the repository, then require the CI workflow in branch protection and validate pre-push behavior in a disposable clone. Branch protection cannot be configured before a remote exists. | S (1 PR, 4-8 h) | Required CI covers the same configured chain as `make pre-pr`; hook bypass is documented and CI remains authoritative. |
| 2 | M5 / verdict observability | Decide how CI observes the four-state model. Every CI job shells through `make`, and GNU make reports its own exit status for any failed recipe, so CI currently cannot distinguish `FAILED` from `BLOCKED`. Either have CI consume the CLI JSON verdict or document make as a convenience wrapper whose exit code is not the contract. | S (1 PR, 4-6 h) | A CI job proves a blocked gate is reported as blocked, or the contract documents make's limitation and names the CLI as authority. |
| 3 | M5 / planning truth | Reconcile OpenSpec checkboxes and `planning/roadmap_data.py` against collected traceability evidence; regenerate projections in the same change. | S (1 PR, 4-6 h) | `make projections` and `make traceability` green with no completed work left marked open. |
| 4 | Post-M5 hardening | Finish the Ruff `ANN`, `PT`, `TID` and stricter MyPy `Any` rollout at configuration and gate boundaries. | M (1-2 PRs, 8-16 h) | Each rule family enabled with typed fixtures and no blanket exclusions. |
| 5 | M5 / container proof | Build and scan the image on a daemon-backed runner for `amd64` and `arm64`. The sandbox that produced this work has no container runtime, so the Dockerfile is validated structurally only. | S (1 PR, 4-6 h) | Both images build in CI and pass the secret and vulnerability scans. |

## Deferred by design

- **Publication remains blocked.** `G-PUB` is intentionally absent. Adding it is a named-human release-authority decision, not remediation work.
- **Airworthiness and flight readiness are outside this harness.** The gates evaluate repository evidence only; they cannot authorize operation or command hardware.
- **Container history scanning is not claimed.** The image excludes `.git` by design. Run the Git-history secret scan in a checkout/CI job with a full clone.
- **Multi-platform container execution needs a CI runner.** The Dockerfile supports `amd64` and `arm64`; a daemon-backed build matrix is still needed to demonstrate both images.

## Ownership notes

The release-orchestration, safety, configuration-provenance, filesystem-boundary, and AQA workstreams have merged, so the remaining rows are owned by release engineering rather than split across parallel workstreams. Rows 1, 2, and 5 all depend on a remote and a CI runner existing, which is why they are sequenced ahead of the lint and planning work despite being smaller.
