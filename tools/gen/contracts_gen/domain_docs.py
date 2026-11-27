# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The domain model's pages and diagrams, written below ``docs/contract/generated/``.

``domain-model/README.md`` holds the overview diagram and an index; each contract has a page with its
diagrams and a field table per type; the ``.d2`` sources and the ``.svg`` files they lay out to sit beside
the pages. ``domain-model.md`` is a stub that points at the README, so earlier links keep working.

``domain_model_files`` builds every text file without running D2, so the pages can be checked without it;
``write_domain_model`` writes them and lays the diagrams out.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .domain import MAX_ENUM_VALUES, ClassNode, DomainModel, build_model, literal, ref_counts
from .domain_d2 import (
    CLASSES_D2,
    CLASSES_DARK_D2,
    CLASSES_DARK_FILE,
    CLASSES_FILE,
    MAX_DIAGRAM_NODES,
    OVERVIEW_FILE,
    Caption,
    Diagram,
    DiagramPlan,
    RelationshipRow,
    check_d2_version,
    dark_svg,
    diagram_caption,
    overview_caption,
    overview_rows,
    plan_diagrams,
    relationship_rows,
    render_d2,
    render_diagram,
    render_overview,
    stubs_of,
)
from .sources import GENERATED_NOTICE, Contract

STUB_FILE = "domain-model.md"
MODEL_DIR = "domain-model"
README_PATH = f"{MODEL_DIR}/README.md"
RENDER_WORKERS = 8

_FIELD_HEADER = ("| Field | Type | Required | Description |", "|---|---|---|---|")
_ENUM_HEADER = ("| Enum | Values | Description |", "|---|---|---|")
_RELATIONSHIP_HEADER = ("| Source | Relation | Target | Cardinality |", "|---|---|---|---|")


def diagram_captions(model: DomainModel, plan: DiagramPlan, contracts: list[Contract]) -> dict[str, Caption]:
    """The text alternative of every SVG, by the path of its ``.d2`` source."""
    captions = {
        f"{MODEL_DIR}/{OVERVIEW_FILE}.d2": overview_caption(model, ref_counts(contracts)),
    }
    for diagrams in plan.diagrams.values():
        for diagram in diagrams:
            captions[f"{MODEL_DIR}/{diagram.path}.d2"] = diagram_caption(model, diagram)
    return captions


def _relationship_table(rows: list[RelationshipRow]) -> list[str]:
    lines: list[str] = list(_RELATIONSHIP_HEADER)
    for row in rows:
        cells = (row.source, row.relation, row.target, row.cardinality)
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return [*lines, ""]


def domain_model_files(contracts: list[Contract]) -> dict[str, str]:
    """Every Markdown and D2 file of the domain model, by path below ``docs/contract/generated``."""
    model = build_model(contracts)
    plan = plan_diagrams(model)
    files = {
        STUB_FILE: render_stub(),
        README_PATH: render_readme(model, plan, contracts),
        f"{MODEL_DIR}/{CLASSES_FILE}": CLASSES_D2,
        f"{MODEL_DIR}/{CLASSES_DARK_FILE}": CLASSES_DARK_D2,
        f"{MODEL_DIR}/{OVERVIEW_FILE}.d2": render_overview(model, plan, ref_counts(contracts)),
    }
    for contract in contracts:
        files[f"{MODEL_DIR}/{contract.stem}.md"] = render_contract_page(model, plan, contract)
    for diagrams in plan.diagrams.values():
        for diagram in diagrams:
            files[f"{MODEL_DIR}/{diagram.path}.d2"] = render_diagram(model, plan, diagram)
    return files


def diagram_sources(files: Iterable[str]) -> list[str]:
    """The ``.d2`` files among ``files`` that D2 lays out: every one but the shared classes."""
    shared = (f"/{CLASSES_FILE}", f"/{CLASSES_DARK_FILE}")
    return [path for path in files if path.endswith(".d2") and not path.endswith(shared)]


def write_domain_model(contracts: list[Contract], docs_dir: Path) -> None:
    """Write the pages and sources below ``docs_dir`` and lay every diagram out beside its source, light and dark."""
    check_d2_version()
    files = domain_model_files(contracts)
    for rel_path, text in files.items():
        path = docs_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    model = build_model(contracts)
    captions = diagram_captions(model, plan_diagrams(model), contracts)
    renders = [(docs_dir / rel_path, dark) for rel_path in diagram_sources(files) for dark in (False, True)]

    def render(source: Path, dark: bool) -> bytes:
        light = source.with_suffix(".svg")
        caption = captions[source.relative_to(docs_dir).as_posix()]
        return render_d2(source, dark_svg(light) if dark else light, caption, dark=dark)

    with ThreadPoolExecutor(max_workers=RENDER_WORKERS) as pool:
        list(pool.map(lambda job: render(*job), renders))


