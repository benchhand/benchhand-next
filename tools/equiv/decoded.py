"""Decoded comparison of the published schemas with the hand-written ones they replaced (ADR-0017).

The contracts moved from hand-written JSON Schema to TypeSpec on top of ``BASE``. This compares each
published schema with ``contracts/<path>.schema.json`` at ``BASE``, after JSON decoding:

- every value must be equal, lists in order, and a ``required`` list in order, since the validator reports
  missing properties in that order;
- at each schema node, two keywords that can both fail on one instance at the same place must come in the
  same order. ``benchhand_contracts.violations`` lists the violations at one place in the order of their
  keywords, and Python's validator raises the first of two that ``jsonschema.exceptions.relevance`` ties,
  so the order decides the violation ``validate`` raises, its ``schema_path``, and the order of the list.
  Keywords whose errors are always deeper in the instance (``properties``, ``items``) and keywords of
  different JSON types (``minLength`` and ``minimum``) never fail at the same place.

Each intended difference is in ``ALLOWED`` with its reason, and anything else fails. ``just
contracts-equivalence`` runs it; ``tools/equiv/results/decoded.txt`` holds the output.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = "41598c2"
"""The last commit whose contracts were hand-written JSON Schema."""
OLD_DIR = "contracts"
NEW_DIR = "packages/benchhand-contracts/src/benchhand_contracts/schemas"
SCHEMA_SUFFIX = ".schema.json"
DATA_KEYWORDS = frozenset(("const", "enum", "examples", "default", "required", "dependentRequired"))
SCHEMA_MAPS = frozenset(("properties", "patternProperties", "$defs", "dependentSchemas"))
TYPE_GROUPS = {
    "object": ("required", "minProperties", "maxProperties", "propertyNames", "dependentRequired"),
    "array": ("minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains"),
    "string": ("minLength", "maxLength", "pattern"),
    "number": ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"),
}
"""Keywords that judge one JSON type and pass every other."""
_GROUP = {keyword: group for group, keywords in TYPE_GROUPS.items() for keyword in keywords}
ANY_TYPE = frozenset(
    ("type", "const", "enum", "$ref", "allOf", "anyOf", "oneOf", "not", "then", "else", "dependentSchemas")
)
"""Keywords whose errors can be at the schema's own place in the instance, for any instance."""

TIMESTAMP = ("jobs/job.schema.json", "/$defs/Timestamp")
EMPTY_SCHEMA_AS_TRUE = "changed: a property schema of {} is written true; both accept every value"
ALLOWED: dict[tuple[str, str], str] = {
    (TIMESTAMP[0], f"{TIMESTAMP[1]}/pattern"): "added: an uppercase T and an explicit offset (ADR-0017)",
    (TIMESTAMP[0], f"{TIMESTAMP[1]}/description"): "changed: the description states the new pattern",
    ("provider/protocol.schema.json", "/$defs/Limits/required"): "removed: `required: []` requires nothing",
    **{
        ("provider/protocol.schema.json", pointer): EMPTY_SCHEMA_AS_TRUE
        for pointer in (
            "/$defs/ErrorObject/properties/data/properties/detail",
            "/$defs/LogParams/properties/data",
            "/$defs/Request/properties/params",
            "/$defs/Notification/properties/params",
            "/$defs/SuccessResponse/properties/result",
        )
    },
}
"""``(contract, JSON pointer) -> reason`` for each difference the migration made on purpose."""
ROOT_DESCRIPTION = "added: a description at the contract root"


def old_schemas() -> dict[str, Any]:
    listing = _git("ls-tree", "-r", "--name-only", BASE, "--", f"{OLD_DIR}/").splitlines()
    return {
        path.removeprefix(f"{OLD_DIR}/"): json.loads(_git("show", f"{BASE}:{path}"))
        for path in listing
        if path.endswith(SCHEMA_SUFFIX)
    }


def new_schemas() -> dict[str, Any]:
    root = REPO_ROOT / NEW_DIR
    paths = sorted(root.rglob(f"*{SCHEMA_SUFFIX}"))
    return {path.relative_to(root).as_posix(): json.loads(path.read_text()) for path in paths}


