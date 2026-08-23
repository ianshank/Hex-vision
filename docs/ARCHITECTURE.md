# Hex-vision architecture

**Audience:** pack authors, governance maintainers, and integrators

**Classification:** technical architecture

Hex-vision separates stack-specific integration from common governance semantics. The generic core owns configuration resolution, result modelling, error-to-verdict conversion, contract conformance, remote policy, traceability, and projections. A pack owns the target mapping and its domain gates.

## Extension and registry model

### Pack registry

The pack registry reads installed Python entry points in the `hexvision.packs` group using `importlib.metadata`. Each advertised entry point must load to a `Pack` instance. Registry loading fails explicitly when an entry point is missing, broken, or returns the wrong type; an unavailable pack must not silently remove its gates from an otherwise green run.

The registry also has an explicit in-process `register(pack)` seam for embedding and isolated tests. It applies duplicate-name protection and is not a replacement for installing a production pack. `available()` returns installed and in-process names in stable order; `load_all()` refuses partial discovery if any advertised pack cannot load.

The included entry point is `jetson = "hexvision.packs.jetson:pack"`. A third-party package follows the same pattern in its own project metadata, so the Hex-vision core does not need an import-list edit or release to learn a new stack.

### Domain gates

A pack supplies its gates from `Pack.domain_gates(config)`. They are normal `Gate` instances, not a separate entry-point registry in this release. That gives an installed pack control of its domain surface while the core owns execution semantics through `run_gate` and `run_gates`.

Every gate declares a name and the clause it enforces, accepts a resolved `Config`, and returns a `GateResult`. Escaped `HexVisionError` and unexpected exceptions are converted to structured non-passing results by the runner. Gate implementations should return anticipated policy failures themselves; exceptions are for unavailable or unanticipated conditions that must fail closed.

### Invariant verifier registry

Conformance does not trust a claimed invariant mapping merely because it appears in configuration. It loads verifiers from the `hexvision.invariant_verifiers` entry-point group. An `InvariantVerifier` provides:

```python
@property
def name(self) -> str: ...

def supports(self, invariant, mechanism, target, gate) -> bool: ...

def verify(self, config, mechanism, target, gate) -> ProbeEvidence: ...
```

The verifier selects one declared enforcement mechanism and runs a negative probe. Its `ProbeEvidence` preserves the probe name, whether it was detected, the observed outcome, and a structured reason. Conformance requires exactly one supporting verifier and checks the configured reason pattern against the evidence. A missing, ambiguous, crashing, or non-detecting verifier produces a conformance finding rather than an assumed pass.

### Projection renderer registry

Projection renderers use a separate, in-process registry. The `@register_renderer(name)` decorator adds a renderer to `hexvision.projections.RENDERERS`; configuration selects one by the output’s `renderer` value. The current built-ins are the Markdown roadmap and Jira-style CSV renderers. This is dynamic lookup driven by configuration, but it is not Python entry-point discovery. Keeping this distinction explicit avoids documenting a plugin surface that the code does not implement.

## Result model

`GateStatus` has four terminal values:

- `PASSED`: the check completed and satisfied policy;
- `FAILED`: valid evidence was inspected and a real finding was detected;
- `BLOCKED`: a required input, tool, policy, or unexpected execution path prevented inspection;
- `SKIPPED_DECLARED`: a configured HIL runner is absent and is surfaced as a declared capability condition.

`PASSED` maps to exit code 0, `FAILED` to 1, and `BLOCKED` to 2. `SKIPPED_DECLARED` also maps to 1 by default. CLI usage errors map to 3. The model deliberately has no plain skipped state: unavailability is evidence, not an absence of evidence.

A `GateResult` contains `gate`, `status`, `clause`, `summary`, `findings`, and `measurements`. It serialises to a stable JSON object that also includes `exit_code`. Passing results cannot carry a Major or Blocker finding; construction rejects that internally inconsistent shape.

