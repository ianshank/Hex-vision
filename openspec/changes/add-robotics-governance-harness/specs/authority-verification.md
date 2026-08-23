# Shared authority verification — Spec Delta

## ADDED Requirements

### Requirement: R-20 — One shared decision-log authority verifier
The system SHALL resolve every decision-log-authorized exception through one shared verifier that returns a typed verified-authority value, matching subjects by exact equality against the configured subject column and treating a record as live only when its status cell equals the configured active value and no other record names it in a supersedes cell. A gate SHALL NOT independently parse or pattern-match the decision log to determine authority, and no code outside the verifier's module SHALL construct the verified-authority type.

#### Scenario: Nonexistent decision subject
- **WHEN** no record's subject cell exactly equals the queried subject
- **THEN** `verify_authority` SHALL return a typed denial rather than a verified authority, and the calling gate SHALL surface the absence as BLOCKED or FAILED, never as an authorized skip.

#### Scenario: Unrelated subject text collision
- **WHEN** a record's free-text decision cell contains the queried subject as a substring, or a record's subject cell is a superstring of the queried subject
- **THEN** `verify_authority` SHALL deny authorization, because matching is equality on the subject column and never substring or prose matching.

#### Scenario: Withdrawn or superseded decision
- **WHEN** a later record names an earlier record's id in its supersedes cell
- **THEN** `verify_authority` SHALL treat the earlier record as non-authoritative regardless of the earlier record's own status cell, and a ledger whose withdrawal graph is inconsistent — a self reference, an unknown id, a cycle, a duplicated record id, or a supersedes cell naming more than one id — SHALL fail closed by denying every query.

#### Scenario: Single construction authority
- **WHEN** the source tree declares a second verified-authority class, or constructs the verified-authority type outside its defining module by direct call, aliased import, attribute call, or `object.__new__`
- **THEN** the conformance gate SHALL report a Blocker finding.
