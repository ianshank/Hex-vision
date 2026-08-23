"""Tests for strict model-card provenance evidence."""

from __future__ import annotations

from typing import Any

import pytest

from hexvision.config import load_config
from hexvision.gates.model import GateStatus, Severity
from hexvision.robotics.model_card import ModelCardGate, parse_front_matter


# Traceability: R-10 [Complete paired model card, Unreviewable model evidence]
def test_model_card_passes_for_complete_card(passing_repo: Any) -> None:
    """A complete card and its artifact produce a green provenance record."""
    root = passing_repo()
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.PASSED
    assert not result.findings
    assert result.measurements == {"cards": 1, "artifacts": 1}


@pytest.mark.parametrize(
    ("field", "severity"),
    [
        ("model_name", Severity.MAJOR),
        ("version", Severity.MAJOR),
        ("task", Severity.MAJOR),
        ("input_shape", Severity.MAJOR),
        ("precision", Severity.MAJOR),
        ("target_runtime", Severity.MAJOR),
        ("target_device", Severity.MAJOR),
        ("dataset_id", Severity.MAJOR),
        ("dataset_license", Severity.BLOCKER),
        ("trained_commit", Severity.MAJOR),
        ("eval_metric", Severity.MAJOR),
        ("eval_value", Severity.MAJOR),
        ("eval_dataset_split", Severity.MAJOR),
        ("known_failure_modes", Severity.MAJOR),
        ("owner", Severity.MAJOR),
        ("artifact_path", Severity.MAJOR),
    ],
)
def test_model_card_required_fields_are_individually_enforced(
    passing_repo: Any, field: str, severity: Severity
) -> None:
    """Every policy-required provenance field is independently actionable."""
    root = passing_repo(card={field: ""})
    result = ModelCardGate().check(load_config(root=root, env={}))
    finding = next(item for item in result.findings if field.upper() in item.id)
    assert result.status is GateStatus.FAILED
    assert finding.id == f"MC-1-{field.upper()}"
    assert "absent or empty" in finding.message
    assert finding.severity is severity
    assert result.measurements == {"cards": 1, "artifacts": 1}


@pytest.mark.parametrize(
    ("card", "finding_id", "severity"),
    [
        ({"precision": "fp8"}, "PRECISION", Severity.MAJOR),
        ({"target_runtime": "bespoke"}, "RUNTIME", Severity.MAJOR),
        ({"trained_commit": "deadbeef"}, "COMMIT", Severity.MINOR),
        ({"trained_commit": "not-a-sha"}, "COMMIT", Severity.MAJOR),
        ({"eval_value": "nope"}, "EVAL-VALUE", Severity.MAJOR),
        ({"artifact_path": 12}, "ARTIFACT", Severity.MAJOR),
    ],
)
def test_model_card_field_rules(
    passing_repo: Any, card: dict[str, Any], finding_id: str, severity: Severity
) -> None:
    """Field-specific policies retain their distinct severity and remediation."""
    root = passing_repo(card=card)
    result = ModelCardGate().check(load_config(root=root, env={}))
    finding = next(item for item in result.findings if item.id == f"MC-1-{finding_id}")
    assert finding.severity is severity


def test_model_card_finds_artifact_without_card(passing_repo: Any) -> None:
    """An unreviewed artifact is a blocker rather than an ignored binary."""
    root = passing_repo()
    extra = root / "models" / "unreviewed.engine"
    extra.write_bytes(b"engine")
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert any(
        item.severity is Severity.BLOCKER and "no corresponding" in item.message
        for item in result.findings
    )


def test_model_card_finds_orphan_card_artifact(passing_repo: Any) -> None:
    """A card naming a missing artifact cannot claim a deployment review."""
    root = passing_repo(card={"artifact_path": "models/detector/missing.engine"})
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert any("not present" in item.message for item in result.findings)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("model_name: detector", r"must begin with a front-matter delimiter"),
        ("---\nmodel_name: detector", r"front matter has no closing delimiter"),
        ("---\nmodel name: detector\n---", r"invalid front-matter key 'model name'"),
        ("---\nname: &alias detector\n---", r"unsupported YAML construct"),
        ("---\nname: 'unterminated\n---", r"unclosed quoted scalar"),
        ("---\nname:\n---", r"empty list value for 'name'"),
    ],
)
def test_front_matter_rejects_ambiguous_or_malformed_yaml(text: str, message: str) -> None:
    """The stdlib parser refuses syntax it cannot interpret exactly."""
    with pytest.raises(ValueError, match=message):
        parse_front_matter(text)


def test_front_matter_accepts_scalars_and_lists() -> None:
    """The intentionally small syntax still supports ordinary reviewed metadata."""
    parsed = parse_front_matter("---\nname: detector\nshapes: [1, 3]\nmodes:\n  - fog\n---")
    assert parsed == {"name": "detector", "shapes": [1, 3], "modes": ["fog"]}


def test_model_card_blocks_invalid_document(passing_repo: Any) -> None:
    """Malformed evidence blocks instead of being treated as empty metadata."""
    root = passing_repo()
    (root / "models/detector/model-card.md").write_text("not front matter", encoding="utf-8")
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "MODEL-CARD-BLOCKED"
    assert "cannot parse model card" in result.findings[0].message
    assert not result.measurements


def test_model_card_checks_each_configured_artifact_root(passing_repo: Any) -> None:
    """Artifact roots, not only the models directory, participate in card pairing."""
    root = passing_repo()
    calibration = root / "calibration"
    calibration.mkdir()
    (calibration / "review-required.engine").write_bytes(b"engine")
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert any("calibration/review-required.engine" in item.message for item in result.findings)


@pytest.mark.parametrize(
    "overlay",
    [
        "[robotics.model_card]\nrequired_fields = []\n",
        "[robotics.model_card]\nruntime_field = ''\n",
    ],
)
def test_model_card_blocks_malformed_retargeting_policy(passing_repo: Any, overlay: str) -> None:
    """An external field mapping must be complete before card evidence is assessed."""
    root = passing_repo()
    (root / "hex-vision.toml").write_text(overlay, encoding="utf-8")
    result = ModelCardGate().check(load_config(root=root, env={}))
    assert result.status is GateStatus.BLOCKED
    assert result.findings[0].id == "MODEL-CARD-BLOCKED"
    assert "non-empty" in result.findings[0].message
    assert not result.measurements
