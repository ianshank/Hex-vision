# Add robotics governance harness

## Why
Robotics and edge-AI repositories need repeatable, auditable gates that distinguish a detected defect from an inability to inspect the repository. Gate Harness Contract v1.1 supplies cross-stack target names and five invariants, while the attached archive lacked the Python reference pack and all roadmap-control documents needed to turn those requirements into an executable plan. This change creates the Hex-vision control plane and specifies the real contract and Jetson behavior being implemented in parallel.

## What Changes
- Add a modular Gate Harness Contract v1.1 implementation: layered configuration, dynamically discovered packs, fail-closed gate results, one remote normalizer, conformance checks, and Makefile-authoritative execution.
- Add deterministic planning projections and a linted requirement-traceability matrix driven by `planning/roadmap_data.py`.
- Add Jetson/edge-AI evidence gates for model-card provenance, latency budgets, deterministic evaluation, mission safety envelopes, and declared hardware-in-the-loop availability.
- Add the governance control plane: a charter, decision log, OpenSpec scenarios, implementation plan, and generated roadmap/backlog projections.

## Impact
- Affected specs: `config.md`, `remotes.md`, `traceability.md`, `projections.md`, `conformance.md`, `robotics-model-card.md`, `robotics-latency.md`, `robotics-determinism.md`, `robotics-safety-envelope.md`, and `robotics-hil.md` (all new).
- Affected code: planned core modules in `src/hexvision/`, Jetson domain gates and pack registration, hook/CI/agent plumbing, and the example repository. The existing baseline at `10b37ddb6ae1` contains configuration, error taxonomy, gate result model, and pack interfaces; core, Jetson, and agents work is in flight.
- Depends on: the parallel CORE, JETSON, and AGENTS workstreams. Their implementations are in flight; this package does not claim their tests or completion state.
- Constraint inherited from charter C-1: a missing tool, unreadable input, empty allowlist, or unexpected gate error must produce a non-pass result rather than a silent success.
