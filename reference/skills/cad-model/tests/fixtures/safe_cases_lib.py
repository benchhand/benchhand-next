# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Shared cases for the safe-edit probes: boxes in raw OCP run through the public safe edits and occ.

Imported by the probes, which supply the OCP of their own environment. Each case reports
{"value": volume} or {"error": message, "type": class name, "cause": cause class name}, with the
count of Python warnings raised during the case and, for injected cases, the occ.boolean calls it made.
Volumes are occ.volume, in mm^3.

Boxes: A 0..10 cubed (1000), B is A moved +5 along X (overlap 500), FAR is A moved +100 along X, SMALL is
2 mm cubed inside A (8).
"""

import sys
import warnings
from pathlib import Path

from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.TopoDS import TopoDS_Shape, TopoDS_Shell, TopoDS_Solid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import occ  # noqa: E402
from cadmodel.motion import load_pose  # noqa: E402
from cadmodel.safe import safe_cut, safe_fuse, safe_intersect  # noqa: E402

REAL = occ.boolean


def box(x0, y0, z0, x1, y1, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def scaled(length, height, depth):
    return box(0, 0, 0, length, height, depth)


A, B, FAR, SMALL = scaled(10, 10, 10), box(5, 0, 0, 15, 10, 10), box(100, 0, 0, 110, 10, 10), box(4, 4, 4, 6, 6, 6)
HALF = scaled(5, 10, 10)


def open_shell(whole):
    """A solid whose shell lacks one face: not a valid B-rep."""
    builder = BRep_Builder()
    shell, solid = TopoDS_Shell(), TopoDS_Solid()
    builder.MakeShell(shell)
    for face in occ.subshapes(whole, "FACE")[:-1]:
        builder.Add(shell, face)
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return solid


def record(call):
    """Run `call` and return its volume (or value) or the refusal, and count Python warnings."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = call()
        except Exception as error:  # noqa: BLE001 - the probe reports every failure kind
            cause = error.__cause__
            return {"error": str(error), "type": type(error).__name__, "cause": type(cause).__name__ if cause else None,
                    "warnings": len(caught)}
    if isinstance(value, TopoDS_Shape):
        return {"value": occ.volume(value), "raw": True, "warnings": len(caught)}
    return {"value": value, "warnings": len(caught)}


def returning(shape):
    def boolean(operation, argument, tools, fuzzy=occ.FUZZY_MM):
        return shape
    return boolean


def using(operation_used, extra=()):
    def boolean(operation, argument, tools, fuzzy=occ.FUZZY_MM):
        return REAL(operation_used, argument, [*tools, *extra], fuzzy)
    return boolean


def raising(error):
    def boolean(operation, argument, tools, fuzzy=occ.FUZZY_MM):
        raise error
    return boolean


def injected(boolean, call):
    """Run `call` with occ.boolean replaced by `boolean`, and list the operations it requested."""
    calls = []

    def counting(*args, **kwargs):
        calls.append(args[0])
        return boolean(*args, **kwargs)
    occ.boolean = counting
    try:
        row = record(call)
    finally:
        occ.boolean = REAL
    row["boolean_calls"] = calls
    return row


