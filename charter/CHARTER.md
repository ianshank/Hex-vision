# Project Charter — Hex-vision
**Change ID:** `add-robotics-governance-harness` | **Charter v1.0** | 2026-08-22
**Source documents:** Gate Harness Contract v1.1; `openspec/changes/add-robotics-governance-harness/`
**Executor:** Hex-vision contributors, operating under the change package above.

## 1. Purpose
Hex-vision provides a modular, fail-closed governance and gate harness for drone, robotics, and edge-AI repositories. It implements Gate Harness Contract v1.1 while adding repository-facing evidence checks for model provenance, latency, determinism, mission safety envelopes, and declared hardware-in-the-loop availability. The harness creates auditable release controls without taking vehicle-control authority.

## 2. Hard constraints (violating any of these stops work)
- **C-1 — Fail-closed gates.** `GateStatus` has no plain `SKIPPED` member and `run_gate` converts escaped failures to `GateResult.blocked(...)`; the conformance job verifies the declared fail-closed target policy. Release condition: no gate reports `PASSED` when its check or required tool could not run.
- **C-2 — No hardcoded operational values.** `hexvision.config.load_config` resolves operational values from layered configuration and records provenance; frozen-key rejection prevents environment and CLI changes to protected prefixes; conformance and peer review reject operational literals outside configuration. Release condition: thresholds, paths, globs, allowlists, budgets, and tool choices resolve through configuration.
- **C-3 — One normalizer (INV-3).** `hexvision.conformance` AST-walks `src/` and rejects any declaration count other than one for `normalize_remote_url`; L1, L2, and L3 invoke that normalizer through the remotes interface. Release condition: the declaration-count check and remote gate pass.
- **C-4 — Zero skipped tests (INV-2).** `tests/conftest.py` turns skipped and xfailed tests into failures, and `ZeroSkipAuditGate` audits declarations against decision-log authority. Release condition: CI records no unapproved skip or xfail.
- **C-5 — Safety bounds are governed, not configured.** `robotics.safety_envelope` is a frozen config prefix; `SafetyEnvelopeGate` compares mission files with their committed baselines and requires a decision-log identifier for any permissive widening. Release condition: every widening has an authorizing log entry or the gate blocks.
- **C-6 — Publication is gated.** The L1 PreToolUse guard, L2 pre-push hook, and L3 CI remotes gate allow only configured destinations after shared normalization; publication workflow checks `docs/decision-log.md` for `G-PUB` before a public GitHub or Hugging Face push. Release condition: an allowlisted destination and a real `G-PUB` entry exist. No `G-PUB` entry is presently logged.

## 3. Scope
**In:** Gate Harness Contract v1.1 target and invariant enforcement; layered configuration and provenance; dynamic pack discovery; traceability and generated planning projections; Jetson/edge-AI repository gates for model cards, latency, determinism, safety envelopes, and declared HIL; hooks, CI, agent operating rules, and a small example repository.

**Out:** Flight-control logic, actuator control, autonomous route selection, sensor fusion, model training, airworthiness certification, real hardware provisioning, and judging whether a human-selected bound is airworthy. Hex-vision never commands a vehicle; it gates repository changes and records whether stated controls are present.

## 4. Milestones and target states
| M | Deliverable | Exit criteria |
|---|---|---|
| M0 | Reconnaissance and guardrails | Verified baseline recorded; control-plane documents exist; `planning.roadmap_data.validate()` passes; re-baselining is recorded. |
| M1 | Contract control plane | Remote normalization, fail-closed contract gates, zero-skip control, coverage-floor enforcement, and conformance scenarios have passing tests and are invoked through Makefile targets. |
| M2 | Traceability and projections | Requirement matrix lint and deterministic roadmap/backlog renderers pass their drift checks. |
| M3 | Edge-AI evidence gates | Model-card, latency, and determinism gates have passing clean and named failure-path tests. |
| M4 | Mission governance gates | Safety-envelope and HIL gates prove bounds, widening authority, and declared runner absence behavior. |
| M5 | Integration and publication readiness | Cross-workstream review completes; CI, hooks, skills, projections, and traceability are green; a human separately records `G-PUB` before public publication. |

