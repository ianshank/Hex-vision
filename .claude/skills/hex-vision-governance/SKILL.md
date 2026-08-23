---
name: hex-vision-governance
description: Mandatory operating rules for planning, implementation, review, tooling changes, and git actions in Hex-vision.
---

# Hex-vision governance operating rules

## Gate table — check before any task
| Phase | Allowed when |
| --- | --- |
| M0 guardrails | Always, within the task scope. |
| M1–M5 engineering | The live `docs/decision-log.md` contains the relevant DEC entry and every dependency named by `tasks.md`. |
| Process/docs track | A live RB entry names the work or PR batch. Urgency is never authorization. |
| Push or publication | The destination is allowlisted and the live log contains the required publication gate (`G-PUB` where publication applies). |

If an entry is missing, STOP and report it. Do not treat a conversation, memory, or this skill as a substitute for a logged decision.

## CONFIRM-FIRST
The live `docs/decision-log.md` is authoritative for DEC-001 onward. Proposed defaults in `openspec/changes/add-robotics-governance-harness/design.md` are proposals, not decisions. Re-check the log before acting, including after a context refresh.

## Source of truth
`tasks.md` owns scope. `charter/CHARTER.md` owns constraints and exit criteria. `docs/ROADMAP.md` and `planning/backlog.csv` are generated projections from `planning/roadmap_data.py`; do not hand-edit them. Charter version pin: **v1.0** (2026-08-22). Stop and reconcile if the charter header differs.

## Budgets
Use the per-milestone PR and engineering-hour budget in the charter. Process-scope work sits outside a milestone budget only when its RB entry explicitly says so. A budget breach triggers the charter owner review; it is not a reason to omit accounting.

## Decisions since 2026-08-22
- **DEC-001** (2026-08-22): project name is Hex-vision.
- **DEC-002** (2026-08-22): Jetson/edge-AI Python is the first pack.
- **DEC-003** (2026-08-22): publication targets are public GitHub and Hugging Face after the publication gate.
- **DEC-004** (2026-08-22): build the complete scaffold in this session.
- **RB-001** (2026-08-22): re-baseline after the supplied archive lacked a Python pack and planning documents.
- **DEC-009** (2026-08-22): retain `@governance-skip` decisions as audit evidence, but make every pytest skip and xfail fail; declared hardware-in-the-loop gate status is unaffected.

This section is mechanically checked by `tests/governance/test_skill_freshness.py`: every decision-log ID dated on or after the date in this heading must appear here.

## Definition of done
1. Failing tests first; green at completion; zero skipped or xfailed tests.
2. `make specs` passes after a specification change.
3. Traceability is updated when a requirement mapping changes.
4. Safety bounds and thresholds are not edited with a failing gate run; widening has its separate decision-backed change.
5. No dependency violates charter constraints.
6. New documents declare audience and classification; factual tree claims are mechanically checked or commit-stamped.

## Collaboration default
Hand every diff to a reviewer before completion, including tooling, configuration, hook, and CI changes. Major and Blocker findings prevent completion.

## Tooling changes
Changing `.mcp.json`, `.claude/settings.json`, a hook, or a plugin source is a governed decision, not housekeeping. The shell guard cannot retroactively govern a server enabled by configuration.

## Local gates
`make pre-pr` invokes every configured CI gate in contract order, including conformance. Use `make specs` and `hexvision conformance --pack jetson`; do not reconstruct their commands manually.
