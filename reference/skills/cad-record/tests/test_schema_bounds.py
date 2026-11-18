#!/usr/bin/env python3
"""Hard bounds, plausibility bands, defaults and CLI/env annotations of every tunable parameter in the bundled
schemas (docs/config-audit.md, bounds table). A hard bound is a schema minimum/maximum or enum: a violation is an
error. A plausibility band is an `x-plausible` annotation: a miss is a warning `plausibility.<field>` that the
config loader emits, so it never blocks and the schema does not enforce it. The expected bounds below come from
the audit, not from the schemas."""

from __future__ import annotations

import copy
import importlib.util
import math
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

SKILL = Path(__file__).resolve().parents[1]
EXAMPLE = SKILL.parents[1] / "examples" / "lamp-arm" / "hw"
NODEFAULT: Any = ...
BASE = "https://srobroek.com/cad/schemas/"


def load(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


registry = load("cad_record_schema_registry", SKILL / "scripts" / "schema_registry.py")

# canonical unit -> {unit: (factor, offset)} with value_in_unit = canonical * factor + offset, written by hand
CONVERT: dict[str, dict[str, tuple[float, float]]] = {
    "mm": {"mm": (1, 0), "um": (1000, 0), "m": (0.001, 0)},
    "mm2": {"mm2": (1, 0)},
    "deg_C": {"deg_C": (1, 0), "K": (1, 273.15)},
    "mm_s": {"mm_s": (1, 0), "m_s": (0.001, 0)},
    "rpm": {"rpm": (1, 0), "Hz": (1 / 60, 0)},
    "kW": {"kW": (1, 0), "W": (1000, 0)},
    "MPa": {"MPa": (1, 0), "GPa": (0.001, 0), "bar": (10, 0)},
    "GPa": {"GPa": (1, 0), "MPa": (1000, 0), "bar": (10000, 0)},
    "kN": {"kN": (1, 0), "N": (1000, 0)},
    "g_cm3": {"g_cm3": (1, 0), "kg_m3": (1000, 0)},
    "deg": {"deg": (1, 0), "rad": (math.pi / 180, 0)},
    "dimensionless": {"dimensionless": (1, 0), "percent": (100, 0)},
}


def parse(text: str) -> tuple[float | None, bool, float | None, bool]:
    """Reads '(0, 90]' as (0, open, 90, closed). An empty side is unbounded."""
    low, high = text[1:-1].split(",")
    return (float(low) if low.strip() else None, text[0] == "(",
            float(high) if high.strip() else None, text[-1] == ")")


@dataclass(frozen=True)
class Case:
    row: int
    name: str
    schema: str
    pointer: str
    shape: str  # number | int | pair | quantity | fact | size | enum
    bounds: str  # the audit's hard bound such as "(0, 90]", or the choices joined by commas for an enum
    band: dict[str, Any] | None = None  # expected x-plausible
    default: Any = NODEFAULT
    canon: str = "mm"  # unit of the bounds and band (quantity, fact)
    band_pointer: str | None = None
    default_pointer: str | None = None  # where the default sits when not on the bounded node
    cli: str | None = None
    env: str | None = None
    refused: tuple[str, ...] = ()  # enum values that must fail besides an arbitrary one


def number(row: int, name: str, schema: str, pointer: str, bounds: str, band: dict[str, Any] | None, **extra: Any) -> Case:
    return Case(row, name, schema, pointer, extra.pop("shape", "number"), bounds, band, **extra)


def fact(row: int, name: str, bounds: str, band: dict[str, Any] | None, canon: str, definition: str | None = None,
         schema: str = "manufacturing-capabilities.schema.json") -> Case:
    """A capability parameter or material property: validated as a fact, its band kept on the quantity."""
    definition = definition or name
    return Case(row, name, schema, f"/$defs/fact_{definition}", "fact", bounds,
                band and {**band, "units": canon} if band and "relative_to" not in band else band, canon=canon,
                band_pointer=f"/$defs/qty_{definition}")


def quantity(row: int, name: str, definition: str, bounds: str, band: dict[str, Any] | None, canon: str) -> Case:
    return Case(row, name, "manufacturing-capabilities.schema.json", f"/$defs/qty_{definition}", "quantity", bounds,
                band and {**band, "units": canon}, canon=canon)


PRODUCT = "product.schema.json"
DRAWING = "drawing.schema.json"
LAYOUT = "layout.schema.json"
PART = "part.schema.json"
FEA = "fea-case.schema.json"
PLAN = "motion-plan.schema.json"
TOOLS = "tool-settings.schema.json"
STACK = "stackup.schema.json"
MESH = "/properties/manufacturing/properties/mesh/properties"
PART_MESH = "/properties/manufacture/properties/mesh/properties"
WALL = "/properties/manufacturing/properties/min_wall_mm/properties"
BUILD = "/properties/build_volume/properties"
MATERIAL = "/properties/material/properties"
CONTRIBUTOR = "/properties/contributors/items/properties"

CASES: tuple[Case, ...] = (
    number(3, "min_wall_mm.fdm", PRODUCT, f"{WALL}/fdm", "[0.2, 25]", {"min": 0.4, "max": 3}, default=1.2),
    number(3, "min_wall_mm.cnc", PRODUCT, f"{WALL}/cnc", "[0.2, 25]", {"min": 0.4, "max": 3}),
    number(8, "rigor", PRODUCT, "/properties/rigor", "maker,pro,regulated", None, shape="enum", default="pro"),
    number(9, "design.clearance_margin_mm", PRODUCT, "/properties/design/properties/clearance_margin_mm", "[0, 1]",
           {"max": 0.5}, default=0.1),
    number(10, "build_volume.x_mm", PRODUCT, f"{BUILD}/x_mm", "(0, 2000]", {"min": 20, "max": 500}),
    number(10, "build_volume.y_mm", PRODUCT, f"{BUILD}/y_mm", "(0, 2000]", {"min": 20, "max": 500}),
    number(10, "build_volume.z_mm", PRODUCT, f"{BUILD}/z_mm", "(0, 2000]", {"min": 20, "max": 500}),
    number(11, "build_volume.margin_mm", PRODUCT, f"{BUILD}/margin_mm", "[0, 1000]", {"max": 20}, default=0),
    number(12, "general_tolerance", PRODUCT, "/properties/general_tolerance/oneOf/0", "(0, 5]", {"min": 0.01, "max": 0.5},
           default="ISO 2768-m", default_pointer="/properties/general_tolerance"),
    number(13, "profile_tolerance_mm", DRAWING, "/$defs/feature_intent/properties/profile_tolerance_mm", "(0, 5]",
           {"max": 0.5}),
    number(14, "zone_mm", DRAWING, "/$defs/geometric_tolerance/properties/zone_mm", "(0, 10]", {"min": 0.01, "max": 1}),
    number(15, "limit_um", DRAWING, "/$defs/texture_requirement/properties/limit_um", "[0.01, 500]", {"max": 100}),
    number(16, "edge_limits", DRAWING, "/$defs/edge_limits", "[-5, 5]", {"min": -0.5, "max": 0.5}, shape="pair"),
    number(17, "deviation_mm", DRAWING, "/$defs/tolerance/oneOf/1/properties/deviation_mm", "[-10, 10]",
           {"min": -1, "max": 1}, shape="pair"),
    number(18, "heat_set.hole_d", DRAWING, "/$defs/heat_set/properties/hole_d", "(0, 100]", {"min": 1.5, "max": 25}),
    number(18, "heat_set.depth_min", DRAWING, "/$defs/heat_set/properties/depth_min", "(0, 100]", {"min": 1.5, "max": 25}),
    number(19, "limits.linear_mm", DRAWING, "/$defs/tolerance_policy/oneOf/1/properties/linear_mm", "(0, 5]", {"max": 0.5}),
    number(19, "limits.angular_deg", DRAWING, "/$defs/tolerance_policy/oneOf/1/properties/angular_deg", "(0, 10]", {"max": 5}),
    number(20, "layout.mesh.linear_deflection_mm", LAYOUT, f"{MESH}/linear_deflection_mm", "[0.001, 1]",
           {"min": 0.01, "max": 0.2}, default=0.05),
    number(20, "part.mesh.linear_deflection_mm", PART, f"{PART_MESH}/linear_deflection_mm", "[0.001, 1]",
           {"min": 0.01, "max": 0.2}, default=0.05),
    number(21, "layout.mesh.angular_deflection_rad", LAYOUT, f"{MESH}/angular_deflection_rad", f"(0, {math.pi!r}]",
           {"min": 0.05, "max": 0.5}, default=0.1),
    number(21, "part.mesh.angular_deflection_rad", PART, f"{PART_MESH}/angular_deflection_rad", f"(0, {math.pi!r}]",
           {"min": 0.05, "max": 0.5}, default=0.1),
    number(22, "volume_rel_tolerance", PART, "/properties/manufacture/properties/volume_rel_tolerance", "(0, 0.1]",
           {"max": 0.01}),
    number(23, "volume_abs_tolerance_mm3", PART, "/properties/manufacture/properties/volume_abs_tolerance_mm3", "(0, 1000]",
           {"max": 10}),
    number(24, "same_state_volume_rel_tolerance", LAYOUT, "/properties/manufacturing/properties/same_state_volume_rel_tolerance",
           "(0, 0.1]", {"max": 1e-3}, default=1e-9),
    number(25, "mesh_size_extent_ratio", FEA, "/properties/mesh_size_extent_ratio", "[0.001, 0.25]", {"min": 0.005, "max": 0.1},
           default=0.05),
    number(25, "mesh_size", FEA, "/properties/mesh_size", "[0.05, 1000]",
           {"relative_to": "part_extent_mm", "min": 0.005, "max": 0.1}),
    number(26, "timeout_seconds", FEA, "/properties/timeout_seconds", "[10, 86400]", {"max": 3600}, default=600),
    number(27, "required_safety_factor", FEA, "/properties/required_safety_factor", "[1, 10]", {"max": 5}, default=2.0),
    number(28, "material.E", FEA, f"{MATERIAL}/E", "(0, 1200000]", None),
    number(28, "material.density", FEA, f"{MATERIAL}/density", "(0, 25000]", {"min": 500}),
    number(28, "material.yield", FEA, f"{MATERIAL}/yield", "(0, 5000]", None),
    number(29, "material.nu", FEA, f"{MATERIAL}/nu", "(0, 0.5)", {"max": 0.45}),
    number(30, "fps", PLAN, "/properties/fps", "[1, 120]", {"min": 10, "max": 60}, shape="int", default=30),
    number(31, "max_step.deg", PLAN, "/properties/max_step/properties/deg", "(0, 90]", {"max": 10}, default=5),
    number(31, "max_step.mm", PLAN, "/properties/max_step/properties/mm", "(0, 100]", {"max": 10}, default=1),
    number(32, "access.step_mm", TOOLS, "/properties/access/properties/step_mm", "(0, 50]", {"max": 5}, default=1.0,
           cli="--step-mm"),
    number(32, "access.min_step_mm", TOOLS, "/properties/access/properties/min_step_mm", "(0, 50]", {"max": 5},
           default=0.05, cli="--min-step-mm"),
    number(33, "access.separation_margin_mm", TOOLS, "/properties/access/properties/separation_margin_mm", "[0, 10]",
           {"max": 5}, default=1.0),
    number(34, "sweep.mesh_band_mm", TOOLS, "/properties/sweep/properties/mesh_band_mm", "(0, 50]", {"max": 10},
           default=2.0, cli="--mesh-band"),
    number(35, "form_check.fdm_min_radius_mm", TOOLS, "/properties/form_check/properties/fdm_min_radius_mm", "(0, 5]",
           {"min": 0.2, "max": 2}, default=1.0, cli="--fdm-min-radius"),
    number(36, "form_check.cnc_tool_radius_mm", TOOLS, "/properties/form_check/properties/cnc_tool_radius_mm", "(0, 50]",
           {"max": 15}, default=1.0, cli="--cnc-tool-radius"),
    number(37, "form_check.joint_tol_mm", TOOLS, "/properties/form_check/properties/joint_tol_mm", "(0, 1]", {"max": 0.2},
           default=0.05, cli="--joint-tol"),
    number(38, "freecad.job_rss_gib", TOOLS, "/properties/freecad/properties/job_rss_gib", "[0.5, 64]", {"min": 1},
           default=1.5),
    number(39, "render.size", TOOLS, "/properties/render/properties/size", "[100, 9999]", {"min": 640, "max": 4000},
           shape="size", default="1600x1200", cli="--size"),
    number(40, "render.jobs", TOOLS, "/properties/render/properties/jobs", "[1, 8]", {"max": 4}, shape="int", default=1,
           cli="--jobs"),
    number(40, "sweep.jobs", TOOLS, "/properties/sweep/properties/jobs", "[1, 8]", {"max": 4}, shape="int", default=1,
           cli="--jobs"),
    number(41, "preflight.sync_timeout_s", TOOLS, "/properties/preflight/properties/sync_timeout_s", "[1, 7200]",
           {"min": 30}, shape="int", default=1800),
    number(41, "preflight.import_timeout_s", TOOLS, "/properties/preflight/properties/import_timeout_s", "[1, 7200]",
           {"min": 30}, shape="int", default=1800),
    number(41, "preflight.startup_timeout_s", TOOLS, "/properties/preflight/properties/startup_timeout_s", "[1, 7200]",
           {"min": 30}, shape="int", default=60),
    number(42, "render.raster_threads", TOOLS, "/properties/render/properties/raster_threads", "1", None, shape="enum", default="1",
           env="CAD_RENDER_RASTER_THREADS"),
    number(43, "calibration.samples", "manufacturing-capabilities.schema.json",
           "/$defs/calibration/properties/result/properties/samples", "[1, ]", {"min": 3}, shape="int"),
    quantity(44, "calibration.bridge_span", "bridge_span", "[0, 256]", {"max": 50}, "mm"),
    quantity(44, "calibration.overhang_angle", "overhang_angle", "[0, 90]", {"min": 20, "max": 70}, "deg"),
    quantity(44, "calibration.min_wall", "min_wall", "[0.1, 25]", {"min": 0.4, "max": 3}, "mm"),
    quantity(44, "calibration.deviation", "deviation", "[-2, 2]", {"min": -0.5, "max": 0.5}, "mm"),
    quantity(0, "calibration.min_bed_contact_area", "min_bed_contact_area", "(0,)", None, "mm2"),
    fact(45, "nozzle_diameter", "(0, 3]", {"min": 0.2, "max": 1.2}, "mm"),
    fact(45, "layer_height", "(0, 3]", {"relative_to": "nozzle_diameter", "max": 0.8}, "mm"),
    fact(45, "hotend_max_temperature", "[0, 500]", {"max": 300}, "deg_C"),
    fact(45, "bed_max_temperature", "[0, 150]", {"max": 120}, "deg_C"),
    fact(45, "max_speed", "(0, 1000]", {"max": 500}, "mm_s"),
    fact(46, "travel_x", "(0, 10000]", {"max": 2000}, "mm"),
    fact(46, "travel_y", "(0, 10000]", {"max": 2000}, "mm"),
    fact(46, "travel_z", "(0, 10000]", {"max": 2000}, "mm"),
    fact(46, "spindle_max_speed", "(0, 200000]", {"max": 60000}, "rpm"),
    fact(47, "power", "(0, 10]", {"max": 0.3}, "kW"),
    fact(47, "pump_pressure", "(0, 700]", {"max": 450}, "MPa"),
    fact(47, "press_brake_force", "(0, 10000]", None, "kN"),
    fact(48, "modulus", "(0, 1200]", None, "GPa", schema="manufacturing-materials.schema.json"),
    fact(48, "density", "(0, 25]", {"min": 0.5}, "g_cm3", schema="manufacturing-materials.schema.json"),
    fact(48, "temperature", "(-273.15, 1000]", {"max": 300}, "deg_C", schema="manufacturing-materials.schema.json"),
    fact(48, "poisson_ratio", "[0, 0.5)", {"max": 0.45}, "dimensionless", "poisson",
         schema="manufacturing-materials.schema.json"),
    number(49, "min_clearance_mm", "interfaces.schema.json", "/properties/interfaces/items/properties/min_clearance_mm",
           "(0, 5]", {"max": 1}),
    number(50, "tol", STACK, f"{CONTRIBUTOR}/tol", "[0, 5]", {"max": 1}),
    number(50, "tol_plus", STACK, f"{CONTRIBUTOR}/tol_plus", "[0, 5]", {"max": 1}),
    number(50, "tol_minus", STACK, f"{CONTRIBUTOR}/tol_minus", "[0, 5]", {"max": 1}),
    number(51, "coverage_factor", STACK, "/properties/statistics/properties/coverage_factor", "[1, 6]",
           {"min": 1.96, "max": 3.5}, default=2),
    number(52, "confidence", "manufacturing.schema.json", "/$defs/uncertainty/properties/confidence", "(0, 1]", {"min": 0.2}),
    number(53, "weight", "requirements.schema.json", "/properties/preferences/items/properties/weight", "(0, 1000]",
           {"max": 100}),
    number(53, "min_visible_fraction", "requirements.schema.json",
           "/properties/requirements/items/properties/visibility/items/properties/min_visible_fraction", "(0, 1]", None,
           default=0.5),
    number(54, "crank_radius_mm", "assembly.schema.json", "/$defs/mechanism/properties/crank_radius_mm", "(0, 1000]",
           {"max": 200}),
    number(54, "rod_length_mm", "assembly.schema.json", "/$defs/mechanism/properties/rod_length_mm", "(0, 1000]",
           {"max": 500}),
    number(54, "period_deg", "assembly.schema.json", "/$defs/profile/properties/period_deg", "(0, 360]", None),
    number(55, "mass_target", PART, "/properties/mass_target", "(0, 10000000]", {"max": 50000}),
    number(55, "bom.mass", "bom-row.schema.json", "/properties/mass", "(0, 10000000]", {"max": 50000}),
    # Fields outside the audit's 55 rows (row 0)
    number(0, "form_check.fidelity", TOOLS, "/properties/form_check/properties/fidelity", "F0,F1,F2,F3", None, shape="enum",
           default="F2", cli="--fidelity", refused=("F4", "f2")),
    number(0, "easing", PLAN, "/properties/segments/items/properties/easing", "linear,ease_in_out", None, shape="enum",
           default="linear", refused=("ease", "LINEAR")),
    number(0, "camera", PLAN, "/properties/segments/items/properties/camera", "iso,front,side", None, shape="enum",
           default="iso", refused=("back", "ISO")),
    number(0, "coverage", PLAN, "/properties/coverage", "full,partial", None, shape="enum", default="full",
           refused=("half", "Full")),
    number(0, "hold_frames", PLAN, "/properties/segments/items/properties/hold_frames", "[1, 10000]", None, shape="int"),
    number(0, "interface.margin_mm", "interfaces.schema.json", "/properties/interfaces/items/properties/margin_mm", "[0, 1]",
           {"max": 0.5}),
)
BY_NAME = {case.name: case for case in CASES}
# Rows of the audit table that live only in the product.yaml `flow.profile` schema, which flow PR 1 owns
FLOW_PROFILE_ROWS = {1, 2, 4, 5, 6, 7}
# Fields that state a fact about a real material, machine or part: they have no default
FACTS = {
    "build_volume.x_mm", "build_volume.y_mm", "build_volume.z_mm",
    "profile_tolerance_mm", "zone_mm", "limit_um", "edge_limits", "deviation_mm", "heat_set.hole_d", "heat_set.depth_min",
    "limits.linear_mm", "limits.angular_deg", "min_wall_mm.cnc", "volume_rel_tolerance", "volume_abs_tolerance_mm3",
    "material.E", "material.density", "material.yield", "material.nu", "calibration.samples", "calibration.bridge_span",
    "calibration.overhang_angle", "calibration.min_wall", "calibration.deviation", "calibration.min_bed_contact_area", "nozzle_diameter", "layer_height",
    "hotend_max_temperature", "bed_max_temperature", "max_speed", "travel_x", "travel_y", "travel_z", "spindle_max_speed",
    "power", "pump_pressure", "press_brake_force", "modulus", "density", "temperature", "poisson_ratio", "min_clearance_mm",
    "tol", "tol_plus", "tol_minus", "confidence", "weight", "crank_radius_mm", "rod_length_mm",
    "period_deg", "mass_target", "bom.mass",
}
# An explicit override that has no default of its own: mesh_size_extent_ratio carries the default and mesh_size wins when set
OVERRIDES = {"mesh_size", "interface.margin_mm"}
# Facts whose plausibility band waits for data: the reason, and the issue that tracks it
BAND_PENDING = {
    "calibration.min_bed_contact_area": "the only fixtures are one calibration of 20 to 25 mm2, too few to size a band; #141",
}
# Content of a document that the author states, where no default fits
CONTENT = {"hold_frames"}
# Schemas that describe tunables and list their enums too. The other schemas hold vocabularies
SURFACES = {"fea-case.schema.json", "motion-plan.schema.json", "tool-settings.schema.json", "stackup.schema.json"}
# Nodes with a bound the audit does not cover: counters, indices and geometry facts bounded only by sign
NOT_IN_AUDIT = {
    ("assembly.schema.json", "/$defs/drawing_item/properties/item"): "a 1-based item index",
    ("bom-row.schema.json", "/properties/level"): "a tree depth",
    ("bom-row.schema.json", "/properties/qty"): "an instance count",
    ("drawing.schema.json", "/$defs/view/properties/sheet"): "a sheet number",
    ("drawing.schema.json", "/$defs/dimension_request/properties/instance"): "a 1-based instance index",
    ("drawing.schema.json", "/$defs/fit/properties/engagement_length_mm"): "sign-only; the upper bound is tracked in #141 and follows the part geometry",
    ("drawing.schema.json", "/$defs/heat_set/properties/engagement_length_mm"): "sign-only; the upper bound is tracked in #141 and follows the part geometry",
    ("evidence-run.schema.json", "/$defs/step/properties/seconds"): "sign-only; a measured step duration in a run report, an output and not a setting",
    ("finding.schema.json", "/properties/location/properties/line"): "a 1-based source line number in a finding, an index and not a setting",
    ("fea-case.schema.json", "/properties/solid_index"): "a 1-based index",
    ("manufacturing-capabilities.schema.json", "/$defs/profile/properties/revision"): "a revision counter",
    ("manufacturing-materials.schema.json", "/$defs/profile/properties/revision"): "a revision counter",
    ("manufacturing.schema.json", "/$defs/money/properties/amount"): "sign-only; a plausibility band is tracked in #141",
    ("part.schema.json", "/$defs/component/properties/multiplicity"): "an instance count",
    ("release-manifest.schema.json", "/$defs/v2/properties/manufacturing/additionalProperties/properties/quantity"): "a unit count",
    ("release-manifest.schema.json", "/$defs/v3/properties/manufacturing/additionalProperties/properties/quantity"): "a unit count",
}
# Nodes that a listed case covers without a case of their own
COVERED_BY = {("motion-plan.schema.json", "/properties/max_step"): "its default repeats the defaults of deg and mm"}
# The absurd values the audit lists, in each case's own unit. The schema must refuse all of them
ABSURD: tuple[tuple[str, str, Any], ...] = (
    ("calibrated bridge of 500 mm", "calibration.bridge_span", 500),
    ("negative calibrated wall of -2 mm", "calibration.min_wall", -2),
    ("layer height of 5 mm", "layer_height", 5),
    ("required_safety_factor of 0.2", "required_safety_factor", 0.2),
    ("mesh_size of 1e-6 mm", "mesh_size", 1e-6),
    ("mesh_size_extent_ratio of 1e-6", "mesh_size_extent_ratio", 1e-6),
    ("timeout of 1e9 s", "timeout_seconds", 1e9),
    ("motion max_step of 180 deg", "max_step.deg", 180),
    ("layout STL deflection of 10 mm", "layout.mesh.linear_deflection_mm", 10),
    ("part STL deflection of 10 mm", "part.mesh.linear_deflection_mm", 10),
    ("product min wall of 0.001 mm", "min_wall_mm.fdm", 0.001),
    ("general_tolerance of 100 mm", "general_tolerance", 100),
    ("build volume of 1e6 mm", "build_volume.x_mm", 1e6),
    ("E of 1e9 GPa, in MPa", "material.E", 1e12),
    ("modulus of 1e9 GPa", "modulus", 1e9),
    ("-500 deg_C", "temperature", -500),
    ("raster threads of 16", "render.raster_threads", "16"),
)


def document(schema: str) -> Any:
    return registry.schema(registry.SCHEMAS, schema)


def node(schema: str, pointer: str) -> Any:
    found = document(schema)
    for part in pointer.split("/")[1:]:
        found = found[int(part)] if isinstance(found, list) else found[part.replace("~1", "/").replace("~0", "~")]
    return found


def validator(case: Case) -> Any:
    ref = f"{BASE}{case.schema}#{quote(case.pointer)}"
    return registry.ref_validator(registry.SCHEMAS, ref)


def instances(case: Case, value: Any, unit: str | None = None, side: str | None = None, partner: float | None = None) -> list[Any]:
    """The documents that put `value` (in `unit`, default the canonical one) into the case's field. For a quantity,
    `side` ("lower" or "upper") gives one ordered interval whose other endpoint is `partner`, so a single endpoint
    can be the only one outside its bound."""
    unit = unit or case.canon
    if case.shape == "pair":
        return [[value, 0], [0, value]]
    if case.shape == "size":
        value = int(value)
        return [f"{value}x{value}", f"{value}x1600", f"1600x{value}"]
    if case.shape in ("quantity", "fact"):
        both = [{"value": value, "units": unit}, {"lower": value, "upper": value, "units": unit}]
        if side:
            ends = {"lower": value, "upper": partner} if side == "lower" else {"lower": partner, "upper": value}
            both = [{**ends, "units": unit}]
        return both if case.shape == "quantity" else [{"status": "known", "value": item} for item in both]
    return [value]


def accepted(case: Case, value: Any, unit: str | None = None, side: str | None = None, partner: float | None = None) -> bool:
    return all(validator(case).is_valid(item) for item in instances(case, value, unit, side, partner))


def rejected(case: Case, value: Any, unit: str | None = None, side: str | None = None, partner: float | None = None) -> bool:
    """Whether the schema refuses every instance."""
    return not any(validator(case).is_valid(item) for item in instances(case, value, unit, side, partner))


def units_of(case: Case) -> dict[str, tuple[float, float]]:
    return CONVERT[case.canon] if case.shape in ("quantity", "fact") else {"": (1, 0)}


def shifted(case: Case, value: float, unit: str) -> float:
    factor, offset = units_of(case)[unit]
    return value * factor + offset


def nudge(value: float, direction: int) -> float:
    return value + direction * 1e-6 * max(1.0, abs(value))


def check_bounds(test: unittest.TestCase, case: Case, accept: Any, reject: Any, label: str = "") -> None:
    """Runs the boundary matrix of `case` through `accept(value, unit, side, partner)` and `reject(...)`. Each hard
    bound refuses a value just outside it and accepts one just inside. A bound that includes its own value accepts it.
    A quantity also gets ordered intervals: only its lower endpoint moves, then only its upper one, while the other
    endpoint sits mid-range, so removing one bound cannot hide behind the other. Other units than the canonical one
    use a nudge, because their conversion is inexact."""
    low, low_open, high, high_open = parse(case.bounds)
    ordered = case.shape in ("quantity", "fact")
    middle = (low + high) / 2 if low is not None and high is not None else (low + 1 if low is not None else high - 1)
    for unit in units_of(case):
        partner = shifted(case, middle, unit)
        exact = unit in ("", case.canon)
        for bound, is_open, direction in ((low, low_open, -1), (high, high_open, 1)):
            if bound is None:
                continue
            edge = shifted(case, bound, unit)
            step = 1 if case.shape in ("int", "size") else None
            outside = edge + direction * step if step else nudge(edge, direction)
            inside = edge - direction * step if step else nudge(edge, -direction)
            side = ("lower" if direction < 0 else "upper") if ordered else None
            with test.subTest(case.name, label=label, unit=unit, bound=bound):
                test.assertTrue(reject(outside, unit or None), f"{outside} should be refused")
                test.assertTrue(reject(outside, unit or None, side, partner), f"only the {side} endpoint {outside} should be refused")
                if exact:
                    test.assertEqual(accept(edge, unit or None), not is_open, f"the bound {edge}")
                    test.assertEqual(accept(edge, unit or None, side, partner), not is_open, f"the {side} endpoint at the bound {edge}")
                test.assertTrue(accept(inside, unit or None), f"{inside} should be accepted")
                test.assertTrue(accept(inside, unit or None, side, partner), f"the {side} endpoint {inside} should be accepted")


class Rows(unittest.TestCase):
    def test_every_audit_row_is_covered_or_belongs_to_the_flow_profile(self) -> None:
        covered = {case.row for case in CASES} - {0}
        self.assertEqual(covered | FLOW_PROFILE_ROWS, set(range(1, 56)))
        self.assertFalse(covered & FLOW_PROFILE_ROWS)

    def test_a_value_just_outside_each_hard_bound_is_an_error_and_the_bound_itself_is_accepted(self) -> None:
        for case in CASES:
            if case.shape != "enum":
                check_bounds(self, case, lambda value, unit, side=None, partner=None, c=case: accepted(c, value, unit, side, partner),
                             lambda value, unit, side=None, partner=None, c=case: rejected(c, value, unit, side, partner))

    def test_an_enum_field_accepts_its_choices_and_refuses_anything_else(self) -> None:
        for case in (c for c in CASES if c.shape == "enum"):
            with self.subTest(case.name):
                for choice in case.bounds.split(","):
                    self.assertTrue(validator(case).is_valid(choice), choice)
                for value in ("bogus", *case.refused):
                    self.assertFalse(validator(case).is_valid(value), value)

    def test_the_audits_absurd_values_are_all_refused(self) -> None:
        for label, name, value in ABSURD:
            with self.subTest(label):
                self.assertTrue(rejected(BY_NAME[name], value))

    def test_a_default_is_recorded_where_the_code_has_one(self) -> None:
        for case in (c for c in CASES if c.default is not NODEFAULT):
            with self.subTest(case.name):
                self.assertEqual(node(case.schema, case.default_pointer or case.pointer)["default"], case.default)

    def test_only_a_fact_or_an_override_has_no_default(self) -> None:
        """A tunable has a default. A fact about a real material, machine or part stays unknown until sourced."""
        without = {case.name for case in CASES if case.default is NODEFAULT}
        self.assertEqual(without - FACTS - CONTENT, OVERRIDES)

    def test_a_fact_has_no_default_in_its_schema(self) -> None:
        for case in (c for c in CASES if c.name in FACTS):
            with self.subTest(case.name):
                self.assertNotIn("default", node(case.schema, case.default_pointer or case.pointer))


class Bands(unittest.TestCase):
    def band_of(self, case: Case) -> Any:
        return node(case.schema, case.band_pointer or case.pointer).get("x-plausible")

    def test_each_band_is_the_audits_and_lies_inside_the_hard_bounds(self) -> None:
        for case in CASES:
            with self.subTest(case.name):
                self.assertEqual(self.band_of(case), case.band)
                if case.band is None or "relative_to" in case.band:
                    continue
                for edge in (case.band.get("min"), case.band.get("max")):
                    if edge is not None:
                        self.assertTrue(accepted(case, edge), f"band edge {edge} is outside the hard bounds")

    def test_every_band_in_every_schema_is_a_listed_one(self) -> None:
        """A band added to a schema without a row in CASES fails here, so none escapes the table."""
        listed = {(c.schema, c.band_pointer or c.pointer) for c in CASES if c.band}
        found = set()
        for path in sorted(registry.SCHEMAS.glob("*.schema.json")):
            found |= {(path.name, pointer) for pointer, item in walk(document(path.name)) if "x-plausible" in item}
        self.assertEqual(found, listed)
        for schema, pointer in found:
            band = node(schema, pointer)["x-plausible"]
            low, high = band.get("min"), band.get("max")
            self.assertTrue(low is None or high is None or low < high, (schema, pointer))


def listed_pointers() -> set[tuple[str, str]]:
    """The (schema, pointer) of every node a case pins: its field, its band, its default and the items of a pair."""
    found = set()
    for case in CASES:
        for pointer in (case.pointer, case.band_pointer, case.default_pointer):
            if pointer:
                found.add((case.schema, pointer))
        if case.shape == "pair":
            found.add((case.schema, f"{case.pointer}/items"))
        if case.shape in ("quantity", "fact"):
            found |= {(case.schema, pointer) for pointer in unit_branches(case)}
    return found | set(COVERED_BY)


def unit_branches(case: Case) -> list[str]:
    """The pointers of the value, lower and upper bounds that the boundary matrix exercises: the allOf branches
    of the quantity definition whose unit the case converts."""
    base = case.band_pointer or case.pointer
    found = []
    for index, branch in enumerate(node(case.schema, base).get("allOf", ())):
        if branch.get("if", {}).get("properties", {}).get("units", {}).get("const") in units_of(case):
            found += [f"{base}/allOf/{index}/then/properties/{key}" for key in ("value", "lower", "upper")]
    return found


class EveryField(unittest.TestCase):
    """A field with a bound, a band, a default or a flag that no case lists fails here, so a new one cannot slip
    past the table. Enums count only in the schemas that describe tunables."""

    KEYS = ("x-plausible", "x-cli", "x-env", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")

    def test_every_bounded_field_is_in_the_table(self) -> None:
        listed = listed_pointers()
        unlisted = []
        for path in sorted(registry.SCHEMAS.glob("*.schema.json")):
            keys = (*self.KEYS, "enum") if path.name in SURFACES else self.KEYS
            for pointer, item in walk(document(path.name)):
                if any(key in item for key in keys) and (path.name, pointer) not in NOT_IN_AUDIT:
                    if (path.name, pointer) not in listed:
                        unlisted.append(f"{path.name}#{pointer}")
        self.assertEqual(unlisted, [], "add each field to CASES, or to NOT_IN_AUDIT with its reason")

    def test_the_audit_exemptions_name_real_bounded_nodes(self) -> None:
        for (schema, pointer), reason in NOT_IN_AUDIT.items():
            with self.subTest(pointer):
                self.assertTrue(reason)
                self.assertTrue(any(key in node(schema, pointer) for key in self.KEYS), "the node has no bound: drop the entry")

    def test_a_pending_band_names_a_case_that_has_none(self) -> None:
        for name, reason in BAND_PENDING.items():
            with self.subTest(name):
                self.assertIn("#141", reason)
                self.assertIsNone(BY_NAME[name].band, "the case has a band now: drop the pending entry")

    def test_the_max_step_default_repeats_its_members_defaults(self) -> None:
        step = node(PLAN, "/properties/max_step")
        self.assertEqual(step["default"], {name: step["properties"][name]["default"] for name in ("deg", "mm")})


class Annotations(unittest.TestCase):
    def test_flags_and_environment_variables_are_those_the_code_uses(self) -> None:
        for case in CASES:
            found = node(case.schema, case.pointer)
            with self.subTest(case.name):
                self.assertEqual(found.get("x-cli"), case.cli)
                self.assertEqual(found.get("x-env"), case.env)


def walk(value: Any, pointer: str = "") -> Any:
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            if key not in ("default", "examples", "const", "enum", "x-plausible"):
                yield from walk(child, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{pointer}/{index}")


class Wiring(unittest.TestCase):
    """The bounds sit on the path a real record takes, not only on a definition nothing reaches."""

    def errors(self, schema: str, data: Any) -> list[str]:
        return [error.message for error in registry.document_validator(registry.SCHEMAS, schema).iter_errors(data)]

    def tst(self) -> dict[str, Any]:
        sys.path.insert(0, str(SKILL.parents[1] / "scripts"))
        from modload import load_module  # noqa: PLC0415 - path set just above
        fixtures = load_module("cad_record_mi_fixtures", Path(__file__).resolve().parent / "fixtures" / "manufacturing_intent.py")
        return copy.deepcopy(fixtures.tst_record())

    def test_a_characteristic_without_a_bound_takes_any_limit(self) -> None:
        schema = "manufacturing-capabilities.schema.json"
        document = self.tst()["manufacturing/capabilities.yaml"]
        calibration = document["profiles"][0]["calibrations"][0]
        calibration["characteristic"] = "flatness"
        calibration["result"]["limits"] = {"value": 50, "units": "mm"}
        self.assertEqual(self.errors(schema, document), [])


CAPABILITIES = "manufacturing-capabilities.schema.json"
MATERIALS = "manufacturing-materials.schema.json"
# The calibration characteristics and material property names that dispatch to a bounded definition
CALIBRATION_NAMES = {
    "calibration.bridge_span": ["bridge_span"], "calibration.overhang_angle": ["overhang_angle"],
    "calibration.min_wall": ["min_wall"],
    "calibration.deviation": ["hole_diameter_deviation", "dimensional_deviation", "profile_deviation"],
    "calibration.min_bed_contact_area": ["min_bed_contact_area"],
}
PROPERTY_NAMES = {
    "modulus": ["youngs_modulus", "flexural_modulus", "shear_modulus", "creep_modulus"], "density": ["density"],
    "temperature": ["heat_deflection_temperature", "vicat_softening_temperature", "glass_transition_temperature",
                    "melting_temperature", "max_service_temperature"],
    "poisson_ratio": ["poisson_ratio"],
}


class Documents(unittest.TestCase):
    """The boundary matrix again, through whole capability and material profile documents and the registry's
    validator. A record dispatches to each parameter, characteristic and property, so a bound that a definition
    holds but no document dispatches to fails here."""

    def setUp(self) -> None:
        sys.path.insert(0, str(SKILL.parents[1] / "scripts"))
        from modload import load_module  # noqa: PLC0415 - path set just above
        fixtures = load_module("cad_record_mi_fixtures", Path(__file__).resolve().parent / "fixtures" / "manufacturing_intent.py")
        self.record = copy.deepcopy(fixtures.tst_record())

    def valid(self, schema: str, document: Any) -> bool:
        return registry.document_validator(registry.SCHEMAS, schema).is_valid(document)

    def known(self, instance: dict[str, Any]) -> dict[str, Any]:
        return {**instance, "sources": [{"kind": "user", "reference": "x", "origin": "lead"}], "basis": "user_declared"}

    def through(self, case: Case, instance: Any, edit: Any) -> bool:
        """Whether the document that `edit` builds around `instance` is valid."""
        schema = case.schema
        document = copy.deepcopy(self.record["manufacturing/capabilities.yaml" if schema == CAPABILITIES else "manufacturing/materials.yaml"])
        edit(document, instance)
        return self.valid(schema, document)

    def run_routes(self, case: Case, label: str, edit: Any) -> None:
        def verdicts(value: float, unit: str | None, side: str | None, partner: float | None) -> list[bool]:
            return [self.through(case, item, edit) for item in instances(case, value, unit, side, partner)]
        check_bounds(self, case, lambda value, unit, side=None, partner=None: all(verdicts(value, unit, side, partner)),
                     lambda value, unit, side=None, partner=None: not any(verdicts(value, unit, side, partner)), label)

    def test_every_capability_parameter_is_bounded_in_a_profile_and_in_a_tool(self) -> None:
        cases = [c for c in CASES if c.schema == CAPABILITIES and c.shape == "fact"]
        self.assertEqual(len(cases), 12)
        for case in cases:
            def in_profile(document: Any, fact: Any, name: str = case.name) -> None:
                document["profiles"][0]["parameters"][name] = self.known(fact)

            def in_tool(document: Any, fact: Any, name: str = case.name) -> None:
                document["profiles"][0]["tools"] = [{"id": "probe", "description": "x", "parameters": {name: self.known(fact)}}]
            self.run_routes(case, "profile", in_profile)
            self.run_routes(case, "tool", in_tool)

    def test_every_calibration_limit_is_bounded_by_its_characteristic(self) -> None:
        cases = [c for c in CASES if c.name in CALIBRATION_NAMES]
        self.assertEqual(len(cases), 5)
        for case in cases:
            for name in CALIBRATION_NAMES[case.name]:
                def edit(document: Any, limits: Any, name: str = name) -> None:
                    calibration = document["profiles"][0]["calibrations"][0]
                    calibration["characteristic"] = name
                    calibration["result"]["limits"] = limits
                self.run_routes(case, name, edit)

    def test_every_material_property_is_bounded_by_its_name(self) -> None:
        cases = [c for c in CASES if c.schema == MATERIALS]
        self.assertEqual(len(cases), 4)
        for case in cases:
            for name in PROPERTY_NAMES[case.name]:
                def edit(document: Any, fact: Any, name: str = name) -> None:
                    prop = document["profiles"][1]["properties"][0]
                    prop["name"] = name
                    prop["value"] = self.known(fact)
                self.run_routes(case, name, edit)

    def test_the_base_profiles_are_valid_so_a_refusal_comes_from_the_bound(self) -> None:
        self.assertTrue(self.valid(CAPABILITIES, self.record["manufacturing/capabilities.yaml"]))
        self.assertTrue(self.valid(MATERIALS, self.record["manufacturing/materials.yaml"]))


BOUND_KEYWORDS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "pattern", "enum", "const"})


def reach(root: str) -> dict[tuple[str, str], tuple[Any, ...]]:
    """The document path to every subschema reachable from the schema `root`, by (file, pointer). A property adds
    its name, items add 0, a map of properties adds a key, and a $ref, allOf, anyOf, oneOf, if, then or else adds
    nothing. The first path found stays."""
    found: dict[tuple[str, str], tuple[Any, ...]] = {}
    queue: list[tuple[str, str, tuple[Any, ...]]] = [(root, "", ())]
    while queue:
        file, pointer, path = queue.pop(0)
        if (file, pointer) in found:
            continue
        found[(file, pointer)] = path
        here = node(file, pointer)
        if not isinstance(here, dict):
            continue
        if "$ref" in here:
            target, _, fragment = here["$ref"].partition("#")
            queue.append((target or file, fragment, path))
        for name, child in (here.get("properties") or {}).items():
            queue.append((file, f"{pointer}/properties/{name.replace('~', '~0').replace('/', '~1')}", (*path, name)))
        for key in ("items", "additionalProperties"):
            if isinstance(here.get(key), dict):
                queue.append((file, f"{pointer}/{key}", (*path, 0 if key == "items" else "key")))
        for key in ("allOf", "anyOf", "oneOf"):
            for index in range(len(here.get(key) or ())):
                queue.append((file, f"{pointer}/{key}/{index}", path))
        for key in ("if", "then", "else"):
            if isinstance(here.get(key), dict):
                queue.append((file, f"{pointer}/{key}", path))
    return found


def nest(path: tuple[Any, ...], leaf: Any) -> Any:
    for step in reversed(path):
        leaf = [leaf] if step == 0 else {step: leaf}
    return leaf


def bound_errors(root: str, data: Any, path: tuple[Any, ...]) -> list[Any]:
    """The bound-keyword errors at `path` or below it, found through the oneOf and anyOf contexts."""
    def leaves(error: Any) -> Any:
        yield error
        for inner in error.context or ():
            yield from leaves(inner)
    found = []
    for top in registry.document_validator(registry.SCHEMAS, root).iter_errors(data):
        found += [e for e in leaves(top) if tuple(e.absolute_path)[:len(path)] == path and e.validator in BOUND_KEYWORDS]
    return found


class Reached(unittest.TestCase):
    """The same matrix for a field under $defs, through the registry's validator. The document follows the path
    from a root schema to the field. Only the bound errors at that path count, so omitted sibling fields do not
    matter."""

    def route(self, case: Case) -> tuple[str, tuple[Any, ...]]:
        roots = [case.schema, *(p.name for p in sorted(registry.SCHEMAS.glob("*.schema.json")) if p.name != case.schema)]
        for root in roots:
            path = REACH.setdefault(root, reach(root)).get((case.schema, case.pointer))
            if path is not None:
                return root, path
        self.fail(f"{case.name}: no document reaches {case.schema}#{case.pointer}")

    def test_every_non_fact_field_is_bounded_where_a_document_puts_it(self) -> None:
        cases = [c for c in CASES if c.shape not in ("fact", "quantity")]
        self.assertGreater(len(cases), 60)
        for case in cases:
            root, path = self.route(case)

            def refused(value: Any, unit: str | None, c: Case = case, r: str = root, p: tuple[Any, ...] = path) -> list[bool]:
                return [bool(bound_errors(r, nest(p, item), p)) for item in instances(c, value, unit)]
            if case.shape == "enum":
                with self.subTest(case.name):
                    self.assertFalse(any(bound_errors(root, nest(path, choice), path) for choice in case.bounds.split(",")))
                    for value in ("bogus", *case.refused):
                        self.assertTrue(bound_errors(root, nest(path, value), path), value)
                continue
            check_bounds(self, case, lambda value, unit, side=None, partner=None, f=refused: not any(f(value, unit)),
                         lambda value, unit, side=None, partner=None, f=refused: all(f(value, unit)), label=root)


REACH: dict[str, dict[tuple[str, str], tuple[Any, ...]]] = {}


class Surfaces(unittest.TestCase):
    """The new schemas take the documents the code reads now."""

    def check(self, schema: str, data: Any) -> list[str]:
        return [error.message for error in registry.document_validator(registry.SCHEMAS, schema).iter_errors(data)]

    def test_a_fea_case_with_explicit_material_validates(self) -> None:
        case = yaml.safe_load("""
step: part.step
material: {E: 2100, nu: 0.35, density: 1240, yield: 50}
mesh_size: 2.0
fixed_faces: {plane: {axis: z, value: 0, tolerance: 0.01}}
loads: [{selector: {plane: {axis: z, value: 10, tolerance: 0.01}}, force: [0, 0, -10]}]
required_safety_factor: 2
timeout_seconds: 600
""")
        self.assertEqual(self.check("fea-case.schema.json", case), [])
        self.assertTrue(self.check("fea-case.schema.json", {**case, "mesh_size": 0}))

    def test_a_motion_plan_validates_and_refuses_unknown_keys(self) -> None:
        plan = yaml.safe_load("""
schema: 1
fps: 30
max_step: {deg: 5, mm: 1}
segments:
  - {id: swivel-out, to: {J-001: 80}, easing: linear, camera: iso}
  - {id: pause, hold_frames: 15}
coverage: partial
coverage_reason: close-up
""")
        self.assertEqual(self.check("motion-plan.schema.json", plan), [])
        self.assertTrue(self.check("motion-plan.schema.json", {**plan, "speed": 1}))
        self.assertTrue(self.check("motion-plan.schema.json", {**plan, "coverage": "half"}))

    def test_the_lamp_arm_example_validates_against_the_bounded_schemas(self) -> None:
        for relative, schema in (("product.yaml", PRODUCT), ("interfaces.yaml", "interfaces.schema.json"),
                                 ("assembly.yaml", "assembly.schema.json"), ("requirements.yaml", "requirements.schema.json"),
                                 ("manufacturing/capabilities.yaml", "manufacturing-capabilities.schema.json"),
                                 ("manufacturing/materials.yaml", "manufacturing-materials.schema.json")):
            path = EXAMPLE / relative
            if path.is_file():
                with self.subTest(relative):
                    self.assertEqual(self.check(schema, yaml.safe_load(path.read_text(encoding="utf-8"))), [])
        for path in sorted(EXAMPLE.glob("parts/*/part.yaml")):
            with self.subTest(path.parent.name):
                self.assertEqual(self.check(PART, yaml.safe_load(path.read_text(encoding="utf-8"))), [])


if __name__ == "__main__":
    unittest.main()
