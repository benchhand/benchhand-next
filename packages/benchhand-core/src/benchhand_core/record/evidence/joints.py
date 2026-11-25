"""assembly.joint: each joining operation judged from its declared joint facts, on every read.

A port of the prototype's assembly_operations.check_joints (skills/cad-record/scripts/assembly_operations.py
at release.toml reference_commit 412b5d9, lines 633-822) and the evidence.py `_joint_results` reading of it
(evidence.py:859): pass only when every joint fact is sourced and suitable, unknown while one is not, fail on
a violation. Material properties resolve as manufacturing_intent.resolve_property does without conditions
(manufacturing_intent.py:2459).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

from benchhand_core.record.evidence.obligations import JOINING_KINDS
from benchhand_core.record.evidence.use_case import fact_at
from benchhand_core.record.evidence.view import JsonMap, RecordView, items, mapping

QUALIFYING_SOURCES = frozenset(("test", "supplier", "datasheet", "standard", "calibration"))
HOST_TEMPERATURE_KINDS = frozenset(("heat_set", "insert", "press_fit"))
TEMPERATURE_LIMITS = ("max_service_temperature", "heat_deflection_temperature")
EDGE_DISTANCE_KINDS = frozenset(("fasten", "insert", "heat_set"))
LENGTH_MM = {"mm": 1.0, "um": 1e-3, "m": 1e3}
JOINT_METHOD = (
    "declared joint evidence: sourced retention, fastener engagement and torque, edge distance against its "
    "criterion, host service temperature limit (cad-record assembly_operations)"
)

PartOf = Callable[[str], str | None]


@dataclass(frozen=True)
class JointFinding:
    outcome: str  # fail or unknown
    text: str


@dataclass(frozen=True)
class Resolution:
    """A resolved material property: its quantity, basis and sources."""

    value: JsonMap
    basis: str | None
    sources: tuple[JsonMap, ...]


def _number(value: object) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def sourced(fact: object) -> bool:
    """A known fact with a qualifying source (assembly_operations.py:805)."""
    fact = mapping(fact)
    return fact.get("status") == "known" and any(
        mapping(source).get("kind") in QUALIFYING_SOURCES for source in items(fact.get("sources"))
    )


def resolve_property(profile: JsonMap, name: str) -> Resolution | None:
    """Property `name` of a material profile with no requested conditions: resolved when its known values
    agree, None when it has none or they disagree (manufacturing_intent.py:2459)."""
    candidates = [
        mapping(p.get("value"))
        for p in items(profile.get("properties"))
        if p.get("name") == name and mapping(p.get("value")).get("status") == "known"
    ]
    if not candidates or len({str(c.get("value")) for c in candidates}) > 1:
        return None
    match = candidates[0]
    return Resolution(mapping(match.get("value")), match.get("basis"), tuple(items(match.get("sources"))))


def _to_deg_c(value: float, units: object) -> float:
    return value - 273.15 if units == "K" else value


def _upper_deg_c(fact: JsonMap) -> float | None:
    if fact.get("status") != "known":
        return None
    quantity = mapping(fact.get("value"))
    upper = quantity.get("value") if quantity.get("upper") is None else quantity.get("upper")
    return None if not _number(upper) else _to_deg_c(float(upper), quantity.get("units"))


def _criterion_mm(criterion: JsonMap) -> tuple[float, float | None] | None:
    """assembly_operations.py:716."""
    units = criterion.get("units")
    scale = LENGTH_MM.get(units) if isinstance(units, str) else None
    value = criterion.get("value")
    if scale is None:
        return None
    if criterion.get("operator") == ">=" and _number(value):
        return value * scale, None
    if criterion.get("operator") == "between" and isinstance(value, list) and len(value) == 2:
        low, high = value
        if _number(low) and _number(high) and low <= high:
            return low * scale, high * scale
    return None


def _quantity_mm(value: object) -> tuple[float, float] | None:
    """assembly_operations.py:731."""
    value = mapping(value)
    units = value.get("units")
    scale = LENGTH_MM.get(units) if isinstance(units, str) else None
    if scale is None:
        return None
    if _number(value.get("value")):
        return value["value"] * scale, value["value"] * scale
    if _number(value.get("lower")) and _number(value.get("upper")):
        return value["lower"] * scale, value["upper"] * scale
    return None


def _edge_distance(op: JsonMap) -> JointFinding | None:
    """A hole-based joint's edge distance against its criterion (assembly_operations.py:683)."""
    ident, edge = op.get("id"), op.get("edge_distance")
    if not isinstance(edge, Mapping):
        if op.get("kind") in EDGE_DISTANCE_KINDS:
            return JointFinding("unknown", f"{ident}: the {op.get('kind')} records no edge distance")
        return None
    bounds = _criterion_mm(mapping(edge.get("criterion")))
    distance = mapping(edge.get("distance"))
    measured = _quantity_mm(distance.get("value")) if distance.get("status") == "known" else None
    if bounds is None:
        return JointFinding("unknown", f"{ident}: the edge distance criterion is not a length bound")
    if measured is None:
        reason = distance.get("reason") or "not a known length"
        return JointFinding(
            "unknown", f"{ident}: the edge distance is {distance.get('status', 'unknown')}: {reason}"
        )
    (minimum, maximum), (lower, upper) = bounds, measured
    if lower < minimum or (maximum is not None and upper > maximum):
        limit = f">= {minimum:g} mm" if maximum is None else f"between {minimum:g} and {maximum:g} mm"
        return JointFinding(
            "fail", f"{ident}: the edge distance is {lower:g}..{upper:g} mm, the criterion {limit}"
        )
    return None