def edit_report():
    report = {}
    big, big_tool = scaled(1000, 1000, 1000), scaled(1, 1, 1)
    unit, unit_tool = scaled(1, 1, 1), box(0.25, 0.25, 0.25, 0.5, 0.5, 0.5)
    slab = lambda x0, x1: box(x0, 0, 0, x1, 10, 10)  # noqa: E731 - a full-section slab of A
    # Accepted real edits, including results exactly on a bound.
    report["cut_real"] = injected(REAL, lambda: safe_cut(A, B))
    report["cut_small_tool"] = record(lambda: safe_cut(A, SMALL))
    report["cut_two_tools"] = injected(REAL, lambda: safe_cut(A, slab(0, 3), slab(7, 10)))
    report["cut_disjoint_tool"] = record(lambda: safe_cut(A, FAR))
    report["fuse_real"] = injected(REAL, lambda: safe_fuse(A, B))
    report["fuse_contained"] = record(lambda: safe_fuse(A, SMALL))
    report["fuse_disjoint"] = record(lambda: safe_fuse(A, FAR))
    report["fuse_three"] = injected(REAL, lambda: safe_fuse(A, B, FAR))
    report["intersect_real"] = injected(REAL, lambda: safe_intersect(A, B))
    report["intersect_contained"] = record(lambda: safe_intersect(A, SMALL))
    report["intersect_three"] = injected(REAL, lambda: safe_intersect(A, B, box(8, 0, 0, 18, 10, 10)))
    report["intersect_third_disjoint"] = record(lambda: safe_intersect(A, B, FAR))
    report["intersect_disjoint"] = record(lambda: safe_intersect(A, FAR))
    report["cut_everything"] = record(lambda: safe_cut(A, A))
    report["compound_source_counted_once"] = record(lambda: safe_cut(occ.compound([A, B]), FAR))
    report["compound_tool_counted_once"] = record(lambda: safe_cut(scaled(30, 10, 10), occ.compound([A, B])))
    before = [occ.volume(A), occ.volume(B)]
    safe_fuse(A, B)
    report["inputs_after_fuse"] = [before, [occ.volume(A), occ.volume(B)]]
    # Volume bounds, each refused by an injected Boolean result.
    report["cut_below_lower"] = injected(using("common"), lambda: safe_cut(A, SMALL))
    report["cut_above_upper"] = injected(using("fuse"), lambda: safe_cut(A, B))
    report["cut_overlapping_tools_sum"] = injected(returning(slab(0, 1)), lambda: safe_cut(A, slab(0, 5), slab(3, 8)))
    report["cut_disjoint_tools_sum"] = injected(returning(slab(0, 0.5)), lambda: safe_cut(A, slab(0, 5), slab(6, 10)))
    report["fuse_below_largest"] = injected(using("common"), lambda: safe_fuse(A, B))
    report["fuse_below_largest_unequal"] = injected(returning(scaled(7.5, 10, 10)), lambda: safe_fuse(A, HALF))
    report["fuse_above_sum"] = injected(using("fuse", [FAR]), lambda: safe_fuse(A, B))
    report["intersect_above_smallest"] = injected(using("fuse"), lambda: safe_intersect(A, B))
    report["intersect_above_smallest_unequal"] = injected(returning(scaled(7.5, 10, 10)), lambda: safe_intersect(A, HALF))
    report["intersect_later_step_checked"] = injected(returning(unit), lambda: safe_intersect(A, B, FAR))
    # Slack: relative regime on a 1e9 mm^3 part (slack 100 mm^3) and the 1e-6 mm^3 floor on a unit part.
    for name, result, call in (
        ("slack_relative_upper_inside", scaled(1000 + 5e-5, 1000, 1000), lambda: safe_cut(big, big_tool)),
        ("slack_relative_upper_outside", scaled(1000 + 2e-4, 1000, 1000), lambda: safe_cut(big, big_tool)),
        ("slack_relative_lower_inside", scaled(1000 - 5e-5, 1000, 1000), lambda: safe_fuse(big, big_tool)),
        ("slack_relative_lower_outside", scaled(1000 - 2e-4, 1000, 1000), lambda: safe_fuse(big, big_tool)),
        ("slack_floor_upper_inside", scaled(1, 1, 1 + 5e-7), lambda: safe_cut(unit, unit_tool)),
        ("slack_floor_upper_outside", scaled(1, 1, 1 + 5e-6), lambda: safe_cut(unit, unit_tool)),
        ("slack_floor_lower_inside", scaled(1, 1, 1 - 5e-7), lambda: safe_fuse(unit, unit_tool)),
        ("slack_floor_lower_outside", scaled(1, 1, 1 - 5e-6), lambda: safe_fuse(unit, unit_tool)),
    ):
        report[name] = injected(returning(result), call)
    # Result checks.
    report["error_cut"] = injected(raising(occ.GeometryError("boom")), lambda: safe_cut(A, B))
    report["error_fuse"] = injected(raising(occ.GeometryError("boom")), lambda: safe_fuse(A, B))
    report["error_intersect"] = injected(raising(occ.GeometryError("boom")), lambda: safe_intersect(A, B))
    report["error_other"] = injected(raising(RuntimeError("odd")), lambda: safe_cut(A, B))
    report["result_invalid"] = injected(returning(open_shell(A)), lambda: safe_fuse(A, B))
    report["result_empty_cut"] = injected(returning(occ.compound([])), lambda: safe_cut(A, B))
    report["result_empty_fuse"] = injected(returning(occ.compound([])), lambda: safe_fuse(A, B))
    report["result_empty_intersect"] = injected(returning(occ.compound([])), lambda: safe_intersect(A, B))
    report["result_overlapping_fuse"] = injected(returning(occ.compound([A, B])), lambda: safe_fuse(A, B))
    report["result_overlapping_cut"] = injected(returning(occ.compound([A, B])), lambda: safe_cut(A, SMALL))
    report["result_tiny_intersection"] = injected(returning(scaled(1e-3, 1e-3, 1e-3)), lambda: safe_intersect(A, B))
    report["result_small_intersection"] = injected(returning(scaled(1e-1, 1e-1, 1e-1)), lambda: safe_intersect(A, B))
    report["result_just_above_floor"] = injected(returning(scaled(0.05, 0.05, 0.05)), lambda: safe_intersect(A, B))
    report["result_just_below_floor"] = injected(returning(scaled(0.04, 0.04, 0.04)), lambda: safe_intersect(A, B))
    # Inputs: each refusal runs no Boolean.
    for name, call in {
        "type_source": lambda: safe_cut("text", B),
        "type_tool_1": lambda: safe_cut(A, 5),
        "type_tool_2": lambda: safe_cut(A, B, None),
        "type_fuse_source": lambda: safe_fuse(3.5, B),
        "type_fuse_input_2": lambda: safe_fuse(A, B, object()),
        "type_intersect_source": lambda: safe_intersect([], B),
        "type_intersect_input_1": lambda: safe_intersect(A, b"x"),
        "null_source": lambda: safe_cut(TopoDS_Shape(), B),
        "null_tool": lambda: safe_cut(A, TopoDS_Shape()),
        "null_fuse_input_1": lambda: safe_fuse(A, TopoDS_Shape()),
        "null_intersect_source": lambda: safe_intersect(TopoDS_Shape(), B),
        "invalid_source": lambda: safe_cut(open_shell(A), B),
        "invalid_tool_2": lambda: safe_cut(A, B, open_shell(A)),
        "invalid_fuse_input_1": lambda: safe_fuse(A, open_shell(A)),
        "invalid_intersect_input_1": lambda: safe_intersect(A, open_shell(A)),
        "no_solid_source": lambda: safe_cut(occ.compound([]), B),
        "no_solid_tool": lambda: safe_cut(A, occ.compound([])),
        "no_solid_face": lambda: safe_fuse(A, occ.subshapes(B, "FACE")[0]),
        "no_solid_intersect_source": lambda: safe_intersect(occ.compound([]), B),
        "inside_out_source": lambda: safe_cut(A.Reversed(), B),
        "inside_out_tool": lambda: safe_cut(A, B.Reversed()),
        "inside_out_fuse_input_1": lambda: safe_fuse(A, B.Reversed()),
        "inside_out_intersect_source": lambda: safe_intersect(A.Reversed(), B),
        "first_failure_wins": lambda: safe_cut(A, TopoDS_Shape(), "text", open_shell(A)),
        "arity_cut": lambda: safe_cut("text"),
        "arity_fuse": lambda: safe_fuse("text"),
        "arity_intersect": lambda: safe_intersect("text"),
    }.items():
        report[name] = injected(returning(A), call)
    return report


