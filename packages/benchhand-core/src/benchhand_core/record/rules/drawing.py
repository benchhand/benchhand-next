# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Drawing intent references: tolerance policies against product.yaml, and datum labels against each part
drawing's datum_features. The references sit at many optional places of a drawing, so these rules walk each
document's JSON, keyed as in the file."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import Part, Product, as_json

PRODUCT = documents.PRODUCT.path
DATUM_LABEL = re.compile(r"[A-HJ-NPR-Z]{1,2}")
VIEW_REFERENCES = ("normal_to", "along_axis", "parallel_to", "perpendicular_to", "toward")
VENDOR_DRAWINGS = ("vendor_specification", "source_control")  # they state "per specification", no tolerance

Where = tuple[str | int, ...]


def stated_general_tolerance(policy: dict[str, Any]) -> str | float:
    """The product.yaml general_tolerance that states a tolerance policy."""
    if policy["kind"] == "standard":
        return f"ISO 2768-{policy['class']}"  # ISO 2768-1:1989 is the only standard the contract admits
    return float(policy["linear_mm"])


def _general_tolerance(product: dict[str, Any], drawing: dict[str, Any]) -> Finding | None:
    name = drawing["general_tolerance_policy"]
    policy = drawing["tolerance_policies"].get(name)
    if policy is None:
        message = f"general_tolerance_policy {name} is not in drawing/tolerance_policies"
        where = pointer("drawing", "general_tolerance_policy")
        return error("drawing.policy", PRODUCT, message, pointer=where)
    tolerance = product["general_tolerance"]
    if isinstance(tolerance, dict):
        message = f"general_tolerance is unknown: the {name} policy cannot state it until the user records it"
        return error("drawing.general_tolerance", PRODUCT, message, pointer="/general_tolerance")
    if tolerance != stated_general_tolerance(policy):
        expected = stated_general_tolerance(policy)
        message = f"general_tolerance {tolerance!r} does not state the {name} policy; expected {expected!r}"
        return error("drawing.general_tolerance", PRODUCT, message, pointer="/general_tolerance")
    return None


def _frame_references(drawing: dict[str, Any]) -> Iterator[tuple[Where, Any]]:
    frame = drawing.get("coordinate_frame", {})
    origin = frame.get("origin", {})
    for index, ref in enumerate(origin.get("intersection", [])):
        yield ("coordinate_frame", "origin", "intersection", index), ref
    if "at" in origin:
        yield ("coordinate_frame", "origin", "at"), origin["at"]
    for axis in ("x", "y", "z"):
        for key, ref in frame.get(axis, {}).items():
            yield ("coordinate_frame", axis, key), ref
    for key, ref in drawing.get("manufacturing", {}).get("build_direction", {}).items():
        yield ("manufacturing", "build_direction", key), ref


def _view_references(drawing: dict[str, Any]) -> Iterator[tuple[Where, Any]]:
    for index, view in enumerate(drawing.get("views", [])):
        for key in VIEW_REFERENCES:
            if key in view:
                yield ("views", index, key), view[key]
        through = view.get("through", [])
        for position, ref in enumerate([through] if isinstance(through, str) else through):
            yield ("views", index, "through", *(() if isinstance(through, str) else (position,))), ref


def _datum_references(drawing: dict[str, Any]) -> Iterator[tuple[Where, Any]]:
    """Every place a part drawing may name a datum label, with its pointer below /drawing."""
    yield from _frame_references(drawing)
    yield from _view_references(drawing)
    for name, feature in drawing.get("features", {}).items():
        if "axial_location_from" in feature:
            yield ("features", name, "axial_location_from"), feature["axial_location_from"]
    for collection in ("dimensions", "geometric_tolerances"):
        for index, item in enumerate(drawing.get(collection, [])):
            for position, ref in enumerate(item.get("datum_frame", [])):
                yield (collection, index, "datum_frame", position), ref


def _policy_references(drawing: dict[str, Any]) -> Iterator[tuple[Where, str]]:
    if "tolerance_policy" in drawing:
        yield ("tolerance_policy",), drawing["tolerance_policy"]
    for name, feature in drawing.get("features", {}).items():
        if "tolerance_policy" in feature:
            yield ("features", name, "tolerance_policy"), feature["tolerance_policy"]
    for index, dimension in enumerate(drawing.get("dimensions", [])):
        if "policy" in dimension.get("tolerance", {}):
            yield ("dimensions", index, "tolerance", "policy"), dimension["tolerance"]["policy"]


def _part_policies(part: dict[str, Any], policies: dict[str, Any], path: str) -> Iterator[Finding]:
    for where, name in _policy_references(part["drawing"]):
        policy = policies.get(name)
        if policy is None:
            message = f"tolerance policy {name} is not in {PRODUCT} drawing/tolerance_policies"
        elif part["process"] not in policy["applies_to"]:
            applies = ", ".join(policy["applies_to"])
            message = f"tolerance policy {name} applies to {applies}, not {part['process']}"
        else:
            continue
        yield error("drawing.policy", path, message, pointer=pointer("drawing", *where), subject=part["PN"])


def _part_datums(part: dict[str, Any], path: str) -> Iterator[Finding]:
    declared = part["drawing"].get("datum_features", {})
    for where, ref in _datum_references(part["drawing"]):
        if isinstance(ref, str) and DATUM_LABEL.fullmatch(ref) and ref not in declared:
            message = f"datum {ref} is not declared in drawing/datum_features"
            at = pointer("drawing", *where)
            yield error("drawing.datum", path, message, pointer=at, subject=part["PN"])


def _part(part: dict[str, Any], product: dict[str, Any]) -> list[Finding]:
    path = documents.part(part["PN"]).path
    policies = product.get("drawing", {}).get("tolerance_policies", {})
    findings = [*_part_policies(part, policies, path), *_part_datums(part, path)]
    if part["drawing"]["type"] not in VENDOR_DRAWINGS and isinstance(product["general_tolerance"], dict):
        message = f"{PRODUCT} general_tolerance is unknown; record it before a drawing states one"
        finding = error("drawing.general_tolerance", path, message, pointer="/drawing", subject=part["PN"])
        findings.append(finding)
    return findings


def check(product_model: Product, parts: Mapping[str, Part]) -> list[Finding]:
    product = as_json(product_model)
    findings: list[Finding] = []
    if "drawing" in product and (finding := _general_tolerance(product, product["drawing"])) is not None:
        findings.append(finding)
    for part in map(as_json, parts.values()):
        if "drawing" in part:
            findings.extend(_part(part, product))
    return findings