def _host_profile(op: JsonMap, record: RecordView, part_of: PartOf) -> tuple[JsonMap | None, str]:
    pn = part_of(str(op.get("into")))
    part = record.parts.get(pn) if pn else None
    if part is None:
        return None, f"{op.get('into')} resolves to no part"
    profile_id = mapping(part.get("intent")).get("material_profile")
    profile = record.materials.get(profile_id) if isinstance(profile_id, str) else None
    return profile, f"{pn} has no resolved material profile"


def _host_temperature(op: JsonMap, record: RecordView, part_of: PartOf) -> JointFinding | None:
    """The host of an insert, heat-set or press fit against the use-case temperature; an estimated or
    unsourced limit can only fail it (assembly_operations.py:752)."""
    ident = op.get("id")
    if op.get("kind") not in HOST_TEMPERATURE_KINDS or op.get("into") is None:
        return None
    profile, missing = _host_profile(op, record, part_of)
    if profile is None:
        return JointFinding("unknown", f"{ident}: the host is unknown: {missing}")
    resolved = [(n, r) for n in TEMPERATURE_LIMITS if (r := resolve_property(profile, n)) is not None]
    upper = _upper_deg_c(fact_at(record.use_case, "environment.temperature"))
    if not resolved or upper is None:
        what = "the use-case temperature" if upper is None else f"{profile.get('id')} temperature limit"
        return JointFinding("unknown", f"{ident}: {what} is unknown")
    qualified = next(((n, r) for n, r in resolved if _qualified(r)), None)
    name, resolution = qualified or resolved[0]
    value = resolution.value
    limit = value.get("lower") if value.get("value") is None else value.get("value")
    limit_c = _to_deg_c(float(limit), value.get("units")) if _number(limit) else math.inf
    if upper > limit_c:
        return JointFinding(
            "fail",
            f"{ident}: the use-case temperature reaches {upper:g} deg_C, above {profile.get('id')} {name} "
            f"{limit_c:g} deg_C ({resolution.basis})",
        )
    if qualified is None:
        return JointFinding(
            "unknown",
            f"{ident}: {profile.get('id')} {name} {limit_c:g} deg_C ({resolution.basis}) is not a qualified "
            f"limit (an estimate, or no {', '.join(sorted(QUALIFYING_SOURCES))} source): it cannot show the "
            f"host holds up to {upper:g} deg_C",
        )
    return None


def _qualified(resolution: Resolution) -> bool:
    """assembly_operations.py:799."""
    return resolution.basis != "estimate" and any(
        source.get("kind") in QUALIFYING_SOURCES for source in resolution.sources
    )


def _findings(op: JsonMap, record: RecordView, part_of: PartOf) -> list[JointFinding]:
    ident, kind = op.get("id"), op.get("kind")
    found = []
    if not sourced(op.get("retention")):
        found.append(JointFinding("unknown", f"{ident}: retention of the {kind} is not a sourced fact"))
    if kind == "fasten":
        for name in ("engagement", "torque"):
            if not sourced(op.get(name)):
                found.append(JointFinding("unknown", f"{ident}: thread {name} is not a sourced fact"))
    for finding in (_edge_distance(op), _host_temperature(op, record, part_of)):
        if finding is not None:
            found.append(finding)
    return found


def joint_results(record: RecordView, part_of: PartOf) -> dict[str, tuple[str, str]]:
    """assembly.joint obligation id -> (result, reason) for every joining operation."""
    results = {}
    for op in items(record.operations):
        if not isinstance(op, Mapping) or op.get("kind") not in JOINING_KINDS:
            continue
        found = _findings(op, record, part_of)
        outcomes = {f.outcome for f in found}
        outcome = "fail" if "fail" in outcomes else "unknown" if "unknown" in outcomes else "pass"
        reason = "; ".join(f.text for f in found if f.outcome == outcome) or JOINT_METHOD
        results[f"assembly.joint@op:{op.get('id')}"] = (outcome, reason)
    return results


def default_part_of(ref: str) -> Any:
    """A bare PN names itself; an @occurrence names none (assembly_operations.py:639)."""
    return None if ref.startswith("@") else ref