**MVP** = M0–M2. **Beta** = M0–M4. **Production-candidate** = M0–M5 plus a clean peer review and the applicable human publication gate.

## 5. CONFIRM-FIRST decisions
- **DEC-005 — Safety-widening authority.** OPEN — default proposal: the repository owner records a separate decision-log entry naming each permissive mission-bound change before merge.
- **DEC-006 — HIL absence authorization.** OPEN — default proposal: the repository owner may authorize a time-bounded declared HIL absence by naming the missing runner and review date in the log.
- **DEC-007 — Public release destination and timing.** OPEN — default proposal: publish only the approved GitHub repository plus Hugging Face dataset and Space after release artifacts and destination allowlists are reviewed; `G-PUB` remains the final gate.
- **DEC-008 — Safety-envelope baseline source.** OPEN — default proposal: use `git show HEAD:<mission-path>` as the widening baseline, treating absent blobs as new files and recording that state in measurements.

Defaults are proposals, not decisions. A decision exists only when it appears in `docs/decision-log.md`.

## 6. Carve-out budgets and review triggers
Budgets are ceilings per milestone before mandatory owner review: M0 **3 PRs / 20 hours**, M1 **4 PRs / 28 hours**, M2 **3 PRs / 20 hours**, M3 **5 PRs / 32 hours**, M4 **4 PRs / 28 hours**, M5 **3 PRs / 20 hours**.

- **R-1** Any L1/L2/L3 destination disagreement, remote-normalization failure, or unallowlisted public destination blocks work under C-3 and C-6.
- **R-2** A milestone budget is exhausted while a CONFIRM-FIRST decision remains OPEN; stop and obtain owner review.
- **R-3** Any gate reports `BLOCKED`, any required tool is absent, or a fail-closed path becomes a pass; stop under C-1.
- **R-4** Any skipped or xfailed test is discovered; `tests/conftest.py` and `ZeroSkipAuditGate` must reject it under C-4.
- **R-5** Work exceeds 125% of its milestone hour budget or the same Major review finding recurs a third time; stop and escalate rather than loop.
- **R-6** A safety-bound widening, coverage-floor reduction, frozen-key bypass, or unreviewed dependency change is proposed; C-2 or C-5 requires owner review and a log entry where applicable.

## 7. Risks
| Risk | Impact | Mitigation |
|---|---|---|
| A missing scanner or runner is mistaken for a clean result | A release control becomes decorative | C-1 and trigger R-3 require `BLOCKED`, not pass. |
| Multiple URL parsers diverge on a publish destination | Unallowlisted destination could be accepted | C-3 and trigger R-1 enforce AST declaration count and shared L1/L2/L3 invocation. |
| A mission bound is widened without human authority | Safety posture changes without reviewable governance | C-5 and trigger R-6 require frozen configuration, widening detection, and a decision-log entry. |
| Parallel workstreams claim evidence before tests collect | Traceability becomes fictional | M2 exit criteria and the traceability linter require collecting test nodes before Green. |
| Public publication occurs before controls are ready | Irreversible disclosure or destination drift | C-6 keeps publication blocked until an allowlisted destination and `G-PUB` entry exist. |

## 8. Working agreement for contributors
Read `design.md` before `tasks.md`; execute tasks in order; write the failing test first for every requirement scenario; run `make specs` after spec edits and `make pre-pr` before handoff; never mark a task complete with skipped tests; stop at any CONFIRM-FIRST boundary or review trigger; and hand every code, configuration, tooling, or safety-envelope diff to a reviewer. Update traceability whenever a requirement mapping changes.
