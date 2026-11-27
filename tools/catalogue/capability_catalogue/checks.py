# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The cross-reference checks: every name the catalogue uses resolves, and every pointer points at a line
that exists, in the repository, the reference map and the published contracts."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from reference_map.entries import load_map

from .catalogue import Catalogue

SCHEMAS_DIR = "packages/benchhand-contracts/src/benchhand_contracts/schemas"
REFERENCE_MAP = "docs/architecture/reference-map.yaml"
ARCHITECTURE_DIR = "docs/architecture"
REPO_SOURCES = ("plan", "adr", "contract", "architecture", "code")
"""Source kinds that point into the repository."""
_LINE = re.compile(r"^(?P<path>[^:#]+)(?::(?P<line>[0-9]+)|#(?P<anchor>[A-Za-z0-9_-]+))?$")


def check_catalogue(catalogue: Catalogue, repo_root: Path) -> list[str]:
    """Every cross-reference problem, in file order; empty when the catalogue holds together."""
    return [
        *_duplicates(catalogue),
        *_references(catalogue),
        *_cycles(catalogue),
        *_tool_reasons(catalogue),
        *_prototype_paths(catalogue, repo_root),
        *_contracts(catalogue, repo_root),
        *_adrs(catalogue, repo_root),
        *_containers(catalogue, repo_root),
        *_owners(catalogue, repo_root),
        *_pointers(catalogue, repo_root),
        *_named_sources(catalogue, repo_root),
    ]


def _duplicates(catalogue: Catalogue) -> Iterator[str]:
    for kind, key, items in (
        ("capability", "id", catalogue.capabilities),
        ("tool", "name", catalogue.tools),
        ("CLI command", "name", catalogue.cli),
        ("prototype command", "command", catalogue.prototype_commands),
        ("open question", "id", catalogue.open_questions),
    ):
        counts = Counter(item[key] for item in items)
        yield from (f"{kind} {name} is listed {count} times" for name, count in counts.items() if count > 1)


def _references(catalogue: Catalogue) -> Iterator[str]:
    capabilities = {item["id"] for item in catalogue.capabilities}
    questions = {item["id"] for item in catalogue.open_questions}
    tools = {item["name"] for item in catalogue.tools}
    commands = {item["command"] for item in catalogue.prototype_commands}
    for where, item in _all_items(catalogue):
        for name in item.get("depends_on", []):
            yield from _missing(where, "depends on", name, capabilities)
        if item.get("capability") is not None and "id" not in item:
            yield from _missing(where, "names the capability", item["capability"], capabilities)
        for name in item.get("open_questions", []):
            yield from _missing(where, "cites the open question", name, questions)
        for name in item.get("mcp", []) if isinstance(item.get("mcp"), list) else []:
            yield from _missing(where, "names the MCP tool", name, tools)
        for name in item["mcp"]["baseline"] if isinstance(item.get("mcp"), dict) else []:
            yield from _missing(where, "names the baseline tool", name, tools)
        for name in item.get("replaces", []):
            yield from _missing(where, "replaces the prototype command", name, commands)
    cited = {name for _, item in _all_items(catalogue) for name in item.get("open_questions", [])}
    yield from (f"open question {name} is cited by nothing" for name in sorted(questions - cited))


def _missing(where: str, verb: str, name: str, known: set[str]) -> Iterator[str]:
    if name not in known:
        yield f"{where} {verb} {name}, which isn't in the catalogue"


def _all_items(catalogue: Catalogue) -> Iterator[tuple[str, dict[str, Any]]]:
    yield from ((f"capability {item['id']}", item) for item in catalogue.capabilities)
    yield from ((f"tool {item['name']}", item) for item in catalogue.tools)
    yield from ((f"CLI command {item['name']}", item) for item in catalogue.cli)
    yield from ((f"prototype command {item['command']}", item) for item in catalogue.prototype_commands)


