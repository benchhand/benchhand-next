"""``docs/contract/generated/domain-model.md``: Mermaid class diagrams of the domain model (``domain.py``)."""

from __future__ import annotations

from collections import Counter

from .domain import MAX_ENUM_VALUES, ClassNode, DomainModel, Relation, build_model, class_id
from .sources import GENERATED_NOTICE, Contract

DOMAIN_MODEL_FILE = "domain-model.md"
MAX_DIAGRAM_CLASSES = 40
"""A group with more classes than this is split by document, one diagram each."""
DOCUMENT_GROUP = "record"
"""The contract directory whose documents the overview shows."""

_ARROWS = {
    "composition": '{source} "1" *-- "{cardinality}" {target} : {label}',
    "association": '{source} --> "{cardinality}" {target} : {label}',
    "inheritance": "{source} <|-- {target}",
}


def render_domain_model(contracts: list[Contract]) -> str:
    model = build_model(contracts)
    lines = ["# Domain model", "", f"{GENERATED_NOTICE} Source: the published schemas of `contracts/`.", ""]
    lines += _legend()
    lines += _overview(model)
    for group, stems in _groups(model).items():
        lines += _group_section(model, group, stems)
    return "\n".join(lines).rstrip("\n") + "\n"


def class_counts(model: DomainModel) -> Counter[str]:
    """Classes per contract stem."""
    return Counter(node.stem for node in model.classes.values())


def _legend() -> list[str]:
    return [
        "Each class is a contract root, a named `$defs` object or union, or an object written inline; "
        "a class named `a.b` is the inline object of property `b` of `a`. A member is `name: type`, with "
        "`?` after the name of an optional property, and an enum's values are written out when it has "
        f"{MAX_ENUM_VALUES} or fewer.",
        "",
        '- `A "1" *-- "0..*" B`: composition, B is nested in A (inline, or a `$ref` in the same contract).',
        '- `A --> "0..1" B`: association, a `$ref` from A to a definition of another contract.',
        "- `A <|-- B`: B is a branch of the union A, or extends A with `allOf`. A union whose branches each "
        "fix one property with a `const` is `<<abstract>>`, with one subclass per value; any other union is "
        "`<<union>>`.",
        "- The number at B is how many B an A holds: `1..*` is an array with at least one, `0..*` an "
        "array that may be empty or absent, `0..1` an optional, nullable or alternative one.",
        "- `<<external>>` is a class of another document, shown so that a relation has both ends.",
        "",
    ]


def _groups(model: DomainModel) -> dict[str, list[str]]:
    """Contract stems by directory, for the stems that own at least one class."""
    groups: dict[str, list[str]] = {}
    for stem in sorted(class_counts(model)):
        groups.setdefault(stem.split("/")[0], []).append(stem)
    return groups


def _group_section(model: DomainModel, group: str, stems: list[str]) -> list[str]:
    counts = class_counts(model)
    total = sum(counts[stem] for stem in stems)
    lines = [f"## `{group}`", ""]
    if total <= MAX_DIAGRAM_CLASSES:
        lines += [f"{total} classes, from {', '.join(f'`{stem}`' for stem in stems)}.", ""]
        lines += _block(model, _owned(model, stems))
        return lines
    lines += [f"{total} classes, more than {MAX_DIAGRAM_CLASSES}, so there is one diagram per document.", ""]
    for stem in stems:
        lines += [f"### `{stem}`", "", f"{counts[stem]} classes.", ""]
        lines += _block(model, _owned(model, [stem]))
    return lines


def _owned(model: DomainModel, stems: list[str]) -> list[str]:
    return [node.id for node in model.classes.values() if node.stem in stems]


def _block(model: DomainModel, classes: list[str]) -> list[str]:
    return ["```mermaid", *_class_diagram(model, classes), "```", ""]


# --- one class diagram


def _class_diagram(model: DomainModel, classes: list[str]) -> list[str]:
    """The diagram of ``classes``, with the classes they refer to that aren't among them as externals."""
    owned = set(classes)
    relations = [rel for rel in model.relations if _shown(rel, owned)]
    stubs = sorted({end for rel in relations for end in (rel.source, rel.target)} - owned)
    labels = _labels(model, classes, stubs)
    lines = ["classDiagram"]
    for class_ in classes:
        lines += _class_lines(model.classes[class_], labels[class_])
    for stub in stubs:
        lines += _class_lines(model.classes[stub], labels[stub], external=True)
    lines += ["    " + _relation_line(rel) for rel in relations]
    return lines


def _shown(relation: Relation, owned: set[str]) -> bool:
    """A relation is drawn from the class that holds it; a parent outside the diagram is drawn too."""
    if relation.kind == "inheritance":
        return relation.source in owned or relation.target in owned
    return relation.source in owned


def _labels(model: DomainModel, owned: list[str], stubs: list[str]) -> dict[str, str]:
    """A class's label, qualified by its contract where two classes of the diagram would share one."""
    labels = {class_: model.classes[class_].label for class_ in owned}
    shared = {label for label, count in Counter(labels.values()).items() if count > 1}
    labels = {
        class_: f"{model.classes[class_].stem.split('/')[-1]}.{label}" if label in shared else label
        for class_, label in labels.items()
    }
    for stub in stubs:
        labels[stub] = f"{model.classes[stub].stem}.{model.classes[stub].label}"
    return labels


def _class_lines(node: ClassNode, label: str, *, external: bool = False) -> list[str]:
    stereotype = "external" if external else node.stereotype
    body = ([f"<<{stereotype}>>"] if stereotype else []) + ([] if external else node.members)
    header = f'    class {node.id}["{label}"]'
    if not body:
        return [header]
    return [f"{header} {{", *(f"        {line}" for line in body), "    }"]


def _relation_line(relation: Relation) -> str:
    template = _ARROWS[relation.kind]
    return template.format(
        source=relation.source,
        target=relation.target,
        cardinality=relation.cardinality,
        label=relation.label,
    )


# --- the overview


def _overview(model: DomainModel) -> list[str]:
    documents = [stem for stem in model.document_stems if stem.startswith(f"{DOCUMENT_GROUP}/")]
    roots = {stem: _root_id(stem) for stem in documents}
    uses = Counter(
        (model.classes[rel.source].stem, model.classes[rel.target].stem)
        for rel in model.relations
        if rel.kind != "inheritance"
    )
    libraries = sorted(
        {
            target
            for (source, target) in uses
            if source in roots and target.startswith(f"{DOCUMENT_GROUP}/") and target not in roots
        }
    )
    lines = [
        "## Overview: the record documents",
        "",
        f"{len(documents)} documents of the record, with their top-level properties. An arrow is a `$ref` "
        "from anywhere in the document, counted; the libraries are contracts that hold shared definitions "
        "and no document of their own.",
        "",
        "```mermaid",
        "classDiagram",
    ]
    for stem in documents:
        node = model.classes[roots[stem]]
        lines += _class_lines(ClassNode(node.id, node.label, stem, "document", node.members), node.label)
    for stem in libraries:
        lines += [f'    class {_root_id(stem)}["{stem.split("/")[-1]}"] {{', "        <<library>>", "    }"]
    for (source, target), count in sorted(uses.items()):
        if source in roots and (target in roots or target in libraries) and source != target:
            lines.append(f"    {roots[source]} --> {_root_id(target)} : {count} refs")
    lines += ["```", ""]
    return lines


def _root_id(stem: str) -> str:
    return class_id(stem, None)
