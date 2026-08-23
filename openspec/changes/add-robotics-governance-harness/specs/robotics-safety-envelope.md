# Robotics safety envelope — Spec Delta

## ADDED Requirements

### Requirement: R-13 — Declared mission safety bounds
The system SHALL inspect mission configuration for every configured required bound, allowed failsafe action, and stated internal-consistency rule without commanding a vehicle.

#### Scenario: Internally consistent mission
- **WHEN** a mission provides all required numeric bounds, `rtl_battery_percent` in 0–100, `max_tilt_deg` in 0–90, positive altitude and geofence, and an allowed failsafe action
- **THEN** `SafetyEnvelopeGate` SHALL pass the declared-envelope check.

#### Scenario: Missing or invalid bound
- **WHEN** a mission omits a required bound, contains an invalid numeric value, or names an unallowed failsafe action
- **THEN** `SafetyEnvelopeGate` SHALL fail and identify the path and bound; it SHALL not substitute a default.

### Requirement: R-14 — Governed permissive widening
The system SHALL require a resolving decision-log entry for every permissive safety-bound change when widening detection is configured.

#### Scenario: Authorized widening
- **WHEN** comparison with `git show HEAD:<mission-path>` shows a higher altitude, speed, tilt, or geofence, a lower RTL battery threshold, or a weaker failsafe action and the change cites a valid decision id
- **THEN** `SafetyEnvelopeGate` SHALL record the baseline comparison and accept the governed widening.

#### Scenario: Unauthorised or unavailable comparison
- **WHEN** a permissive widening lacks a valid decision id
- **THEN** `SafetyEnvelopeGate` SHALL block; when Git or the baseline blob is unavailable it SHALL record the file as new or unavailable and SHALL not silently claim a clean comparison.
