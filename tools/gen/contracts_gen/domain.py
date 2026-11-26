"""The domain model: the classes of the published contracts and how they refer to one another.

``build_model`` reads the published schemas the other generators read and returns the classes, one per
contract root, named ``$defs`` object or union, and per inline object, with their relations. It reads nothing
else: a new contract or definition shows up in the diagrams without a change here. ``domain_render`` writes
the Mermaid.

Relations, from the property that holds the reference:

- composition: a nested object, inline or a ``$ref`` to a definition of the same contract;
- association: a ``$ref`` to a definition of another contract;
- inheritance: a union (``oneOf`` or ``anyOf``) of objects, and an ``allOf`` with a ``$ref``. A union whose
  branches all carry a ``const`` under one property name is a discriminated union: an abstract parent with
  one subclass per branch.

Cardinality at the referenced end comes from the property: an array gives ``*`` for ``items``, ``minItems``
of 1 or more or a required property gives a lower bound of 1, and a nullable or alternative one gives 0.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field, replace
from typing import Any

from .sources import SCHEMA_SUFFIX, Contract, ContractSourceError

MAX_ENUM_VALUES = 6
"""An enum is written out in a type label only up to this many values."""

_Ref = tuple[str, str | None]
"""A contract stem and a definition name, or ``None`` for the contract's root."""

_NULL = {"type": "null"}
_TYPE_KEYWORDS = ("$ref", "type", "const", "enum", "properties", "allOf", "oneOf", "anyOf", "items")
_DISCRIMINATOR_NAMES = ("kind", "type", "status")
_MEMBER_TRANSLATION = str.maketrans(
    {"(": "[", ")": "]", "<": "[", ">": "]", "{": "[", "}": "]", '"': "'", "~": "-", "`": "'"}
)


@dataclass
class ClassNode:
    """One class: a contract root, a named ``$defs`` object or union, an inline object, or a union branch."""

    id: str
    label: str
    stem: str
    """The contract it is defined in, e.g. ``record/assembly``."""
    stereotype: str = ""
    """``abstract`` for a discriminated union, ``union`` for another union, or empty."""
    members: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Relation:
    source: str
    target: str
    kind: str
    """``composition``, ``association`` or ``inheritance``; an inheritance runs from parent to child."""
    label: str = ""
    cardinality: str = ""


@dataclass
class DomainModel:
    classes: dict[str, ClassNode]
    relations: list[Relation]
    document_stems: list[str]
    """Contracts whose root is a class, in schema order."""


@dataclass(frozen=True)
class _Cursor:
    """Where a schema sits: the contract it is read in, and the id and label of the class that owns it."""

    stem: str
    id: str
    label: str

    def child(self, name: str) -> _Cursor:
        return _Cursor(self.stem, f"{self.id}__{_identifier(name)}", f"{self.label}.{name}")


@dataclass(frozen=True)
class _Hold:
    """How a property holds what it refers to."""

    many: bool = False
    """Inside an array."""
    min_items: int = 0
    alternative: bool = False
    """One of several branches, or nullable: the reference may be absent whatever the property requires."""


@dataclass(frozen=True)
class _Target:
    id: str
    kind: str
    hold: _Hold


def class_id(stem: str, name: str | None) -> str:
    base = _identifier(stem)
    return base if name is None else f"{base}__{_identifier(name)}"


def _identifier(text: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in text)


def _carries_type(schema: Any) -> bool:
    """False for a branch that only states a condition, such as ``{"required": ["x"]}``."""
    return schema is True or (isinstance(schema, dict) and any(key in schema for key in _TYPE_KEYWORDS))


def _branches(schema: dict[str, Any]) -> list[Any]:
    """The typed branches of a ``oneOf`` or ``anyOf``, a ``null`` branch included."""
    return [
        branch
        for keyword in ("oneOf", "anyOf")
        for branch in schema.get(keyword, [])
        if _carries_type(branch)
    ]


def _is_alias(schema: Any) -> bool:
    keywords = ("properties", "allOf", "oneOf", "anyOf", "type", "enum", "const")
    return isinstance(schema, dict) and "$ref" in schema and not any(key in schema for key in keywords)


