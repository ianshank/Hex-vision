---
name: robotics-gate-authoring
description: How to author auditable, fail-closed Hex-vision robotics domain gates without commanding hardware.
---

# Robotics gate authoring

A robotics domain gate subclasses `hexvision.gates.base.Gate`, declares a non-empty `clause`, and returns `GateResult`. It governs repository evidence; it never commands a vehicle, device, simulator, or hardware runner.

## Required implementation pattern
1. Read all paths, globs, thresholds, allowlists, and budgets from `hexvision.config.load_config`; do not embed operational values in Python.
2. Return **FAILED** when the gate inspected valid evidence and found a policy violation.
3. Return **BLOCKED** when evidence, configuration, baseline, parser, or required tooling is unavailable or unreadable. Do not turn an inability to inspect into a pass.
4. Record `measurements` for every verdict, including passing values, units, runtime/device identifiers, and calculated headroom where applicable.
5. Write a scenario-derived failing test before implementation and test both the clean and unavailable-input paths.

## Worked trap: permissive direction is per bound
Mission envelopes are not uniformly “larger is less safe.” Raising `max_altitude_m`, `max_horizontal_speed_ms`, `max_tilt_deg`, or `geofence_radius_m` widens the envelope. Lowering `rtl_battery_percent` widens it. A weaker failsafe may also widen it. Compare each configured bound against the committed baseline and require its decision-log evidence for each permissive movement. Do not substitute a global greater-than rule.

## Worked trap: identical seeds across runs
A deterministic evaluation record needs enough runs, a bounded metric spread, and every configured seed field in every run. The seed values must be identical across runs. Different seeds can make repeated measurements look plausible while testing a different question; report that as BLOCKED or FAILED according to whether the record could be evaluated.

## Review checklist
- The gate does not issue hardware commands or call a runner as proof that hardware is safe.
- The clause maps to a real OpenSpec requirement.
- Tests assert the specific BLOCK reason where the unavailable-input path is expected.
- `hexvision conformance --pack jetson` and `make pre-pr` remain green.
