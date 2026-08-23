# Release orchestration — Spec Delta

## ADDED Requirements

### Requirement: R-19 — Active pack domain-gate release orchestration
The system SHALL execute every domain gate registered by each dynamically
discovered pack named in the reviewed `orchestration.active_packs` allowlist
through the common gate runner before release. It SHALL retain the four-state
verdict model when aggregating results: blocked evidence remains `BLOCKED`,
declared unavailability remains `SKIPPED_DECLARED`, and neither is a success.
Installed packs absent from the allowlist SHALL be ignored; an allowlisted pack
that cannot load or evaluate SHALL block the release path.

#### Scenario: Registered gate failure blocks release orchestration
- **WHEN** an active pack registers several domain gates and one evaluates
  evidence as failed
- **THEN** the orchestration command SHALL invoke every registered gate, retain
  the failed finding id and reason, and exit with code 1.

#### Scenario: Unavailable domain gate evidence
- **WHEN** an active pack's domain gate cannot evaluate its required evidence
- **THEN** the aggregate release verdict SHALL be `BLOCKED`, retain the blocked
  reason, and exit with code 2 rather than code 1.

#### Scenario: Active allowlist admits only reviewed packs
- **WHEN** an allowlisted discovered pack is invalid and a separate installed
  pack is absent from `orchestration.active_packs`
- **THEN** the invalid allowlisted pack SHALL block the release path and the
  unallowlisted pack SHALL not be loaded or trusted.

#### Scenario: Declared skip trusts only verified authority
- **WHEN** aggregation receives a `SKIPPED_DECLARED` result
- **THEN** the release verdict SHALL convert it to a pass only when every
  attached authority is verifier-minted and its subject exactly equals the
  producing gate's name, the subject separator, and the runner key it is
  attached under, and the result carries no blocking findings. A bare
  decision-id string in measurements, an authority minted for a different gate
  or runner, a subject with no runner segment, a gate name containing the
  separator, or a blocking finding riding on the declared result SHALL fail the
  release verdict while naming the offending gate and the exact problem.

#### Scenario: Configured release order
- **WHEN** the configured `contract.pre_pr_order` includes active-pack
  domain-gate orchestration
- **THEN** the Makefile `pre-pr` prerequisites and CI `needs` chain SHALL
  contain precisely that configured order.
