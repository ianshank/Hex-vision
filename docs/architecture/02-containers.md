# C4 Level 2 — Containers

**Audience:** maintainers, pack authors, release engineers, and security reviewers
**Classification:** technical architecture

Hex-vision is one Python application package with a CLI front door. The repository supplies its policy and generated evidence; Make and CI are orchestration containers rather than a second implementation of gate logic. The `Dockerfile` packages the same application and verified scanner binaries for isolated command execution.

```mermaid
flowchart TB
    cli["CLI\nhexvision.cli\nargparse, JSON/text results"]
    config["Configuration layer\nhexvision.config\nlayered immutable Config + provenance"]
    gate_engine["Gate engine\nhexvision.gates.base + model\nrun_gate(s), results, exit codes"]
    packs["Pack registry\nhexvision.packs.registry\nPython entry-point discovery"]
    verifiers["Invariant verifier registry\nhexvision.invariant_verifiers\nnegative mechanism probes"]
    projections["Projection + traceability services\nhexvision.projections / traceability"]
    policy["Repository policy and evidence\nTOML, OpenSpec, decision log, tests, planning data"]
    artifacts["Evidence artefacts\nroadmap Markdown, backlog CSV, JSON result output"]
    make["Makefile and hook scripts\nordered local / CI invocation"]
    ci["GitHub Actions workflow\nMake target invocations"]
    image["Container image\nPython, uv environment, gitleaks, osv-scanner"]

    make --> cli
    ci --> make
    image --> cli
    cli --> config
    cli --> gate_engine
    cli --> packs
    cli --> projections
    gate_engine --> config
    packs --> config
    packs --> gate_engine
    verifiers --> config
    verifiers --> gate_engine
    gate_engine --> policy
    config --> policy
    projections --> policy
    projections --> artifacts
    cli --> artifacts
```

The configuration layer is shared by all runtime components. It merges packaged defaults, repository and `pyproject.toml` policy, environment variables, and explicit overrides while rejecting overrides to frozen prefixes. `scanner_identity` is a supporting module used by Make to resolve a scanner path and verify the bytes before invocation.
