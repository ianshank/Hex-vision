<!-- Generated from planning.roadmap_data; do not edit directly. -->
# Roadmap: add-robotics-governance-harness

## M0 — Reconnaissance and guardrails

Baseline and control-plane records are verified; roadmap data validates.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 0.1 | Write or verify failing configuration scenarios | done | 4 | R-1, R-2 |  |
| 0.2 | Deliver layered configuration and frozen-key mechanism | done | 8 | R-1, R-2 |  |
| 0.3 | Deliver committed shared fail-closed foundations | done | 4 |  |  |
| 0.4 | Record archive gap and re-baseline | done | 2 |  |  |
| 0.5 | Update M0 traceability | done | 2 | R-1, R-2 | 0.1 |

## M1 — Contract control plane

Contract and fail-closed gate tests pass through Makefile targets.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 1.1 | Write failing contract-control tests | done | 8 | R-18, R-3, R-4, R-8, R-9 |  |
| 1.2 | Implement core contract-control modules | deferred | 16 | R-18, R-3, R-4, R-8, R-9 | 1.1 |
| 1.3 | Update M1 traceability | done | 4 | R-18, R-3, R-4, R-8, R-9 | 1.2 |

## M2 — Traceability and projections

Matrix lint and deterministic projection drift checks pass.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 2.1 | Write failing traceability and projection tests | done | 6 | R-5, R-6, R-7 |  |
| 2.2 | Implement traceability lint and projections | done | 10 | R-5, R-6, R-7 | 2.1 |
| 2.3 | Update M2 traceability | done | 4 | R-5, R-6, R-7 | 2.2 |

## M3 — Edge-AI evidence gates

Model-card, latency, and determinism gates pass clean and failure-path tests.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 3.1 | Write failing edge-AI evidence-gate tests | done | 10 | R-10, R-11, R-12 |  |
| 3.2 | Implement edge-AI evidence gates and examples | done | 18 | R-10, R-11, R-12 | 3.1 |
| 3.3 | Update M3 traceability | done | 4 | R-10, R-11, R-12 | 3.2 |

## M4 — Mission governance gates

Safety and HIL governance tests prove bound and absence behavior.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 4.1 | Write failing safety and HIL tests | done | 10 | R-13, R-14, R-15 |  |
| 4.2 | Implement safety-envelope and HIL gates | deferred | 14 | R-13, R-14, R-15 | 4.1 |
| 4.3 | Update M4 traceability | done | 4 | R-13, R-14, R-15 | 4.2 |

## M5 — Integration and publication readiness

CI, hooks, skills, projections, and traceability are integrated; publication remains gated.

| ID | Title | Status | Estimate hours | Requirements | Depends on |
| --- | --- | --- | ---: | --- | --- |
| 5.1 | Write failing publication and non-commanding-boundary tests | done | 6 | R-16, R-17 |  |
| 5.2 | Integrate hooks, CI, skills, and peer review | deferred | 10 | R-16, R-17 | 1.2, 2.2, 3.2, 4.2, 5.1 |
| 5.3 | Update final traceability and regenerate projections | done | 4 | R-16, R-17 | 5.2 |
