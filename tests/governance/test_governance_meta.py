"""Meta-tests that keep Hex-vision's operational controls from silently drifting."""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from tests.governance.conftest import run_process

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = REPO_ROOT / "src" / "hexvision" / "defaults" / "hex-vision.toml"
MAKEFILE = REPO_ROOT / "Makefile"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SKIP_MARKER = re.compile(
    r"^\s*#\s*@governance-skip:\s*(?:DEC-\d+|RB-\d+[a-z]?|G-[A-Z]+|S\d+\.\d+)\s+\S.*\s*$"
)


def contract() -> dict[str, Any]:
    """Load authoritative target names and order rather than duplicating them in tests."""
    with DEFAULTS.open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
    value = loaded["contract"]
    assert isinstance(value, dict)
    return value


def ci_jobs() -> dict[str, str]:
    """Read job bodies without duplicating their names or declared dependency order."""
    workflow = CI.read_text(encoding="utf-8")
    jobs = workflow.split("\njobs:\n", maxsplit=1)
    assert len(jobs) == 2, "workflow has no jobs mapping"
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"^  (?P<name>[a-z][a-z0-9-]*):\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
            jobs[1],
            re.M | re.S,
        )
    }


def test_makefile_contains_all_contract_targets_from_defaults() -> None:
    """Contract targets come from the defaults file, the only list this test trusts."""
    text = MAKEFILE.read_text(encoding="utf-8")
    targets = contract()["targets"]
    assert isinstance(targets, list)
    missing = [target for target in targets if not re.search(rf"^{re.escape(target)}:", text, re.M)]
    assert missing == [], f"Makefile omits contract targets configured in defaults: {missing}"