def occ_report():
    report = {}
    report["slack"] = {name: occ.volume_slack(*values) for name, values in {
        "none": (), "zero": (0.0,), "unit": (1.0,), "ten": (10.0,), "hundred": (100.0,), "million": (1e6,),
        "negative": (-1e6, 5.0), "largest_of_many": (3e6, 1e6, 2e6), "equal_pair": (1e6, 1e6),
        "tiny_pair": (5.0, 0.5), "mixed_sign_floor": (-0.5, 2.0)}.items()}
    report["bool_cut"] = record(lambda: occ.boolean("cut", A, [B]))
    report["bool_fuse"] = record(lambda: occ.boolean("fuse", A, [B]))
    report["bool_common"] = record(lambda: occ.boolean("common", A, [B]))
    report["bool_positional_fuzzy"] = record(lambda: occ.boolean("common", A, [B], 1e-7))
    report["bool_generator_tools"] = record(lambda: occ.boolean("cut", A, (t for t in [box(0, 0, 0, 3, 10, 10), box(7, 0, 0, 10, 10, 10)])))
    report["bool_tuple_tools"] = record(lambda: occ.boolean("cut", A, (box(0, 0, 0, 3, 10, 10), box(7, 0, 0, 10, 10, 10))))
    empty = occ.boolean("common", A, [FAR])
    report["bool_disjoint_common"] = {"solids": occ.count(empty, "SOLID"), "volume": occ.volume(empty)}
    report["bool_unknown_operation"] = record(lambda: occ.boolean("xor", A, [B]))
    keep, tool = scaled(10, 10, 10), box(5, 0, 0, 15, 10, 10)
    faces = occ.count(keep, "FACE")
    occ.boolean("cut", keep, [tool])
    occ.boolean("fuse", keep, [tool])
    report["bool_inputs_unchanged"] = {"volume": occ.volume(keep), "faces": [faces, occ.count(keep, "FACE")],
                                       "tool_volume": occ.volume(tool)}
    pose = load_pose()
    pairs = {"sphere_and_box": lambda: (BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 6).Shape(), box(0, 0, 0, 7, 7, 7)),
             "near_touching_boxes": lambda: (scaled(10, 10, 10), box(10.0000005, 0, 0, 20, 10, 10)),
             "box_and_crossing_cylinder": lambda: (scaled(10, 10, 10), BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5, 5, -5), gp_Dir(0, 0, 1)), 3, 20).Shape())}
    unchanged = {}
    for name, make in pairs.items():
        for operation in ("cut", "fuse", "common"):
            argument, tool = make()
            before = (pose.shape_bytes(argument), pose.shape_bytes(tool))
            occ.boolean(operation, argument, [tool])
            unchanged[f"{name}_{operation}"] = before == (pose.shape_bytes(argument), pose.shape_bytes(tool))
    report["bool_inputs_bytes_unchanged"] = unchanged
    one, volume = occ.occupied(A)
    report["occupied_single"] = {"same_object": one is A, "volume": volume}
    nothing = occ.compound([])
    same, volume = occ.occupied(nothing)
    report["occupied_none"] = {"same_object": same is nothing, "volume": volume}
    for name, parts in {"overlap": [A, B], "disjoint": [A, FAR], "touching": [A, box(10, 0, 0, 20, 10, 10)],
                        "contained": [A, SMALL], "three": [A, B, box(10, 0, 0, 20, 10, 10)]}.items():
        member = occ.compound(parts)
        shape, volume = occ.occupied(member)
        report[f"occupied_{name}"] = {"volume": volume, "counted": occ.volume(member), "valid": occ.is_valid(shape),
                                      "input_after": occ.volume(member)}
    report["occupied_positional_fuzzy"] = {"volume": occ.occupied(occ.compound([A, B]), 1e-7)[1]}
    return report


