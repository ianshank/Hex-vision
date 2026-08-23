# Traceability — Spec Delta

## ADDED Requirements

### Requirement: R-5 — Complete linted requirement matrix
The system SHALL lint one traceability row for every specification requirement with the configured columns and a status from the configured enum.

#### Scenario: Missing or duplicate requirement row
- **WHEN** a required id is absent from the matrix or appears in more than one row
- **THEN** the traceability gate SHALL fail and identify the absent or duplicate id.

#### Scenario: Inherited or waived row authority
- **WHEN** a row has status `Inherited` or `Waived`
- **THEN** the gate SHALL require its configured inheritance detail or a decision-log reference respectively, and SHALL reject an unresolved reference.

### Requirement: R-6 — Green requires collecting evidence
The system SHALL require every `Green` traceability row to cite a pytest node id that `pytest --collect-only` actually collects.

#### Scenario: Collecting Green node
- **WHEN** a Green row cites a collecting test node id
- **THEN** the traceability gate SHALL accept the evidence cell.

#### Scenario: Noncollecting Green node
- **WHEN** a Green row cites a missing node id or pytest cannot run collection
- **THEN** the traceability gate SHALL fail or block, respectively, and SHALL not accept Green status.
