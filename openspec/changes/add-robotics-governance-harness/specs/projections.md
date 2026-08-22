# Projections — Spec Delta

## ADDED Requirements

### Requirement: R-7 — Deterministic generated planning projections
The system SHALL render `docs/ROADMAP.md` and `planning/backlog.csv` solely from `planning.roadmap_data` and fail CI on byte drift.

#### Scenario: Stable source data
- **WHEN** the same valid roadmap data is rendered twice
- **THEN** both outputs SHALL have identical bytes, fixed column order, `
` line endings, and a generated-file header naming `planning/roadmap_data.py`.

#### Scenario: Drift or malformed data module
- **WHEN** an output differs from its deterministic render or the configured data module is missing or malformed
- **THEN** projection checking SHALL fail or block, respectively, and SHALL report the drift or data error.
