# AGENTS workstream handoff

## Built
- L1 PreToolUse and L2 pre-push guards that delegate their destination verdict only to `python -m hexvision.cli remotes --json`. They bind Git's exact supplied URL into temporary Git configuration for the normalizer rather than parsing it in Bash. Their documented runner chain is project venv, then `uv run`, then BLOCK (exit 2).
- Segment-aware L1 analysis across `;`, `&&`, `||`, pipes, and newlines. Malformed payloads and unresolvable push-shaped segments BLOCK with a reason.
- A worktree-safe, idempotent hook installer that resolves the actual hook directory with `git rev-parse --path-format=absolute --git-path hooks`, preserving unrelated hooks and correctly honoring linked worktrees plus absolute or relative `core.hooksPath`.
- Strict-plus-structural OpenSpec validation for `openspec/changes/*` that warns on every run when its optional strict validator is absent.
- L3 Python CI with SHA-pinned actions, pinned Ubuntu 24.04 runners, disabled checkout credential persistence, full history before the secret scan, Makefile-only installation and gate calls, an executable `needs` chain in configured pre-PR order, read-only default permission, concurrency cancellation, and Jetson conformance. The authoritative scanner invocations carry fixed reviewed Gitleaks and OSV-Scanner versions.
- Four agents, the governance skill, and a robotics gate-authoring skill.
- Scanner configuration and 51 isolated governance tests, including no-gitleaks and no-osv-scanner fail-closed tests, hostile valid/malformed/raw L1 inputs, every required segment boundary, URL-bound venv and `uv` fallback probes, and linked/custom-hook-path fixtures.

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
6. CORE's root `tests/conftest.py` owns the runtime zero-skip listener. Its marker parser must apply the same enforced `<DEC-id> <reason>` format asserted by `tests/governance/test_governance_meta.py`; this worktree cannot modify or execute that CORE-owned listener before integration.

## Deliberate limits and shortfalls
- No source coverage percentage is reported: CORE and JETSON source tests are not present in this isolated worktree, so a project coverage claim would be misleading. Governance tests passed 51/51.
- The supplied toolkit did not contain the requested `settings-TEMPLATE.json`; `.claude/settings.json` was designed from the workstream requirements and records its governing-decision status inline.
- L1 command-shape matching is intentionally a first-pass filter. L3 CI remains the authoritative destination control, and every script header states its boundary and measurement stamp.
- The hook tests use an executable fake normalizer to prove that the URL is injected into the normalizer input and that both venv and `uv` routes deny a rejected URL. They do not execute CORE's real normalizer until its parallel workstream is merged.
