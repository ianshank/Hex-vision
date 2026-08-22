# Tasks — add-robotics-governance-harness

`tasks.md` owns scope. `planning/roadmap_data.py` is the projection source; `docs/ROADMAP.md` and `planning/backlog.csv` are generated views. Statuses below reflect the verified baseline and parallel workstreams as of 2026-08-22.

## 0. Reconnaissance and guardrails (charter M0)
- [ ] 0.1 Write or verify failing configuration scenarios for R-1 and R-2 before further configuration changes (per D1/D2). Dependency: test evidence is not verified in this worktree.
- [x] 0.2 Deliver the committed layered configuration engine and frozen-key mechanism for R-1 and R-2 (per D1/D2). Evidence: baseline commit `10b37ddb6ae1`; this task does not claim test counts.
- [x] 0.3 Deliver the committed error taxonomy, gate result model, gate base, and pack interface needed for fail-closed work. Dependency: core implementation and tests remain in flight.
- [x] 0.4 Record archive-versus-plan gap and re-baseline under RB-001: the archive had no Python reference pack or roadmap-control documents.
- [ ] 0.5 Update traceability for M0 requirements R-1 and R-2. Dependency: CORE traceability lint is in flight.

## 1. Contract control plane (charter M1)
- [ ] 1.1 Write failing contract tests for remote normalization/authorization, contract conformance, zero-skip behavior, and per-file coverage (R-3, R-4, R-8, R-9, R-18; per D4/D6/D7). Dependency: CORE workstream owns tests/core.
- [ ] 1.2 Implement the core remotes, conformance, contract-gate, registry, and CLI behaviors (R-3, R-4, R-8, R-9, R-18). Dependency: CORE workstream is in flight; no completion is claimed here.
- [ ] 1.3 Update traceability for R-3, R-4, R-8, R-9, and R-18. Dependency: collecting tests must exist before any Green row.

## 2. Traceability and projections (charter M2)
- [ ] 2.1 Write failing tests for matrix completeness, Green-node collection, deterministic rendering, drift, and malformed data (R-5, R-6, R-7; per D5). Dependency: CORE workstream owns tests/core.
- [ ] 2.2 Implement traceability lint and projection renderer registry/check/write flow (R-5, R-6, R-7). Dependency: CORE workstream is in flight.
- [ ] 2.3 Update traceability for R-5, R-6, and R-7. Dependency: renderer output must be regenerated and byte-checked.

## 3. Edge-AI evidence gates (charter M3)
- [ ] 3.1 Write failing model-card, latency, and determinism scenarios including missing-input BLOCK paths (R-10, R-11, R-12; per D6). Dependency: JETSON workstream owns tests/robotics.
- [ ] 3.2 Implement Jetson model-card, latency-budget, and determinism gates plus realistic example evidence (R-10, R-11, R-12). Dependency: JETSON workstream is in flight.
- [ ] 3.3 Update traceability for R-10, R-11, and R-12. Dependency: only collected tests may support Green.

## 4. Mission governance gates (charter M4)
- [ ] 4.1 Write failing safety-envelope and HIL scenarios, including each permissive direction and undeclared HIL absence (R-13, R-14, R-15; per D8). Dependency: JETSON workstream owns tests/robotics.
- [ ] 4.2 Implement safety-envelope widening detection and declared HIL availability handling (R-13, R-14, R-15). Dependency: DEC-005, DEC-006, and DEC-008 remain OPEN for policy authority; implementation must stop at those boundaries.
- [ ] 4.3 Update traceability for R-13, R-14, and R-15. Dependency: no Green without collected tests.

## 5. Integration and publication readiness (charter M5)
- [ ] 5.1 Write failing L1/L2/L3 destination and non-commanding-boundary scenarios (R-16, R-17; per D4/D8). Dependency: AGENTS workstream owns hooks and governance tests.
- [ ] 5.2 Integrate CI, hooks, agent operating rules, and peer review for the non-commanding boundary and publication gate (R-16, R-17). Dependency: AGENTS workstream is in flight; `G-PUB` is intentionally absent.
- [ ] 5.3 Final traceability update for R-16 and R-17; regenerate projections and run the integration gate suite. Dependency: `hexvision projections --write` must run from the merged renderer; publication remains blocked without G-PUB.
