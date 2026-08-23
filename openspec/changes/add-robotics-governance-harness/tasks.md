# Tasks — add-robotics-governance-harness

`tasks.md` owns scope. `planning/roadmap_data.py` is the projection source; `docs/ROADMAP.md` and `planning/backlog.csv` are generated views. Reconciled on 2026-08-22 against the collecting test evidence required by `traceability/REQUIREMENT-TRACEABILITY.md`: completed baseline tasks are checked, while known remediation work is explicitly **deferred** rather than represented as generic in-progress work.

## 0. Reconnaissance and guardrails (charter M0)
- [x] 0.1 Write or verify failing configuration scenarios for R-1 and R-2 before further configuration changes (per D1/D2). Evidence: collecting traceability evidence exists for R-1 and R-2.
- [x] 0.2 Deliver the committed layered configuration engine and frozen-key mechanism for R-1 and R-2 (per D1/D2). Evidence: baseline commit `10b37ddb6ae1`; this task does not claim test counts.
- [x] 0.3 Deliver the committed error taxonomy, gate result model, gate base, and pack interface needed for fail-closed work. Dependency: core implementation and tests remain in flight.
- [x] 0.4 Record archive-versus-plan gap and re-baseline under RB-001: the archive had no Python reference pack or roadmap-control documents.
- [x] 0.5 Update traceability for M0 requirements R-1 and R-2. Evidence: the checked matrix has collected Green evidence for both requirements.

## 1. Contract control plane (charter M1)
- [x] 1.1 Write failing contract tests for remote normalization/authorization, contract conformance, zero-skip behavior, and per-file coverage (R-3, R-4, R-8, R-9, R-18; per D4/D6/D7). Evidence: the traceability matrix cites collecting `tests/core` and governance nodes.
- [-] 1.2 Implement the core remotes, conformance, contract-gate, registry, and CLI behaviors (R-3, R-4, R-8, R-9, R-18). **Deferred remediation:** GAP-01/GAP-02 require all-active-pack runtime execution in the release path, and HC-01/HC-02/LOOP-01 require the config-contract/provenance follow-up in `docs/NEXT-STEPS.md`.
- [x] 1.3 Update traceability for R-3, R-4, R-8, R-9, and R-18. Evidence: every listed requirement has a collecting Green node and matching source marker.

## 2. Traceability and projections (charter M2)
- [x] 2.1 Write failing tests for matrix completeness, Green-node collection, deterministic rendering, drift, and malformed data (R-5, R-6, R-7; per D5). Evidence: the checked core test nodes collect.
- [x] 2.2 Implement traceability lint and projection renderer registry/check/write flow (R-5, R-6, R-7). Evidence: `hexvision projections --check` and the traceability gate are release checks.
- [x] 2.3 Update traceability for R-5, R-6, and R-7. Evidence: generated roadmap/backlog projections and the checked matrix are current.

## 3. Edge-AI evidence gates (charter M3)
- [x] 3.1 Write failing model-card, latency, and determinism scenarios including missing-input BLOCK paths (R-10, R-11, R-12; per D6). Evidence: collecting robotics test nodes cover the declared scenarios.
- [x] 3.2 Implement Jetson model-card, latency-budget, and determinism gates plus realistic example evidence (R-10, R-11, R-12). Evidence: the Jetson pack registers these gates and traceability cites their collecting tests.
- [x] 3.3 Update traceability for R-10, R-11, and R-12. Evidence: all three requirements have Green rows with source markers.

## 4. Mission governance gates (charter M4)
- [x] 4.1 Write failing safety-envelope and HIL scenarios, including each permissive direction and undeclared HIL absence (R-13, R-14, R-15; per D8). Evidence: collecting robotics test nodes cover the declared baseline scenarios.
- [-] 4.2 Implement safety-envelope widening detection and declared HIL availability handling (R-13, R-14, R-15). **Deferred remediation:** SAFE-01 must make unavailable, timed-out, unreadable, and malformed baselines non-passing with diagnosable evidence; filesystem-boundary coverage remains scheduled in `docs/NEXT-STEPS.md`.
- [x] 4.3 Update traceability for R-13, R-14, and R-15. Evidence: all three requirements have Green rows with collecting test nodes; the deferred remediation above is not represented as a false completion.

## 5. Integration and publication readiness (charter M5)
- [x] 5.1 Write failing L1/L2/L3 destination and non-commanding-boundary scenarios (R-16, R-17; per D4/D8). Evidence: collecting governance and core test nodes cover the declared boundary.
- [-] 5.2 Integrate CI, hooks, agent operating rules, and peer review for the non-commanding boundary and publication gate (R-16, R-17). **Deferred remediation:** the release-orchestration command must be wired into the configured chain and CI as specified in `docs/QUALITY-LOOPS.md`; `G-PUB` remains intentionally absent.
- [x] 5.3 Final traceability update for R-16 and R-17; regenerate projections and run the integration gate suite. Evidence: traceability is Green with collected nodes and projections are regenerated below; publication remains blocked without G-PUB.

## Deferred remediation register

`[-]` means the historical baseline task has a known, scoped remediation that is not complete. It is not a hidden pass and it is not a generic “in progress” placeholder. The governing follow-up sequence, sizing, and exit evidence are in [`docs/NEXT-STEPS.md`](../../../docs/NEXT-STEPS.md):

- **M1:** release orchestration and configuration/tool provenance (GAP-01, GAP-02, HC-01, HC-02, LOOP-01);
- **M4:** safety baseline failure classification and hostile filesystem boundaries (SAFE-01, TEST-01, LOG-01);
- **M5:** authoritative all-active-pack loop wiring and branch-protection verification.