def render_stub() -> str:
    return "\n".join(
        [
            "# Domain model",
            "",
            f"{GENERATED_NOTICE} The domain model is now a set of pages: see "
            f"[the domain model]({README_PATH}).",
            "",
        ]
    )


# --- the README


def render_readme(model: DomainModel, plan: DiagramPlan, contracts: list[Contract]) -> str:
    lines = ["# Domain model", "", f"{GENERATED_NOTICE} Source: the published schemas of `contracts/`.", ""]
    lines += [
        f"{len(model.classes)} types of {len(contracts)} contracts, in "
        f"{sum(len(found) for found in plan.diagrams.values())} diagrams of at most "
        f"{MAX_DIAGRAM_NODES} types each. The overview shows the record documents and the libraries they "
        "refer to. Every contract has a page with its diagrams and a table of the fields of each type.",
        "",
        f"![The record documents and libraries, with the number of `$ref`s between them]({OVERVIEW_FILE}.svg)",
        "",
        "### Relationships in the overview",
        "",
        "Each arrow of the overview as a row. The cardinality is the number of `$ref`s from the source to the target.",
        "",
        *_relationship_table(overview_rows(model, ref_counts(contracts))),
    ]
    lines += _legend()
    lines += _index(model, plan, contracts)
    return "\n".join(lines).rstrip("\n") + "\n"


def _legend() -> list[str]:
    return [
        "## Legend",
        "",
        "Each table is a type: a contract root, a named `$defs` object or union, or an object written "
        "inline. An inline object `b` of property `a` is named `a.b`. Each row is a field, and `req` marks "
        "a required one. A box with a dashed border groups the types that one root owns.",
        "",
        "- Types: the header of a table names its type, so that colour is never the only cue. "
        "`«document»` (blue) is a contract root, `«type»` (teal) is any other type, and a "
        "union (purple) is `«union»`, or `«abstract»` when every branch fixes one property "
        "with a `const`. A grey box with a dashed border is a stub: a type that another diagram of the same "
        "contract or another contract owns. It has no fields.",
        "- **Enums have no colour.** D2 cannot colour one table cell, and the model has no node for an "
        "enum. An enum shows in the type of its field: its values when there are six or fewer, and its "
        "name when it is a named definition. Each contract page lists its enums in one table.",
        "- Arrows: a solid line is composition, a type nested in another (inline, or a `$ref` within the "
        "contract). A dashed line is association, a `$ref` to a type of another contract. A hollow "
        "triangle is inheritance: a branch of a union, or a type that extends another with `allOf`. A "
        "label lists the fields and the number held: `1..*` is at least one, `0..*` any number, `2` exactly "
        "two, `0..1` an optional, nullable or alternative one.",
        "- In a type, `T[]` is an array of any length, `T[1..*]` at least one, `T[2]` exactly two. "
        "`[A, B]` is a tuple. `T by key` is an object whose every value is a T, and a `[key]` row holds "
        "the other keys of an object that also has named properties. Values are JSON: `null`, `true`, and "
        "a string bare.",
        "- In the overview, a blue page shape is a record document, an amber package shape is a library "
        "(shared definitions and no document of its own), and an arrow counts the `$ref`s from one record "
        "contract to another.",
        "- Every diagram has a text alternative: a table of its relationships follows it, with the source, the "
        "relation, the target and the cardinality of each arrow, and its `.svg` file has a title and a "
        "description that spell out the same arrows.",
        "- A diagram is also a link target: in the `.svg` file, a stub and an overview node link to the "
        "diagram that owns the type. In a Markdown page the image is static, so the contract pages "
        "list the related contracts.",
        "",
    ]


def _index(model: DomainModel, plan: DiagramPlan, contracts: list[Contract]) -> list[str]:
    counts = Counter(node.stem for node in model.classes.values())
    groups: dict[str, list[Contract]] = {}
    for contract in contracts:
        groups.setdefault(contract.stem.split("/")[0], []).append(contract)
    lines = ["## Contracts", ""]
    for group, members in groups.items():
        lines += [f"### `{group}`", "", "| Contract | Types | Diagrams |", "|---|---|---|"]
        for contract in members:
            diagrams = len(plan.diagrams.get(contract.stem, []))
            lines.append(
                f"| [`{contract.stem}`]({contract.stem}.md) | {counts[contract.stem]} | {diagrams} |"
            )
        lines.append("")
    return lines


def render_contract_page(model: DomainModel, plan: DiagramPlan, contract: Contract) -> str:
    page = f"{MODEL_DIR}/{contract.stem}.md"
    up = "../" * page.count("/")  # from the page's directory to docs/contract/generated/
    nodes = [node for node in model.classes.values() if node.stem == contract.stem]
    diagrams = plan.diagrams.get(contract.stem, [])
    lines = [f"# `{contract.stem}`", ""]
    lines += [
        f"{GENERATED_NOTICE} Contract reference: [`{contract.stem}`]({up}{contract.stem}.md). "
        f"Source: [`{contract.source}`]({up}../../../{contract.source}).",
        "",
    ]
    if contract.schema.get("description"):
        lines += [contract.schema["description"], ""]
    lines += _diagram_section(model, plan, contract.stem, diagrams, page)
    lines += _type_section(nodes, diagrams, {contract.schema.get("description", "")})
    lines += _enum_section(contract, nodes)
    return "\n".join(lines).rstrip("\n") + "\n"


