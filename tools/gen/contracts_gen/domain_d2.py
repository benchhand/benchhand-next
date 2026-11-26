"""D2 diagrams of the domain model (``domain.py``): a preview renderer next to the Mermaid one.

The model is split per contract into *aggregates*: a root class plus the classes only it owns, meaning the
classes reached through compositions and union branches whose every parent sits in the same aggregate. A
class held from two aggregates, or from none, roots one of its own. An aggregate over ``MAX_DIAGRAM_NODES``
sheds its largest subtrees that fit, so none does. A diagram then packs the aggregates of one contract that
belong together, up to the same bound, each in a container named after its root; a class defined elsewhere
is a grey stub that links to the diagram that owns it.

Every class is in exactly one diagram. ``render_diagram`` writes the D2 of one, ``render_overview`` the
overview of the record contracts, and ``CLASSES_D2`` holds the colours the diagrams import. The diagrams are
laid out with ``d2 --layout elk``, which this module pins to ``D2_VERSION``.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from collections import Counter, deque
from dataclasses import dataclass

from .domain import ClassNode, DomainModel, Relation, class_id

D2_VERSION = "0.9.0"
D2_LAYOUT = "elk"
D2_PAD = 40
D2_COMMAND = "d2"
CLASSES_FILE = "classes.d2"
OVERVIEW_FILE = "overview"
MAX_DIAGRAM_NODES = 12
"""The classes one diagram owns, stubs not counted."""
SMALL_AGGREGATE = 3
"""An aggregate this small, with no relation to a diagram that has room, shares a diagram with its kind."""
MAX_TYPE_CHARS = 60
"""A table cell holds one line, so a longer type, such as an enum of many values, is cut here and ends in an ellipsis."""
OVERVIEW_GROUP = "record"
"""The contract directory whose documents and libraries the overview shows."""

_VERSION_PATTERN = re.compile(r"^v?(\d+\.\d+\.\d+)\b")

CLASSES_D2 = """\
# The colours of every diagram, set once. A sql_table takes its header from `fill` and its body from `stroke`.
classes: {
  document: { style: { fill: "#1d4ed8"; stroke: "#eff6ff"; font-color: "#ffffff" } }
  owned: { style: { fill: "#0f766e"; stroke: "#f0fdfa"; font-color: "#ffffff" } }
  union: { style: { fill: "#7c3aed"; stroke: "#f5f3ff"; font-color: "#ffffff" } }
  overview_document: { style: { fill: "#1d4ed8"; stroke: "#1e3a8a"; font-color: "#ffffff"; font-size: 20 } }
  overview_library: { style: { fill: "#b45309"; stroke: "#78350f"; font-color: "#ffffff"; font-size: 20 } }
  stub: {
    style: { fill: "#e5e7eb"; stroke: "#9ca3af"; font-color: "#4b5563"; font-size: 14; stroke-dash: 2 }
  }
  aggregate: {
    style: { fill: "#f8fafc"; stroke: "#94a3b8"; stroke-dash: 3; font-size: 22; font-color: "#334155" }
  }
  composition: { style: { stroke: "#334155"; stroke-width: 2 } }
  association: { style: { stroke: "#6b7280"; stroke-dash: 4 } }
  inheritance: {
    style: { stroke: "#7c3aed"; stroke-width: 2 }
    target-arrowhead: { shape: triangle; style: { filled: false } }
  }
  reference: { style: { stroke: "#64748b" } }
}
"""


class D2VersionError(RuntimeError):
    """The installed D2 is not the pinned one, or isn't there."""


def parse_d2_version(output: str) -> str:
    """The version in the output of ``d2 --version``, e.g. ``0.9.0`` for ``v0.9.0``."""
    found = _VERSION_PATTERN.match(output.strip())
    if not found:
        raise D2VersionError(f"can't read a D2 version from {output!r}")
    return found.group(1)


