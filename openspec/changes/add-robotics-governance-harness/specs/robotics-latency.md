# Robotics latency — Spec Delta

## ADDED Requirements

### Requirement: R-11 — Runtime-specific latency budget evidence
The system SHALL compare a recorded latency measurement at the configured percentile with the configured budget for the model runtime and record per-model headroom and target device.

#### Scenario: Measurement within configured budget
- **WHEN** a card records the configured percentile and a runtime with a configured budget greater than or equal to measured latency
- **THEN** `LatencyBudgetGate` SHALL pass and record `budget - measured` headroom and the target device.

#### Scenario: Ungoverned latency claim
- **WHEN** the percentile is absent or mismatched, the runtime lacks a budget, or the measurement cannot be read as a number
- **THEN** `LatencyBudgetGate` SHALL block and SHALL not treat the model as budgeted.
