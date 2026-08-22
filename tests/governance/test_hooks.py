"""Behavior tests for L1/L2 guard scripts and the worktree-safe installer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.conftest import install_fake_normalizer, run_process


@pytest.mark.parametrize("command", ["git status", "echo ordinary work"])
def test_pretooluse_allows_non_push_commands(git_repo: Path, command: str) -> None:
    """Ordinary commands must not require a normalizer that they do not use."""
    payload = json.dumps({"tool_input": {"command": command}})
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text=payload,
        env={"CLAUDE_PROJECT_DIR": str(git_repo)},
    )
    assert result.returncode == 0


def test_pretooluse_blocks_push_when_normalizer_is_absent_with_reason(git_repo: Path) -> None:
    """Fail closed when no installed venv can reach the single normalizer."""
    payload = json.dumps({"tool_input": {"command": "git push origin main"}})
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text=payload,
        env={"CLAUDE_PROJECT_DIR": str(git_repo), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "shared normalizer did not allow the push-shaped command" in result.stderr


def test_pretooluse_blocks_normalizer_refusal_with_reason(git_repo: Path) -> None:
    """A normalizer refusal is surfaced as a BLOCK reason, not an opaque exit."""
    install_fake_normalizer(git_repo)
    payload = json.dumps({"tool_input": {"command": "git push origin main"}})
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text=payload,
        env={"CLAUDE_PROJECT_DIR": str(git_repo), "HV_NORMALIZER_EXIT": "1"},
    )
    assert result.returncode == 2
    assert "shared normalizer did not allow the push-shaped command (exit 1)" in result.stderr


def test_pretooluse_allows_only_normalizer_pass(git_repo: Path) -> None:
    """The sole allow path for a push-shaped command is a normalizer pass."""
    install_fake_normalizer(git_repo)
    payload = json.dumps({"tool_input": {"command": "git push origin main"}})
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text=payload,
        env={"CLAUDE_PROJECT_DIR": str(git_repo), "HV_NORMALIZER_EXIT": "0"},
    )
    assert result.returncode == 0


def test_pretooluse_blocks_unanalyzable_push_shaped_payload_with_reason(git_repo: Path) -> None:
    """Malformed JSON may not hide a push-shaped command from the first-pass guard."""
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text="not json but git push origin main",
        env={"CLAUDE_PROJECT_DIR": str(git_repo)},
    )
    assert result.returncode == 2
    assert "unanalyzable payload contains a push-shaped command" in result.stderr


def test_pretooluse_allows_unanalyzable_non_push_payload(git_repo: Path) -> None:
    """Malformed non-dangerous payloads retain the documented ordinary-work behavior."""
    result = run_process(
        ["/bin/bash", "scripts/pretooluse_guard.sh"],
        cwd=git_repo,
        input_text="not json but ordinary work",
        env={"CLAUDE_PROJECT_DIR": str(git_repo)},
    )
    assert result.returncode == 0


def test_pre_push_blocks_missing_invocation_arguments_with_reason(git_repo: Path) -> None:
    """A direct or malformed L2 invocation is visibly blocked."""
    result = run_process(["/bin/bash", "scripts/pre_push_scan.sh"], cwd=git_repo)
    assert result.returncode == 2
    assert "missing <remote-name> <remote-url>" in result.stderr


def test_pre_push_blocks_without_normalizer_with_reason(git_repo: Path) -> None:
    """L2 fails closed rather than implementing URL parsing in shell."""
    result = run_process(
        ["/bin/bash", "scripts/pre_push_scan.sh", "origin", "https://example.test/org/repo"],
        cwd=git_repo,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "shared normalizer did not allow this push" in result.stderr


def test_pre_push_blocks_normalizer_refusal_with_reason(git_repo: Path) -> None:
    """A denied destination keeps the L2 reason rather than only a non-zero exit."""
    install_fake_normalizer(git_repo)
    result = run_process(
        ["/bin/bash", "scripts/pre_push_scan.sh", "origin", "https://example.test/org/repo"],
        cwd=git_repo,
        env={"HV_NORMALIZER_EXIT": "1"},
    )
    assert result.returncode == 2
    assert "shared normalizer did not allow this push (exit 1)" in result.stderr


def test_pre_push_allows_normalizer_pass(git_repo: Path) -> None:
    """L2 allows only after the common Python normalizer accepts the repository."""
    install_fake_normalizer(git_repo)
    result = run_process(
        ["/bin/bash", "scripts/pre_push_scan.sh", "origin", "https://example.test/org/repo"],
        cwd=git_repo,
        env={"HV_NORMALIZER_EXIT": "0"},
    )
    assert result.returncode == 0
    assert "shared normalizer allowed" in result.stderr


def test_install_hooks_handles_git_worktree_dotgit_file(git_repo: Path) -> None:
    """A linked worktree has a .git file, so installation must use Git's git-path API."""
    (git_repo / "README.md").write_text("fixture\n", encoding="utf-8")
    for arguments in (["git", "add", "."], ["git", "commit", "-m", "fixture"]):
        result = run_process(arguments, cwd=git_repo)
        assert result.returncode == 0, result.stderr
    linked = git_repo.parent / "linked-worktree"
    result = run_process(
        ["git", "worktree", "add", "-b", "fixture-linked", str(linked)], cwd=git_repo
    )
    assert result.returncode == 0, result.stderr
    assert (linked / ".git").is_file()
    result = run_process(
        ["/bin/bash", "scripts/install_hooks.sh", "--repo", str(linked)], cwd=git_repo
    )
    assert result.returncode == 0, result.stderr
    hook_path = run_process(
        ["git", "-C", str(linked), "rev-parse", "--git-path", "hooks/pre-push"], cwd=git_repo
    )
    assert hook_path.returncode == 0
    installed = Path(hook_path.stdout.strip())
    assert installed.is_file()
    assert "scripts/pre_push_scan.sh" in installed.read_text(encoding="utf-8")


def test_install_hooks_preserves_unrelated_hook(git_repo: Path) -> None:
    """An unrelated local hook is copied aside with an explicit preservation message."""
    hook_dir = run_process(["git", "rev-parse", "--git-path", "hooks"], cwd=git_repo)
    assert hook_dir.returncode == 0
    existing = git_repo / hook_dir.stdout.strip() / "pre-push"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("#!/usr/bin/env bash\necho local hook\n", encoding="utf-8")
    result = run_process(["/bin/bash", "scripts/install_hooks.sh"], cwd=git_repo)
    assert result.returncode == 0
    assert "preserved unrelated pre-push hook" in result.stderr
    assert list(existing.parent.glob("pre-push.pre-hex-vision.*"))


def test_install_hooks_rejects_non_repository(tmp_path: Path) -> None:
    """Installer failure is explicit instead of reporting a non-installed hook as success."""
    result = run_process(
        [
            "/bin/bash",
            str(Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"),
            "--repo",
            str(tmp_path),
        ],
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "not a git worktree" in result.stderr
