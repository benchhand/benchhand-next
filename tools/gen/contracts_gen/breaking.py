"""Breaking-change check: each contract against its version at the last release tag.

The rules are documented in docs/contract/versioning.md. A change is breaking when an instance that
the old schema accepted can be rejected by the new one, or when a published definition disappears.
Such a change needs a higher major ``x-version``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sources import CONTRACTS_DIR, SCHEMA_SUFFIX, load_contracts

RELEASE_TAG_PATTERN = "v[0-9]*"

LOWER_BOUNDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties", "minContains")
UPPER_BOUNDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties", "maxContains")
EXACT_KEYWORDS = ("$ref", "const", "pattern", "multipleOf", "contentMediaType", "contentEncoding")
SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")
SCHEMA_SINGLES = (
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
)
SCHEMA_LISTS = ("prefixItems", "allOf", "anyOf", "oneOf")


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


def last_release_tag(repo_root: Path) -> str | None:
    """The nearest ``v*`` tag reachable from HEAD, or ``None`` when there is none."""
    _git(repo_root, "rev-parse", "--verify", "HEAD")  # not a repository is an error, not "no tag"
    result = _git(
        repo_root, "describe", "--tags", "--abbrev=0", f"--match={RELEASE_TAG_PATTERN}", check=False
    )
    return result.strip() or None


def check_against(repo_root: Path, base: str) -> list[ContractReport]:
    """Compare the contracts in the working tree with those at git revision ``base``."""
    old = _contracts_at(repo_root, base)
    new = {contract.rel_path: contract.schema for contract in load_contracts(repo_root / CONTRACTS_DIR)}
    reports = []
    for rel_path in sorted(old):
        old_schema = old[rel_path]
        new_schema = new.get(rel_path)
        if new_schema is None:
            change = BreakingChange("", "schema-removed", f"{CONTRACTS_DIR}/{rel_path} was removed")
            reports.append(ContractReport(rel_path, old_schema.get("x-version"), None, (change,)))
            continue
        changes = tuple(compare(old_schema, new_schema))
        reports.append(
            ContractReport(rel_path, old_schema.get("x-version"), new_schema.get("x-version"), changes)
        )
    return reports


def compare(old: Any, new: Any, pointer: str = "") -> Iterator[BreakingChange]:
    """Every breaking change from schema ``old`` to schema ``new``, walking both in parallel."""
    if isinstance(old, bool) or isinstance(new, bool):
        yield from _boolean_schema(old, new, pointer)
        return
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    for rule in RULES:
        yield from rule(old, new, pointer)
    yield from _subschemas(old, new, pointer)


def _subschemas(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword in SCHEMA_MAPS:
        old_map, new_map = old.get(keyword, {}), new.get(keyword, {})
        for name in old_map:
            if name in new_map:
                yield from compare(old_map[name], new_map[name], f"{pointer}/{keyword}/{_escape(name)}")
    for keyword in SCHEMA_SINGLES:
        if keyword in old and keyword in new:
            yield from compare(old[keyword], new[keyword], f"{pointer}/{keyword}")
    for keyword in SCHEMA_LISTS:
        for index, (old_branch, new_branch) in enumerate(
            zip(old.get(keyword, []), new.get(keyword, []), strict=False)
        ):
            yield from compare(old_branch, new_branch, f"{pointer}/{keyword}/{index}")


def _boolean_schema(old: Any, new: Any, pointer: str) -> Iterator[BreakingChange]:
    if new is False and old is not False:
        yield BreakingChange(pointer, "schema-closed", "the schema now rejects everything")
    elif isinstance(old, bool) and old and isinstance(new, dict) and new:
        yield BreakingChange(
            pointer, "schema-constrained", "a schema that accepted everything now has constraints"
        )


def _removed_entries(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword, rule in (("$defs", "definition-removed"), ("properties", "property-removed")):
        for name in old.get(keyword, {}):
            if name not in new.get(keyword, {}):
                yield BreakingChange(f"{pointer}/{keyword}/{_escape(name)}", rule, f"{name!r} was removed")


def _required_added(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    added = sorted(set(new.get("required", [])) - set(old.get("required", [])))
    if added:
        yield BreakingChange(f"{pointer}/required", "required-added", f"newly required: {', '.join(added)}")
    for name, needs in new.get("dependentRequired", {}).items():
        extra = sorted(set(needs) - set(old.get("dependentRequired", {}).get(name, [])))
        if extra:
            yield BreakingChange(
                f"{pointer}/dependentRequired/{_escape(name)}", "required-added", f"newly required: {extra}"
            )


def _type_narrowed(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    if "type" not in new:
        return
    old_types = _types(old.get("type"))
    new_types = _types(new["type"])
    if "number" in new_types:
        new_types.add("integer")
    lost = sorted(old_types - new_types)
    if lost:
        yield BreakingChange(f"{pointer}/type", "type-narrowed", f"no longer accepts {', '.join(lost)}")


def _enum_narrowed(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    if "enum" not in new:
        return
    if "enum" not in old:
        yield BreakingChange(f"{pointer}/enum", "enum-added", "values are now restricted to an enum")
        return
    removed = [value for value in old["enum"] if value not in new["enum"]]
    if removed:
        yield BreakingChange(f"{pointer}/enum", "enum-value-removed", f"removed: {json.dumps(removed)}")


def _exact_changed(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword in EXACT_KEYWORDS:
        if keyword in new and old.get(keyword, _MISSING) != new[keyword]:
            yield BreakingChange(
                f"{pointer}/{_escape(keyword)}",
                f"{keyword.lstrip('$')}-changed",
                f"{json.dumps(old.get(keyword))} -> {json.dumps(new[keyword])}",
            )


def _bounds_tightened(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword in LOWER_BOUNDS + UPPER_BOUNDS:
        if keyword not in new:
            continue
        before, after = old.get(keyword), new[keyword]
        if before is None or (after > before if keyword in LOWER_BOUNDS else after < before):
            yield BreakingChange(f"{pointer}/{keyword}", "bound-tightened", f"{before} -> {after}")
    if new.get("uniqueItems") is True and old.get("uniqueItems") is not True:
        yield BreakingChange(f"{pointer}/uniqueItems", "bound-tightened", "items must now be unique")


def _closed(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword in ("additionalProperties", "unevaluatedProperties", "items", "unevaluatedItems"):
        if keyword in new and keyword not in old and new[keyword] not in (True, {}):
            yield BreakingChange(f"{pointer}/{keyword}", "schema-constrained", f"{keyword} was added")


def _branches_changed(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[BreakingChange]:
    for keyword in ("anyOf", "oneOf", "prefixItems"):
        old_count, new_count = len(old.get(keyword, [])), len(new.get(keyword, []))
        if new_count < old_count or (keyword in new and keyword not in old):
            yield BreakingChange(
                f"{pointer}/{keyword}", "branches-reduced", f"{old_count} -> {new_count} branches"
            )
    old_count, new_count = len(old.get("allOf", [])), len(new.get("allOf", []))
    if new_count > old_count:
        yield BreakingChange(
            f"{pointer}/allOf", "constraint-added", f"{old_count} -> {new_count} allOf branches"
        )
    for keyword in ("not", "if", "contains", "propertyNames", "dependentSchemas"):
        if keyword in new and keyword not in old:
            yield BreakingChange(f"{pointer}/{keyword}", "constraint-added", f"{keyword} was added")


_MISSING = object()

RULES: tuple[Callable[[dict[str, Any], dict[str, Any], str], Iterator[BreakingChange]], ...] = (
    _removed_entries,
    _required_added,
    _type_narrowed,
    _enum_narrowed,
    _exact_changed,
    _bounds_tightened,
    _closed,
    _branches_changed,
)


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
    listing = _git(repo_root, "ls-tree", "-r", "--name-only", revision, "--", f"{CONTRACTS_DIR}/")
    contracts = {}
    for path in listing.splitlines():
        if path.endswith(SCHEMA_SUFFIX):
            rel_path = path.removeprefix(f"{CONTRACTS_DIR}/")
            contracts[rel_path] = json.loads(_git(repo_root, "show", f"{revision}:{path}"))
    return contracts


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout if result.returncode == 0 else ""
