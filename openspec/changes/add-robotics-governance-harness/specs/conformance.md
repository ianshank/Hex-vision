# Conformance — Spec Delta

## ADDED Requirements

### Requirement: R-8 — Gate Harness Contract conformance
The system SHALL verify all Contract v1.1 target, order, missing-tool, loud-degradation, normalizer, invariant, domain-gate, threshold-flag, and rationale clauses for each pack.

#### Scenario: Valid Jetson pack
- **WHEN** the Jetson pack declares all configured contract targets, the configured `pre-pr` order, required gate clauses, and allowed missing-tool behavior
- **THEN** conformance SHALL pass.

#### Scenario: Contract violation
- **WHEN** a pack omits a target, changes `pre-pr` order, has two normalizer declarations, omits a clause, or passes a forbidden threshold flag
- **THEN** conformance SHALL fail with the violated clause and SHALL not silently repair the pack.

### Requirement: R-9 — Zero skipped tests
The system SHALL convert skipped and xfailed tests into failures unless a valid, resolvable governance-skip authorization is supported by the configured decision log.

#### Scenario: Unapproved skip
- **WHEN** collection or execution observes `skip`, `skipif`, `xfail`, or `pytest.skip()` without a valid authorization
- **THEN** the test run and `ZeroSkipAuditGate` SHALL fail.

#### Scenario: Unresolvable authorization
- **WHEN** a governance-skip annotation names an id absent from the decision log
- **THEN** it SHALL be treated as no authorization and SHALL fail.

### Requirement: R-18 — Per-file coverage integrity
The system SHALL include untested source files and enforce configured per-file line and branch coverage floors.

#### Scenario: One file below the floor
- **WHEN** a coverage report contains one source file below a configured line or branch floor
- **THEN** `CoverageFloorGate` SHALL fail and report that file and its measured values.

#### Scenario: Untested source file
- **WHEN** coverage runs with a real Python source file that no test imports
- **THEN** the report SHALL include that file and the configured per-file floor SHALL apply.

#### Scenario: Coverage report unavailable
- **WHEN** the configured coverage report is absent or unparseable
- **THEN** `CoverageFloorGate` SHALL return `BLOCKED`, never a pass.
