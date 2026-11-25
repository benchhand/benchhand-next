"""Rewrite the JSON Schema bundle that TypeSpec emits into the published per-contract schemas (ADR-0017).

``tsp compile`` writes every declaration of ``contracts/*.tsp`` into one bundle, keyed by its ``$id``. A
namespace's ``@baseUri`` names its contract: ``…/contracts/record/part/`` holds the ``$defs`` of
``record/part.schema.json``, and the declaration whose ``@id`` is ``…/contracts/record/part.schema.json`` is
that contract's root. This module splits the bundle into those files and rewrites the emitter's idioms
into the plain form the generators read. ``x-*`` values, which hold the JSON Schema TypeSpec has no syntax
for, are copied as they are. Each rewrite accepts and rejects the same instances:

- a ``$ref`` to a bundle ``$id`` becomes ``#/$defs/<name>``, or ``<file>#/$defs/<name>`` for another
  contract, relative to the file;
- a declaration marked ``x-inline`` is written in place of each ``$ref`` to it, since TypeSpec can only
  decorate a declaration; a ``$ref`` from another contract points at its place in its own contract;
- a ``$defs`` entry inside a declaration (a template instance such as ``Record<string>``) is inlined;
- ``unevaluatedProperties`` becomes ``additionalProperties`` (``{"not": {}}`` becomes ``false``, ``{}`` is
  dropped). This is exact only when no in-place applicator beside it names a property the object
  doesn't list, so any other case is refused;
- an ``anyOf`` of plain types becomes a ``type`` list, an ``anyOf`` of literals (and ``null``) an ``enum``,
  and a one-branch ``anyOf`` of a ``$ref`` or ``{}`` its branch;
- ``type`` beside a ``const`` of that type, ``items: {}`` and ``properties: {}`` are dropped;
- a property whose schema is ``{}`` (``unknown``) gets ``true``: datamodel-code-generator types ``{}`` as
  ``Any`` even where an ``allOf`` branch narrows it, but takes the branch's type over ``true``.

The keywords of every schema are then put in ``KEYWORD_ORDER``. Python's validator reports the first of
two errors at the same place in the instance in the order of their keywords, so the order decides which
violation ``benchhand_contracts.validate`` raises; a fixed order keeps it from depending on how the
emitter happened to write a schema. ``@extension("x-keyword-order", #[...])`` lists keywords that take
each other's places in another order: on a contract's namespace for each of its schemas, on a declaration
or a property for that schema alone. ``x-required-order`` puts a ``required`` list, which the emitter writes
in property order, in the order the validator should report missing properties in.
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

BASE_URI = "https://benchhand.github.io/benchhand/contracts/"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_SUFFIX = ".schema.json"
INLINE = "x-inline"
_HOME = "x-inline-home"
"""A temporary marker on an inlined helper, so that its JSON pointer can be found once the file is final."""
_ELSEWHERE = "x-inline-elsewhere"
"""A temporary ``$ref`` value: the ``$id`` of another file's inlined helper, before its pointer is known."""
DATA_KEYWORDS = frozenset(("const", "enum", "examples", "default", "required", "dependentRequired"))
MAX_REF_DEPTH = 16
SCHEMA_MAPS = frozenset(("properties", "patternProperties", "$defs", "dependentSchemas"))
JSON_TYPES = {"string": str, "boolean": bool, "null": type(None)}
KEYWORD_ORDER_KEY = "x-keyword-order"
REQUIRED_ORDER_KEY = "x-required-order"
_EXTENSIONS = "x-*"
KEYWORD_ORDER = (
    *("$schema", "$id", "title", "description", "$comment", _EXTENSIONS, "type"),
    *("additionalProperties", "minProperties", "maxProperties", "propertyNames", "required"),
    *("dependentRequired", "properties", "patternProperties"),
    *("minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains"),
    *("items", "prefixItems"),
    *("minLength", "maxLength", "pattern", "format"),
    *("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum", "multipleOf"),
    *("const", "enum", "$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependentSchemas"),
    *("default", "examples", "$defs"),
)
"""The order of the keywords in a published schema: the hand-written contracts' order, where they agreed.
A keyword not listed here comes last."""
_RANK = {keyword: index for index, keyword in enumerate(KEYWORD_ORDER)}


