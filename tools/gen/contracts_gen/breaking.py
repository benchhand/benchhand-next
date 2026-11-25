"""Breaking-change check: each published contract against its version at the last release tag.

It compares the published schemas (``SCHEMAS_OUT``), which have the same paths before and after the move to
TypeSpec, rather than the sources under contracts/.

The rules are documented in docs/contract/versioning.md. A change is breaking when an instance that
the old schema accepted can be rejected by the new one, or when a published definition disappears.
Such a change needs a higher major ``x-version``.

The check is conservative: it accepts only changes it can show to be widenings. Any other change to a
validation keyword is reported as ``unproven-change``.
"""

from __future__ import annotations

import json
import posixpath
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from .sources import SCHEMA_SUFFIX, SCHEMAS_OUT, load_contracts

RELEASE_TAG_PATTERN = "v[0-9]*"

ANNOTATIONS = frozenset(
    ("title", "description", "$comment", "examples", "default", "deprecated", "readOnly", "writeOnly")
    + ("format",)  # an annotation in both validators (docs/contract/versioning.md)
)
"""Keywords that never reject an instance; ``x-*`` keywords are annotations too."""
DATA_KEYWORDS = ("const", "enum", "required", "dependentRequired")
"""Keywords whose values are instance data or property names, never schemas."""
SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")

LOWER_BOUNDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties", "minContains")
UPPER_BOUNDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties", "maxContains")
BOUND_DEFAULTS = {"minContains": 1}
EXACT_KEYWORDS = ("$ref", "const", "pattern", "multipleOf", "contentMediaType", "contentEncoding")
RULE_KEYWORDS = frozenset(
    ("type", "enum", "required", "dependentRequired", "uniqueItems", *EXACT_KEYWORDS)
    + LOWER_BOUNDS
    + UPPER_BOUNDS
)
COVARIANT_SINGLES = (
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "propertyNames",
    "then",
    "else",
)
"""An absent subschema here means ``true``, and a wider subschema never makes the parent reject more."""
WALKED_KEYWORDS = frozenset(("properties", "$defs", "allOf", "anyOf", *COVARIANT_SINGLES))
STRICT_KEYWORDS = ("oneOf", "not", "if", "contains", "dependentSchemas")
"""Removing one of these drops a constraint, but any other change can make the parent reject more,
even when the subschema got wider: a wider ``oneOf`` branch can overlap another, ``not`` and ``if``
invert their subschema, and ``contains`` is bounded by ``maxContains``. A ``oneOf`` whose branches are
provably disjoint is the exception: it behaves like ``anyOf``."""
ROOT = ""
"""The name under which a whole contract, rather than one ``$defs`` entry, is a strict target."""
MAX_REF_DEPTH = 16


@dataclass(frozen=True)
class BreakingChange:
    pointer: str
    """JSON pointer into the schema where the change is."""
    rule: str
    detail: str


@dataclass(frozen=True)
class ContractReport:
    rel_path: str
    old_version: str | None
    new_version: str | None
    changes: tuple[BreakingChange, ...]

    @property
    def allowed(self) -> bool:
        """No breaking change, or a major ``x-version`` bump that announces them."""
        if not self.changes:
            return True
        return _major(self.new_version) > _major(self.old_version)


class GitError(Exception):
    """git failed while reading the release tag."""


@dataclass(frozen=True)
class Scope:
    """The new contracts and the path of the one being walked, for resolving ``$ref``s."""

    contracts: dict[str, Any]
    rel_path: str

    def resolve(self, schema: Any) -> tuple[Any, Scope]:
        """Follow ``$ref``s from ``schema`` to a schema that has none, or that can't be resolved.

        The target alone is a superset of a ``$ref`` with sibling keywords, which is what the disjointness
        proof needs.
        """
        scope = self
        for _ in range(MAX_REF_DEPTH):
            if not (isinstance(schema, dict) and isinstance(schema.get("$ref"), str)):
                break
            target_path, name = _ref_target(scope.rel_path, schema["$ref"])
            target = _definition(scope.contracts.get(target_path), name)
            if target is None:
                break
            schema, scope = target, Scope(scope.contracts, target_path)
        return schema, scope


_NO_SCOPE = Scope({}, "")


