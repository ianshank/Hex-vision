"""Mechanical floor for tests that would pass without exercising any implementation."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "tests"


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return every test function, including class-contained tests, in source order."""

    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def _effective_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """Remove a docstring because prose alone cannot make a behavioral test."""

    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def test_test_suite_rejects_literal_true_and_empty_test_bodies() -> None:
    """The mechanically certain no-op classes cannot become born-green test coverage."""

    literal_true: list[str] = []
    empty: list[str] = []
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _test_functions(tree):
            location = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
            body = _effective_body(node)
            if not body or all(isinstance(statement, ast.Pass) for statement in body):
                empty.append(location)
            literal_true.extend(
                location
                for assertion in ast.walk(node)
                if isinstance(assertion, ast.Assert)
                and isinstance(assertion.test, ast.Constant)
                and assertion.test.value is True
            )
    assert empty == [], f"test bodies with no executable behavioral assertion: {empty}"
    assert literal_true == [], (
        f"literal `assert True` tests provide no behavioral evidence: {literal_true}"
    )
