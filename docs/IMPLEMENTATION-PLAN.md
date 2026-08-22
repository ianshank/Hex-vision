# Hex-vision implementation plan
**Audience:** repository owner, integrator, and workstream leads  
**Classification:** internal engineering planning  
**Baseline inspected:** `10b37ddb6ae1` (`2026-08-22`, `M0.0: config engine, error taxonomy, gate result model, pack interface`)

## Current position
At the inspected baseline, the tracked tree contains layered configuration and defaults, error taxonomy, observability, gate result/base interfaces, and pack base interfaces. This plan does not claim tests, coverage, completed gates, generated projections, hooks, CI, or domain-gate behavior because those artifacts were not present in the inspected worktree. CORE, JETSON, and AGENTS are parallel workstreams and their work is in flight.

The attached V2 harness archive did not contain a Python reference pack even though the Contract names Python as the reference. The Contract's required Python-reference change—add `remotes` to the Makefile and insert it in `pre-pr` between `audit` and `projections`—therefore remains implementation work. The archive also did not include roadmap, charter, milestone, or next-steps documents; the governance toolkit supplies the instantiated control-plane pattern. The Contract identifies literal placeholder versions in Node and JVM packs as unpinned; an unpinned tool moves its gate definition and is not an acceptable model for this implementation.

## Milestone execution plan
| Milestone | Entry criteria | Exit criteria | Owner | Budget | Gates proving exit |
|---|---|---|---|---|---|
| M0 — Reconnaissance and guardrails | Baseline checkout available | RB-001 is recorded; control-plane data validates; constraints and scope are separate | Governance | 3 PRs / 20h | `planning.roadmap_data.validate()`; spec validation once AGENTS script lands |
| M1 — Contract control plane | M0 records available | R-3/R-4/R-8/R-9/R-18 have tested core implementations invoked through Makefile authority | CORE | 4 PRs / 28h | remotes, conformance, zero-skip, coverage, and Makefile-authority checks |
| M2 — Traceability and projections | M1 interfaces available | Matrix lint and deterministic render/check cycle are passing | CORE + Governance | 3 PRs / 20h | `make traceability`; `make projections` |
| M3 — Edge-AI evidence gates | Core gate model available | Model-card, latency, and determinism clean/failure paths are tested | JETSON | 5 PRs / 32h | Jetson domain gates and pack conformance |
| M4 — Mission governance gates | M3 pack path available; OPEN decision boundaries honored | Safety widening and HIL absence have tested governed outcomes | JETSON + owner | 4 PRs / 28h | safety-envelope and HIL gates; frozen-key tests |
| M5 — Integration and publication readiness | M1–M4 changes merged into integration tree | CI, hooks, skills, generated views, and traceability agree; publication remains gated | Integrator + AGENTS | 3 PRs / 20h | `make pre-pr`, conformance, projections, traceability, peer review; `G-PUB` for public publication |

## Parallel-agent execution model
CORE owns stack-agnostic modules and core tests; JETSON owns robotics modules, Jetson pack, examples, and robotics tests; AGENTS owns hooks, CI, skill/agent instructions, and governance tests; GOVERNANCE owns the charter, OpenSpec package, planning data, decisions, traceability, and planning documents. Each workstream edits only its assigned worktree paths; integration is performed after commits are reviewed rather than by cross-editing parallel worktrees. Every task follows the test-first sequence in `tasks.md`; the peer-review gate occurs after implementation and traceability update, before a task is marked done. A third recurrence of the same Major review finding triggers R-5 stop-and-review.

## Risk register
| Risk | Consequence | Named mitigation |
|---|---|---|
| Renderer output differs from hand-prepared placeholders | Projection drift at integration | M2 runs `hexvision projections --write`; CI byte-checks the resulting files. |
| Traceability turns Green before test collection | False readiness claim | R-6 and the traceability linter require actual collection. |
| Hardware is unavailable in CI | Invisible HIL omission | R-15 requires a declared, logged absence or a blocker. |
| Safety widening direction is implemented incorrectly | Permissive mission change bypasses review | R-14 tests each bound direction; C-5 freezes safety configuration. |
| Hook is bypassed locally | Public destination check is treated as authoritative when it is not | Contract L3 CI and L4 ruleset remain authoritative; L2 documents `--no-verify` limitation. |

## Explicitly not in scope
Hex-vision does not command a vehicle, operate actuators, approve airworthiness, choose flight bounds, train perception models, provision real HIL hardware, or publish artifacts automatically without a real `G-PUB` decision entry and destination allowlisting. The harness reports repository evidence and governance status; named humans retain safety and release authority.
