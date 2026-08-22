# Robotics model card — Spec Delta

## ADDED Requirements

### Requirement: R-10 — Model provenance and artifact pairing
The system SHALL require every deployed model artifact and model card to have a counterpart and SHALL validate configured required provenance fields.

#### Scenario: Complete paired model card
- **WHEN** a model artifact has one matching card containing every required non-empty field, permitted precision/runtime, a 40-hex trained commit, dataset license, numeric evaluation value and named split, and known failure modes
- **THEN** `ModelCardGate` SHALL pass the model evidence.

#### Scenario: Unreviewable model evidence
- **WHEN** an artifact lacks a card, a card lacks an artifact, the dataset license is missing, or front matter is malformed
- **THEN** `ModelCardGate` SHALL fail or block as applicable and SHALL not infer missing provenance.