class Opaque(Exception):
    """An exception with no text."""


def diff_report():
    from cadmodel import diff

    def row(a, b, va=None, vb=None):
        metrics = lambda shape, v: {"volume_mm3": occ.volume(shape) if v is None else v,  # noqa: E731
                                    "bbox_mm": {"min": [0.0] * 3, "max": [1.0] * 3, "size": [1.0] * 3}, "solids": 1}
        try:
            result = diff.compare_part(metrics(a, va), metrics(b, vb), a, b)
        except Exception as error:  # noqa: BLE001
            return {"raised": type(error).__name__}
        return {key: result[key] for key in ("status", "shared_mm3", "a_only_mm3", "b_only_mm3", "error") if key in result}

    report = {"identical": row(A, A), "disjoint": row(A, FAR), "overlap": row(A, B), "contained": row(A, SMALL),
              "contains": row(SMALL, A), "a_empty": row(occ.compound([]), A, 0.0, None),
              "b_empty": row(A, occ.compound([]), None, 0.0), "both_empty": row(occ.compound([]), occ.compound([]), 0.0, 0.0),
              "overlapping_members": row(occ.compound([A, B]), scaled(15, 10, 10)),
              "identical_copies": row(A, scaled(10, 10, 10))}
    for name, error in {"text": occ.GeometryError("kernel said no"), "no_text": Opaque(), "other_type": KeyError("k")}.items():
        occ.boolean = raising(error)
        try:
            report[f"error_{name}"] = row(A, B)
        finally:
            occ.boolean = REAL
    return report
