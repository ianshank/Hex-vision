# R-17 publication control handoff

## Commit

`ac9c535 feat: gate public publication`

## Delivered

- Added `hexvision.gates.publication.PublicationGate`, a release-time `publication` gate for R-17.
- The gate calls `hexvision.remotes.check_remotes` and `normalize_remote_url`; it adds no URL parser.
- It permits public publication only when the normalized destination passes the shared remote allowlist and a real four-column `G-PUB` decision-log row exists.
- Missing authority is a `BLOCKED` result (exit 2); rejected destinations are `FAILED` results (exit 1), preserving the normalizer reason for credential-bearing URLs.
- Added `hexvision publication [destination]`; omitted destination resolves `publication.default_destination`.
- Added a release-time `make publication` target without changing `contract.pre_pr_order` or `pre-pr`.
- Updated R-17 traceability to Green with four collecting pytest nodes and source `Traceability: R-17` markers.

## Configuration

- `publication.default_destination`
- `publication.authorization_id`
- `publication.decision_log_path`

`publication.authorization_id` is validated against the existing `traceability.decision_id_patterns`; no publication-specific decision-ID regex was added.

## Verification

- `make traceability`: passed.
- `make publication`: exited 2, as intended, with: `required publication authorization gate 'G-PUB' has no decision-log entry in docs/decision-log.md`.
- `make conformance`: passed.
- `make pre-pr`: passed; 324 tests and 93.67% coverage.
- Ruff check, Ruff format check, and mypy: passed.

## Deliberate non-change

No real `G-PUB` decision-log entry was added. Public publication remains blocked until an authorized release decision is recorded.
