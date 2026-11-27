"""The domain model: the classes of the published contracts and how they refer to one another.

``build_model`` reads the published schemas the other generators read and returns the classes, one per
contract root, named ``$defs`` object or union, and per inline object, with their relations. It reads nothing
else: a new contract or definition shows up in the diagrams without a change here. ``domain_d2`` lays the
classes out and ``domain_docs`` writes the pages.

Relations, from the property that holds the reference:

- composition: a nested object, inline or a ``$ref`` to a definition of the same contract;
- association: a ``$ref`` to a definition of another contract;
- inheritance: a union (``oneOf`` or ``anyOf``) of objects, and an ``allOf`` with a ``$ref``. A union whose
  branches all carry a ``const`` under one property name is a discriminated union: an abstract parent with
  one subclass per branch.

Cardinality at the referenced end comes from the property. Array bounds (``minItems``, ``maxItems``) and map
bounds (``minProperties``, ``maxProperties`` of an ``additionalProperties`` value) multiply through nested
arrays and maps; a required single property gives 1, and an optional, nullable or alternative one a lower
bound of 0.
"""

from __future__ import annotations

import json
import posixpath
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from .sources import SCHEMA_SUFFIX, Contract, ContractSourceError

MAX_ENUM_VALUES = 6
"""An enum is written out in a type label only up to this many values."""

_Ref = tuple[str, str | None]
"""A contract stem and a definition name, or ``None`` for the contract's root."""

_NULL = {"type": "null"}
_TYPE_KEYWORDS = (
    "$ref",
    "type",
    "const",
    "enum",
    "properties",
    "allOf",
    "oneOf",
    "anyOf",
    "items",
    "prefixItems",
    "additionalProperties",
)
_JSON_WORDS = ("null", "true", "false")
_DISCRIMINATOR_NAMES = ("kind", "type", "status")


@dataclass(frozen=True)
class Field:
    """One property of a class: its name, the type as a short phrase, and whether the schema requires it."""

    name: str
    type: str
    required: bool
    description: str = ""
    values: tuple[str, ...] = ()
    """The values of an enum property, or of the enum an array property holds, as ``literal`` writes them."""


@dataclass
class ClassNode:
    """One class: a contract root, a named ``$defs`` object or union, an inline object, or a union branch."""

    id: str
    label: str
    stem: str
    """The contract it is defined in, e.g. ``record/assembly``."""
    stereotype: str = ""
    """``abstract`` for a discriminated union, ``union`` for another union, or empty."""
    description: str = ""
    fields: list[Field] = field(default_factory=list)


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
    """How many of what it refers to a property holds: bounds multiplied through arrays and maps."""

    lower: int = 1
    upper: int | None = 1
    """None: no upper bound."""
    alternative: bool = False
    """One of several branches, or nullable: the reference may be absent whatever the property requires."""

    def times(self, low: int, high: int | None) -> _Hold:
        """Inside an array or map of ``low`` to ``high`` elements."""
        upper = None if self.upper is None or high is None else self.upper * high
        return replace(self, lower=self.lower * low, upper=upper)

    def cardinality(self, required: bool) -> str:
        lower = self.lower if required and not self.alternative else 0
        if self.upper is None:
            return f"{lower}..*"
        return str(lower) if lower == self.upper else f"{lower}..{self.upper}"


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


def _nullable(schema: Any) -> bool:
    """A ``null`` branch, or ``null`` in a list of types."""
    if not isinstance(schema, dict):
        return False
    types = schema.get("type")
    return _NULL in _branches(schema) or (isinstance(types, list) and "null" in types)


def _map_values(schema: Any) -> Any:
    """The schema of every value of a map: a schema-valued ``additionalProperties``, else None."""
    if not isinstance(schema, dict):
        return None
    values = schema.get("additionalProperties")
    return values if isinstance(values, dict) and _carries_type(values) else None


def _array_bounds(schema: dict[str, Any]) -> tuple[int, int | None]:
    prefix = schema.get("prefixItems", [])
    closed = "items" not in schema and bool(prefix)
    low = schema.get("minItems", 0)
    high = schema.get("maxItems", len(prefix) if closed else None)
    return low, high


