# JETSON workstream handoff

## Delivered

- `hexvision.robotics` with five documented, structured-logging domain gates:
  `ModelCardGate` (`R-MC`), `LatencyBudgetGate` (`R-LAT`),
  `DeterminismGate` (`R-DET`), `SafetyEnvelopeGate` (`R-SAFE`), and
  `HardwareInLoopGate` (`R-HIL`).
- `hexvision.packs.jetson.JetsonPack` and the entry-point object `pack`.
- `examples/jetson-perception`, containing a passing TensorRT model card,
  artifact, eval-run record, mission config, and an isolated `broken/` demo
  with documented independent defects.
- 117 passing tests under `tests/robotics`, including the intentional
  per-bound widening direction check and the identical-seed determinism check.

## Added configuration policy

`src/hexvision/defaults/hex-vision.toml` now includes:

- `robotics.model_card.artifact_field`, `robotics.model_card.artifact_globs`,
  and `artifact_path` in `robotics.model_card.required_fields`.
- `robotics.latency.percentile_field`.
- `robotics.determinism.record_globs`, `toml_suffix`, `schema_version_field`,
  `schema_version`, `model_name_field`, `runs_field`, and `metric_field`.
- `robotics.safety_envelope.decision_id_field`, `decision_log_path`,
  `decision_id_pattern`, `baseline_command`, `git_timeout_seconds`,
  `permissive_directions`, `failsafe_strength`, and
  `numeric_limits.{rtl_battery_percent,max_tilt_deg,geofence_radius_m,max_altitude_m}`.
- `robotics.hardware_in_loop.runners`, `decision_log_path`,
  `decision_id_pattern`, and `timeout_seconds`.
- `packs.jetson.package_manager`, `runner`, `targets`, `tools`, and
  `degraded_rationale`.

`robotics.artifact_roots` is pre-existing and is now consumed directly when
finding configured artifact formats.

## Eval-run record schema

Each JSON or TOML file matched by `robotics.determinism.record_globs` is a
versioned object/table:

```json
{
  "schema_version": 1,
  "model_name": "detector",
  "runs": [
    {
      "metric_value": 0.9100,
      "python_seed": 42,
      "numpy_seed": 42,
      "framework_seed": 42
    }
  ]
}
```

All schema field names and the accepted TOML suffix come from configuration.
There must be at least `required_runs`; every configured seed field must be
present and identical in all runs; metric spread is compared to the configured
tolerance.

## Integrator wiring

- The existing `hexvision.packs` entry point already names
  `hexvision.packs.jetson:pack`; the CORE registry only needs to discover that
  standard entry point. No direct pack import was added.
- Retain the default-config additions in the merge; each gate requires them
  rather than carrying fallback operational values.
- Projects using safety widening must keep the configured decision log and put
  a valid `safety_decision_id` in a widened mission. The default baseline
  command is `git show HEAD:{path}`; unavailable history is reported as a new
  mission in measurements.
- Replace the default HIL runner command names with real runner executables,
  or record an authorising `DEC-<number>` entry containing the absent optional
  gate name in the configured decision log. Missing hardware remains a visible
  `skipped-declared` result.

## Validation

- `mypy`: passed.
- `pytest --cov --cov-report=term-missing`: 117 passed, total 90.10% combined
  coverage. New module line/branch coverage: Jetson pack 32/33, 3/4;
  determinism 107/111, 46/48; hardware 75/76, 22/24; latency 66/70, 16/18;
  model card 164/179, 59/68; safety 121/126, 44/46.
- Targeted `ruff check` and `ruff format --check` for every JETSON-owned source
  file and test file passed.

## Shortfall / pre-existing worktree issue

The requested full-tree `ruff check src tests` and `ruff format --check src
tests` are not clean because CORE-owned, pre-existing files fail before any
JETSON change: `config.py`, `gates/base.py`, `errors.py`, and `gates/model.py`
for `ruff check`, and `config.py` plus `gates/base.py` for formatting. I did not
edit these files because the brief explicitly prohibits modifying CORE-owned
files. No JETSON-owned file has a Ruff finding or formatting drift.