def _const_of(prop: Any) -> Any:
    return prop.get("const") if isinstance(prop, dict) else None


def _discriminator_rank(name: str) -> int:
    """Conventional discriminator names first, the other names in schema order."""
    return _DISCRIMINATOR_NAMES.index(name) if name in _DISCRIMINATOR_NAMES else len(_DISCRIMINATOR_NAMES)


def _safe(text: str) -> str:
    """A Mermaid class member can't hold these: they read as a method, a generic, a type or markup."""
    return text.translate(_MEMBER_TRANSLATION)


def _enum_label(values: list[Any]) -> str:
    return "enum " + "|".join(str(value) for value in values) if len(values) <= MAX_ENUM_VALUES else "enum"


class _Registry:
    """The published schemas, with ``$ref`` resolution and the kind of each schema."""

    def __init__(self, contracts: list[Contract]) -> None:
        self.contracts = {contract.stem: contract for contract in contracts}

    def resolve(self, stem: str, ref: str) -> _Ref:
        """The contract and definition a ``$ref`` read in ``stem`` points at."""
        target, _, fragment = ref.partition("#")
        if target:
            joined = posixpath.normpath(posixpath.join(posixpath.dirname(stem), target))
            stem = joined.removesuffix(SCHEMA_SUFFIX)
        if stem not in self.contracts:
            raise ContractSourceError(f"$ref {ref!r} read in {stem}: no such contract")
        if not fragment:
            return stem, None
        prefix = "/$defs/"
        name = fragment.removeprefix(prefix) if fragment.startswith(prefix) else fragment
        resolved = stem, name
        try:
            self.schema_of(resolved)
        except (KeyError, IndexError, TypeError) as error:
            raise ContractSourceError(f"$ref {ref!r} in {stem} doesn't resolve") from error
        return resolved

    def schema_of(self, target: _Ref) -> Any:
        """The schema at a resolved ref: a ``$defs`` entry by name, or any other JSON Pointer as written."""
        node: Any = self.contracts[target[0]].schema
        if target[1] is None:
            return node
        if not target[1].startswith("/"):
            return node["$defs"][target[1]]
        for part in target[1].split("/")[1:]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node

    def final(self, stem: str, ref: str) -> _Ref:
        """The definition a ``$ref`` ends at, through aliases such as ``{"$ref": "#/$defs/other"}``."""
        seen: set[_Ref] = set()
        target = self.resolve(stem, ref)
        while _is_alias(schema := self.schema_of(target)) and target not in seen:
            seen.add(target)
            target = self.resolve(target[0], schema["$ref"])
        return target

    def kind(self, stem: str, schema: Any, seen: frozenset[_Ref] = frozenset()) -> str | None:
        """``object`` for a schema with properties, ``union`` for a union of such, else ``None``."""
        if not isinstance(schema, dict):
            return None
        if "$ref" in schema:
            target = self.final(stem, schema["$ref"])
            if target in seen:
                return None
            return self.kind(target[0], self.schema_of(target), seen | {target})
        members = schema.get("allOf", ())
        if "properties" in schema or any(self.kind(stem, m, seen) == "object" for m in members):
            return "object"
        branches = [branch for branch in _branches(schema) if branch != _NULL]
        if branches and all(self.kind(stem, branch, seen) for branch in branches):
            return "union"
        return None

    def effective_properties(self, stem: str, schema: Any) -> dict[str, Any]:
        """The properties of a schema with those of its ``$ref`` and ``allOf`` members."""
        if not isinstance(schema, dict):
            return {}
        found: dict[str, Any] = {}
        if "$ref" in schema:
            target = self.final(stem, schema["$ref"])
            found.update(self.effective_properties(target[0], self.schema_of(target)))
        for member in schema.get("allOf", []):
            found.update(self.effective_properties(stem, member))
        found.update(schema.get("properties", {}))
        return found

    def discriminator(self, stem: str, branches: list[Any]) -> tuple[str, list[str]] | None:
        """The property every branch fixes with a ``const``, and its value in each branch."""
        props = [self.effective_properties(stem, branch) for branch in branches]
        if len(props) < 2:
            return None
        names = [name for name in props[0] if all(_const_of(found.get(name)) is not None for found in props)]
        for name in sorted(names, key=_discriminator_rank):
            values = [str(_const_of(found[name])) for found in props]
            if len(set(values)) == len(values):
                return name, values
        return None

    def type_label(self, stem: str, schema: Any) -> str:
        """The type of a property as a short phrase: ``string``, ``enum a|b``, ``part_ref[]``, ``A or B``."""
        if schema is True or schema == {} or not isinstance(schema, dict):
            return "any"
        if "$ref" in schema:
            return self._ref_label(stem, schema["$ref"])
        if "const" in schema:
            return f"const {schema['const']}"
        if "enum" in schema:
            return _enum_label(schema["enum"])
        for keyword, joiner in (("oneOf", " or "), ("anyOf", " or "), ("allOf", " and ")):
            branches = [b for b in schema.get(keyword, []) if _carries_type(b)]
            labels = [self.type_label(stem, branch) for branch in branches]
            labels = [label for label in labels if label != "any"] if keyword == "allOf" else labels
            if labels:
                return joiner.join(dict.fromkeys(labels))
        return self._plain_label(stem, schema)

    def _plain_label(self, stem: str, schema: dict[str, Any]) -> str:
        types = schema["type"] if isinstance(schema.get("type"), list) else [schema.get("type", "any")]
        return " or ".join(
            f"{self.type_label(stem, schema.get('items', True))}[]" if name == "array" else str(name)
            for name in types
        )

    def ref_name(self, target: _Ref) -> str:
        """A definition's name, the last key of any other pointer, or a contract's file name for its root."""
        if target[1] is None:
            return target[0].rsplit("/", 1)[-1]
        return target[1].rsplit("/", 1)[-1]

    def _ref_label(self, stem: str, ref: str) -> str:
        target = self.final(stem, ref)
        schema = self.schema_of(target)
        name = self.ref_name(target)
        if isinstance(schema, dict) and "enum" in schema and len(schema["enum"]) <= MAX_ENUM_VALUES:
            return f"{name} = {'|'.join(str(value) for value in schema['enum'])}"
        return name


