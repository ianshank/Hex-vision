# Quality loops and hook policy

**Audience:** contributors, release engineers, and CI maintainers
**Classification:** operational governance

Hex-vision uses three feedback loops. The loops are intentionally overlapping: a local bypass is never a release bypass.

| Loop | Mechanism | Scope | Bypass consequence |
| --- | --- | --- | --- |
| L1 — edit/commit feedback | `scripts/pre_commit_check.sh`, installed as the native `pre-commit` hook; `.pre-commit-config.yaml` offers the same optional framework integration | Ruff check, Ruff format check, and `gitleaks protect --staged` using the verified scanner binary | `git commit --no-verify` skips only this fast feedback. The pushed release chain and CI still run their controls. |
| L2 — push feedback | `scripts/pre_push_scan.sh`, installed as the native `pre-push` hook | Validates the exact Git-supplied destination through the shared normalizer, then runs `make pre-pr` | `git push --no-verify`, an uninstalled hook, or a server-side action bypasses L2. L3 is the authority. |
| L3 — merge authority | `.github/workflows/ci.yml` invoking Make targets | Ordered, isolated CI jobs; scanner installer and scanner identity verification | Repository branch protection must require this workflow. A passing local command is not merge authority. |

The native installer supports linked worktrees through `git rev-parse --git-path hooks`, preserves an unrelated existing hook once, and regenerates its own reviewed hook. The pre-push hook is deliberately expensive because it is the last local opportunity to exercise the complete release chain; L1 remains short enough for normal commits.

## Current enforcement and required parent wiring

The `install` target executes `scripts/install_hooks.sh`, so the L1/L2 hooks become active through the existing installation flow.

## Governed release order

The configured order in `contract.pre_pr_order` is the single authority. The `make pre-pr` prerequisite list and the CI job graph are both checked against it by `test_makefile_and_ci_follow_the_configured_release_order`, so a target added in one place and not the others fails the suite rather than drifting silently. The order is:

```
install lint types cov secrets specs audit remotes projections agent-validation traceability conformance domain-gates
```

Two of these are release orchestration rather than per-pack targets, and neither appears in `contract.targets`, which remains the fifteen stack-pack target names:

- `agent-validation` validates every governed agent and skill definition deterministically, checking frontmatter schemas, description bounds, and that referenced file paths, Make targets, CLI commands, and `@agent:`/`@skill:` references resolve against the real checkout. Adding an agent or skill therefore requires it to be valid, not merely present.
- `domain-gates` executes every registered domain gate for each pack named in the frozen `orchestration.active_packs` allowlist. Before this existed, the five Jetson domain gates were reachable only from tests, so no local or CI path ran them against the repository.

## A known limitation of make as the invocation authority

Every CI job shells through `make`, and GNU make reports its own exit status for any failed recipe. The harness distinguishes `FAILED` (a gate looked and found a problem) from `BLOCKED` (a gate could not look), and that distinction does not survive the wrapper. `tests/aqa/test_exit_code_authority.py` pins this as a known property rather than leaving it as folklore: the CLI is the verdict authority, and `make` is a convenience wrapper whose exit code answers only whether the chain succeeded. Consume the CLI JSON when a caller needs the specific verdict.

## Container use

The image uses a digest-pinned Python base, lockfile-driven `uv sync`, a non-root `hexvision` user, and release-downloaded gitleaks 8.28.0 / osv-scanner 2.2.4 binaries whose downloaded and installed bytes are verified with SHA-256 at build time. Build and run it with:

```sh
docker build --tag hexvision-governance:local .
docker run --rm hexvision-governance:local pack list --json
```

The build context intentionally excludes Git metadata and credentials. Therefore a container invocation is appropriate for CLI, conformance, and lockfile checks, while the repository-history secret scan remains a checkout/CI responsibility.