class NormaliseError(Exception):
    """The bundle uses a form this module can't rewrite exactly."""


@dataclass
class _Declaration:
    rel_path: str
    """The contract, e.g. ``record/part.schema.json``."""
    name: str | None
    """The ``$defs`` name, or ``None`` for the contract's root."""
    schema: dict[str, Any]

    @property
    def inline(self) -> bool:
        return self.schema.get(INLINE) is True


@dataclass
class _Contract:
    rel_path: str
    root: dict[str, Any] | None = None
    defs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Source:
    """What the TypeSpec compiler reports about the source (``contracts/scripts/declarations.mjs``)."""

    ids: Sequence[str]
    """The ``$id`` of every declaration, in source order. The bundle lists declarations in the order the
    emitter reached them, so the published ``$defs`` take their order from the source instead."""
    keyword_orders: dict[str, list[str]] = field(default_factory=dict)
    """The ``x-keyword-order`` of each contract's namespace, keyed by the contract's path."""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Source:
        orders: dict[str, list[str]] = {}
        for namespace in data["namespaces"]:
            extensions = dict(namespace["extensions"])
            order = extensions.pop(KEYWORD_ORDER_KEY, None)
            if extensions:
                raise NormaliseError(
                    f"{namespace['baseUri']}: the emitter writes no @extension of a namespace, only of a "
                    f"declaration; {', '.join(sorted(extensions))} would be lost"
                )
            if order is not None:
                orders[_locate(f"{namespace['baseUri']}namespace.json")[0]] = _keyword_order(order)
        return cls([declaration["id"] for declaration in data["declarations"]], orders)


def normalise(bundle: dict[str, Any], source: Source) -> dict[str, dict[str, Any]]:
    """The published schema of every contract in ``bundle``, keyed by path below ``contracts/``."""
    declarations = _declarations(bundle)
    contracts = _contracts(declarations, source.ids)
    inlined = {schema_id: d for schema_id, d in declarations.items() if d.inline}
    resolved = {rel: _file(contract, declarations, inlined) for rel, contract in contracts.items()}
    published = {
        rel: _simplify_file(schema, _Scope(rel, resolved), source.keyword_orders.get(rel, []))
        for rel, schema in resolved.items()
    }
    homes = {rel: _take_homes(schema) for rel, schema in published.items()}
    for rel, schema in published.items():
        _point_at_homes(schema, rel, homes)
    for rel, schema in published.items():
        _check_refs(schema, rel, published)
    return published


def _map_subschemas(node: dict[str, Any], change: Any, skip_extensions: bool = False) -> dict[str, Any]:
    """``node`` with ``change`` applied to each value that holds schemas; instance data stays as it is."""
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in DATA_KEYWORDS or (skip_extensions and key.startswith("x-")):
            out[key] = value
        elif key in SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: change(item) for name, item in value.items()}
        else:
            out[key] = change(value)
    return out


def _subschemas(node: dict[str, Any]) -> list[tuple[str, Any]]:
    """``(pointer suffix, value)`` for each value of ``node`` that holds schemas."""
    found: list[tuple[str, Any]] = []
    for key, value in node.items():
        if key in DATA_KEYWORDS:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            found += [(f"/{_escape(key)}/{_escape(name)}", item) for name, item in value.items()]
        else:
            found.append((f"/{_escape(key)}", value))
    return found


# --- splitting the bundle ----------------------------------------------------------------------------------


