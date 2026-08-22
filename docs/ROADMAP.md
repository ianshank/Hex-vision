<!-- GENERATED FROM planning/roadmap_data.py; DO NOT HAND-EDIT. Regenerate with: hexvision projections --write -->
# Hex-vision roadmap

**Change:** `add-robotics-governance-harness`

## M0 — Reconnaissance and guardrails
**Budget:** 3 PRs / 20 hours  
**Exit criteria:** Baseline and control-plane records are verified; roadmap data validates.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 0.1 | Write or verify failing configuration scenarios | in-progress | 4h | R-1, R-2 | — |
| 0.2 | Deliver layered configuration and frozen-key mechanism | done | 8h | R-1, R-2 | — |
| 0.3 | Deliver committed shared fail-closed foundations | done | 4h | — | — |
| 0.4 | Record archive gap and re-baseline | done | 2h | — | — |
| 0.5 | Update M0 traceability | todo | 2h | R-1, R-2 | 0.1 |

## M1 — Contract control plane
**Budget:** 4 PRs / 28 hours  
**Exit criteria:** Contract and fail-closed gate tests pass through Makefile targets.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 1.1 | Write failing contract-control tests | in-progress | 8h | R-3, R-4, R-8, R-9, R-18 | — |
| 1.2 | Implement core contract-control modules | in-progress | 16h | R-3, R-4, R-8, R-9, R-18 | 1.1 |
| 1.3 | Update M1 traceability | todo | 4h | R-3, R-4, R-8, R-9, R-18 | 1.2 |

## M2 — Traceability and projections
**Budget:** 3 PRs / 20 hours  
**Exit criteria:** Matrix lint and deterministic projection drift checks pass.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 2.1 | Write failing traceability and projection tests | in-progress | 6h | R-5, R-6, R-7 | — |
| 2.2 | Implement traceability lint and projections | in-progress | 10h | R-5, R-6, R-7 | 2.1 |
| 2.3 | Update M2 traceability | todo | 4h | R-5, R-6, R-7 | 2.2 |

## M3 — Edge-AI evidence gates
**Budget:** 5 PRs / 32 hours  
**Exit criteria:** Model-card, latency, and determinism gates pass clean and failure-path tests.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 3.1 | Write failing edge-AI evidence-gate tests | in-progress | 10h | R-10, R-11, R-12 | — |
| 3.2 | Implement edge-AI evidence gates and examples | in-progress | 18h | R-10, R-11, R-12 | 3.1 |
| 3.3 | Update M3 traceability | todo | 4h | R-10, R-11, R-12 | 3.2 |

## M4 — Mission governance gates
**Budget:** 4 PRs / 28 hours  
**Exit criteria:** Safety and HIL governance tests prove bound and absence behavior.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 4.1 | Write failing safety and HIL tests | in-progress | 10h | R-13, R-14, R-15 | — |
| 4.2 | Implement safety-envelope and HIL gates | in-progress | 14h | R-13, R-14, R-15 | 4.1 |
| 4.3 | Update M4 traceability | todo | 4h | R-13, R-14, R-15 | 4.2 |

## M5 — Integration and publication readiness
**Budget:** 3 PRs / 20 hours  
**Exit criteria:** CI, hooks, skills, projections, and traceability are integrated; publication remains gated.

| Task | Status | Estimate | Requirements | Dependencies |
|---|---|---:|---|---|
| 5.1 | Write failing publication and non-commanding-boundary tests | in-progress | 6h | R-16, R-17 | — |
| 5.2 | Integrate hooks, CI, skills, and peer review | in-progress | 10h | R-16, R-17 | 5.1, 1.2, 2.2, 3.2, 4.2 |
| 5.3 | Update final traceability and regenerate projections | todo | 4h | R-16, R-17 | 5.2 |
