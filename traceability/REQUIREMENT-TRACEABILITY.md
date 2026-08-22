# Requirement Traceability — Hex-vision

**Source of truth:** `openspec/changes/add-robotics-governance-harness/specs/*.md` (R-1 through R-18), read at source for this matrix. `planning/roadmap_data.py` contains the same identifier set and milestone mapping.

**Maintenance:** update whenever a task mapping changes; scheduled updates are tasks 0.5, 1.3, 2.3, 3.3, 4.3, and 5.3.

**Enforcement:** `hexvision.traceability` runs in the CI guard path. It expects columns `requirement id`, `statement`, `status`, `test node id`, `inherits-from`, `decision ref`, and `notes`; it rejects duplicate/missing rows and validates Green test-node collection. Status enum: `Green | Amber | Red | Inherited | Waived`.

All implementation and test references below are planned or in flight unless a cited baseline module is explicitly named. No row is Green because no collecting test node was verified in this worktree.

| requirement id | statement | status | test node id | inherits-from | decision ref | notes |
|---|---|---|---|---|---|---|
| R-1 | Layered configuration retains provenance and fails closed on malformed layers. | Amber | (in flight: `tests/core/test_config.py`) | (none) | DEC-004 | Baseline `src/hexvision/config.py` exists; CORE test verification is in flight. |
| R-2 | Frozen operational controls reject environment and CLI overrides. | Amber | (in flight: `tests/core/test_config.py`) | (none) | DEC-004 | Baseline frozen-key mechanism exists; no Green claim without collection. |
| R-3 | One shared normalizer handles supported remote URL spellings. | Red | (in flight: `tests/core/test_remotes.py`) | (none) | DEC-004 | CORE owns `src/hexvision/remotes.py`; implementation is in flight. |
| R-4 | Remote authorization blocks empty, invalid, unreadable, or unallowlisted destinations. | Red | (in flight: `tests/core/test_remotes.py`) | (none) | DEC-004 | CORE implementation is in flight. |
| R-5 | Traceability rows are complete, unique, and linted against configured semantics. | Red | (in flight: `tests/core/test_traceability.py`) | (none) | DEC-004 | CORE traceability linter is in flight. |
| R-6 | Green traceability evidence must cite a collecting pytest node. | Red | (in flight: `tests/core/test_traceability.py`) | (none) | DEC-004 | No Green row is claimed until collection is verified. |
| R-7 | Roadmap and backlog are deterministic generated projections with drift checks. | Amber | (in flight: `tests/core/test_projections.py`) | (none) | RB-001 | Planning source exists; renderer is in flight and output needs regeneration. |
| R-8 | Packs conform to every Gate Harness Contract v1.1 clause. | Red | (in flight: `tests/core/test_conformance.py`) | (none) | DEC-004 | CORE conformance implementation is in flight. |
| R-9 | Skipped and xfailed tests fail unless validly authorized. | Red | (in flight: `tests/core/test_contract.py`) | (none) | DEC-004 | CORE conftest and zero-skip audit are in flight. |
| R-10 | Model provenance and model-card/artifact pairing are enforced. | Red | (in flight: `tests/robotics/test_model_card.py`) | (none) | DEC-002 | JETSON implementation is in flight. |
| R-11 | Runtime-specific latency evidence includes configured percentile, budget, headroom, and device. | Red | (in flight: `tests/robotics/test_latency.py`) | (none) | DEC-002 | JETSON implementation is in flight. |
| R-12 | Evaluation evidence proves repeatable seeds and metric tolerance. | Red | (in flight: `tests/robotics/test_determinism.py`) | (none) | DEC-002 | JETSON implementation is in flight. |
| R-13 | Mission safety bounds are declared and internally consistent without vehicle command. | Red | (in flight: `tests/robotics/test_safety_envelope.py`) | (none) | DEC-004 | JETSON implementation is in flight; non-commanding boundary is specified. |
| R-14 | Permissive safety-bound widening requires decision-log authority. | Red | (in flight: `tests/robotics/test_safety_envelope.py`) | (none) | OPEN DEC-005/DEC-008 | Owner decision boundaries remain open; implementation must not assume authorization. |
| R-15 | Hardware-in-the-loop runner absence is declared and authorized or blocks. | Red | (in flight: `tests/robotics/test_hardware_in_loop.py`) | (none) | OPEN DEC-006 | JETSON implementation is in flight; no absence authorization is logged. |
| R-16 | Robotics governance remains non-commanding. | Red | (in flight: `tests/governance/test_governance_meta.py`) | (none) | DEC-004 | AGENTS enforcement and review instructions are in flight. |
| R-17 | Public publication requires both destination allowlisting and G-PUB authority. | Red | (in flight: `tests/governance/test_hooks.py`) | (none) | OPEN DEC-007 | G-PUB is intentionally absent; public publication is blocked. |
| R-18 | Per-file coverage includes untested files and enforces configured floors. | Red | (in flight: `tests/core/test_contract.py`) | (none) | DEC-004 | CORE coverage gate is in flight. |