def _diagram_section(
    model: DomainModel, plan: DiagramPlan, stem: str, diagrams: list[Diagram], page: str
) -> list[str]:
    if not diagrams:
        return ["This contract has no types: it holds no object or union.", ""]
    lines = [
        "## Diagrams",
        "",
        f"{sum(len(d.owned) for d in diagrams)} types in {len(diagrams)} diagrams.",
        "",
    ]
    for diagram in diagrams:
        image = posixpath.relpath(f"{MODEL_DIR}/{diagram.path}.svg", posixpath.dirname(page))
        lines += [
            f"### {diagram.number}. `{diagram.title}`",
            "",
            f"![Diagram {diagram.number} of {stem}, {diagram.title}: the table below lists its relationships]({image})",
            "",
            *_diagram_relationships(model, diagram),
        ]
    related = sorted(
        {
            model.classes[stub].stem
            for diagram in diagrams
            for stub in stubs_of(model, diagram)
            if model.classes[stub].stem != stem
        }
    )
    if related:
        links = ", ".join(
            f"[`{other}`]({posixpath.relpath(f'{MODEL_DIR}/{other}.md', posixpath.dirname(page))})"
            for other in related
        )
        lines += [f"Types of other contracts, drawn as stubs: {links}.", ""]
    return lines


def _diagram_relationships(model: DomainModel, diagram: Diagram) -> list[str]:
    """The text alternative of a diagram's arrows: a table of its relationships, or a line saying it has none."""
    rows = relationship_rows(model, diagram)
    if not rows:
        return [f"Diagram {diagram.number} has no relationships.", ""]
    return [f"Relationships in diagram {diagram.number}:", "", *_relationship_table(rows)]


def _type_section(nodes: list[ClassNode], diagrams: list[Diagram], shown: set[str]) -> list[str]:
    if not nodes:
        return []
    number = {member: diagram.number for diagram in diagrams for member in diagram.owned}
    # A description already shown, as the contract's or as a field's, is not repeated under the type.
    shown = shown | {held.description for node in nodes for held in node.fields}
    lines = ["## Types", ""]
    for diagram in diagrams:
        for member in diagram.owned:
            node = next(node for node in nodes if node.id == member)
            lines += _type_table(node, number[member] if len(diagrams) > 1 else None, shown)
    return lines


def _type_table(node: ClassNode, diagram_number: int | None, shown: set[str]) -> list[str]:
    kind = f" «{node.stereotype}»" if node.stereotype else ""
    lines = [f"### `{node.label}`{kind}", ""]
    if diagram_number is not None:
        lines += [f"In diagram {diagram_number}.", ""]
    if node.description and node.description not in shown:
        lines += [_text(node.description), ""]
    if not node.fields:
        return [*lines, "No fields of its own.", ""]
    lines += list(_FIELD_HEADER)
    for held in node.fields:
        cells = (f"`{held.name}`", f"`{held.type}`", "yes" if held.required else "no", held.description)
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return [*lines, ""]


def _enum_section(contract: Contract, nodes: list[ClassNode]) -> list[str]:
    rows = _enum_rows(contract, nodes)
    if not rows:
        return []
    lines = [
        "## Enums",
        "",
        "Named enum definitions, and the enums of fields that have more than "
        f"{MAX_ENUM_VALUES} values, which the field's type does not spell out. "
        "Enums have no colour in the diagrams.",
        "",
        *_ENUM_HEADER,
    ]
    for name, values, description in rows:
        cells = (f"`{name}`", ", ".join(f"`{value}`" for value in values), description)
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return [*lines, ""]


def _enum_rows(contract: Contract, nodes: list[ClassNode]) -> list[tuple[str, tuple[str, ...], str]]:
    rows: list[tuple[str, tuple[str, ...], str]] = []
    definitions: dict[str, Any] = contract.schema.get("$defs", {})
    for name, schema in definitions.items():
        if isinstance(schema, dict) and "enum" in schema:
            values = tuple(literal(value) for value in schema["enum"])
            rows.append((name, values, schema.get("description", "")))
    for node in nodes:
        rows += [
            (f"{node.label}.{held.name}", held.values, held.description)
            for held in node.fields
            if len(held.values) > MAX_ENUM_VALUES
        ]
    return rows


def _text(text: str) -> str:
    return " ".join(text.split())


def _cell(text: str) -> str:
    """A table cell: one line, with the pipes escaped."""
    return _text(text).replace("|", "\\|")