def _declarations(bundle: dict[str, Any]) -> dict[str, _Declaration]:
    found: dict[str, _Declaration] = {}
    for key, schema in bundle.get("$defs", {}).items():
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            raise NormaliseError(f"bundle entry {key} has no $id")
        if schema_id in found:
            raise NormaliseError(f"two declarations have the $id {schema_id}")
        rel_path, name = _locate(schema_id)
        body = {k: v for k, v in schema.items() if k not in ("$schema", "$id")}
        found[schema_id] = _Declaration(rel_path, name, _inline_local_defs(body, schema_id))
    return found


def _locate(schema_id: str) -> tuple[str, str | None]:
    if not schema_id.startswith(BASE_URI):
        raise NormaliseError(f"{schema_id} is not below {BASE_URI}")
    path = schema_id.removeprefix(BASE_URI)
    if path.endswith(SCHEMA_SUFFIX):
        return path, None
    directory, _, file = path.rpartition("/")
    if not directory or not file.endswith(".json"):
        raise NormaliseError(f"{schema_id} names no contract: expected …/<dir>/<contract>/<name>.json")
    return f"{directory}{SCHEMA_SUFFIX}", file.removesuffix(".json")


def _contracts(declarations: dict[str, _Declaration], order: Sequence[str]) -> dict[str, _Contract]:
    position = {schema_id: index for index, schema_id in enumerate(order)}
    contracts: dict[str, _Contract] = {}
    for schema_id in sorted(declarations, key=lambda i: (position.get(i, len(position)), i)):
        declaration = declarations[schema_id]
        if schema_id not in position:
            raise NormaliseError(f"{schema_id} is in the bundle but not declared in the TypeSpec source")
        contract = contracts.setdefault(declaration.rel_path, _Contract(declaration.rel_path))
        if declaration.name is None:
            contract.root = declaration.schema
        elif not declaration.inline:
            contract.defs[declaration.name] = declaration.schema
    lost = sorted(set(order) - set(declarations))
    if lost:
        raise NormaliseError(
            f"declared in the TypeSpec source but missing from the bundle: {', '.join(lost)}. The emitter "
            "keeps one of two declarations with the same name, so give each a unique name"
        )
    for rel_path, contract in sorted(contracts.items()):
        if contract.root is None:
            raise NormaliseError(f"contract {rel_path} has no root type: give one declaration its @id")
    return dict(sorted(contracts.items()))


def _inline_local_defs(schema: dict[str, Any], schema_id: str) -> dict[str, Any]:
    """Replace each ``#/$defs/<name>`` ref to the declaration's own ``$defs`` with that entry. Instance data
    (``const``, ``enum``, ``examples``, ``default``) and ``x-*`` values are copied as they are."""
    local = schema.pop("$defs", None)
    if not local:
        return schema

    def substitute(node: Any, depth: int) -> Any:
        if depth > 32:
            raise NormaliseError(f"{schema_id}: its local $defs refer to each other in a cycle")
        if isinstance(node, list):
            return [substitute(item, depth) for item in node]
        if not isinstance(node, dict):
            return node
        rest = {key: value for key, value in node.items() if key != "$ref"}
        out = _map_subschemas(rest, lambda value: substitute(value, depth), skip_extensions=True)
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/") and ref.removeprefix("#/$defs/") in local:
            return _merge(out, substitute(local[ref.removeprefix("#/$defs/")], depth + 1), schema_id)
        if "$ref" in node:
            out = {"$ref": ref, **out}
        return out

    return substitute(schema, 0)


# --- one published file --------------------------------------------------------------------------------


def _file(
    contract: _Contract, declarations: dict[str, _Declaration], inlined: dict[str, _Declaration]
) -> dict[str, Any]:
    rel = contract.rel_path
    root = _resolve(contract.root or {}, rel, declarations, inlined, ())
    schema: dict[str, Any] = {"$schema": SCHEMA_DIALECT, "$id": f"{BASE_URI}{rel}", **root}
    if contract.defs:
        schema["$defs"] = {
            name: _resolve(body, rel, declarations, inlined, ()) for name, body in contract.defs.items()
        }
    return schema


