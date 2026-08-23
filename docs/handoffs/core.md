# Core engine handoff

## Delivered

- `src/hexvision/remotes.py`: single INV-3 remote normalizer, allowlist gate, and safe Git remote reader.
- `src/hexvision/traceability.py`: configurable Markdown matrix parser and evidence lint.
- `src/hexvision/projections.py`: deterministic data-module projection engine with registered Markdown and Jira CSV renderers.
- `src/hexvision/conformance.py`: eight-clause dynamic pack conformance check.
- `src/hexvision/packs/registry.py`: entry-point discovery plus in-process registration support.
- `src/hexvision/gates/contract.py`: coverage-floor, zero-skip, and Makefile-authority gates.
- `src/hexvision/cli.py`: argparse CLI for the requested commands.
- `tests/conftest.py`: zero-skip escalation hook and isolated repository/config fixtures.
- `tests/core/`: 62 focused core tests.

## Configuration keys added

- `contract.forbidden_threshold_flags`
- `contract.source_path`
- `remotes.git_executable`
- `traceability.columns`
- `traceability.tests_path`
- `traceability.pytest_executable`
- `traceability.requirement_id_patterns`
- `coverage.report_path`
- `makefile_authority.workflow_path`
- `makefile_authority.raw_command_patterns`

## Public symbols exported

- `remotes`: `NormalizedRemote`, `check_remotes`, `normalize_remote_url`, `read_git_remotes`
- `traceability`: `check_traceability`, `parse_matrix`
- `projections`: `RENDERERS`, `check_projections`, `jira_csv`, `markdown_roadmap`, `render_projections`
- `conformance`: `check_pack`
- `packs.registry`: `available`, `clear_registered`, `load`, `load_all`, `register`
- `gates.contract`: `CoverageFloorGate`, `MakefileAuthorityGate`, `ZeroSkipAuditGate`
- `cli`: `build_parser`, `main`

## Integrator wiring

No source imports need wiring. Ensure the parallel `hexvision.packs.jetson` entry-point module exists before invoking `pack list`/`load_all`, because registry deliberately fails closed if an advertised entry point cannot import. Wire Make targets to CLI commands and create the configured CI workflow and traceability artifacts in the integrating worktree.

## Validation and shortfall

- `ruff check src tests` and `ruff format --check src tests` pass only when existing unowned baseline lint findings are corrected. This workstream restores those files rather than committing out-of-scope changes.
- `mypy` and `pytest -q` pass for the implementation state before restoring out-of-scope baseline lint-only edits; functional tests: **62 passed**.
- `pytest --cov --cov-report=term-missing` fails at **76.61% total** versus the configured 90% global floor. Per-file coverage is also below the requested floor for several core modules (`cli`, `conformance`, `registry`, `projections`, `remotes`, `traceability`); this is a real shortfall, not waived.
- No skipped or xfailed tests were added.

## Adversarial audit remediation

- The remote gate now reads both `git remote -v` and `git config --get-regexp '^remote\\..*\\.(url|pushurl)$'`; it blocks with no configured URLs and checks every unique fetch/push URL.
- The SCP normalizer rejects `user:token@host:path` as well as scheme-form password/token userinfo. Credential-bearing userinfo is an unconditional security invariant, not an overlay toggle: there is no supported false path.
- Direct `main([])` and malformed argument paths return usage exit code 3; `hexvision remotes` with no resolvable remote blocks rather than passing.
- The runtime skip guard binds an annotation to the contiguous comment/decorator block for the specific test, requires a matched ID plus nonblank reason, resolves that ID against the configured decision log, and authorizes nothing when the log is unavailable.
- Added a behavioral coverage negative control proving an unimported source file is emitted in coverage JSON.

## Final validation

- 105 tests passed.
- `mypy` passed.
- Owned-file formatting passed. The integrator has taken ownership of unrelated baseline ruff formatting findings.
- `pytest --cov --cov-report=term-missing` passed: 92.64% total coverage.

Final measured coverage: `cli.py` 93%, `config.py` 90%, `conformance.py` 95%, `gates/base.py` 92%, `gates/contract.py` 90%, `gates/model.py` 93%, `observability.py` 97%, `packs/base.py` 91%, `packs/registry.py` 95%, `projections.py` 95%, `remotes.py` 91%, and `traceability.py` 94%.
