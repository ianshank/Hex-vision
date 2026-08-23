# Hex-vision

Hex-vision is a modular governance and gate harness for drone, robotics, and edge-AI repositories. It implements Gate Harness Contract v1.1 and adds repository-evidence gates for model provenance, latency, deterministic evaluation, mission safety envelopes, and declared hardware-in-the-loop availability. It is deliberately a repository control: it does not command vehicles, actuators, flight systems, or hardware.

A stack integration is a pack. The included `jetson` pack is the reference for Python-based Jetson perception work, but the contract is retargetable to other drone, robotics, and edge-AI stacks.

## Quick start

Requirements: Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
make help
make pre-pr
```

`make pre-pr` is the local integration target. It installs the development environment and then runs the configured CI gates in the contract order. Use `make help` rather than reconstructing gate commands by hand.

## Gate outcomes are evidence, not decoration

Every gate returns one of four terminal statuses:

| Status | Meaning | Process exit code |
| --- | --- | ---: |
| `passed` | The gate ran and its policy was satisfied. | 0 (`OK`) |
| `failed` | The gate looked at valid evidence and found a policy violation. | 1 (`FAILED`) |
| `blocked` | The gate could not inspect the required tool, input, policy, or evidence. | 2 (`BLOCKED`) |
| `skipped-declared` | A configured HIL runner is absent and that absence is reported explicitly. It remains non-passing unless the producing gate has the required decision-log authority. | 1 (`FAILED`) |

A malformed command line returns 3 (`USAGE`). These meanings are intentionally separate. `FAILED` says “the gate looked and found a problem”; `BLOCKED` says “the gate could not look”. Both stop the workflow, but an audit must be able to distinguish a detected defect from a control that was unavailable. A plain `SKIPPED` status does not exist.

Each result has a stable gate name, status, clause, summary, findings, measurements, and exit code. Findings carry an identifier, bounded severity, location, clause, disposition, and structured context so that automated consumers do not have to interpret prose.

## Contract targets

The contract fixes the shared target names; packs provide their stack-specific command mapping. In this repository the Jetson pack delegates them to the Makefile, which is the authority for invocation.

| Target | What it enforces here |
| --- | --- |
| `install` | Creates or refreshes the development environment and installs the Git hooks. |
| `format` | Applies Ruff formatting. |
| `lint` | Runs Ruff checks, formatting verification, and Vulture dead-code analysis. |
| `types` | Runs strict MyPy checking. |
| `test` | Runs the test suite; the project rejects skipped and xfailed tests. |
| `cov` | Produces coverage evidence and applies configured project and per-file coverage policy. |
| `secrets` | Scans both the working tree and Git history; scanner identity is verified before use. |
| `specs` | Validates the OpenSpec package, using the structural validator when the external validator is unavailable. |
| `audit` | Scans the lockfile for dependency vulnerabilities. |
| `remotes` | Checks repository destinations against the shared normalizer and allowlist. |
| `projections` | Detects drift in generated roadmap and backlog projections. |
| `traceability` | Lints the requirement matrix against OpenSpec requirements and collecting tests. |
| `guard-probe` | Shows the PreToolUse guard verdict for a supplied command. |
| `pre-pr` | Runs the configured CI chain in the required order. |
| `clean` | Removes generated local caches and reports. |

Two additional repository targets complete the control plane:

- `conformance` checks a named pack against Gate Harness Contract v1.1, including behavioural proof of every declared invariant.
- `publication` is a release-time control, not part of `pre-pr`. It requires both an allowlisted, normalised destination and the configured publication decision-log entry.

Run `make conformance PACK=jetson` for the reference pack. The CLI also exposes structured output; for example, `hexvision conformance --pack jetson --json` emits one result object.

## The five invariants

The contract’s invariant statements are policy, and conformance verifies their declared mechanisms with negative probes:

1. **INV-1 — Secret scanning:** the working tree and Git history are scanned, and missing security tooling fails closed.
2. **INV-2 — No skipped tests:** skips and xfails are failures, not a route to a green run.
3. **INV-3 — One remote normalizer:** the guard, hook, and CI use exactly one URL normalizer.
4. **INV-4 — Governed hooks:** the hook installer is itself invoked by CI and recreates the required pre-push hook.
5. **INV-5 — Makefile authority:** configured gates run through Makefile targets rather than raw duplicated CI commands.

## Extension model

Hex-vision is modular, but its extension mechanisms are intentionally precise:

- **Packs** are discovered from the `hexvision.packs` Python entry-point group. Installing a package that advertises a pack makes it available without editing a core import list.
- **Domain gates** are supplied dynamically by each pack’s `domain_gates(config)` method. The generic runner executes the returned `Gate` objects and gives each the same result and fail-closed semantics.
- **Invariant verifiers** are discovered from the `hexvision.invariant_verifiers` entry-point group. A verifier proves that a declared invariant mechanism detects a synthetic violation.
- **Projection renderers** are looked up from the in-process renderer registry in `hexvision.projections`; configured outputs name the renderer. They are dynamically selected by configuration, not registered as Python entry points in this release.

This separation is deliberate: adding a stack means installing a pack package rather than changing core, while a pack can bring its own domain gates and, where needed, an invariant verifier. Read [the architecture guide](docs/ARCHITECTURE.md) for interfaces, configuration provenance, and a worked pack walkthrough.

### Write a new pack

Start with the reference material already in the tree:

- [`examples/jetson-perception/`](examples/jetson-perception/) contains clean and intentionally broken evidence for the existing robotics gates.
- [`src/hexvision/packs/jetson.py`](src/hexvision/packs/jetson.py) shows a pack that maps every contract target from configuration and contributes five domain gates.
- [`src/hexvision/packs/base.py`](src/hexvision/packs/base.py) defines `Pack`, `PackMeta`, and `TargetSpec`.

A new pack implements metadata, maps every configured contract target to an argument-vector `TargetSpec`, supplies any domain `Gate` objects, and exposes the pack through the `hexvision.packs` entry-point group. It should read operational values from `Config`, not embed paths, budgets, thresholds, or tool choices. Test it with `hexvision conformance --pack <name> --json`.

## Specification-driven workflow

The OpenSpec deltas under [`openspec/`](openspec/) are the source of truth for requirements and scenarios. The requirements under `openspec/changes/add-robotics-governance-harness/specs/` define the released R-1 through R-18 set.

[`traceability/REQUIREMENT-TRACEABILITY.md`](traceability/REQUIREMENT-TRACEABILITY.md) is a checked projection, not an alternative specification. The traceability gate derives the requirement set from OpenSpec, requires a Green row to cite a test node that actually collects, and requires the corresponding executable test source to contain its traceability marker. Generated roadmap and backlog views are likewise checked against `planning/roadmap_data.py`.

## Decision authority

[`docs/decision-log.md`](docs/decision-log.md) is an append-only, machine-read authority record. A proposal in a design document, a conversation, or a comment is not an authorisation. The configured decision-log grammar determines which rows count; examples in code fences and HTML comments do not.

This boundary matters particularly for safety-envelope widening, declared HIL absence, waivers, and publication. The harness records repository evidence and governance state; named humans retain release, safety, and airworthiness authority.

## Publication control

R-17 keeps public GitHub and Hugging Face publication separate from ordinary pull-request validation. `make publication` evaluates the destination through the shared remote policy and then requires the configured `G-PUB` authorisation in `docs/decision-log.md`. The current decision log intentionally has no `G-PUB` entry, so the publication gate remains blocked. Do not add an entry merely to publish documentation; it is a human release-authority decision.

## Licence

Hex-vision is licensed under the [Apache License, Version 2.0](LICENSE). Copyright 2026 Ian Shank.