def last_release_tag(repo_root: Path) -> str | None:
    """The nearest ``v*`` tag reachable from HEAD, or ``None`` when there is none."""
    _git(repo_root, "rev-parse", "--verify", "HEAD")  # not a repository is an error, not "no tag"
    result = _git(
        repo_root, "describe", "--tags", "--abbrev=0", f"--match={RELEASE_TAG_PATTERN}", check=False
    )
    return result.strip() or None


def check_against(repo_root: Path, base: str) -> list[ContractReport]:
    """Compare the published contracts in the working tree with those at git revision ``base``."""
    new = {contract.rel_path: contract.schema for contract in load_contracts(repo_root / SCHEMAS_OUT)}
    return compare_contracts(_contracts_at(repo_root, base), new)


def compare_contracts(old: dict[str, Any], new: dict[str, Any]) -> list[ContractReport]:
    """A report for each old contract, keyed by path below contracts/, against the new contracts."""
    strict = strict_definitions(new)
    reports = []
    for rel_path in sorted(old):
        old_schema, new_schema = old[rel_path], new.get(rel_path)
        if new_schema is None:
            change = BreakingChange("", "schema-removed", f"{rel_path} was removed")
            reports.append(ContractReport(rel_path, old_schema.get("x-version"), None, (change,)))
            continue
        scope = Scope(new, rel_path)
        changes = tuple(_compare_contract(old_schema, new_schema, strict.get(rel_path, set()), scope))
        reports.append(
            ContractReport(rel_path, old_schema.get("x-version"), new_schema.get("x-version"), changes)
        )
    return reports


def strict_definitions(contracts: dict[str, Any]) -> dict[str, set[str]]:
    """Per contract, the ``$defs`` names (``ROOT`` for the whole contract) that must not change.

    These are the targets of a ``$ref`` under a strict keyword such as ``oneOf``, and everything they
    reference in turn: the check can't tell whether a change to them makes the referrer reject more.
    """
    found: dict[str, set[str]] = {}
    pending = [
        (rel_path, ref)
        for rel_path, schema in contracts.items()
        for ref in _strict_refs(schema, Scope(contracts, rel_path))
    ]
    while pending:
        rel_path, ref = pending.pop()
        target_path, name = _ref_target(rel_path, ref)
        target = _definition(contracts.get(target_path), name)
        if target is None or name in found.setdefault(target_path, set()):
            continue
        found[target_path].add(name)
        pending += [(target_path, inner) for inner in _strict_refs(target, _NO_SCOPE, strict=True)]
    return found


def disjoint_branches(branches: list[Any], scope: Scope) -> bool:
    """Whether no instance can match two of ``branches``, so that a ``oneOf`` of them is an ``anyOf``.

    Two branches are disjoint when their types don't overlap, or when one is an object type and the
    other can't have a property that the first requires, with a value that the first allows.
    """
    resolved = [scope.resolve(branch) for branch in branches]
    return all(_disjoint(first, second) for first, second in combinations(resolved, 2))


def _disjoint(first: tuple[Any, Scope], second: tuple[Any, Scope]) -> bool:
    schema_a, schema_b = first[0], second[0]
    if not isinstance(schema_a, dict) or not isinstance(schema_b, dict):
        return False
    if not _overlapping_types(schema_a) & _overlapping_types(schema_b):
        return True
    if "object" not in (schema_a.get("type"), schema_b.get("type")):
        return False
    return _excludes(first, second) or _excludes(second, first)


def _overlapping_types(schema: dict[str, Any]) -> set[str]:
    types = _types(schema.get("type"))
    if types & {"number", "integer"}:
        types |= {"number", "integer"}
    return types


def _excludes(first: tuple[Any, Scope], second: tuple[Any, Scope]) -> bool:
    """Whether every object of ``first`` has a property that no object of ``second`` has with that value."""
    (schema_a, scope_a), (schema_b, scope_b) = first, second
    properties_a, properties_b = schema_a.get("properties", {}), schema_b.get("properties", {})
    for name in schema_a.get("required", []):
        if name not in properties_b:
            if schema_b.get("additionalProperties") is False and not schema_b.get("patternProperties"):
                return True
            continue
        values_a = _allowed_values(scope_a.resolve(properties_a.get(name, True))[0])
        values_b = _allowed_values(scope_b.resolve(properties_b[name])[0])
        if values_a is not None and values_b is not None and not values_a & values_b:
            return True
    return False