def _resolve(
    node: Any,
    rel: str,
    declarations: dict[str, _Declaration],
    inlined: dict[str, _Declaration],
    stack: tuple[str, ...],
) -> Any:
    """Rewrite bundle refs: inline ``x-inline`` declarations and make every other ref file-relative."""
    if isinstance(node, list):
        return [_resolve(item, rel, declarations, inlined, stack) for item in node]
    if not isinstance(node, dict):
        return node
    rest = {key: value for key, value in node.items() if key not in ("$ref", INLINE)}
    out = _map_subschemas(rest, lambda value: _resolve(value, rel, declarations, inlined, stack))
    ref = node.get("$ref")
    if not isinstance(ref, str) or ref not in declarations:
        if isinstance(ref, str) and "://" in ref:
            raise NormaliseError(f"{rel}: $ref {ref} is not a declaration in the bundle")
        return {"$ref": ref, **out} if "$ref" in node else out
    target = declarations[ref]
    if ref in inlined:
        if ref in stack:
            raise NormaliseError(f"{ref}: an x-inline declaration can't refer to itself")
        if target.rel_path != rel:
            return {"$ref": {_ELSEWHERE: ref}, **out}
        body = _resolve(target.schema, rel, declarations, inlined, (*stack, ref))
        return {**_merge(out, body, ref), _HOME: ref}
    return {"$ref": _relative_ref(rel, target), **out}


def _relative_ref(rel: str, target: _Declaration) -> str:
    file = "" if target.rel_path == rel else posixpath.relpath(target.rel_path, posixpath.dirname(rel))
    if target.name is None:
        return file or "#"
    return f"{file}#/$defs/{target.name}"


def _merge(site: dict[str, Any], body: dict[str, Any], what: str) -> dict[str, Any]:
    merged = dict(site)
    for key, value in body.items():
        if key in merged and merged[key] != value:
            raise NormaliseError(f"{what}: inlining it would overwrite {key} at the site that refers to it")
        merged[key] = value
    return merged


# --- inlined declarations referred to from another file ---------------------------------------------------


def _take_homes(schema: dict[str, Any]) -> dict[str, str | None]:
    """Remove the inline markers from ``schema``; the JSON pointer of each inlined declaration."""
    homes: dict[str, list[str]] = {}

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{pointer}/{index}")
        elif isinstance(node, dict):
            home = node.pop(_HOME, None)
            if isinstance(home, str):
                homes.setdefault(home, []).append(pointer)
            for suffix, value in _subschemas(node):
                walk(value, pointer + suffix)

    walk(schema, "")
    return {home: pointers[0] if len(pointers) == 1 else None for home, pointers in homes.items()}


def _point_at_homes(schema: dict[str, Any], rel: str, homes: dict[str, dict[str, str | None]]) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, dict):
                schema_id = ref[_ELSEWHERE]
                home_rel, _ = _locate(schema_id)
                pointer = homes.get(home_rel, {}).get(schema_id)
                if pointer is None:
                    raise NormaliseError(
                        f"{rel}: refers to the x-inline {schema_id}, which must be used exactly once in its "
                        f"own contract to have a place to point at"
                    )
                node["$ref"] = f"{posixpath.relpath(home_rel, posixpath.dirname(rel))}#{pointer}"
            for _, value in _subschemas(node):
                walk(value)

    walk(schema)


def _check_refs(schema: dict[str, Any], rel: str, published: dict[str, dict[str, Any]]) -> None:
    """Every ``$ref`` in the output, including those written by hand in an extension, resolves."""

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                file, _, fragment = ref.partition("#")
                target_rel = posixpath.normpath(posixpath.join(posixpath.dirname(rel), file)) if file else rel
                if target_rel not in published or _pointer(published[target_rel], fragment) is None:
                    raise NormaliseError(f"{rel}: $ref {ref} doesn't resolve")
            for _, value in _subschemas(node):
                walk(value)

    walk(schema)


def _pointer(document: Any, fragment: str) -> Any:
    node = document
    for token in fragment.split("/")[1:] if fragment else []:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return None
    return node


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


