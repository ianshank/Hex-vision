"""Generate deterministic planning projections from one configured data module.

Projection files are derivative evidence. Rendering them from a single source
lets review focus on scope changes while byte comparisons reveal any hand edit or
stale generated artifact.
"""

from __future__ import annotations

import csv
import difflib
import importlib
import io
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from hexvision.config import Config
from hexvision.gates.model import Finding, GateResult, Severity

__all__ = ["RENDERERS", "check_projections", "jira_csv", "markdown_roadmap", "render_projections"]

_CLAUSE: Final = "PROJECTIONS"
Renderer = Callable[[Mapping[str, Any], str], bytes]
RENDERERS: dict[str, Renderer] = {}


def _register(name: str) -> Callable[[Renderer], Renderer]:
    """Register a renderer centrally so the checker never branches by output type."""

    def decorator(renderer: Renderer) -> Renderer:
        RENDERERS[name] = renderer
        return renderer

    return decorator


def _header(module: str, prefix: str) -> str:
    """Mark output provenance so reviewers know edits belong in the data module."""
    return f"{prefix} Generated from {module}; do not edit directly.\n"


@_register("markdown_roadmap")
def markdown_roadmap(data: Mapping[str, Any], module: str) -> bytes:
    """Render milestones and tasks into stable Markdown for human planning review."""
    lines = [_header(module, "<!--").rstrip() + " -->", f"# Roadmap: {data['change_id']}", ""]
    for milestone in sorted(data["milestones"], key=lambda item: str(item["id"])):
        lines.extend(
            [
                f"## {milestone['id']} — {milestone['name']}",
                "",
                str(milestone["exit_criteria"]),
                "",
                "| ID | Title | Status | Estimate hours | Requirements | Depends on |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for task in sorted(milestone["tasks"], key=lambda item: str(item["id"])):
            lines.append(
                (
                    "| {id} | {title} | {status} | {estimate_hours} | "
                    "{requirements} | {depends_on} |"
                ).format(
                    id=task["id"],
                    title=task["title"],
                    status=task["status"],
                    estimate_hours=task["estimate_hours"],
                    requirements=", ".join(sorted(task["requirement_ids"])),
                    depends_on=", ".join(sorted(task["depends_on"])),
                )
            )
        lines.append("")
    lines.pop()
    return ("\n".join(lines) + "\n").encode()


@_register("jira_csv")
def jira_csv(data: Mapping[str, Any], module: str) -> bytes:
    """Render tasks into a fixed-column CSV compatible with issue import tools."""
    output = io.StringIO(newline="")
    output.write(_header(module, "#"))
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["id", "milestone", "title", "status", "estimate_hours", "requirement_ids", "depends_on"]
    )
    for milestone in sorted(data["milestones"], key=lambda item: str(item["id"])):
        for task in sorted(milestone["tasks"], key=lambda item: str(item["id"])):
            writer.writerow(
                [
                    task["id"],
                    milestone["id"],
                    task["title"],
                    task["status"],
                    task["estimate_hours"],
                    " ".join(sorted(task["requirement_ids"])),
                    " ".join(sorted(task["depends_on"])),
                ]
            )
    return output.getvalue().encode()


def _load_data(config: Config) -> tuple[Mapping[str, Any], str]:
    """Import and validate the configured single source before rendering anything."""
    module_name = str(config.require("projections.data_module", clause=_CLAUSE))
    repository_root = str(config.root)
    if repository_root not in sys.path:
        # A console-script entry point starts from its virtualenv's bin directory,
        # not the checkout. Repository-owned projection modules must remain
        # configurable without requiring callers to hand-maintain PYTHONPATH.
        sys.path.insert(0, repository_root)
    module = importlib.import_module(module_name)
    factory = module.data
    data = factory()
    required = {"change_id", "generated_from", "milestones", "requirements"}
    if not isinstance(data, Mapping) or not required <= set(data):
        raise ValueError("projection data() must return the required mapping shape")
    if not isinstance(data["milestones"], list) or not isinstance(data["requirements"], list):
        raise TypeError("projection milestones and requirements must be lists")
    return data, module_name


def render_projections(config: Config) -> dict[Path, bytes]:
    """Render every configured output in deterministic output-name order."""
    data, module_name = _load_data(config)
    outputs = config.require("projections.outputs", clause=_CLAUSE)
    rendered: dict[Path, bytes] = {}
    for output in sorted(outputs, key=lambda item: str(item["name"])):
        renderer_name = str(output["renderer"])
        renderer = RENDERERS.get(renderer_name)
        if renderer is None:
            raise ValueError(f"projection renderer {renderer_name!r} is not registered")
        rendered[config.root / str(output["path"])] = renderer(data, module_name)
    return rendered


def check_projections(config: Config, *, write: bool = False) -> GateResult:
    """Write generated projections or compare them byte-for-byte for drift."""
    try:
        rendered = render_projections(config)
    except (ImportError, AttributeError, OSError, TypeError, ValueError, KeyError) as exc:
        return GateResult.blocked(
            "projections",
            summary="projection source cannot be rendered",
            reason=str(exc),
            clause=_CLAUSE,
        )
    if write:
        try:
            for path, content in rendered.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        except OSError as exc:
            return GateResult.blocked(
                "projections",
                summary="projection output cannot be written",
                reason=str(exc),
                clause=_CLAUSE,
            )
        return GateResult.passed(
            "projections",
            summary="projections regenerated",
            clause=_CLAUSE,
            measurements={"outputs": len(rendered)},
        )
    findings: list[Finding] = []
    for path, expected in rendered.items():
        try:
            actual = path.read_bytes()
        except OSError:
            actual = b""
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    actual.decode(errors="replace").splitlines(keepends=True),
                    expected.decode(errors="replace").splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=f"generated:{path}",
                )
            )
            findings.append(
                Finding(
                    f"PROJECTION-{len(findings) + 1:03d}",
                    Severity.MAJOR,
                    f"generated projection drifted: {path.relative_to(config.root)}",
                    str(path.relative_to(config.root)),
                    _CLAUSE,
                    "Run `hexvision projections --write` and commit the result.",
                    {"diff": diff},
                )
            )
    if findings:
        return GateResult.failed(
            "projections",
            summary="generated projections have drift",
            findings=findings,
            clause=_CLAUSE,
        )
    return GateResult.passed(
        "projections",
        summary="generated projections are current",
        clause=_CLAUSE,
        measurements={"outputs": len(rendered)},
    )