def test_pre_pr_chains_configured_targets_in_exact_configured_order() -> None:
    """A local pre-PR pass predicts CI only when configured ordering remains exact."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(r"^pre-pr:\s*(.*?)\s*##", text, re.M)
    assert match, "Makefile lost the pre-pr target or its contract documentation"
    prerequisites = match.group(1).split()
    order = contract()["pre_pr_order"]
    assert isinstance(order, list)
    assert prerequisites == order, "pre-pr must chain contract.pre_pr_order exactly"


def test_ci_invokes_configured_gate_targets_via_make_without_raw_duplicates() -> None:
    """The workflow must call targets rather than reconstruct gate commands."""
    ci = CI.read_text(encoding="utf-8")
    order = contract()["pre_pr_order"]
    assert isinstance(order, list)
    for target in order:
        assert re.search(rf"run:\s*make\s+{re.escape(target)}(?:\s|$)", ci), (
            f"CI no longer invokes make {target}; local and CI gates would drift"
        )
    forbidden_raw = (
        r"pytest\s+--cov",
        r"ruff\s+check",
        r"\bmypy\b",
        r"gitleaks\s+(dir|git)",
        r"osv-scanner\s+scan",
    )
    for pattern in forbidden_raw:
        assert not re.search(pattern, ci), f"CI contains raw gated command matching {pattern!r}"


def test_ci_jobs_enforce_the_configured_pre_pr_dependency_graph() -> None:
    """`needs` makes configured order executable rather than an aspirational comment."""
    order = contract()["pre_pr_order"]
    assert isinstance(order, list)
    jobs = ci_jobs()
    missing = [target for target in order if target not in jobs]
    assert missing == [], f"CI lacks configured gate jobs: {missing}"
    for index, target in enumerate(order):
        body = jobs[target]
        assert "run: make install" in body, f"{target} bypasses the install target"
        if index == 0:
            assert not re.search(r"^\s+needs:", body, re.M), (
                "first configured gate has a predecessor"
            )
        else:
            predecessor = order[index - 1]
            assert re.search(rf"^\s+needs:\s*{re.escape(predecessor)}\s*$", body, re.M), (
                f"{target} must need its configured predecessor {predecessor}"
            )


def test_ci_gate_sequence_equals_the_configured_pre_pr_order() -> None:
    """Parsed CI jobs must have exactly the same ordered gate sequence as local pre-PR."""

    order = contract()["pre_pr_order"]
    assert isinstance(order, list)
    jobs = ci_jobs()
    ci_sequence = [
        name for name in jobs if re.search(rf"run:\s*make\s+{re.escape(name)}(?:\s|$)", jobs[name])
    ]
    assert ci_sequence == order, "CI gate sequence must equal contract.pre_pr_order"


def test_ci_fetches_full_history_for_secret_scan() -> None:
    """A history scanner on a shallow checkout is not a meaningful gate."""
    secrets = ci_jobs()["secrets"]
    assert "fetch-depth: 0" in secrets
    assert "make secrets" in secrets


def test_ci_actions_are_pinned_to_full_commit_shas() -> None:
    """Every mutable action reference is rejected before CI can drift under a tag."""
    uses = re.findall(r"^\s*-\s+uses:\s+[^@\s]+@([^\s#]+)", CI.read_text(encoding="utf-8"), re.M)
    assert uses, "CI contains no action references to verify"
    unpinned = [reference for reference in uses if re.fullmatch(r"[0-9a-f]{40}", reference) is None]
    assert unpinned == [], f"CI action references must be full 40-hex commit SHAs: {unpinned}"


def test_ci_never_interpolates_github_event_data_into_run_blocks() -> None:
    """Event-derived branch and title data belong in env, never executable shell text."""
    ci = CI.read_text(encoding="utf-8")
    run_blocks = re.findall(r"run:\s*\|\n((?:\s{10,}.*\n?)*)", ci)
    assert all("github.event." not in block for block in run_blocks)


def test_ci_has_least_privilege_concurrency_and_jetson_conformance() -> None:
    """L3 has read-only defaults, cancels stale work, and checks the actual first pack."""
    ci = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in ci
    assert "cancel-in-progress: true" in ci
    assert "make conformance PACK=jetson" in ci


def test_ci_pins_runner_disables_checkout_credentials_and_uses_scanner_config() -> None:
    """PR code never receives persisted credentials or scanner identity pins from Make literals."""
    ci = CI.read_text(encoding="utf-8")
    assert "ubuntu-latest" not in ci
    assert ci.count("runs-on: ubuntu-24.04") == len(ci_jobs())
    checkout_count = ci.count("uses: actions/checkout@")
    assert checkout_count == ci.count("persist-credentials: false")
    makefile = MAKEFILE.read_text(encoding="utf-8")
    defaults = DEFAULTS.read_text(encoding="utf-8")
    assert "[scanners.gitleaks]" in defaults
    assert "[scanners.osv-scanner]" in defaults
    assert "artifact_sha256" in defaults
    assert "GITLEAKS_VERSION" not in makefile
    assert "OSV_VERSION" not in makefile
    assert "scanner_identity" in makefile
    assert "checksum mismatch; refusing to install" in makefile
    assert "make secrets-install INSTALL_DIR=" in ci
    assert "make audit-install INSTALL_DIR=" in ci
    assert "INSTALL_METHOD=release" in ci
    assert "make secrets\n" in ci
    assert "make audit\n" in ci


def test_guard_scripts_delegate_to_single_cli_normalizer_with_block_fallback() -> None:
    """L1/L2 may not grow a Bash URL parser while the normalizer is unavailable."""
    for name in ("pre_push_scan.sh", "pretooluse_guard.sh"):
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "-m hexvision.cli remotes --json" in text
        assert "uv run --project" in text
        assert "no project Python or uv runner is available" in text
        assert "BLOCKED (INV-3)" in text
        assert "check-url" not in text
        assert "GIT_CONFIG_VALUE_" in text
        assert "normaliz" in text.lower()


def test_every_script_header_states_limit_and_commit_stamp() -> None:
    """First-pass controls stay honest about what a later layer must catch."""
    for script in (REPO_ROOT / "scripts").glob("*.sh"):
        header = "\n".join(script.read_text(encoding="utf-8").splitlines()[:8]).lower()
        assert "commit stamp:" in header, f"{script.name} lacks a measurement commit stamp"
        assert "does not" in header or "not catch" in header or "not caught" in header, (
            f"{script.name} does not state a limit"
        )


def test_settings_and_mcp_are_governed_and_do_not_store_secrets() -> None:
    """Tooling control changes remain reviewable and credentials remain environment-owned."""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    mcp = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert "Governed decision" in settings["_comment"]
    assert (
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        == "bash scripts/pretooluse_guard.sh"
    )
    assert any("git push" in rule for rule in settings["permissions"]["deny"])
    assert "Governed decision" in mcp["_comment"]
    assert set(mcp["mcpServers"]) == {"github", "huggingface"}
    serialized = json.dumps(mcp)
    assert "${GITHUB_PERSONAL_ACCESS_TOKEN}" in serialized
    assert "${HF_TOKEN}" in serialized


def test_hook_installer_builds_shim_that_invokes_the_governed_remote_target() -> None:
    """The installed L2 shim delegates to the governed target rather than parsing URLs."""
    text = (REPO_ROOT / "scripts" / "install_hooks.sh").read_text(encoding="utf-8")
    assert "git-path hooks" in text
    assert "make -C" in text
    assert "remotes" in text
    assert "preserved unrelated pre-push hook" in text


def test_governance_skip_markers_require_a_resolved_identifier_and_reason() -> None:
    """A bare decision ID cannot exempt a skipped test from the zero-skip guard."""
    assert SKIP_MARKER.fullmatch("# @governance-skip: DEC-004 hardware unavailable")
    assert SKIP_MARKER.fullmatch("# @governance-skip: RB-12a documented exception")
    assert SKIP_MARKER.fullmatch("# @governance-skip: DEC-004") is None


def test_requirement_markers_cited_by_tests_resolve_when_governance_docs_exist() -> None:
    """Explicit Requirement: markers are checked against charter and OpenSpec deltas."""
    cited: set[str] = set()
    for test in (REPO_ROOT / "tests").rglob("test_*.py"):
        cited.update(
            re.findall(r"Requirement:\s*(R-[A-Za-z0-9.-]+)", test.read_text(encoding="utf-8"))
        )
    sources = ""
    for source in (REPO_ROOT / "charter", REPO_ROOT / "openspec"):
        if source.exists():
            sources += "\n".join(path.read_text(encoding="utf-8") for path in source.rglob("*.md"))
    missing = sorted(identifier for identifier in cited if identifier not in sources)
    assert missing == [], f"test requirement markers absent from charter or spec deltas: {missing}"


def test_make_secrets_fails_closed_without_gitleaks() -> None:
    """No-gitleaks machine: the secrets target blocks rather than silently skipping."""
    make = shutil.which("make")
    uv = shutil.which("uv")
    assert make is not None
    assert uv is not None
    result = run_process(
        [make, "secrets"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "PM": str(Path(uv).resolve())},
    )
    assert result.returncode == 2
    assert "scanner identity BLOCKED: gitleaks version 8.28.0 is not found on PATH" in (
        result.stdout + result.stderr
    )


def test_make_audit_fails_closed_without_osv_scanner() -> None:
    """No-osv-scanner machine: the audit target blocks rather than silently skipping."""
    make = shutil.which("make")
    uv = shutil.which("uv")
    assert make is not None
    assert uv is not None
    result = run_process(
        [make, "audit"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "PM": str(Path(uv).resolve())},
    )
    assert result.returncode == 2
    assert "scanner identity BLOCKED: osv-scanner version 2.2.4 is not found on PATH" in (
        result.stdout + result.stderr
    )


@pytest.mark.parametrize(
    ("make_assignment", "environment"),
    [
        ("GITLEAKS=true", None),
        ("GITLEAKS=/bin/echo", None),
        ("GITLEAKS=", None),
        (None, {"GITLEAKS": "true"}),
        (None, {"GITLEAKS": "/bin/echo"}),
        (None, {"GITLEAKS": ""}),
    ],
)
def test_make_secrets_ignores_untrusted_scanner_overrides_and_blocks_a_planted_secret(
    make_assignment: str | None, environment: dict[str, str] | None
) -> None:
    """A scanner selector supplied at invocation cannot turn INV-1 into a no-op."""
    planted = REPO_ROOT / "planted-control-bypass-secret.txt"
    secret = f"ghp_{sha256(b'gitleaks-control-bypass').hexdigest()[:36]}"
    planted.write_text(f"credential = {secret}\n", encoding="utf-8")
    try:
        arguments = ["make", "secrets"]
        if make_assignment is not None:
            arguments.append(make_assignment)
        result = run_process(arguments, cwd=REPO_ROOT, env=environment)
    finally:
        planted.unlink(missing_ok=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "leaks found" in output


def test_make_secrets_rejects_a_version_spoofing_path_shadow(tmp_path: Path) -> None:
    """A fake scanner that reports the configured version still fails on its artifact digest."""
    fake = tmp_path / "gitleaks"
    fake.write_text(
        "#!/usr/bin/env bash\nif [ \"$1\" = version ]; then printf '8.28.0\\n'; fi\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = run_process(
        ["make", "secrets"],
        cwd=REPO_ROOT,
        env={"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 2
    assert (
        "scanner identity BLOCKED: gitleaks SHA-256 digest mismatch"
        in result.stdout + result.stderr
    )


def test_make_audit_rejects_a_version_spoofing_path_shadow(tmp_path: Path) -> None:
    """OSV receives the same artifact-digest protection as the secret scanner."""
    fake = tmp_path / "osv-scanner"
    fake.write_text(
        (
            "#!/usr/bin/env bash\n"
            "if [ \"$1\" = --version ]; then printf 'osv-scanner version: 2.2.4\\n'; fi\n"
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = run_process(
        ["make", "audit"],
        cwd=REPO_ROOT,
        env={"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 2
    assert (
        "scanner identity BLOCKED: osv-scanner SHA-256 digest mismatch"
        in result.stdout + result.stderr
    )


def test_make_secrets_passes_with_the_verified_installed_scanner() -> None:
    """The configured genuine gitleaks artifact remains usable after identity verification."""
    result = run_process(["make", "secrets"], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