# --- the emitter's idioms --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scope:
    """The file being simplified, and every file before simplification, to look a ``$ref`` up in."""

    rel: str
    files: dict[str, dict[str, Any]]

    def lookup(self, ref: Any) -> Any:
        if isinstance(ref, dict):  # a ref to an inlined declaration of another file, resolved later
            return None
        file, _, fragment = ref.partition("#")
        target = posixpath.normpath(posixpath.join(posixpath.dirname(self.rel), file)) if file else self.rel
        return _pointer(self.files.get(target), fragment) if target in self.files else None


def _simplify_file(schema: dict[str, Any], scope: _Scope, keyword_order: list[str]) -> dict[str, Any]:
    out = _simplify({key: value for key, value in schema.items() if key != "$defs"}, scope)
    if "$defs" in schema:
        out["$defs"] = {name: _simplify(body, scope) for name, body in schema["$defs"].items()}
    return _order_keywords(out, keyword_order)


def _keyword_order(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(k, str) and k in _RANK for k in value):
        raise NormaliseError(f"{KEYWORD_ORDER_KEY} must list keywords of KEYWORD_ORDER, not {value!r}")
    return value


def _required_order(order: Any, required: Any) -> list[str]:
    if not isinstance(order, list) or not isinstance(required, list) or sorted(order) != sorted(required):
        raise NormaliseError(f"{REQUIRED_ORDER_KEY} {order!r} must reorder the required list {required!r}")
    return order


def _order_keywords(node: Any, contract_order: list[str]) -> Any:
    """``node`` and its subschemas with their keywords in ``KEYWORD_ORDER``, except that the keywords of
    the ``x-keyword-order`` in force take each other's places in its order."""
    if isinstance(node, list):
        return [_order_keywords(item, contract_order) for item in node]
    if not isinstance(node, dict):
        return node
    own = node.get(KEYWORD_ORDER_KEY)
    order = contract_order if own is None else _keyword_order(own)
    rest = {key: value for key, value in node.items() if key not in (KEYWORD_ORDER_KEY, REQUIRED_ORDER_KEY)}
    if REQUIRED_ORDER_KEY in node:
        rest["required"] = _required_order(node[REQUIRED_ORDER_KEY], node.get("required"))
    out = _map_subschemas(rest, lambda value: _order_keywords(value, contract_order), skip_extensions=True)
    keys = sorted(out, key=lambda key: _RANK.get(_EXTENSIONS if key.startswith("x-") else key, len(_RANK)))
    reordered = iter(sorted((key for key in keys if key in order), key=order.index))
    keys = [next(reordered) if key in order else key for key in keys]
    return {key: out[key] for key in keys}


def _simplify(node: Any, scope: _Scope) -> Any:
    """Apply the exact rewrites of the module docstring, children first."""
    if isinstance(node, list):
        return [_simplify(item, scope) for item in node]
    if not isinstance(node, dict):
        return node
    out = _collapse_any_of(_map_subschemas(node, lambda value: _simplify(value, scope), skip_extensions=True))
    if out.get("items") == {}:
        del out["items"]
    _drop_type_beside_const(out)
    if "unevaluatedProperties" in out:
        out = _additional_properties(out, scope)
    if out.get("properties") == {}:
        del out["properties"]
    elif isinstance(out.get("properties"), dict):
        out["properties"] = {
            name: True if value == {} else value for name, value in out["properties"].items()
        }
    return out


def _bare(branch: Any) -> dict[str, Any] | None:
    """A branch without the inline marker, or ``None`` if it isn't an object."""
    if not isinstance(branch, dict):
        return None
    return {key: value for key, value in branch.items() if key != _HOME}


