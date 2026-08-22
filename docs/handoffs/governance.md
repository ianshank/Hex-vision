# Governance workstream handoff

## Delivered
- Created the Hex-vision charter, append-only decision log, Director-level implementation plan, OpenSpec proposal/design/tasks package, ten capability spec deltas, traceability matrix, planning package, and provisional generated roadmap/backlog projections.
- Created `planning/roadmap_data.py` as the typed, validated single source for M0–M5 planning data. It exposes `data()` and `validate()` and has no I/O or `hexvision` imports.
- Kept requirements R-1 through R-18 identical across spec deltas, roadmap data, and traceability. Matrix rows are Amber or Red; none is Green without a verified collecting test node.

## Decisions and boundaries
- Logged only DEC-001 through DEC-004 and RB-001, all dated 2026-08-22 and recorded by `ian`.
- Left DEC-005 safety-widening authority, DEC-006 HIL absence authorization, DEC-007 public release destination/timing, and DEC-008 safety-envelope baseline source OPEN.
- Intentionally did not log `G-PUB`. Public GitHub and Hugging Face publication must remain blocked until the integrator records that final gate at publication time.

## Config and public interfaces
- Config keys added: none. This workstream did not edit defaults or `pyproject.toml`.
- Public planning symbols: `planning.roadmap_data.data`, `planning.roadmap_data.validate`, and the typed schema declarations `TaskData`, `MilestoneData`, `RequirementData`, and `RoadmapData`.

## Validation run
- `uv venv && uv pip install -q -e ".[dev]"`
- `.venv/bin/ruff check planning`
- `.venv/bin/ruff format --check planning`
- `.venv/bin/mypy --strict planning`
- `.venv/bin/python -c "import planning.roadmap_data as r; r.validate(); print('validate ok')"`
- Custom checks for three-way requirement IDs, scenario WHEN/THEN structure, template-remnant removal, no non-BMP symbols, no unverified Green traceability rows, owned-file presence, and whitespace errors.

No tests were added because GOVERNANCE owns no files under `tests/`; no test count or coverage percentage is claimed.

## Required integration actions
1. Run `hexvision projections --write` from the merged CORE renderer. `docs/ROADMAP.md` and `planning/backlog.csv` are deliberate provisional hand renders and must be regenerated once; treat that first difference as expected, then require byte stability in CI.
2. Ensure the CORE traceability parser accepts the required exact columns already used by the matrix: requirement id, statement, status, test node id, inherits-from, decision ref, notes. Verify it accepts `(none)` in non-Green rows or update the non-Green convention consistently.
3. CORE must add planning-data tests. Decide whether `planning/` enters the coverage source root; current `pyproject.toml` covers only `src/hexvision`, so these importable governance data modules are not presently covered by the stated per-file floor. This is an integration decision; GOVERNANCE did not edit `pyproject.toml`.
4. Merge CORE, JETSON, and AGENTS implementation/test changes before moving any traceability row to Green. Run collection for every Green node id.
5. Preserve the OPEN boundaries in the charter and tasks. Do not implement past DEC-005, DEC-006, DEC-007, or DEC-008 without owner decisions recorded in `docs/decision-log.md`.
6. Keep `G-PUB` absent until publication time. At that time, the integrator must record the actual authorization and verify the destination allowlist before public GitHub or Hugging Face publication.
7. Run the merged `make specs`, `make projections`, `make traceability`, `make conformance`, and `make pre-pr` gates; this worktree could not run gates owned by the parallel workstreams.
