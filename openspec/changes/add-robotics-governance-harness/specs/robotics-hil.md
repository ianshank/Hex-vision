# Robotics hardware in loop — Spec Delta

## ADDED Requirements

### Requirement: R-15 — Declared hardware-in-the-loop availability
The system SHALL represent each configured optional HIL gate as a passed run, a declared absence authorized by the decision log, or a blocking undeclared absence.

#### Scenario: Runner is present
- **WHEN** the configured runner proves it can execute the named HIL gate
- **THEN** `HardwareInLoopGate` SHALL run it and return its result.

#### Scenario: Runner is absent
- **WHEN** the configured HIL runner is absent
- **THEN** `HardwareInLoopGate` SHALL return `skipped-declared` only with a resolving decision id; without one it SHALL carry a Blocker finding.

### Requirement: R-16 — Non-commanding safety boundary
The system SHALL limit robotics gates to repository evidence inspection and SHALL not issue vehicle, actuator, flight, or hardware-control commands.

#### Scenario: Mission review
- **WHEN** `SafetyEnvelopeGate` evaluates a mission file
- **THEN** it SHALL read configuration and baseline evidence only and SHALL return a gate result without invoking vehicle-control operations.

#### Scenario: Hardware execution request
- **WHEN** a requested check requires commanding hardware rather than invoking a configured evidence runner
- **THEN** the harness SHALL refuse the unsupported action and report that airworthiness and vehicle control require named human engineering authority.

### Requirement: R-17 — Gated publication destinations
The system SHALL block public GitHub or Hugging Face publication until the destination is allowlisted by the shared remotes control and `docs/decision-log.md` contains a `G-PUB` entry.

#### Scenario: Publication gate absent
- **WHEN** a publication task targets a public destination and no `G-PUB` line exists
- **THEN** the publication control SHALL block and name the absent gate.

#### Scenario: Publication gate and allowlist present
- **WHEN** the destination normalizes to an allowlisted entry and a real `G-PUB` line authorizes publication
- **THEN** the publication control SHALL permit the publication workflow to proceed.
