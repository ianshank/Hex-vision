"""Single source for Hex-vision roadmap and backlog projections.

This module contains only typed planning data and light referential-integrity
validation. ``docs/ROADMAP.md`` and ``planning/backlog.csv`` are generated from
this source by ``hexvision projections --write`` and are byte-checked in CI; they
must not become independently maintained plans. Keeping the data independent of
``hexvision`` makes it inspectable before the application package is installed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Final, Literal, TypedDict, cast

TaskStatus = Literal["todo", "in-progress", "done", "blocked"]


class TaskData(TypedDict):
    """One deliverable task within a milestone projection."""

    id: str
    title: str
    requirement_ids: list[str]
    status: TaskStatus
    estimate_hours: int
    depends_on: list[str]


class MilestoneData(TypedDict):
    """A budgeted milestone rendered into roadmap and backlog projections."""

    id: str
    name: str
    exit_criteria: str
    budget_prs: int
    budget_hours: int
    tasks: list[TaskData]


class RequirementData(TypedDict):
    """A stable requirement statement mapped to its owning milestone."""

    id: str
    statement: str
    milestone: str


class RoadmapData(TypedDict):
    """The complete serialized schema consumed by the projection renderer."""

    change_id: str
    generated_from: str
    milestones: list[MilestoneData]
    requirements: list[RequirementData]


_DATA: Final[RoadmapData] = {
    "change_id": "add-robotics-governance-harness",
    "generated_from": "planning/roadmap_data.py",
    "milestones": [
        {
            "id": "M0",
            "name": "Reconnaissance and guardrails",
            "exit_criteria": (
                "Baseline and control-plane records are verified; roadmap data validates."
            ),
            "budget_prs": 3,
            "budget_hours": 20,
            "tasks": [
                {
                    "id": "0.1",
                    "title": "Write or verify failing configuration scenarios",
                    "requirement_ids": ["R-1", "R-2"],
                    "status": "in-progress",
                    "estimate_hours": 4,
                    "depends_on": [],
                },
                {
                    "id": "0.2",
                    "title": "Deliver layered configuration and frozen-key mechanism",
                    "requirement_ids": ["R-1", "R-2"],
                    "status": "done",
                    "estimate_hours": 8,
                    "depends_on": [],
                },
                {
                    "id": "0.3",
                    "title": "Deliver committed shared fail-closed foundations",
                    "requirement_ids": [],
                    "status": "done",
                    "estimate_hours": 4,
                    "depends_on": [],
                },
                {
                    "id": "0.4",
                    "title": "Record archive gap and re-baseline",
                    "requirement_ids": [],
                    "status": "done",
                    "estimate_hours": 2,
                    "depends_on": [],
                },
                {
                    "id": "0.5",
                    "title": "Update M0 traceability",
                    "requirement_ids": ["R-1", "R-2"],
                    "status": "todo",
                    "estimate_hours": 2,
                    "depends_on": ["0.1"],
                },
            ],
        },
        {
            "id": "M1",
            "name": "Contract control plane",
            "exit_criteria": "Contract and fail-closed gate tests pass through Makefile targets.",
            "budget_prs": 4,
            "budget_hours": 28,
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Write failing contract-control tests",
                    "requirement_ids": ["R-3", "R-4", "R-8", "R-9", "R-18"],
                    "status": "in-progress",
                    "estimate_hours": 8,
                    "depends_on": [],
                },
                {
                    "id": "1.2",
                    "title": "Implement core contract-control modules",
                    "requirement_ids": ["R-3", "R-4", "R-8", "R-9", "R-18"],
                    "status": "in-progress",
                    "estimate_hours": 16,
                    "depends_on": ["1.1"],
                },
                {
                    "id": "1.3",
                    "title": "Update M1 traceability",
                    "requirement_ids": ["R-3", "R-4", "R-8", "R-9", "R-18"],
                    "status": "todo",
                    "estimate_hours": 4,
                    "depends_on": ["1.2"],
                },
            ],
        },
        {
            "id": "M2",
            "name": "Traceability and projections",
            "exit_criteria": "Matrix lint and deterministic projection drift checks pass.",
            "budget_prs": 3,
            "budget_hours": 20,
            "tasks": [
                {
                    "id": "2.1",
                    "title": "Write failing traceability and projection tests",
                    "requirement_ids": ["R-5", "R-6", "R-7"],
                    "status": "in-progress",
                    "estimate_hours": 6,
                    "depends_on": [],
                },
                {
                    "id": "2.2",
                    "title": "Implement traceability lint and projections",
                    "requirement_ids": ["R-5", "R-6", "R-7"],
                    "status": "in-progress",
                    "estimate_hours": 10,
                    "depends_on": ["2.1"],
                },
                {
                    "id": "2.3",
                    "title": "Update M2 traceability",
                    "requirement_ids": ["R-5", "R-6", "R-7"],
                    "status": "todo",
                    "estimate_hours": 4,
                    "depends_on": ["2.2"],
                },
            ],
        },
        {
            "id": "M3",
            "name": "Edge-AI evidence gates",
            "exit_criteria": (
                "Model-card, latency, and determinism gates pass clean and failure-path tests."
            ),
            "budget_prs": 5,
            "budget_hours": 32,
            "tasks": [
                {
                    "id": "3.1",
                    "title": "Write failing edge-AI evidence-gate tests",
                    "requirement_ids": ["R-10", "R-11", "R-12"],
                    "status": "in-progress",
                    "estimate_hours": 10,
                    "depends_on": [],
                },
                {
                    "id": "3.2",
                    "title": "Implement edge-AI evidence gates and examples",
                    "requirement_ids": ["R-10", "R-11", "R-12"],
                    "status": "in-progress",
                    "estimate_hours": 18,
                    "depends_on": ["3.1"],
                },
                {
                    "id": "3.3",
                    "title": "Update M3 traceability",
                    "requirement_ids": ["R-10", "R-11", "R-12"],
                    "status": "todo",
                    "estimate_hours": 4,
                    "depends_on": ["3.2"],
                },
            ],
        },
        {
            "id": "M4",
            "name": "Mission governance gates",
            "exit_criteria": "Safety and HIL governance tests prove bound and absence behavior.",
            "budget_prs": 4,
            "budget_hours": 28,
            "tasks": [
                {
                    "id": "4.1",
                    "title": "Write failing safety and HIL tests",
                    "requirement_ids": ["R-13", "R-14", "R-15"],
                    "status": "in-progress",
                    "estimate_hours": 10,
                    "depends_on": [],
                },
                {
                    "id": "4.2",
                    "title": "Implement safety-envelope and HIL gates",
                    "requirement_ids": ["R-13", "R-14", "R-15"],
                    "status": "in-progress",
                    "estimate_hours": 14,
                    "depends_on": ["4.1"],
                },
                {
                    "id": "4.3",
                    "title": "Update M4 traceability",
                    "requirement_ids": ["R-13", "R-14", "R-15"],
                    "status": "todo",
                    "estimate_hours": 4,
                    "depends_on": ["4.2"],
                },
            ],
        },
        {
            "id": "M5",
            "name": "Integration and publication readiness",
            "exit_criteria": (
                "CI, hooks, skills, projections, and traceability are integrated; "
                "publication remains gated."
            ),
            "budget_prs": 3,
            "budget_hours": 20,
            "tasks": [
                {
                    "id": "5.1",
                    "title": "Write failing publication and non-commanding-boundary tests",
                    "requirement_ids": ["R-16", "R-17"],
                    "status": "in-progress",
                    "estimate_hours": 6,
                    "depends_on": [],
                },
                {
                    "id": "5.2",
                    "title": "Integrate hooks, CI, skills, and peer review",
                    "requirement_ids": ["R-16", "R-17"],
                    "status": "in-progress",
                    "estimate_hours": 10,
                    "depends_on": ["5.1", "1.2", "2.2", "3.2", "4.2"],
                },
                {
                    "id": "5.3",
                    "title": "Update final traceability and regenerate projections",
                    "requirement_ids": ["R-16", "R-17"],
                    "status": "todo",
                    "estimate_hours": 4,
                    "depends_on": ["5.2"],
                },
            ],
        },
    ],
    "requirements": [
        {
            "id": "R-1",
            "statement": (
                "Layered configuration retains provenance and fails closed on malformed layers."
            ),
            "milestone": "M0",
        },
        {
            "id": "R-2",
            "statement": "Frozen operational controls reject environment and CLI overrides.",
            "milestone": "M0",
        },
        {
            "id": "R-3",
            "statement": "One shared normalizer handles supported remote URL spellings.",
            "milestone": "M1",
        },
        {
            "id": "R-4",
            "statement": (
                "Remote authorization blocks empty, invalid, unreadable, or "
                "unallowlisted destinations."
            ),
            "milestone": "M1",
        },
        {
            "id": "R-5",
            "statement": (
                "Traceability rows are complete, unique, and linted against configured semantics."
            ),
            "milestone": "M2",
        },
        {
            "id": "R-6",
            "statement": "Green traceability evidence must cite a collecting pytest node.",
            "milestone": "M2",
        },
        {
            "id": "R-7",
            "statement": (
                "Roadmap and backlog are deterministic generated projections with drift checks."
            ),
            "milestone": "M2",
        },
        {
            "id": "R-8",
            "statement": "Packs conform to every Gate Harness Contract v1.1 clause.",
            "milestone": "M1",
        },
        {
            "id": "R-9",
            "statement": "Skipped and xfailed tests fail unless validly authorized.",
            "milestone": "M1",
        },
        {
            "id": "R-10",
            "statement": "Model provenance and model-card/artifact pairing are enforced.",
            "milestone": "M3",
        },
        {
            "id": "R-11",
            "statement": (
                "Runtime-specific latency evidence includes configured percentile, budget, "
                "headroom, and device."
            ),
            "milestone": "M3",
        },
        {
            "id": "R-12",
            "statement": "Evaluation evidence proves repeatable seeds and metric tolerance.",
            "milestone": "M3",
        },
        {
            "id": "R-13",
            "statement": (
                "Mission safety bounds are declared and internally consistent without vehicle "
                "command."
            ),
            "milestone": "M4",
        },
        {
            "id": "R-14",
            "statement": "Permissive safety-bound widening requires decision-log authority.",
            "milestone": "M4",
        },
        {
            "id": "R-15",
            "statement": (
                "Hardware-in-the-loop runner absence is declared and authorized or blocks."
            ),
            "milestone": "M4",
        },
        {
            "id": "R-16",
            "statement": "Robotics governance remains non-commanding.",
            "milestone": "M5",
        },
        {
            "id": "R-17",
            "statement": (
                "Public publication requires both destination allowlisting and G-PUB authority."
            ),
            "milestone": "M5",
        },
        {
            "id": "R-18",
            "statement": (
                "Per-file coverage includes untested files and enforces configured floors."
            ),
            "milestone": "M1",
        },
    ],
}


def data() -> dict[str, object]:
    """Return an isolated projection payload for consumers of the planning contract.

    A deep copy prevents a renderer or test from mutating the module's canonical
    data and causing a later render in the same process to depend on call order.
    """
    return cast(dict[str, object], deepcopy(_DATA))


def validate() -> None:
    """Validate requirement, task, dependency, milestone, and status integrity.

    Raises:
        ValueError: If an identifier is duplicated, a task refers to a missing
            requirement or dependency, a requirement names a missing milestone,
            or a task uses an unsupported status.
    """
    milestone_ids = [milestone["id"] for milestone in _DATA["milestones"]]
    _require_unique("milestone", milestone_ids)

    requirement_ids = [requirement["id"] for requirement in _DATA["requirements"]]
    _require_unique("requirement", requirement_ids)
    requirement_id_set = set(requirement_ids)
    milestone_id_set = set(milestone_ids)

    for requirement in _DATA["requirements"]:
        if requirement["milestone"] not in milestone_id_set:
            raise ValueError(
                f"requirement {requirement['id']} names missing milestone "
                f"{requirement['milestone']}"
            )

    tasks = [task for milestone in _DATA["milestones"] for task in milestone["tasks"]]
    task_ids = [task["id"] for task in tasks]
    _require_unique("task", task_ids)
    task_id_set = set(task_ids)
    allowed_statuses: frozenset[str] = frozenset({"todo", "in-progress", "done", "blocked"})

    for task in tasks:
        if task["status"] not in allowed_statuses:
            raise ValueError(f"task {task['id']} has unsupported status {task['status']!r}")
        for requirement_id in task["requirement_ids"]:
            if requirement_id not in requirement_id_set:
                raise ValueError(
                    f"task {task['id']} references missing requirement {requirement_id}"
                )
        for dependency_id in task["depends_on"]:
            if dependency_id not in task_id_set:
                raise ValueError(f"task {task['id']} depends on missing task {dependency_id}")
            if dependency_id == task["id"]:
                raise ValueError(f"task {task['id']} cannot depend on itself")


def _require_unique(kind: str, identifiers: list[str]) -> None:
    """Raise a clear error if a data category contains a repeated identifier."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate {kind} id(s): {joined}")