def _cycles(catalogue: Catalogue) -> Iterator[str]:
    """depends_on is a graph without cycles; each cycle is reported once, from its first capability."""
    edges = {item["id"]: item.get("depends_on", []) for item in catalogue.capabilities}
    done: set[str] = set()
    for start in edges:
        path = _cycle_from(start, edges, [], done)
        if path:
            yield "depends_on has a cycle: " + " -> ".join(path)
            done.update(path)


def _cycle_from(node: str, edges: dict[str, list[str]], trail: list[str], done: set[str]) -> list[str]:
    if node in trail:
        return [*trail[trail.index(node) :], node]
    if node in done or node not in edges:
        return []
    for target in edges[node]:
        found = _cycle_from(target, edges, [*trail, node], done)
        if found:
            return found
    done.add(node)
    return []


def _tool_reasons(catalogue: Catalogue) -> Iterator[str]:
    for item in catalogue.capabilities:
        if "no_tool_reason" in item and catalogue.tools_of(item["id"]):
            yield f"capability {item['id']} has tools, so it takes no `no_tool_reason`"


def _prototype_paths(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    """Every prototype path is a reference-map entry, and a command's path is one of its capability's."""
    entries = {entry.path for entry in load_map(repo_root / REFERENCE_MAP).entries}
    for item in catalogue.capabilities:
        for path in item.get("prototype", []):
            if path not in entries:
                yield f"capability {item['id']}: {path} is not an entry of {REFERENCE_MAP}"
    for command in catalogue.prototype_commands:
        if command["path"] not in entries:
            yield f"prototype command {command['command']}: {command['path']} is not an entry of {REFERENCE_MAP}"
        elif command["capability"] and command["path"] not in _capability_paths(
            catalogue, command["capability"]
        ):
            yield (
                f"prototype command {command['command']}: capability {command['capability']} "
                f"doesn't list {command['path']} among its prototype sources"
            )


def _capability_paths(catalogue: Catalogue, capability_id: str) -> list[str]:
    known = [item for item in catalogue.capabilities if item["id"] == capability_id]
    return known[0].get("prototype", []) if known else []


def _contracts(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    """Every contract reference resolves to a published schema's $id, and its fragment to a $defs entry."""
    base = catalogue.data["contract_base"]
    for where, reference in _contract_references(catalogue):
        relative, _, fragment = reference.partition("#")
        schema_file = repo_root / SCHEMAS_DIR / relative
        if not schema_file.is_file():
            yield f"{where}: {reference} is not a published contract under {SCHEMAS_DIR}"
            continue
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        if schema.get("$id") != base + relative:
            yield f"{where}: {reference} resolves to {base + relative}, and the schema's $id is {schema.get('$id')}"
        name = fragment.removeprefix("/$defs/")
        if fragment and name not in schema.get("$defs", {}):
            yield f"{where}: {relative} has no $defs/{name}"


def _contract_references(catalogue: Catalogue) -> Iterator[tuple[str, str]]:
    for item in catalogue.capabilities:
        yield from ((f"capability {item['id']}", reference) for reference in item.get("contracts", []))
    for tool in catalogue.tools:
        for field in ("input", "output"):
            if tool[field] != "not yet defined":
                yield f"tool {tool['name']} {field}", tool[field]


def _adrs(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    present = {int(path.name[:4]) for path in (repo_root / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")}
    for item in catalogue.capabilities:
        for number in item["adrs"]:
            if number not in present:
                yield f"capability {item['id']}: there is no ADR-{number:04d} in docs/adr/"


def _containers(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    """A container names a node that its architecture page draws, such as `record[` in containers.md."""
    for item in catalogue.capabilities:
        page, _, node = item["container"].partition(":")
        page_file = repo_root / ARCHITECTURE_DIR / page
        if not page_file.is_file():
            yield f"capability {item['id']}: {ARCHITECTURE_DIR}/{page} doesn't exist"
        elif not re.search(rf"\b{re.escape(node)}\s*[\[(]", page_file.read_text(encoding="utf-8")):
            yield f"capability {item['id']}: {page} draws no node {node}"


def _owners(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    for item in catalogue.capabilities:
        if item["status"] in ("built", "partial"):
            for owner in item["owner"]:
                if not (repo_root / owner).exists():
                    yield f"capability {item['id']} is {item['status']}, and its owner {owner} doesn't exist"


def _pointers(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    for where, pointer in _all_pointers(catalogue):
        problem = pointer_problem(repo_root, pointer)
        if problem:
            yield f"{where}: {problem}"


def _all_pointers(catalogue: Catalogue) -> Iterator[tuple[str, str]]:
    for question in catalogue.open_questions:
        where = f"open question {question['id']}"
        yield from ((where, pointer) for pointer in question["pointers"])
        yield from ((where, position["source"]) for position in question.get("positions", []))
    for where, item in _all_items(catalogue):
        yield from ((where, pointer) for pointer in _item_pointers(item))


def _item_pointers(item: dict[str, Any]) -> Iterable[str]:
    yield from item.get("evidence", [])
    yield from item.get("implied_by", [])
    if isinstance(item.get("mcp"), dict):
        yield from (source["ref"] for source in item["mcp"]["sources"] if source["kind"] in REPO_SOURCES)
    if "id" in item and item.get("source", {}).get("kind") in REPO_SOURCES:
        yield item["source"]["ref"]


def pointer_problem(repo_root: Path, pointer: str) -> str | None:
    """Why ``pointer`` (a path, path:LINE or path#anchor) doesn't resolve, or None when it does."""
    found = _LINE.match(pointer)
    if not found:
        return f"{pointer} is not a path, path:LINE or path#anchor"
    target = repo_root / found["path"]
    if ".." in Path(found["path"]).parts:
        return f"{pointer}: a pointer stays inside the repository"
    if not target.is_file():
        return f"{pointer}: no file {found['path']}"
    if found["line"] is not None:
        count = len(target.read_text(encoding="utf-8").splitlines())
        if not 1 <= int(found["line"]) <= count:
            return f"{pointer}: {found['path']} has {count} lines"
    return None


def _named_sources(catalogue: Catalogue, repo_root: Path) -> Iterator[str]:
    """A tool or command whose source points into the repository is named on the line it points to."""
    for kind, items, named in (
        ("tool", catalogue.tools, tool_named),
        ("CLI command", catalogue.cli, cli_named),
    ):
        for item in items:
            if item["source"]["kind"] in REPO_SOURCES:
                problem = _named_on_line(repo_root, item["source"]["ref"], item["name"], named)
                if problem:
                    yield f"{kind} {item['name']}: {problem}"


def _word_named(name: str, line: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", line) is not None


def cli_named(name: str, line: str) -> bool:
    """``line`` names the command's words in order, in full or in the usage forms the sources use: optional
    words in brackets (`mcp [--http]`), alternatives (`policy get|set`) and a Typer group's command
    (`@record.command("migrate")`)."""
    text = re.sub(r'\.command\("([\w-]+)"\)', r" \1", line).replace("[", " ").replace("]", " ")
    words = r"\s+".join(rf"(?:[\w-]+\|)*{re.escape(word)}(?:\|[\w-]+)*" for word in name.split())
    return re.search(rf"(?<![\w.-]){words}(?![\w-])", text) is not None


def tool_named(name: str, line: str) -> bool:
    """``line`` names the tool in full, or in the one shorthand the plan uses: after a tool of the same
    namespace, the rest of the name alone in a code span, as in "`model.measure`, `section`"."""
    if _word_named(name, line):
        return True
    namespace, _, rest = name.rpartition(".")
    sibling = re.search(rf"`{re.escape(namespace)}\.\w", line)
    return sibling is not None and re.search(rf"`{re.escape(rest)}[`(]", line[sibling.end() :]) is not None


def _named_on_line(repo_root: Path, pointer: str, name: str, named: Callable[[str, str], bool]) -> str | None:
    found = _LINE.match(pointer)
    if not found or found["line"] is None:
        return f"its {pointer} needs a path:LINE"
    problem = pointer_problem(repo_root, pointer)
    if problem:
        return problem
    line = (repo_root / found["path"]).read_text(encoding="utf-8").splitlines()[int(found["line"]) - 1]
    return None if named(name, line) else f"{pointer} doesn't name {name}"