def differences(old: Any, new: Any, pointer: str = "") -> Iterator[tuple[str, str]]:
    """``(JSON pointer, what differs)`` for every difference between two decoded schemas."""
    if isinstance(old, dict) and isinstance(new, dict):
        yield from _object_differences(old, new, pointer)
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
            yield from differences(old_item, new_item, f"{pointer}/{index}")
    elif not _same_value(old, new):
        yield pointer, f"{_short(old)} -> {_short(new)}"


def _object_differences(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[tuple[str, str]]:
    for key in sorted(old.keys() - new.keys()):
        yield f"{pointer}/{_escape(key)}", "removed"
    for key in sorted(new.keys() - old.keys()):
        yield f"{pointer}/{_escape(key)}", "added"
    for first, second in same_place_order_changes(old, new):
        yield pointer or "/", f"keyword order: {first} before {second} -> after it"
    for key in [key for key in old if key in new]:
        child = f"{pointer}/{_escape(key)}"
        if key in DATA_KEYWORDS or key.startswith("x-"):
            if old[key] != new[key]:
                yield child, f"{_short(old[key])} -> {_short(new[key])}"
        elif key in SCHEMA_MAPS and isinstance(old[key], dict) and isinstance(new[key], dict):
            yield from _map_differences(old[key], new[key], child)
        else:
            yield from differences(old[key], new[key], child)


def _map_differences(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[tuple[str, str]]:
    for name in sorted(old.keys() - new.keys()):
        yield f"{pointer}/{_escape(name)}", "removed"
    for name in sorted(new.keys() - old.keys()):
        yield f"{pointer}/{_escape(name)}", "added"
    for name in [name for name in old if name in new]:
        yield from differences(old[name], new[name], f"{pointer}/{_escape(name)}")


def same_place_order_changes(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str]]:
    """Pairs of keywords that can fail at the same place, ``old`` lists first, and ``new`` reverses."""
    in_old = [key for key in old if key in new and _reports_here(key, old[key])]
    position = {key: index for index, key in enumerate(new)}
    return [
        (first, second)
        for first, second in itertools.combinations(in_old, 2)
        if _same_place(first, second) and position[first] > position[second]
    ]


def _reports_here(keyword: str, value: Any) -> bool:
    if keyword == "additionalProperties":
        return value is False  # a schema there reports at the extra property
    return keyword in _GROUP or keyword in ANY_TYPE


def _same_place(first: str, second: str) -> bool:
    groups = {_GROUP.get("required" if k == "additionalProperties" else k) for k in (first, second)}
    return None in groups or len(groups) == 1


def _same_value(old: Any, new: Any) -> bool:
    numbers = (int, float)
    if isinstance(old, numbers) and isinstance(new, numbers):
        return isinstance(old, bool) == isinstance(new, bool) and old == new
    return type(old) is type(new) and old == new


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else f"{text[:77]}..."


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _reason(rel_path: str, pointer: str, what: str) -> str | None:
    if (rel_path, pointer) in ALLOWED:
        return ALLOWED[(rel_path, pointer)]
    if pointer == "/description" and what == "added":
        return ROOT_DESCRIPTION
    return None


def main() -> int:
    old, new = old_schemas(), new_schemas()
    unexpected, allowed, matched = [], [], set()
    if old.keys() != new.keys():
        unexpected.append(f"contract sets differ: {sorted(old.keys() ^ new.keys())}")
    for rel_path in sorted(old.keys() & new.keys()):
        for pointer, what in differences(old[rel_path], new[rel_path]):
            reason = _reason(rel_path, pointer, what)
            line = f"{rel_path}#{pointer}: {what}"
            if reason:
                allowed.append(f"{line}  [{reason}]")
                matched.add((rel_path, pointer))
            else:
                unexpected.append(line)
    unused = sorted(set(ALLOWED) - matched)
    print(f"decoded comparison of {len(new)} published schemas with {OLD_DIR}/ at {BASE}")
    for title, lines in (("allowed", allowed), ("unexpected", unexpected), ("unused allowlist", unused)):
        print(f"{title}: {len(lines)}")
        print("".join(f"  {line}\n" for line in lines), end="")
    return 1 if unexpected or unused else 0


if __name__ == "__main__":
    sys.exit(main())
