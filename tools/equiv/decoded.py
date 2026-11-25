"""Decoded comparison of the published schemas with the hand-written ones they replaced (ADR-0017).

The contracts moved from hand-written JSON Schema to TypeSpec on top of ``BASE``. This compares each
published schema with ``contracts/<path>.schema.json`` at ``BASE``, after JSON decoding:

- every value must be the same, lists in order. Literal data (``const``, ``enum``, ``examples``,
  ``default``, ``required``, ``dependentRequired`` and ``x-*`` values) is compared recursively by JSON type,
  so ``true`` is not ``1`` and ``1`` is not ``1.0``, with a ``required`` list and the keys of a
  ``dependentRequired`` in order, since the validator reports missing properties in that order;
- at each schema node, two keywords that can both report a violation at the same instance path must come
  in the same order. ``benchhand_contracts.violations`` sorts the violations by instance path and keeps
  the validator's order among those at one path, which is the order of the keywords, and
  ``jsonschema.exceptions.best_match`` takes the first of two it ranks alike. So the order decides the
  violation ``validate`` raises, its ``schema_path``, and the order of the list.

No model of where a keyword reports is trusted: every pair of keywords except the ``SILENT`` ones counts
as able to report at one instance path, so the check can only over-report. An order change the source can
express is restored there; one it can't is an ``Allowed`` entry.

Each intended difference is an ``Allowed`` entry with its exact old value, new value, kind and reason,
and anything else fails, as does an entry that matches nothing. ``just contracts-equivalence`` runs it;
``tools/equiv/results/decoded.txt`` holds the output.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
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


class _Absent:
    def __repr__(self) -> str:
        return "absent"


ABSENT: Any = _Absent()
"""The old value of an added keyword, the new value of a removed one."""


@dataclass(frozen=True)
class Difference:
    pointer: str
    kind: str
    """``added``, ``removed``, ``changed``, ``key order`` (of a ``dependentRequired``) or ``keyword order``
    (``old`` and ``new`` are then the two keywords, in each schema's order)."""
    old: Any
    new: Any

    def __str__(self) -> str:
        return f"{self.pointer or '/'}: {self.kind}: {_short(self.old)} -> {_short(self.new)}"


@dataclass(frozen=True)
class Allowed:
    rel_path: str
    pointer: str
    kind: str
    old: Any
    new: Any
    reason: str

    def matches(self, rel_path: str, difference: Difference) -> bool:
        return (
            (rel_path, difference.pointer, difference.kind) == (self.rel_path, self.pointer, self.kind)
            and same_data(difference.old, self.old)
            and same_data(difference.new, self.new)
        )


SILENT = frozenset(
    (
        "$schema", "$id", "$anchor", "$dynamicAnchor", "$comment", "$defs", "$vocabulary", "title",
        "description", "examples", "default", "deprecated", "readOnly", "writeOnly", "then", "else",
        "contentEncoding", "contentMediaType", "contentSchema",
    )
)  # fmt: skip
"""Keywords that never report on their own: annotations, and then/else, which jsonschema reports under if."""
TIMESTAMP = ("jobs/job.schema.json", "/$defs/Timestamp")
TIMESTAMP_PATTERN = (
    "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)"
    "(\\.[0-9]+)?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$"
)
TIMESTAMP_DESCRIPTION = (
    "A date-time, RFC 3339-shaped with an explicit offset: Z or a numeric one, after an uppercase T. The "
    "pattern refuses a lowercase t or z, which the validators of each language disagree on; it doesn't "
    "check that the date exists. The job service writes UTC."
)
EMPTY_SCHEMA_AS_TRUE = "a property schema of {} is written true; both accept every value"
WHOLE_NUMBER = (
    "TypeSpec values are JavaScript numbers, so the example's 20.0 is written 20: the same JSON number, "
    "and an example is an annotation"
)
ALLOWED: tuple[Allowed, ...] = (
    Allowed(
        TIMESTAMP[0], f"{TIMESTAMP[1]}/pattern", "added", ABSENT, TIMESTAMP_PATTERN,
        "an uppercase T and an explicit offset (ADR-0017)",
    ),
    Allowed(
        TIMESTAMP[0], f"{TIMESTAMP[1]}/description", "changed", "UTC, RFC 3339.", TIMESTAMP_DESCRIPTION,
        "the description states the new pattern",
    ),
    Allowed(
        "provider/protocol.schema.json", "/$defs/Limits/required", "removed", [], ABSENT,
        "`required: []` requires nothing",
    ),
    *(
        Allowed("provider/protocol.schema.json", pointer, "changed", {}, True, EMPTY_SCHEMA_AS_TRUE)
        for pointer in (
            "/$defs/ErrorObject/properties/data/properties/detail",
            "/$defs/LogParams/properties/data",
            "/$defs/Request/properties/params",
            "/$defs/Notification/properties/params",
            "/$defs/SuccessResponse/properties/result",
        )
    ),
    *(
        Allowed(rel_path, f"/examples/{pointer}", "changed", float(value), value, WHOLE_NUMBER)
        for rel_path, pointer, value in (
            ("record/interfaces.schema.json", "0/interfaces/0/limits/press_fit/engagement_length_mm", 20),
            ("record/interfaces.schema.json", "0/interfaces/0/limits/heat_set/0/min_depth_mm", 8),
            ("record/interfaces.schema.json", "0/interfaces/0/limits/heat_set/0/engagement_length_mm", 8),
            ("record/manufacturing-guideline.schema.json", "0/limits/4/quantity/value", 2),
            ("record/manufacturing-guideline.schema.json", "0/limits/5/quantity/value", 2),
            ("record/part.schema.json", "1/drawing/edges/internal/0", 0),
            ("record/part.schema.json", "1/drawing/edges/external/1", 0),
        )
    ),
)  # fmt: skip
"""Each difference the migration made on purpose, with its exact old and new value."""
ROOT_DESCRIPTION = "a description added at the contract root, an annotation"


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


def same_data(old: Any, new: Any) -> bool:
    """JSON values equal by JSON type, recursively: ``true`` is not ``1``, and ``1`` is not ``1.0``."""
    if isinstance(old, dict) and isinstance(new, dict):
        return old.keys() == new.keys() and all(same_data(old[key], new[key]) for key in old)
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(map(same_data, old, new))
    return type(old) is type(new) and old == new


def differences(old: Any, new: Any, pointer: str = "") -> Iterator[Difference]:
    """Every difference between two decoded schemas."""
    if isinstance(old, dict) and isinstance(new, dict):
        yield from _object_differences(old, new, pointer)
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
            yield from differences(old_item, new_item, f"{pointer}/{index}")
    elif not same_data(old, new):
        yield Difference(pointer, "changed", old, new)


def _object_differences(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[Difference]:
    yield from _key_differences(old, new, pointer)
    for first, second in same_path_order_changes(old, new):
        yield Difference(pointer or "/", "keyword order", [first, second], [second, first])
    for key in [key for key in old if key in new]:
        child = f"{pointer}/{_escape(key)}"
        if key in DATA_KEYWORDS or key.startswith("x-"):
            yield from _data_differences(key, old[key], new[key], child)
        elif key in SCHEMA_MAPS and isinstance(old[key], dict) and isinstance(new[key], dict):
            yield from _key_differences(old[key], new[key], child)
            for name in [name for name in old[key] if name in new[key]]:
                yield from differences(old[key][name], new[key][name], f"{child}/{_escape(name)}")
        else:
            yield from differences(old[key], new[key], child)


def _key_differences(old: dict[str, Any], new: dict[str, Any], pointer: str) -> Iterator[Difference]:
    for key in sorted(old.keys() - new.keys()):
        yield Difference(f"{pointer}/{_escape(key)}", "removed", old[key], ABSENT)
    for key in sorted(new.keys() - old.keys()):
        yield Difference(f"{pointer}/{_escape(key)}", "added", ABSENT, new[key])


def _data_differences(key: str, old: Any, new: Any, pointer: str) -> Iterator[Difference]:
    both_maps = isinstance(old, dict) and isinstance(new, dict)
    if key == "dependentRequired" and both_maps and old.keys() == new.keys() and list(old) != list(new):
        yield Difference(pointer, "key order", list(old), list(new))
    if key in ("const", "enum"):
        # jsonschema prints repr(const) and repr(enum) in its message, in insertion order, so member order
        # inside these literals is part of the first diagnostic.
        yield from _member_order_differences(old, new, pointer)
    yield from _literal_differences(old, new, pointer)


def _member_order_differences(old: Any, new: Any, pointer: str) -> Iterator[Difference]:
    """Each object inside literal data that lists the same members on both sides, in another order."""
    if isinstance(old, dict) and isinstance(new, dict):
        if old.keys() == new.keys() and list(old) != list(new):
            yield Difference(pointer, "key order", list(old), list(new))
        for key in [key for key in old if key in new]:
            yield from _member_order_differences(old[key], new[key], f"{pointer}/{_escape(key)}")
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
            yield from _member_order_differences(old_item, new_item, f"{pointer}/{index}")


def _literal_differences(old: Any, new: Any, pointer: str) -> Iterator[Difference]:
    """Each leaf of literal data that differs, by JSON type."""
    if isinstance(old, dict) and isinstance(new, dict):
        yield from _key_differences(old, new, pointer)
        for key in [key for key in old if key in new]:
            yield from _literal_differences(old[key], new[key], f"{pointer}/{_escape(key)}")
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
            yield from _literal_differences(old_item, new_item, f"{pointer}/{index}")
    elif not same_data(old, new):
        yield Difference(pointer, "changed", old, new)


def same_path_order_changes(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str]]:
    """Pairs of keywords ``old`` lists in one order and ``new`` in the other. Every keyword that can report
    counts as able to report at any instance path, so this can only over-report an order change."""
    shared = [key for key in old if key in new and key not in SILENT and not key.startswith("x-")]
    position = {key: index for index, key in enumerate(new)}
    return [(a, b) for a, b in itertools.combinations(shared, 2) if position[a] > position[b]]


def reason(rel_path: str, difference: Difference, allowed: tuple[Allowed, ...] = ALLOWED) -> str | None:
    """Why ``difference`` is intended, or None."""
    for entry in allowed:
        if entry.matches(rel_path, difference):
            return entry.reason
    added_at_root = (difference.pointer, difference.kind, difference.old) == ("/description", "added", ABSENT)
    if added_at_root and isinstance(difference.new, str):
        return ROOT_DESCRIPTION
    return None


def _short(value: Any) -> str:
    if value is ABSENT:
        return "absent"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else f"{text[:77]}..."


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def main() -> int:
    old, new = old_schemas(), new_schemas()
    unexpected, allowed, matched = [], [], set()
    if old.keys() != new.keys():
        unexpected.append(f"contract sets differ: {sorted(old.keys() ^ new.keys())}")
    for rel_path in sorted(old.keys() & new.keys()):
        for difference in differences(old[rel_path], new[rel_path]):
            line = f"{rel_path}#{difference}"
            why = reason(rel_path, difference)
            if why is None:
                unexpected.append(line)
                continue
            allowed.append(f"{line}  [{why}]")
            matched.update(i for i, entry in enumerate(ALLOWED) if entry.matches(rel_path, difference))
    unused = [f"{e.rel_path}#{e.pointer}: {e.kind}" for i, e in enumerate(ALLOWED) if i not in matched]
    print(f"decoded comparison of {len(new)} published schemas with {OLD_DIR}/ at {BASE}")
    for title, lines in (("allowed", allowed), ("unexpected", unexpected), ("unused allowlist", unused)):
        print(f"{title}: {len(lines)}")
        print("".join(f"  {line}\n" for line in lines), end="")
    return 1 if unexpected or unused else 0


if __name__ == "__main__":
    sys.exit(main())