A `Finding` is an immutable record with a stable ID, `Severity`, message, optional repository location, clause, required disposition, and machine-readable context. Severity is bounded to Blocker, Major, Minor, and Info. Major and Blocker findings block completion, and result constructors sort findings worst-first with stable ID tie-breaking.

## Configuration and policy provenance

`load_config()` merges five layers in order:

1. packaged `hexvision/defaults/hex-vision.toml`;
2. repository `hex-vision.toml` when present;
3. `[tool.hexvision]` in `pyproject.toml` when present;
4. `HEXVISION_` environment variables, with `__` separating nested keys;
5. explicit caller overrides.

The resulting immutable `Config` records provenance for every key: the winning layer, source, value, and shadowed lower-precedence values. `hexvision config explain <key>` exposes that record. Tables merge recursively; lists replace rather than concatenate, so an overlay can narrow an allowlist.

Protected prefixes are read from `meta.frozen.prefixes`. In this repository they include coverage, safety-envelope, contract, decision-log, and scanner policy. Frozen values may come from the packaged, repository, or pyproject layers, but environment and explicit overrides are rejected with `FrozenKeyOverrideError`. This protects reviewable quality and safety bars from a shell-level change that leaves no governed diff.

All operational paths are resolved against `Config.root` unless configured as absolute. Packs and gates therefore read thresholds, globs, budgets, tools, paths, allowlists, and field names from configuration rather than Python literals.

## Worked walkthrough: add an Aurora stack pack

This example uses a hypothetical `hexvision-aurora` package. “Aurora” is only a name; the steps describe the contract rather than a built-in integration.

1. **Declare package metadata.** Define an entry point in the external package:

   ```toml
   [project.entry-points."hexvision.packs"]
   aurora = "hexvision_aurora.pack:pack"
   ```

   Installing the package makes `hexvision pack list` discover `aurora` through metadata.

2. **Implement `Pack`.** Give it `PackMeta` with a stable `name`, stack description, summary, and reference documents. Implement `targets(config)` with every name in `config.require("contract.targets")`. Each `TargetSpec.command` is an argument tuple, not a shell string. Set the underlying tool and any permitted degraded-mode rationale explicitly.

3. **Use configuration, not literals.** Place Aurora commands, globs, thresholds, and tooling in the adopter’s `hex-vision.toml` or its reviewed `[tool.hexvision]` policy. Read them through `Config.require`, `Config.section`, and `Config.resolve_path`. Do not write a repository path, coverage floor, destination, or safety bound into the pack implementation.

4. **Add domain evidence gates.** Implement `Gate` subclasses for Aurora-specific repository evidence. Give each a non-empty name and clause, return `FAILED` after inspecting invalid evidence, and return `BLOCKED` when the evidence or policy cannot be inspected. Return them from `domain_gates(config)`.

5. **Prove any new invariant mechanism.** If Aurora maps an invariant to a different mechanism from the existing pack, publish an `InvariantVerifier` through `hexvision.invariant_verifiers`. Its negative probe must show that the declared mechanism catches a synthetic violation and produce the reason evidence required by configuration.

6. **Validate the integration.** Install the external package, inspect it with `hexvision pack show aurora --json`, and run `hexvision conformance --pack aurora --json`. Conformance checks target completeness, Makefile delegation, fail-closed policy, the shared remote-normalizer count, gate clauses, forbidden threshold flags, and invariant evidence.

The reference implementation is `src/hexvision/packs/jetson.py`, and `examples/jetson-perception/` supplies clean and broken evidence for its five domain gates. The core should not need a change for the hypothetical pack to be discoverable.

## Authority boundaries

The architecture enforces repository governance rather than operational control. Robotics gates inspect model cards, evaluation records, mission configuration, Git baselines, and configured runners; the safety review does not command a vehicle or certify airworthiness. Human authority is represented only by real rows in the configured decision log. Publication separately composes the shared remote policy with the R-17 `G-PUB` authority check.
