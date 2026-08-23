# C4 Level 3 — Components

**Audience:** core maintainers, pack authors, and reviewers
**Classification:** technical architecture

## Gate engine and result model

```mermaid
flowchart LR
    cli["CLI dispatcher\nhexvision.cli"] --> runner["Gate runner\nrun_gate / run_gates"]
    runner --> gate_abc["Gate ABC\nname, clause, evaluate(config)"]
    runner --> result["GateResult / Finding\nPASSED, FAILED, BLOCKED, SKIPPED_DECLARED"]
    runner --> errors["Error taxonomy\nHexVisionError subclasses"]
    errors --> runner
    contract["Contract gates\ncoverage, zero-skip, Make authority"] --> gate_abc
    publication["Publication gate\nremote policy + G-PUB"] --> gate_abc
    robotics["Robotics gates\nmodel card, latency, determinism,\nsafety envelope, HIL"] --> gate_abc
    remote["Remote policy\nnormalize and inspect Git URLs"] --> publication
    decision["Decision-log parser\nvalidated authority records"] --> publication
```

`run_gate` turns expected `HexVisionError` and unexpected exceptions into a non-passing `GateResult`; it does not permit an unavailable tool or input to become a pass. Gates provide expected policy failures directly. The CLI serializes the resulting stable result model and maps its terminal status to the documented process exit code.

## Pack and verifier registries

```mermaid
flowchart TB
    metadata["importlib.metadata\nPython entry points"] --> pack_registry["Pack registry\navailable, load, load_all"]
    metadata --> verifier_registry["Invariant verifier registry\navailable, load_all"]
    in_process_pack["In-process registration\ntest / embedding seam"] --> pack_registry
    pack_registry --> pack["Pack implementation\nmetadata, targets, domain_gates(config)"]
    pack --> targets["TargetSpec tuples\nconfigured contract mapping"]
    pack --> domain_gates["Domain Gate instances"]
    domain_gates --> runner["Shared gate runner"]
    verifier_registry --> verifier["InvariantVerifier\nsupports + negative probe"]
    verifier --> conformance["Conformance check\nhexvision.conformance"]
    targets --> conformance
    domain_gates --> conformance
```

Packs are entry-point-discovered instances of the `Pack` abstract base class. `load_all()` refuses partial discovery if an advertised pack is broken. Domain gates are returned by the loaded pack and run through the common runner. Invariant verifiers are a separate entry-point registry: conformance selects exactly one supporting verifier and requires its negative probe to produce the configured evidence.

Projection renderers are deliberately different: `hexvision.projections` has an in-process decorator registry for the built-in Markdown roadmap and Jira-style CSV renderers. It is dynamic lookup driven by configuration, not Python entry-point discovery.
