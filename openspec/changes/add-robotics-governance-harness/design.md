# Design — add-robotics-governance-harness

Defaults below are proposals unless a decision-log line says otherwise.

## D1 — Layered configuration with provenance
**Proposal (default):** Resolve packaged, repository, pyproject, environment, and explicit-override layers in declared order, retaining the winning source and shadowed values per key.
**Status:** decided by committed baseline `10b37ddb6ae1`; no new owner decision is claimed.
**Rationale:** Operators must be able to explain a threshold or policy without reading code.
**Rejected:** Scattered module constants — they cannot provide provenance or reviewable overlay changes.

## D2 — Frozen keys protect non-negotiable bars
**Proposal (default):** Refuse environment and CLI writes to frozen prefixes, including `coverage`, `robotics.safety_envelope`, and `contract`.
**Status:** decided by committed baseline `10b37ddb6ae1`; no new owner decision is claimed.
**Rationale:** A quality or safety bar that can be lowered from a shell has no reviewable change record.
**Rejected:** Accept-and-warn overrides — an operator could believe a lower bar was applied.

## D3 — Entry-point pack discovery
**Proposal (default):** Discover packs through the `hexvision.packs` entry-point group and retain an in-process registration seam for tests.
**Status:** proposal pending implementation; no DEC entry is required for this architecture already specified by the contract.
**Rationale:** New stacks should install as packages without editing core import lists.
**Rejected:** Static pack imports — they couple core release cadence to every stack.

## D4 — Exactly one remote normalizer
**Proposal (default):** Provide one `normalize_remote_url` implementation and have hooks and CI call it through the remotes interface.
**Status:** proposal pending implementation.
**Rationale:** Different parsers create inconsistent allowlist decisions for equivalent Git remote spellings.
**Rejected:** Bash parsing in hooks — it duplicates security-critical behavior and violates INV-3.

## D5 — Generated planning projections
**Proposal (default):** Treat `planning/roadmap_data.py` as the single source; render roadmap Markdown and backlog CSV deterministically and byte-check them in CI.
**Status:** proposal pending implementation.
**Rationale:** Hand-maintained planning views inevitably drift from scope and requirement mappings.
**Rejected:** Editing roadmap and backlog independently — it creates competing sources of truth.

## D6 — BLOCKED is distinct from FAILED
**Proposal (default):** Use `FAILED` when a gate examined evidence and found a problem, and `BLOCKED` when it could not inspect required evidence or tooling.
**Status:** decided by committed baseline `10b37ddb6ae1`; no new owner decision is claimed.
**Rationale:** Audit records must distinguish a detected defect from a missing control.
**Rejected:** A single nonzero outcome — it hides whether the control ran.

## D7 — Per-file coverage floors
**Proposal (default):** Include untested source files and enforce configured line and branch floors per file as well as project-wide coverage.
**Status:** proposal pending CORE implementation.
**Rationale:** An aggregate percentage lets a well-tested module conceal an untested gate.
**Rejected:** Project-average-only coverage — it has a known omission vector.

## D8 — Non-commanding robotics safety boundary
**Proposal (default):** Inspect mission configuration and evidence only; never invoke vehicle-control, actuator, flight, or hardware-command operations.
**Status:** decided as project scope under DEC-004; it is not an airworthiness approval.
**Rationale:** Repository governance can require accountable review without representing itself as a flight-control or certification system.
**Rejected:** Automated bound enforcement on a vehicle — this is outside the harness authority and would require separate safety engineering.