def _allowed_values(schema: Any) -> set[str] | None:
    """The JSON texts of the values a ``const`` or ``enum`` schema allows, or ``None`` for others."""
    if isinstance(schema, dict) and "const" in schema:
        return {json.dumps(schema["const"], sort_keys=True)}
    if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
        return {json.dumps(value, sort_keys=True) for value in schema["enum"]}
    return None


def _compare_contract(
    old: dict[str, Any], new: dict[str, Any], strict: set[str], scope: Scope
) -> Iterator[BreakingChange]:
    if ROOT in strict:
        yield from _must_match(old, new, "")
        return
    old_defs, new_defs = old.get("$defs", {}), new.get("$defs", {})
    shared = sorted(strict & old_defs.keys() & new_defs.keys())
    for name in shared:
        yield from _must_match(old_defs[name], new_defs[name], f"/$defs/{_escape(name)}")
    yield from compare(_without_definitions(old, shared), _without_definitions(new, shared), "", scope)


def compare(old: Any, new: Any, pointer: str = "", scope: Scope = _NO_SCOPE) -> Iterator[BreakingChange]:
    """Every breaking change from schema ``old`` to schema ``new``, walking both in parallel.

    A ``$defs`` entry that another schema references under a strict keyword needs
    :func:`compare_contracts`, which compares it for equality instead. ``scope`` resolves the
    ``$ref``s of a ``oneOf`` for the disjointness proof.
    """
    if isinstance(old, bool) or isinstance(new, bool):
        yield from _boolean_schema(old, new, pointer)
        return
    if not isinstance(old, dict) or not isinstance(new, dict):
        yield from _must_match(old, new, pointer)
        return
    for rule in RULES:
        yield from rule(old, new, pointer, scope)


def _boolean_schema(old: Any, new: Any, pointer: str) -> Iterator[BreakingChange]:
    if new is False and old is not False:
        yield BreakingChange(pointer, "schema-closed", "the schema now rejects everything")
    elif old is True and _semantic(new) not in (True, {}):
        yield BreakingChange(
            pointer, "schema-constrained", "a schema that accepted everything now has constraints"
        )
    elif not (old is True or old is False or (isinstance(old, dict) and new is True)):
        yield from _must_match(old, new, pointer)


def _must_match(old: Any, new: Any, pointer: str) -> Iterator[BreakingChange]:
    if _semantic(old) != _semantic(new):
        yield BreakingChange(
            pointer,
            "unproven-change",
            "changed where the check can't prove that every instance accepted before is still accepted",
        )