def check_d2_version(output: str | None = None) -> None:
    """Refuse any D2 but ``D2_VERSION``: its layout is part of the output. ``output`` stands in for ``d2 --version``."""
    if output is None:
        try:
            output = subprocess.run(
                [D2_COMMAND, "--version"], capture_output=True, text=True, check=True, timeout=30
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise D2VersionError(f"can't run `{D2_COMMAND} --version`: {error}") from error
    found = parse_d2_version(output)
    if found != D2_VERSION:
        raise D2VersionError(f"D2 {found} is installed, and the diagrams are pinned to D2 {D2_VERSION}")


# --- aggregates and diagrams


@dataclass(frozen=True)
class Aggregate:
    root: str
    members: tuple[str, ...]
    """Class ids, the root included, in model order."""


@dataclass(frozen=True)
class Diagram:
    stem: str
    number: int
    """One-based, within the contract."""
    title: str
    aggregates: tuple[Aggregate, ...]

    @property
    def owned(self) -> list[str]:
        return [member for aggregate in self.aggregates for member in aggregate.members]

    @property
    def path(self) -> str:
        """Where the diagram is written, without a suffix: ``record/part/01-part``."""
        return f"{self.stem}/{self.number:02d}-{_slug(self.title)}"


@dataclass(frozen=True)
class DiagramPlan:
    """The diagrams of every contract, and the diagram that owns each class."""

    diagrams: dict[str, list[Diagram]]
    home: dict[str, Diagram]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "type"


def plan_diagrams(model: DomainModel) -> DiagramPlan:
    """Split every contract of ``model`` into aggregates and pack them into diagrams."""
    stems = sorted({node.stem for node in model.classes.values()})
    diagrams = {stem: _diagrams_of(model, stem) for stem in stems}
    home = {member: diagram for found in diagrams.values() for diagram in found for member in diagram.owned}
    return DiagramPlan(diagrams, home)


def _diagrams_of(model: DomainModel, stem: str) -> list[Diagram]:
    ids = [node.id for node in model.classes.values() if node.stem == stem]
    inside = set(ids)
    parents: dict[str, list[str]] = {class_: [] for class_ in ids}
    links: set[frozenset[str]] = set()
    for relation in model.relations:
        if relation.source in inside and relation.target in inside and relation.source != relation.target:
            links.add(frozenset((relation.source, relation.target)))
            if relation.kind != "association":
                parents[relation.target].append(relation.source)
    root = next((class_ for class_ in ids if class_ == _root_id(stem)), None)
    aggregates = _aggregates(ids, parents, root)
    pages = _pack(aggregates, links, root)
    return [
        Diagram(stem, number, model.classes[page[0].root].label, tuple(page))
        for number, page in enumerate(pages, start=1)
    ]


def _root_id(stem: str) -> str:
    return class_id(stem, None)


def _aggregates(ids: list[str], parents: dict[str, list[str]], root: str | None) -> list[Aggregate]:
    owner = _owners(ids, parents, root)
    found: list[Aggregate] = []
    for head in dict.fromkeys(owner.values()):
        members = [class_ for class_ in ids if owner[class_] == head]
        found += _shed(head, members, parents)
    return found


def _owners(ids: list[str], parents: dict[str, list[str]], root: str | None) -> dict[str, str]:
    """The root of each class's aggregate: that of its parents when they agree, else the class itself."""
    owner: dict[str, str] = {}
    for class_ in ids:
        if class_ == root or not parents[class_]:
            owner[class_] = class_
    while len(owner) < len(ids):
        pending = [class_ for class_ in ids if class_ not in owner]
        ready = [class_ for class_ in pending if all(parent in owner for parent in parents[class_])]
        if not ready:  # a cycle with no way in: take the first class that something already placed holds
            held = [class_ for class_ in pending if any(parent in owner for parent in parents[class_])]
            ready = held[:1] or pending[:1]
        for class_ in ready:
            heads = {owner[parent] for parent in parents[class_] if parent in owner}
            owner[class_] = heads.pop() if len(heads) == 1 else class_
    return owner


def _children(head: str, members: list[str], parents: dict[str, list[str]]) -> dict[str, list[str]]:
    """A spanning tree of the aggregate from its root, breadth first; what it doesn't reach hangs off the root."""
    held = set(members)
    tree: dict[str, list[str]] = {class_: [] for class_ in members}
    seen = {head}
    queue = deque([head])
    while queue:
        current = queue.popleft()
        for class_ in members:
            if class_ not in seen and current in parents[class_]:
                seen.add(class_)
                tree[current].append(class_)
                queue.append(class_)
    tree[head] += [class_ for class_ in members if class_ not in seen and class_ in held]
    return tree


def _subtree(head: str, tree: dict[str, list[str]]) -> list[str]:
    found = [head]
    for child in tree[head]:
        found += _subtree(child, tree)
    return found


def _shed(head: str, members: list[str], parents: dict[str, list[str]]) -> list[Aggregate]:
    """The aggregate, or the aggregate less the largest subtrees that fit, each of those an aggregate."""
    found: list[Aggregate] = []
    while len(members) > MAX_DIAGRAM_NODES:
        tree = _children(head, members, parents)
        sizes = {class_: len(_subtree(class_, tree)) for class_ in members if class_ != head}
        best = max(
            (class_ for class_ in members if sizes.get(class_, MAX_DIAGRAM_NODES + 1) <= MAX_DIAGRAM_NODES),
            key=lambda class_: sizes[class_],
        )
        shed = set(_subtree(best, tree))
        found.append(Aggregate(best, tuple(class_ for class_ in members if class_ in shed)))
        members = [class_ for class_ in members if class_ not in shed]
    return [Aggregate(head, tuple(members)), *found]


def _pack(aggregates: list[Aggregate], links: set[frozenset[str]], root: str | None) -> list[list[Aggregate]]:
    """Diagrams of at most ``MAX_DIAGRAM_NODES`` classes: an aggregate joins the diagram it is most linked to."""
    order = sorted(aggregates, key=lambda aggregate: (aggregate.root != root, -len(aggregate.members)))
    pages: list[list[Aggregate]] = []
    shared: list[int] = []  # the diagrams made for small aggregates that belong to no other
    for aggregate in order:
        room = [
            index
            for index, page in enumerate(pages)
            if _size(page) + len(aggregate.members) <= MAX_DIAGRAM_NODES
        ]
        linked = {index: _linked(pages[index], aggregate, links) for index in room}
        joined = max(
            (index for index in room if linked[index]), key=lambda index: linked[index], default=None
        )
        if joined is None and len(aggregate.members) <= SMALL_AGGREGATE:
            joined = next((index for index in shared if index in room), None)
            if joined is None:
                shared.append(len(pages))
        if joined is None:
            pages.append([aggregate])
        else:
            pages[joined].append(aggregate)
    return pages


def _size(page: list[Aggregate]) -> int:
    return sum(len(aggregate.members) for aggregate in page)


def _linked(page: list[Aggregate], aggregate: Aggregate, links: set[frozenset[str]]) -> int:
    held = {member for other in page for member in other.members}
    return sum(1 for pair in links if len(pair & held) == 1 and len(pair & set(aggregate.members)) == 1)


# --- one diagram


def _quote(text: str) -> str:
    """A D2 double-quoted string."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return '"' + escaped.replace("\n", "\\n") + '"'


def _cell(type_label: str) -> str:
    return type_label if len(type_label) <= MAX_TYPE_CHARS else type_label[: MAX_TYPE_CHARS - 1] + "…"


def _node_class(node: ClassNode, stem_root: str) -> str:
    if node.stereotype:
        return "union"
    return "document" if node.id == stem_root else "owned"


def _table(node: ClassNode, stem_root: str, indent: str) -> list[str]:
    label = f"{node.label}  «{node.stereotype}»" if node.stereotype else node.label
    lines = [f"{indent}{_quote(node.id)}: {{", f"{indent}  class: {_node_class(node, stem_root)}"]
    lines += [f"{indent}  label: {_quote(label)}", f"{indent}  shape: sql_table"]
    for field in node.fields:
        marker = ' { constraint: "req" }' if field.required else ""
        lines.append(f"{indent}  {_quote(field.name)}: {_quote(_cell(field.type))}{marker}")
    return [*lines, f"{indent}}}"]


def _stub(node: ClassNode, here: Diagram, target: Diagram) -> list[str]:
    label = node.label if node.stem == here.stem else f"{node.label}\n({node.stem})"
    link = posixpath.relpath(f"{target.path}.svg", posixpath.dirname(here.path))
    return [
        f"{_quote(_stub_id(node.id))}: {{",
        "  class: stub",
        f"  label: {_quote(label)}",
        f"  link: {_quote(link)}",
        "}",
    ]


def _stub_id(class_id: str) -> str:
    return f"stub__{class_id}"


def shown_relations(model: DomainModel, owned: set[str]) -> list[Relation]:
    """The relations a diagram draws: those a class it owns holds, and any inheritance one end of which it owns."""
    return [
        relation
        for relation in model.relations
        if relation.source in model.classes
        and relation.target in model.classes
        and (
            relation.source in owned or relation.target in owned
            if relation.kind == "inheritance"
            else relation.source in owned
        )
    ]


def stubs_of(model: DomainModel, diagram: Diagram) -> list[str]:
    """The classes a diagram draws without owning them, in id order."""
    owned = set(diagram.owned)
    ends = {end for relation in shown_relations(model, owned) for end in (relation.source, relation.target)}
    return sorted(ends - owned)


def render_diagram(model: DomainModel, plan: DiagramPlan, diagram: Diagram) -> str:
    """The D2 source of ``diagram``; it imports ``classes.d2`` from the root of the output."""
    depth = diagram.path.count("/")
    owned = set(diagram.owned)
    stem_root = _root_id(diagram.stem)
    lines = [f"...@{'../' * depth}{CLASSES_FILE.removesuffix('.d2')}", "direction: right", ""]
    where: dict[str, str] = {}
    for aggregate in diagram.aggregates:
        boxed = len(aggregate.members) > 1
        prefix = f"{_quote('aggregate__' + aggregate.root)}." if boxed else ""
        where.update({member: f"{prefix}{_quote(member)}" for member in aggregate.members})
        lines += _aggregate_lines(model, aggregate, stem_root, boxed=boxed)
    for stub in stubs_of(model, diagram):
        where[stub] = _quote(_stub_id(stub))
        lines += _stub(model.classes[stub], diagram, plan.home[stub])
    lines += [""]
    lines += _edges(model, shown_relations(model, owned), where)
    return "\n".join(lines) + "\n"


def _aggregate_lines(model: DomainModel, aggregate: Aggregate, stem_root: str, *, boxed: bool) -> list[str]:
    nodes = [model.classes[member] for member in aggregate.members]
    if not boxed:
        return [line for node in nodes for line in _table(node, stem_root, "")]
    head = model.classes[aggregate.root]
    lines = [
        f"{_quote('aggregate__' + aggregate.root)}: {{",
        "  class: aggregate",
        f"  label: {_quote(head.label)}",
    ]
    lines += [line for node in nodes for line in _table(node, stem_root, "  ")]
    return [*lines, "}"]


def _edges(model: DomainModel, relations: list[Relation], where: dict[str, str]) -> list[str]:
    """One edge per inheritance, and one per pair of classes and kind of relation between them.

    The edge of several fields lists them under their cardinality: ``a, b [1]`` and ``c [0..1]``.
    """
    lines = []
    held: dict[tuple[str, str, str], list[Relation]] = {}
    for relation in relations:
        if relation.kind == "inheritance":
            lines.append(f"{where[relation.target]} -> {where[relation.source]}: {{ class: inheritance }}")
        else:
            held.setdefault((relation.source, relation.target, relation.kind), []).append(relation)
    for (source, target, kind), group in held.items():
        start = where[source]
        if len(group) == 1 and any(field.name == group[0].label for field in model.classes[source].fields):
            start = f"{start}.{_quote(group[0].label)}"
        lines.append(f"{start} -> {where[target]}: {_quote(_edge_label(group))} {{ class: {kind} }}")
    return lines


def _edge_label(group: list[Relation]) -> str:
    """The fields of a group of relations, under each cardinality in turn."""
    names: dict[str, list[str]] = {}
    for relation in group:
        names.setdefault(relation.cardinality, []).append(relation.label)
    return "\n".join(f"{', '.join(fields)} [{cardinality}]" for cardinality, fields in names.items())


# --- the overview


def overview_nodes(model: DomainModel, refs: Counter[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """The documents and the libraries of the overview: record contracts that hold a document, and those that don't."""
    prefix = f"{OVERVIEW_GROUP}/"
    documents = [stem for stem in model.document_stems if stem.startswith(prefix)]
    libraries = sorted({end for pair in refs for end in pair if end.startswith(prefix)} - set(documents))
    return documents, libraries


def render_overview(model: DomainModel, plan: DiagramPlan, refs: Counter[tuple[str, str]]) -> str:
    """The D2 source of the overview: documents and libraries, an edge per pair, labelled by its ``$ref`` count."""
    documents, libraries = overview_nodes(model, refs)
    shown = set(documents) | set(libraries)
    lines = [f"...@{CLASSES_FILE.removesuffix('.d2')}", "direction: right", ""]
    for stem, kind in [(stem, "document") for stem in documents] + [(stem, "library") for stem in libraries]:
        link = f"{plan.diagrams[stem][0].path}.svg"
        lines += [
            f"{_quote(stem)}: {{",
            f"  class: overview_{kind}",
            f"  label: {_quote(stem.rsplit('/', 1)[-1])}",
            f"  link: {_quote(link)}",
            "}",
        ]
    lines.append("")
    for (source, target), count in sorted(refs.items()):
        if source in shown and target in shown:
            lines.append(
                f"{_quote(source)} -> {_quote(target)}: {_quote(f'{count} refs')} {{ class: reference }}"
            )
    return "\n".join(lines) + "\n"
