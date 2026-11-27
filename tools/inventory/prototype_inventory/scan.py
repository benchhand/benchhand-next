# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The public functions, classes and entry points of one prototype module, read with ``ast``."""

from __future__ import annotations

import ast
from typing import TypedDict

from .commands import CommandRecord, scan_commands
from .text import first_line


class FunctionRecord(TypedDict):
    name: str
    """``function`` or ``Class.method``."""
    kind: str
    """``function``, ``async function``, ``method`` or ``async method``."""
    signature: str
    """``def name(arguments) -> return``, with ``async`` in front for a coroutine."""
    summary: str
    """The first line of the docstring."""
    decorators: list[str]
    line: int


class ClassRecord(TypedDict):
    name: str
    signature: str
    """``class Name(bases)``."""
    summary: str
    decorators: list[str]
    line: int


class ModuleRecord(TypedDict):
    summary: str
    entry_points: list[str]
    """The statements of each ``if __name__ == "__main__":`` block, as source."""
    commands: list[CommandRecord]
    classes: list[ClassRecord]
    functions: list[FunctionRecord]
    """Functions and the methods of public classes, in source order."""


Function = ast.FunctionDef | ast.AsyncFunctionDef


def scan_source(source: str, filename: str) -> ModuleRecord:
    """Parse ``source``; a syntax error is raised as ``SyntaxError`` carrying ``filename``."""
    tree = ast.parse(source, filename=filename)
    classes: list[ClassRecord] = []
    functions: list[FunctionRecord] = []
    entry_points: list[str] = []
    for node in _statements(tree.body):
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            classes.append(_class_record(node))
            functions += [_function_record(item, node.name) for item in _public_functions(node.body)]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
            functions.append(_function_record(node, None))
        elif isinstance(node, ast.If) and _is_main_guard(node.test):
            entry_points.append("; ".join(ast.unparse(statement) for statement in node.body))
    return {
        "summary": first_line(ast.get_docstring(tree)),
        "entry_points": entry_points,
        "commands": scan_commands(tree),
        "classes": classes,
        "functions": functions,
    }


def _statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """The module's statements, with the bodies of a top-level ``try`` or ``if`` (an import fallback, a
    ``TYPE_CHECKING`` block) opened up; a ``__main__`` guard stays whole."""
    found: list[ast.stmt] = []
    for node in body:
        if isinstance(node, ast.If) and not _is_main_guard(node.test):
            found += _statements(node.body) + _statements(node.orelse)
        elif isinstance(node, ast.Try):
            found += _statements(node.body) + _statements(node.orelse) + _statements(node.finalbody)
            for handler in node.handlers:
                found += _statements(handler.body)
        else:
            found.append(node)
    return found


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _public_functions(body: list[ast.stmt]) -> list[Function]:
    return [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name)
    ]


def _is_main_guard(test: ast.expr) -> bool:
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)):
        return False
    sides = [test.left, *test.comparators]
    return any(isinstance(side, ast.Name) and side.id == "__name__" for side in sides) and any(
        isinstance(side, ast.Constant) and side.value == "__main__" for side in sides
    )


def _class_record(node: ast.ClassDef) -> ClassRecord:
    arguments = [ast.unparse(item) for item in [*node.bases, *node.keywords]]
    return {
        "name": node.name,
        "signature": f"class {node.name}({', '.join(arguments)})" if arguments else f"class {node.name}",
        "summary": first_line(ast.get_docstring(node)),
        "decorators": [ast.unparse(item) for item in node.decorator_list],
        "line": node.lineno,
    }


def _function_record(node: Function, owner: str | None) -> FunctionRecord:
    is_async = isinstance(node, ast.AsyncFunctionDef)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    keyword = "async def" if is_async else "def"
    kind = ("async " if is_async else "") + ("method" if owner else "function")
    return {
        "name": f"{owner}.{node.name}" if owner else node.name,
        "kind": kind,
        "signature": f"{keyword} {node.name}({ast.unparse(node.args)}){returns}",
        "summary": first_line(ast.get_docstring(node)),
        "decorators": [ast.unparse(item) for item in node.decorator_list],
        "line": node.lineno,
    }