def _bounds_suffix(low: int, high: int | None) -> str:
    """``[]`` for any number, ``[2]`` for exactly two, ``[1..*]`` or ``[2..4]`` for a range."""
    if high is None:
        return "[]" if low == 0 else f"[{low}..*]"
    return f"[{low}]" if low == high else f"[{low}..{high}]"


def literal(value: Any) -> str:
    """A JSON value as written in a type label: a string bare, unless it reads as another JSON value."""
    if isinstance(value, str):
        try:
            json.loads(value)
        except ValueError:
            return value
        return json.dumps(value)
    return json.dumps(value)


def _is_alias(schema: Any) -> bool:
    keywords = ("properties", "allOf", "oneOf", "anyOf", "type", "enum", "const")
    return isinstance(schema, dict) and "$ref" in schema and not any(key in schema for key in keywords)


def _const_of(prop: Any) -> Any:
    return prop.get("const") if isinstance(prop, dict) else None


def _discriminator_rank(name: str) -> int:
    """Conventional discriminator names first, the other names in schema order."""
    return _DISCRIMINATOR_NAMES.index(name) if name in _DISCRIMINATOR_NAMES else len(_DISCRIMINATOR_NAMES)


def _enum_values(prop: Any) -> tuple[str, ...]:
    """The values of the enum ``prop`` is, or that its array items are."""
    if not isinstance(prop, dict):
        return ()
    if "enum" in prop:
        return tuple(literal(value) for value in prop["enum"])
    return _enum_values(prop.get("items"))