def _collapse_any_of(node: dict[str, Any]) -> dict[str, Any]:
    branches = node.get("anyOf")
    if not isinstance(branches, list) or not branches or any(_bare(b) != b for b in branches):
        return node
    rest = {key: value for key, value in node.items() if key != "anyOf"}
    if all(set(b) == {"type"} and isinstance(b["type"], str) for b in branches) and "type" not in rest:
        return {**rest, "type": [b["type"] for b in branches]}
    literals = [b for b in branches if set(b) == {"const"}]
    nulls = [b for b in branches if b == {"type": "null"}]
    if literals and len(literals) + len(nulls) == len(branches) and "enum" not in rest:
        # A union of one literal is an enum too; a const declaration is a scalar with a const extension.
        return {**rest, "enum": [b["const"] if "const" in b else None for b in branches]}
    if len(branches) == 1:
        (branch,) = branches
        mergeable = set(branch) <= {"$ref"}
        if mergeable and not set(branch) & set(rest):
            return {**rest, **branch}
    return node


def _drop_type_beside_const(node: dict[str, Any]) -> None:
    if "const" not in node or not isinstance(node.get("type"), str):
        return
    value, kind = node["const"], node["type"]
    if kind in ("number", "integer"):
        matches = isinstance(value, int | float) and not isinstance(value, bool)
        matches = matches and (kind == "number" or float(value).is_integer())
    else:
        matches = kind in JSON_TYPES and type(value) is JSON_TYPES[kind]
    if matches:
        del node["type"]


def _additional_properties(node: dict[str, Any], scope: _Scope) -> dict[str, Any]:
    value = node["unevaluatedProperties"]
    closed = value is False or value == {"not": {}}
    open_ = value is True or value == {}
    out: dict[str, Any] = {}
    for key, item in node.items():
        if key != "unevaluatedProperties":
            out[key] = item
        elif open_:
            continue
        else:
            if "additionalProperties" in node:
                raise NormaliseError(f"{scope.rel}: unevaluatedProperties beside additionalProperties")
            _check_no_unlisted_property(node, scope)
            out["additionalProperties"] = False if closed else value
    return out


def _check_no_unlisted_property(node: dict[str, Any], scope: _Scope) -> None:
    """``unevaluatedProperties`` sees the properties that an in-place applicator evaluates, and
    ``additionalProperties`` doesn't. They agree when the object lists every such property itself."""
    listed = set(node.get("properties", {}))
    for name in _applicator_properties(node, scope, top=True):
        if name is None:
            raise NormaliseError(
                f"{scope.rel}: unevaluatedProperties beside an applicator that can evaluate "
                "unlisted properties"
            )
        if name not in listed:
            raise NormaliseError(
                f"{scope.rel}: unevaluatedProperties can't become additionalProperties: an applicator "
                f"beside it names the property {name!r}, which the object doesn't list"
            )


def _applicator_properties(node: Any, scope: _Scope, top: bool = False, depth: int = 0) -> list[str | None]:
    """Property names that in-place applicators of ``node`` evaluate; ``None`` for an unknowable set."""
    if not isinstance(node, dict):
        return []
    if depth > MAX_REF_DEPTH:
        return [None]
    names: list[str | None] = []
    if not top:
        names += list(node.get("properties", {}))
        if any(key in node for key in ("patternProperties", "additionalProperties", "unevaluatedProperties")):
            names.append(None)
        if "$dynamicRef" in node:
            names.append(None)
    subschemas = _in_place_subschemas(node)
    if "$ref" in node:
        target = scope.lookup(node["$ref"])
        names += [None] if target is None else _applicator_properties(target, scope, depth=depth + 1)
    for subschema in subschemas:
        names += _applicator_properties(subschema, scope, depth=depth + 1)
    return names


def _in_place_subschemas(node: dict[str, Any]) -> list[Any]:
    found: list[Any] = []
    for key in ("allOf", "anyOf", "oneOf"):
        if isinstance(node.get(key), list):
            found += node[key]
    found += [node[key] for key in ("if", "then", "else") if key in node]
    if isinstance(node.get("dependentSchemas"), dict):
        found += list(node["dependentSchemas"].values())
    return found