class _Builder:
    def __init__(self, contracts: list[Contract]) -> None:
        self.registry = _Registry(contracts)
        self.classes: dict[str, ClassNode] = {}
        self.relations: list[Relation] = []
        self.document_stems: list[str] = []

    def build(self) -> DomainModel:
        for stem, contract in self.registry.contracts.items():
            root = _Cursor(stem, class_id(stem, None), stem.rsplit("/", 1)[-1])
            if self.registry.kind(stem, contract.schema):
                self.document_stems.append(stem)
                self._define(root, contract.schema)
            for name, schema in contract.schema.get("$defs", {}).items():
                self._build_definition(_Cursor(stem, class_id(stem, name), name), schema)
        return DomainModel(self.classes, list(dict.fromkeys(self.relations)), self.document_stems)

    def _build_definition(self, cursor: _Cursor, schema: Any) -> None:
        if _is_alias(schema):
            return
        if self.registry.kind(cursor.stem, schema):
            self._define(cursor, schema)
        else:
            self._targets(cursor, schema, _Hold())  # the inline objects of a definition that isn't a class

    # --- classes

    def _define(self, cursor: _Cursor, schema: dict[str, Any]) -> str:
        if cursor.id not in self.classes:
            node = ClassNode(cursor.id, cursor.label, cursor.stem)
            self.classes[cursor.id] = node
            if self.registry.kind(cursor.stem, schema) == "object":
                self._define_object(cursor, schema, node)
            else:
                self._define_union(cursor, schema, node)
        return cursor.id

    def _define_object(self, cursor: _Cursor, schema: dict[str, Any], node: ClassNode) -> None:
        properties: dict[str, Any] = dict(schema.get("properties", {}))
        required = set(schema.get("required", []))
        for part in schema.get("allOf", []):
            if "$ref" in part:
                parent = self._class_of(cursor.stem, part["$ref"])
                if parent:
                    self.relations.append(Relation(parent, cursor.id, "inheritance"))
                continue
            properties.update(part.get("properties", {}))
            required |= set(part.get("required", []))
        for name, prop in properties.items():
            self._member(cursor, node, name, prop, name in required)
        self._define_variants(cursor, schema, node)

    def _define_union(self, cursor: _Cursor, schema: dict[str, Any], node: ClassNode) -> None:
        self._define_variants(cursor, schema, node)

    def _define_variants(self, cursor: _Cursor, schema: dict[str, Any], node: ClassNode) -> None:
        """The branches of a ``oneOf`` or ``anyOf`` that are classes: the schema is their parent."""
        branches = [branch for branch in _branches(schema) if branch != _NULL]
        if not branches or not all(self.registry.kind(cursor.stem, branch) for branch in branches):
            return
        found = self.registry.discriminator(cursor.stem, branches)
        node.stereotype = "abstract" if found else "union"
        if found and not any(member.startswith(f"{found[0]}") for member in node.members):
            node.members.append(f"{found[0]}: discriminator")
        for index, branch in enumerate(branches):
            child = self._branch(cursor, branch, found[1][index] if found else str(index + 1))
            self.relations.append(Relation(cursor.id, child, "inheritance"))

    def _class_for(self, target: _Ref) -> str | None:
        """The class at a resolved ref, defined now if it isn't yet (a pointer outside ``$defs``), or None."""
        schema = self.registry.schema_of(target)
        if not self.registry.kind(target[0], schema):
            return None
        return self._define(_Cursor(target[0], class_id(*target), self.registry.ref_name(target)), schema)

    def _branch(self, cursor: _Cursor, branch: dict[str, Any], name: str) -> str:
        if "$ref" in branch:
            return self._class_for(self.registry.final(cursor.stem, branch["$ref"])) or ""
        return self._define(cursor.child(name), branch)

    def _class_of(self, stem: str, ref: str) -> str | None:
        return self._class_for(self.registry.final(stem, ref))

    # --- properties

    def _member(self, cursor: _Cursor, node: ClassNode, name: str, prop: Any, required: bool) -> None:
        label = self.registry.type_label(cursor.stem, prop)
        node.members.append(_safe(f"{name}{'' if required else '?'}: {label}"))
        for target in self._targets(cursor.child(name), prop, _Hold()):
            hold = target.hold
            lower = int(required and not hold.alternative and (not hold.many or hold.min_items > 0))
            bounds = f"{lower}..{'*' if hold.many else 1}"
            cardinality = "1" if bounds == "1..1" else bounds
            self.relations.append(Relation(cursor.id, target.id, target.kind, name, cardinality))

    def _targets(self, cursor: _Cursor, schema: Any, hold: _Hold) -> list[_Target]:
        """The classes a property's schema refers to, with how each is held."""
        if not isinstance(schema, dict):
            return []
        if "$ref" in schema:
            return self._ref_targets(cursor, schema["$ref"], hold)
        if self.registry.kind(cursor.stem, schema):
            return [_Target(self._define(cursor, schema), "composition", hold)]
        if "items" in schema:
            many = replace(hold, many=True, min_items=schema.get("minItems", 0))
            return self._targets(cursor, schema["items"], many)
        branches = _branches(schema)
        if len(branches) > 1:
            hold = replace(hold, alternative=True)
        found: list[_Target] = []
        for index, branch in enumerate(branches):
            site = cursor.child(str(index + 1)) if len(branches) > 1 else cursor
            found += self._targets(site, branch, hold)
        for member in schema.get("allOf", []):
            found += self._targets(cursor, member, hold)
        return found

    def _ref_targets(self, cursor: _Cursor, ref: str, hold: _Hold) -> list[_Target]:
        target = self.registry.final(cursor.stem, ref)
        schema = self.registry.schema_of(target)
        found_class = self._class_for(target)
        if found_class:
            kind = "composition" if target[0] == cursor.stem else "association"
            return [_Target(found_class, kind, hold)]
        # A definition that isn't a class, an array or a union of mixed types, may still hold classes.
        inner = _Cursor(target[0], class_id(*target), self.registry.ref_name(target))
        return [
            replace(found, kind="composition" if target[0] == cursor.stem else "association")
            for found in self._targets(inner, schema, hold)
        ]


def build_model(contracts: list[Contract]) -> DomainModel:
    """Every class and relation of the published ``contracts``."""
    return _Builder(contracts).build()
