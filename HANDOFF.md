# AGENTS workstream handoff

## Built
- L1 PreToolUse and L2 pre-push guards that delegate their destination verdict only to `python -m hexvision.cli remotes --json`. Their documented runner chain is project venv, then `uv run`, then BLOCK (exit 2); neither reimplements remote URL parsing.
- A worktree-safe, idempotent hook installer that preserves unrelated hooks and installs a shim referencing `scripts/pre_push_scan.sh`.
- Strict-plus-structural OpenSpec validation for `openspec/changes/*` that warns on every run when its optional strict validator is absent.
- L3 Python CI with SHA-pinned actions, full history before the secret scan, Makefile-only gate calls, read-only default permission, concurrency cancellation, and Jetson conformance.
- Four agents, the governance skill, and a robotics gate-authoring skill.
- Scanner configuration and 40 isolated governance tests, including no-gitleaks and no-osv-scanner fail-closed tests.

## Config keys added
None. This workstream consumes `contract.targets` and `contract.pre_pr_order` from the packaged defaults rather than restating either list.

## Public symbols exported
None. The workstream adds shell entry points and Claude configuration, not Python API.

## Integration required
1. Merge CORE's `src/hexvision/cli.py` with the documented `remotes --json` command. Until it is present, both L1 and L2 intentionally BLOCK push-shaped commands.
2. Merge GOVERNANCE's `docs/decision-log.md` and `charter/CHARTER.md`. The freshness test automatically uses those live files when present; the skill is pinned to charter v1.0 and the seeded 2026-08-22 decision IDs.
3. Merge JETSON's pack before CI conformance can pass in a full integration run.
4. Run `hexvision projections --write` after merging GOVERNANCE's source data, then commit the generated roadmap/backlog output as its brief requires.
5. Validate the selected Hugging Face MCP package name/version against the project-approved MCP distribution before enabling it in a production client; the supplied toolkit had no settings template or MCP schema example.

## Deliberate limits and shortfalls
- No source coverage percentage is reported: CORE and JETSON source tests are not present in this isolated worktree, so a project coverage claim would be misleading. Governance tests passed 40/40.
- The supplied toolkit did not contain the requested `settings-TEMPLATE.json`; `.claude/settings.json` was designed from the workstream requirements and records its governing-decision status inline.
- L1 command-shape matching is intentionally a first-pass filter. L3 CI remains the authoritative destination control, and every script header states its boundary and measurement stamp.