def _enum_label(values: list[Any]) -> str:
    if len(values) > MAX_ENUM_VALUES:
        return "enum"
    return "enum " + "|".join(literal(value) for value in values)


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
        if len(branches) > 1 and all(self.kind(stem, branch, seen) for branch in branches):
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

    def effective_required(self, stem: str, schema: Any, seen: frozenset[_Ref] = frozenset()) -> set[str]:
        """The property names a schema requires, with those of its ``$ref`` and ``allOf`` members."""
        if not isinstance(schema, dict):
            return set()
        found: set[str] = set()
        if "$ref" in schema:
            target = self.final(stem, schema["$ref"])
            if target not in seen:
                found |= self.effective_required(target[0], self.schema_of(target), seen | {target})
        for member in schema.get("allOf", []):
            found |= self.effective_required(stem, member, seen)
        return found | set(schema.get("required", []))

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
            return f"const {literal(schema['const'])}"
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
        if _map_values(schema) is not None and "properties" not in schema:
            values = f"{self.type_label(stem, _map_values(schema))} by key"
            return " or ".join(values if name == "object" else str(name) for name in types)
        return " or ".join(
            self._array_label(stem, schema) if name == "array" else str(name) for name in types
        )

    def _array_label(self, stem: str, schema: dict[str, Any]) -> str:
        """``T[]`` with its bounds, or a tuple ``[A, B]``; a nested array keeps its own level."""
        prefix = schema.get("prefixItems")
        if prefix:
            element = "[" + ", ".join(self.type_label(stem, item) for item in prefix) + "]"
            closed = "items" not in schema or schema["items"] is False
            low, high = _array_bounds(schema)
            if closed and low == high == len(prefix):
                return element
            return f"{element}{_bounds_suffix(low, high)}"
        return f"{self.type_label(stem, schema.get('items', True))}{_bounds_suffix(*_array_bounds(schema))}"

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
            return f"{name} = {'|'.join(literal(value) for value in schema['enum'])}"
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
            node = ClassNode(cursor.id, cursor.label, cursor.stem, description=schema.get("description", ""))
            self.classes[cursor.id] = node
            if self.registry.kind(cursor.stem, schema) == "object":
                self._define_object(cursor, schema, node)
            else:
                self._define_union(cursor, schema, node)
        return cursor.id

    def _define_object(self, cursor: _Cursor, schema: dict[str, Any], node: ClassNode) -> None:
        properties: dict[str, Any] = dict(schema.get("properties", {}))
        required = set(schema.get("required", []))
        inherited: set[str] = set()
        for part in schema.get("allOf", []):
            if "$ref" in part:
                parent = self._class_of(cursor.stem, part["$ref"])
                if parent:
                    self.relations.append(Relation(parent, cursor.id, "inheritance"))
                inherited |= self.registry.effective_required(cursor.stem, part)
                continue
            properties.update(part.get("properties", {}))
            required |= set(part.get("required", []))
        required |= inherited  # a property this class redeclares stays as required as its parent has it
        for name, prop in properties.items():
            self._member(cursor, node, name, prop, name in required)
        values = _map_values(schema)
        if values is not None:  # the other keys of an object with named properties too
            key_type = self.registry.type_label(cursor.stem, values)
            node.fields.append(Field("[key]", key_type, required=False))
            for target in self._targets(cursor.child("key"), values, _Hold().times(0, None)):
                cardinality = target.hold.cardinality(required=False)
                self.relations.append(Relation(cursor.id, target.id, target.kind, "[key]", cardinality))
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
        if found and not any(held.name.startswith(found[0]) for held in node.fields):
            node.fields.append(Field(found[0], "discriminator", required=True))
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
        description = prop.get("description", "") if isinstance(prop, dict) else ""
        node.fields.append(Field(name, label, required, description, _enum_values(prop)))
        for target in self._targets(cursor.child(name), prop, _Hold()):
            cardinality = target.hold.cardinality(required)
            self.relations.append(Relation(cursor.id, target.id, target.kind, name, cardinality))

    def _targets(self, cursor: _Cursor, schema: Any, hold: _Hold) -> list[_Target]:
        """The classes a property's schema refers to, with how each is held."""
        if not isinstance(schema, dict):
            return []
        if _nullable(schema):
            hold = replace(hold, alternative=True)
        if "$ref" in schema:
            return self._ref_targets(cursor, schema["$ref"], hold)
        if self.registry.kind(cursor.stem, schema):
            return [_Target(self._define(cursor, schema), "composition", hold)]
        if "items" in schema or "prefixItems" in schema:
            return self._array_targets(cursor, schema, hold)
        values = _map_values(schema)
        if values is not None:
            within = hold.times(schema.get("minProperties", 0), schema.get("maxProperties"))
            return self._targets(cursor, values, within)
        branches = [branch for branch in _branches(schema) if branch != _NULL]
        if len(branches) > 1:
            hold = replace(hold, alternative=True)
        found: list[_Target] = []
        for index, branch in enumerate(branches):
            site = cursor.child(str(index + 1)) if len(branches) > 1 else cursor
            found += self._targets(site, branch, hold)
        for member in schema.get("allOf", []):
            found += self._targets(cursor, member, hold)
        return found

    def _array_targets(self, cursor: _Cursor, schema: dict[str, Any], hold: _Hold) -> list[_Target]:
        """An array's element classes: a tuple position holds one per array, ``items`` holds the bounds."""
        within = hold.times(*_array_bounds(schema))
        low = _array_bounds(schema)[0]
        found: list[_Target] = []
        for index, item in enumerate(schema.get("prefixItems", [])):  # present when the array is that long
            found += self._targets(cursor.child(str(index + 1)), item, hold.times(int(low > index), 1))
        if isinstance(schema.get("items"), dict):
            found += self._targets(cursor, schema["items"], within)
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


def ref_counts(contracts: list[Contract]) -> Counter[tuple[str, str]]:
    """How many ``$ref``s each contract's schema holds, anywhere in it, to each other contract."""
    registry = _Registry(contracts)
    counts: Counter[tuple[str, str]] = Counter()
    for stem, contract in registry.contracts.items():
        for ref in _refs(contract.schema):
            target = registry.resolve(stem, ref)[0]
            if target != stem:
                counts[stem, target] += 1
    return counts


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return own + [ref for key, value in node.items() if key != "$ref" for ref in _refs(value)]
    if isinstance(node, list):
        return [ref for value in node for ref in _refs(value)]
    return []
