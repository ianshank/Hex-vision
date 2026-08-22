# Robotics determinism — Spec Delta

## ADDED Requirements

### Requirement: R-12 — Reproducible evaluation evidence
The system SHALL require configured run count, identical configured seed fields across runs, and metric spread within configured tolerance for each model evaluation record.

#### Scenario: Reproducible runs
- **WHEN** an evaluation record has at least the configured number of runs, identical required seeds, and metric spread at or below tolerance
- **THEN** `DeterminismGate` SHALL pass and record the observed spread.

#### Scenario: Missing or inconsistent runs
- **WHEN** the run record is missing or unreadable
- **THEN** `DeterminismGate` SHALL return `BLOCKED`; when recorded runs use different seeds or exceed tolerance it SHALL return `FAILED`.
