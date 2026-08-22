# Configuration — Spec Delta

## ADDED Requirements

### Requirement: R-1 — Layered configuration provenance
The system SHALL resolve operational policy through `hexvision.config.load_config` in declared layer order and retain provenance for every resolved key.

#### Scenario: Later allowed layer wins with provenance
- **WHEN** packaged configuration provides a latency budget and a repository overlay provides a replacement budget
- **THEN** `config.explain` SHALL return the repository value and identify the repository layer and source path.

#### Scenario: Malformed configured layer
- **WHEN** an explicitly selected configuration file is unreadable or invalid TOML
- **THEN** configuration loading SHALL fail closed with a configuration error, never silently use packaged defaults.

### Requirement: R-2 — Frozen operational controls
The system SHALL reject environment and CLI override attempts for configured frozen prefixes.

#### Scenario: Frozen safety override
- **WHEN** an environment variable targets `robotics.safety_envelope.max_altitude_m`
- **THEN** configuration loading SHALL raise a frozen-key override error and SHALL not return a resolved configuration.

#### Scenario: Authorized repository safety change
- **WHEN** a repository overlay changes a frozen safety-envelope value
- **THEN** configuration loading SHALL resolve that value with repository provenance because the change is reviewable in the repository.
