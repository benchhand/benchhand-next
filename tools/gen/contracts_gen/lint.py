"""The `jsonschema lint` findings that the published schemas keep, each with its location, name and reason.

``required_properties_in_properties`` reads one schema object: a ``required`` there must name a property of
the same object's ``properties``. A contract also requires a property in a condition about properties the
enclosing object declares (``then``, ``else``, ``not``, an ``allOf`` branch), or beside an ``allOf`` of
``$ref``s that declare it. Those findings are listed here by location and by the property name the
``required`` entry there holds. Any other finding fails, and so does a listed location whose name changed,
so a misspelt name can't reuse an exemption, and an entry the lint no longer reports, so the list can't go
stale.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

CONDITION = "a condition on a property the enclosing object declares"
BESIDE_REF = "beside an allOf of $refs that declare the property"

ALLOWED: dict[str, dict[str, tuple[str, str]]] = {
    "record/common.schema.json": {
        "/$defs/not_assessed_rule/then/required/0": ("reason", CONDITION),
        "/$defs/not_assessed_rule/else/not/required/0": ("reason", CONDITION),
    },
    "record/drawing.schema.json": {
        "/$defs/part_drawing/properties/edges/allOf/1/required/0": ("external", BESIDE_REF),
        "/$defs/part_drawing/properties/edges/allOf/1/required/1": ("internal", BESIDE_REF),
        "/$defs/product_drawing/properties/default_sheet/allOf/1/required/0": ("sizes", BESIDE_REF),
    },
    "record/manufacturing-guideline.schema.json": {
        "/$defs/limit/allOf/0/then/oneOf/0/properties/quantity/required/0": ("value", CONDITION),
        "/$defs/limit/allOf/1/then/properties/quantity/required/0": ("lower", CONDITION),
        "/$defs/limit/allOf/1/then/properties/quantity/required/1": ("upper", CONDITION),
        "/$defs/limit/properties/quantities/items/required/0": ("value", BESIDE_REF),
        "/$defs/relative/properties/floor/required/0": ("value", BESIDE_REF),
        "/$defs/scope/properties/nozzle_diameter/required/0": ("lower", BESIDE_REF),
        "/$defs/scope/properties/nozzle_diameter/required/1": ("upper", BESIDE_REF),
    },
    "record/manufacturing-materials.schema.json": {
        "/$defs/property/allOf/5/then/properties/conditions/not/required/0": ("gauge", CONDITION),
    },
    "record/manufacturing-selection.schema.json": {
        "/$defs/candidate_part/allOf/0/then/properties/route/contains/required/0": ("purchase", CONDITION),
        "/allOf/2/then/properties/assessment/required/0": ("decision", CONDITION),
    },
}
"""Published path -> JSON pointer -> (required name, reason), of each
``required_properties_in_properties`` finding kept."""


def _location(error: dict[str, Any]) -> tuple[str, str]:
    parts = PurePosixPath(error["path"]).parts
    rel_path = "/".join(parts[parts.index("schemas") + 1 :])
    tokens = (str(part).replace("~", "~0").replace("/", "~1") for part in error["schemaLocation"])
    return rel_path, "".join(f"/{token}" for token in tokens)


def _named(error: dict[str, Any]) -> Any:
    """The value at the finding's location in the linted file: the name a ``required`` entry holds."""
    node: Any = json.loads(Path(error["path"]).read_text(encoding="utf-8"))
    for token in error["schemaLocation"]:
        node = node[token]
    return node


def unexpected(report: str) -> tuple[list[str], list[str]]:
    """The findings of a ``jsonschema lint --json`` report that aren't in ``ALLOWED`` with the same name,
    and the entries of ``ALLOWED`` it doesn't report."""
    errors = json.loads(report).get("errors", [])
    found = {_location(error): (error["id"], _named(error)) for error in errors}
    allowed = {
        (path, pointer): name for path, pointers in ALLOWED.items() for pointer, (name, _) in pointers.items()
    }
    new = [
        f"{path}#{pointer}: {rule} names {name!r}"
        + (f", the exemption {allowed[path, pointer]!r}" if (path, pointer) in allowed else "")
        for (path, pointer), (rule, name) in sorted(found.items())
        if allowed.get((path, pointer)) != name
    ]
    stale = [f"{path}#{pointer}" for path, pointer in sorted(allowed.keys() - found.keys())]
    return new, stale