def _removed_entries(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    for keyword, rule in (("$defs", "definition-removed"), ("properties", "property-removed")):
        for name in old.get(keyword, {}):
            if name not in new.get(keyword, {}):
                yield BreakingChange(f"{pointer}/{keyword}/{_escape(name)}", rule, f"{name!r} was removed")


def _required_added(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    added = sorted(set(new.get("required", [])) - set(old.get("required", [])))
    if added:
        yield BreakingChange(f"{pointer}/required", "required-added", f"newly required: {', '.join(added)}")
    for name, needs in new.get("dependentRequired", {}).items():
        extra = sorted(set(needs) - set(old.get("dependentRequired", {}).get(name, [])))
        if extra:
            yield BreakingChange(
                f"{pointer}/dependentRequired/{_escape(name)}", "required-added", f"newly required: {extra}"
            )


def _type_narrowed(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    if "type" not in new:
        return
    old_types = _types(old.get("type"))
    new_types = _types(new["type"])
    if "number" in new_types:
        new_types.add("integer")
    lost = sorted(old_types - new_types)
    if lost:
        yield BreakingChange(f"{pointer}/type", "type-narrowed", f"no longer accepts {', '.join(lost)}")


def _enum_narrowed(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    if "enum" not in new:
        return
    if "enum" not in old:
        yield BreakingChange(f"{pointer}/enum", "enum-added", "values are now restricted to an enum")
        return
    removed = [value for value in old["enum"] if value not in new["enum"]]
    if removed:
        yield BreakingChange(f"{pointer}/enum", "enum-value-removed", f"removed: {json.dumps(removed)}")


def _exact_changed(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    for keyword in EXACT_KEYWORDS:
        if keyword in new and old.get(keyword, _MISSING) != new[keyword]:
            yield BreakingChange(
                f"{pointer}/{_escape(keyword)}",
                f"{keyword.lstrip('$')}-changed",
                f"{json.dumps(old.get(keyword))} -> {json.dumps(new[keyword])}",
            )


def _bounds_tightened(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    for keyword in LOWER_BOUNDS + UPPER_BOUNDS:
        after = new.get(keyword, BOUND_DEFAULTS.get(keyword))
        if after is None:
            continue
        before = old.get(keyword, BOUND_DEFAULTS.get(keyword))
        if before is None or (after > before if keyword in LOWER_BOUNDS else after < before):
            yield BreakingChange(f"{pointer}/{keyword}", "bound-tightened", f"{before} -> {after}")
    if new.get("uniqueItems") is True and old.get("uniqueItems") is not True:
        yield BreakingChange(f"{pointer}/uniqueItems", "bound-tightened", "items must now be unique")


def _strict_changed(
    old: dict[str, Any], new: dict[str, Any], pointer: str, scope: Scope
) -> Iterator[BreakingChange]:
    for keyword in STRICT_KEYWORDS:
        if keyword not in new:
            continue
        if keyword not in old:
            yield BreakingChange(f"{pointer}/{keyword}", "constraint-added", f"{keyword} was added")
        elif keyword == "oneOf" and disjoint_branches(new["oneOf"], scope):
            yield from _branch_pairs(old["oneOf"], new["oneOf"], f"{pointer}/oneOf", scope)
        else:
            yield from _must_match(old[keyword], new[keyword], f"{pointer}/{keyword}")


def _other_keywords(
    old: dict[str, Any], new: dict[str, Any], pointer: str, _scope: Scope
) -> Iterator[BreakingChange]:
    """Keywords without a rule, such as ``prefixItems`` or ``patternProperties``: any change counts."""
    handled = RULE_KEYWORDS | WALKED_KEYWORDS | ANNOTATIONS | set(STRICT_KEYWORDS)
    for keyword in sorted((old.keys() | new.keys()) - handled):
        if not keyword.startswith("x-"):
            yield from _must_match(
                old.get(keyword, _MISSING), new.get(keyword, _MISSING), f"{pointer}/{_escape(keyword)}"
            )


def _properties(
    old: dict[str, Any], new: dict[str, Any], pointer: str, scope: Scope
) -> Iterator[BreakingChange]:
    old_properties = old.get("properties", {})
    unlisted = _unlisted_property_schema(old)
    for name, schema in new.get("properties", {}).items():
        location = f"{pointer}/properties/{_escape(name)}"
        if name in old_properties:
            yield from compare(old_properties[name], schema, location, scope)
        elif unlisted is not None:
            yield from compare(unlisted, schema, location, scope)


def _unlisted_property_schema(old: dict[str, Any]) -> Any:
    """The schema ``old`` applied to a property it didn't list, or ``None`` when it accepted any value.

    A new optional property of an object that accepts any other property is a minor change
    (docs/contract/versioning.md), so that case isn't compared.
    """
    if old.get("patternProperties"):
        return True  # the property may match a pattern; report any constraint on it
    additional = old.get("additionalProperties", True)
    return None if _semantic(additional) in (True, {}) else additional


def _definitions(
    old: dict[str, Any], new: dict[str, Any], pointer: str, scope: Scope
) -> Iterator[BreakingChange]:
    old_definitions = old.get("$defs", {})
    for name, schema in new.get("$defs", {}).items():
        if name in old_definitions:
            yield from compare(old_definitions[name], schema, f"{pointer}/$defs/{_escape(name)}", scope)


def _singles(
    old: dict[str, Any], new: dict[str, Any], pointer: str, scope: Scope
) -> Iterator[BreakingChange]:
    for keyword in COVARIANT_SINGLES:
        if keyword in old or keyword in new:
            yield from compare(old.get(keyword, True), new.get(keyword, True), f"{pointer}/{keyword}", scope)


def _branches(
    old: dict[str, Any], new: dict[str, Any], pointer: str, scope: Scope
) -> Iterator[BreakingChange]:
    # An absent anyOf is anyOf [true].
    if "anyOf" in new:
        yield from _branch_pairs(old.get("anyOf", [True]), new["anyOf"], f"{pointer}/anyOf", scope)
    # An absent allOf is allOf []; a new branch is compared with true.
    old_all = old.get("allOf", [])
    for index, after in enumerate(new.get("allOf", [])):
        before = old_all[index] if index < len(old_all) else True
        yield from compare(before, after, f"{pointer}/allOf/{index}", scope)


def _branch_pairs(old: list[Any], new: list[Any], pointer: str, scope: Scope) -> Iterator[BreakingChange]:
    """Alternatives (``anyOf``): each old branch is compared with the new branch at its index."""
    if len(new) < len(old):
        yield BreakingChange(pointer, "branches-reduced", f"{len(old)} -> {len(new)} branches")
    for index, (before, after) in enumerate(zip(old, new, strict=False)):
        yield from compare(before, after, f"{pointer}/{index}", scope)


_MISSING = object()

RULES: tuple[Callable[[dict[str, Any], dict[str, Any], str, Scope], Iterator[BreakingChange]], ...] = (
    _removed_entries,
    _required_added,
    _type_narrowed,
    _enum_narrowed,
    _exact_changed,
    _bounds_tightened,
    _strict_changed,
    _other_keywords,
    _properties,
    _definitions,
    _singles,
    _branches,
)


def _semantic(node: Any) -> Any:
    """``node`` without annotations, so that a documentation change compares equal."""
    if isinstance(node, list):
        return [_semantic(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key in ANNOTATIONS or key.startswith("x-"):
            continue
        if key in DATA_KEYWORDS:
            result[key] = value
        elif key in SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {name: _semantic(schema) for name, schema in value.items()}
        else:
            result[key] = _semantic(value)
    return result


def _strict_refs(node: Any, scope: Scope, strict: bool = False) -> Iterator[str]:
    """The ``$ref``s at or below a strict keyword in schema ``node``; with ``strict``, every ``$ref``."""
    if isinstance(node, list):
        for item in node:
            yield from _strict_refs(item, scope, strict)
        return
    if not isinstance(node, dict):
        return
    if strict and isinstance(node.get("$ref"), str):
        yield node["$ref"]
    for key, value in node.items():
        if key in DATA_KEYWORDS or key in ANNOTATIONS:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            for schema in value.values():
                yield from _strict_refs(schema, scope, strict)
        else:
            yield from _strict_refs(value, scope, strict or _is_strict(key, value, scope))


def _is_strict(keyword: str, value: Any, scope: Scope) -> bool:
    if keyword == "oneOf":
        return not (isinstance(value, list) and disjoint_branches(value, scope))
    return keyword in STRICT_KEYWORDS


def _ref_target(rel_path: str, ref: str) -> tuple[str, str]:
    """``(contract path, $defs name or ROOT)`` that ``ref`` in contract ``rel_path`` points into."""
    target, _, fragment = ref.partition("#")
    target_path = rel_path
    if target:
        target_path = posixpath.normpath(posixpath.join(posixpath.dirname(rel_path), target))
    parts = fragment.split("/")
    if len(parts) > 2 and parts[0] == "" and parts[1] == "$defs":
        return target_path, parts[2].replace("~1", "/").replace("~0", "~")
    return target_path, ROOT


def _definition(schema: Any, name: str) -> Any:
    """The schema of ``$defs`` entry ``name`` (the root, without ``$defs``, for ``ROOT``)."""
    if not isinstance(schema, dict):
        return None
    if name == ROOT:
        return {key: value for key, value in schema.items() if key != "$defs"}
    return schema.get("$defs", {}).get(name)


def _without_definitions(schema: dict[str, Any], names: list[str]) -> dict[str, Any]:
    if not names:
        return schema
    definitions = {name: value for name, value in schema.get("$defs", {}).items() if name not in names}
    return {**schema, "$defs": definitions}


def _types(value: Any) -> set[str]:
    if value is None:
        return {"null", "boolean", "object", "array", "number", "integer", "string"}
    return set(value) if isinstance(value, list) else {value}


def _major(version: str | None) -> int:
    if not version:
        return -1
    return int(version.split(".", 1)[0])


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _contracts_at(repo_root: Path, revision: str) -> dict[str, dict[str, Any]]:
    listing = _git(repo_root, "ls-tree", "-r", "--name-only", revision, "--", f"{SCHEMAS_OUT}/")
    contracts = {}
    for path in listing.splitlines():
        if path.endswith(SCHEMA_SUFFIX):
            rel_path = path.removeprefix(f"{SCHEMAS_OUT}/")
            contracts[rel_path] = json.loads(_git(repo_root, "show", f"{revision}:{path}"))
    return contracts


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout if result.returncode == 0 else ""
