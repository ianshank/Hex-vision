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

This workstream owns hooks and documents the integration contract but does not modify the concurrently owned Makefile or CI workflow. The existing `install` target already executes `scripts/install_hooks.sh`, so the new L1/L2 hooks become active through the existing installation flow.

The release-orchestration remediation must add the all-active-packs domain-gate command to the Makefile and CI. Once its CLI surface is merged, wire it using the following exact shape (substitute only the confirmed command name if the orchestration implementation publishes a different documented surface):

```make
# Makefile: make the dynamic pack execution an explicit governed target.
.PHONY: pack-gates
pack-gates: ## Execute every configured active pack's registered domain gates
	$(RUN) python -m $(PKG).cli gates --all-active-packs --json

# Keep the prerequisite order byte-for-byte aligned with contract.pre_pr_order.
pre-pr: install lint types cov secrets specs audit remotes projections traceability conformance pack-gates
```

```yaml
# .github/workflows/ci.yml: add after the conformance job (or make conformance
# depend on it if that is the agreed order), retaining Makefile authority.
  pack-gates:
    needs: conformance
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@e3f3cf96a6157d90bd3d29b2f7aa51de3ca0d90d # v5.4.0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with: { python-version: "3.11" }
      - run: make install
      - run: make pack-gates
```

The parent must also add `"pack-gates"` to `contract.pre_pr_order` in the same relative position as the Make prerequisite and confirm that the conformance metadata accepts the expanded order. This is intentionally not a documentation-only promise: CI must invoke the Make target, not duplicate the raw CLI command.

## Container use

The image uses a digest-pinned Python base, lockfile-driven `uv sync`, a non-root `hexvision` user, and release-downloaded gitleaks 8.28.0 / osv-scanner 2.2.4 binaries whose downloaded and installed bytes are verified with SHA-256 at build time. Build and run it with:

```sh
docker build --tag hexvision-governance:local .
docker run --rm hexvision-governance:local pack list --json
```

The build context intentionally excludes Git metadata and credentials. Therefore a container invocation is appropriate for CLI, conformance, and lockfile checks, while the repository-history secret scan remains a checkout/CI responsibility.
