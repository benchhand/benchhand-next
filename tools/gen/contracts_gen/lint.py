"""The `jsonschema lint` findings that the published schemas keep, each at its location with its reason.

``required_properties_in_properties`` reads one schema object: a ``required`` there must name a property of
the same object's ``properties``. A contract also requires a property in a condition about properties the
enclosing object declares (``then``, ``else``, ``not``, an ``allOf`` branch), or beside an ``allOf`` of
``$ref``s that declare it. Those findings are listed here by location; any other one fails, and so does an
entry the lint no longer reports, so the list can't hide a new finding or go stale.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

CONDITION = "a condition on a property the enclosing object declares"
BESIDE_REF = "beside an allOf of $refs that declare the property"

ALLOWED: dict[str, dict[str, str]] = {
    "record/common.schema.json": {
        "/$defs/not_assessed_rule/then/required/0": CONDITION,
        "/$defs/not_assessed_rule/else/not/required/0": CONDITION,
    },
    "record/drawing.schema.json": {
        "/$defs/part_drawing/properties/edges/allOf/1/required/0": BESIDE_REF,
        "/$defs/part_drawing/properties/edges/allOf/1/required/1": BESIDE_REF,
        "/$defs/product_drawing/properties/default_sheet/allOf/1/required/0": BESIDE_REF,
    },
    "record/manufacturing-guideline.schema.json": {
        "/$defs/limit/allOf/0/then/oneOf/0/properties/quantity/required/0": CONDITION,
        "/$defs/limit/allOf/1/then/properties/quantity/required/0": CONDITION,
        "/$defs/limit/allOf/1/then/properties/quantity/required/1": CONDITION,
        "/$defs/limit/properties/quantities/items/required/0": BESIDE_REF,
        "/$defs/relative/properties/floor/required/0": BESIDE_REF,
        "/$defs/scope/properties/nozzle_diameter/required/0": BESIDE_REF,
        "/$defs/scope/properties/nozzle_diameter/required/1": BESIDE_REF,
    },
    "record/manufacturing-materials.schema.json": {
        "/$defs/property/allOf/5/then/properties/conditions/not/required/0": CONDITION,
    },
    "record/manufacturing-selection.schema.json": {
        "/$defs/candidate_part/allOf/0/then/properties/route/contains/required/0": CONDITION,
        "/allOf/2/then/properties/assessment/required/0": CONDITION,
    },
}
"""Published path -> JSON pointer -> reason, of each ``required_properties_in_properties`` finding kept."""


def _location(error: dict[str, Any]) -> tuple[str, str]:
    parts = PurePosixPath(error["path"]).parts
    rel_path = "/".join(parts[parts.index("schemas") + 1 :])
    tokens = (str(part).replace("~", "~0").replace("/", "~1") for part in error["schemaLocation"])
    return rel_path, "".join(f"/{token}" for token in tokens)


def unexpected(report: str) -> tuple[list[str], list[str]]:
    """The findings of a ``jsonschema lint --json`` report that aren't in ``ALLOWED``, and the entries of
    ``ALLOWED`` it doesn't report."""
    found = {_location(error): error["id"] for error in json.loads(report).get("errors", [])}
    allowed = {(path, pointer) for path, pointers in ALLOWED.items() for pointer in pointers}
    new = [f"{path}#{pointer}: {found[path, pointer]}" for path, pointer in sorted(found.keys() - allowed)]
    stale = [f"{path}#{pointer}" for path, pointer in sorted(allowed - found.keys())]
    return new, stale
