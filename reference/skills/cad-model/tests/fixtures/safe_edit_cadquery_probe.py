# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "vtk==9.6.2"]
# ///
"""Run the safe edits and the occ Booleans in the CadQuery environment (OCP 7.9) and report the wrapper kind
each template gets back.

Usage: uv run --script safe_edit_cadquery_probe.py
stdout: {"edits", "occ"} as safe_edit_probe.py, and "wrap": {case: {"type", "volume", "stack"}}.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import safe_cases_lib as lib  # noqa: E402
from cadmodel import occ  # noqa: E402
from cadmodel.safe import safe_cut, safe_fuse, safe_intersect  # noqa: E402


def describe(value):
    stack = len(value.vals()) if isinstance(value, cq.Workplane) else None
    return {"type": type(value).__name__, "stack": stack, "volume": occ.volume(occ.to_topods(value))}


def case(call):
    try:
        return describe(call())
    except Exception as error:  # noqa: BLE001
        return {"error": str(error), "type": type(error).__name__}


solid_a, solid_b = cq.Solid.makeBox(10, 10, 10), cq.Solid.makeBox(10, 10, 10, cq.Vector(5, 0, 0))
plane_a, plane_b = cq.Workplane("XY").box(10, 10, 10, centered=False), cq.Workplane("XY").box(10, 10, 10, centered=False).translate((5, 0, 0))
stack = cq.Workplane("XY").add(solid_a)
wrap = {
    "shape_cut": case(lambda: safe_cut(solid_a, solid_b)),
    "shape_fuse": case(lambda: safe_fuse(solid_a, solid_b)),
    "shape_intersect": case(lambda: safe_intersect(solid_a, solid_b)),
    "workplane_cut": case(lambda: safe_cut(plane_a, plane_b)),
    "workplane_fuse": case(lambda: safe_fuse(plane_a, plane_b)),
    "workplane_intersect": case(lambda: safe_intersect(plane_a, plane_b)),
    "workplane_with_shape_tool": case(lambda: safe_cut(plane_a, solid_b)),
    "shape_with_workplane_tool": case(lambda: safe_cut(solid_a, plane_b)),
    "raw_first_with_cadquery_tool": case(lambda: safe_cut(lib.A, solid_b)),
    "raw_first": case(lambda: lib.safe_cut(lib.A, lib.B)),
    "compound_shape": case(lambda: safe_cut(cq.Compound.makeCompound([solid_a]), solid_b)),
    "unknown_wrapper": case(lambda: safe_cut(SimpleNamespace(wrapped=lib.A), lib.B)),
    "workplane_two_objects": case(lambda: safe_cut(cq.Workplane("XY").add(solid_a).add(cq.Solid.makeBox(10, 10, 10, cq.Vector(0, 0, 20))), solid_b)),
}
before = len(stack.vals())
result = safe_cut(stack, solid_b)
wrap["workplane_template_unchanged"] = {"stack_before": before, "stack_after": len(stack.vals()), "same_object": result is stack}
print(json.dumps({"edits": lib.edit_report(), "occ": lib.occ_report(), "diff": lib.diff_report(), "wrap": wrap}))
