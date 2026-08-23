# Remotes — Spec Delta

## ADDED Requirements

### Requirement: R-3 — Shared remote normalization
The system SHALL normalize supported Git remote spellings through exactly one `normalize_remote_url` declaration shared by the guard, hook, and CI gate.

#### Scenario: Equivalent GitHub spellings
- **WHEN** the normalizer receives `git@github.com:Org/Repo.git`, `ssh://git@github.com:22/org/repo`, or `https://GitHub.com/Org/Repo/`
- **THEN** each result SHALL compare as `github.com/org/repo` while retaining the original spelling for diagnostics.

#### Scenario: Credential-bearing remote
- **WHEN** the normalizer receives a remote containing `user:token@`
- **THEN** it SHALL return a blocking result and SHALL not normalize the credential away.

### Requirement: R-4 — Fail-closed destination authorization
The system SHALL block remote validation when the allowlist is empty, unreadable, a remote is unparseable, Git cannot be invoked, or a normalized destination is not allowlisted.

#### Scenario: Empty allowlist
- **WHEN** remote validation runs with `remotes.allowlist` empty
- **THEN** it SHALL return `BLOCKED`, never `PASSED`.

#### Scenario: Unreadable remote inspection
- **WHEN** Git cannot be invoked to read the repository's configured remotes
- **THEN** validation SHALL return `BLOCKED` with the inspection failure reason.

#### Scenario: Invalid remote destination
- **WHEN** a discovered remote cannot be parsed as a supported credential-free Git destination
- **THEN** validation SHALL fail and retain the parser's blocking reason.

#### Scenario: Unallowlisted destination
- **WHEN** a discovered remote normalizes successfully but is absent from the configured allowlist
- **THEN** validation SHALL fail and identify the denied normalized destination.

#### Scenario: Allowlisted destination
- **WHEN** every discovered remote normalizes to a destination in a non-empty configured allowlist
- **THEN** validation SHALL pass and record the normalized destinations.
