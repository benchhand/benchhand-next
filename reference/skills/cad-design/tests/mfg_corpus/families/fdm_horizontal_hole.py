"""FDM treatment of horizontal holes (axis parallel to the bed), judged by the fdm support obligation on the TEST profile.

The TEST profile has no self-supporting-hole calibration, so no round roof counts as support-free here. Each pair changes
one thing: a round roof (mutant) against a 45 deg teardrop or diamond roof of the same width (twin), at a fixed height. The
teardrop flanks sit at the 45 deg overhang limit. The square pair uses the 5 mm bridge calibration. Every case plans no
supports.
Geometry is real B-rep probed by form_check.probe. Millimetres, bed frame, +Z up, hole axis along Y.
"""

import math
from typing import Any

from corpus import Family, Outcome, Pair
from support import printed_verdict, solids

SUPPORT = "process.fdm.support@"
SMALL = 8.0  # small round hole diameter
LARGE = 20.0  # large round hole diameter
BRIDGE = 5.0  # calibrated bridge span
BLOCK = (40.0, 30.0, 40.0)  # x, y, z of the block the hole goes through
MID = 20.0  # axis height of a mid-height hole


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(shape, SUPPORT)


def _prism(points: list[tuple[float, float]]) -> Any:
    """A closed (x, z) polygon extruded along Y across the block, with a margin either side."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    wire = BRepBuilderAPI_MakePolygon()
    for x, z in points:
        wire.Add(gp_Pnt(x, -1, z))
    wire.Close()
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, BLOCK[1] + 2, 0)).Shape()


def _round(diameter: float, z: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(BLOCK[0] / 2, -1, z), gp_Dir(0, 1, 0)), diameter / 2, BLOCK[1] + 2).Shape()


def _teardrop(diameter: float, z: float) -> Any:
    """The round bore plus a triangle to an apex r*sqrt(2) above the axis, tangent to the circle at 45 deg."""
    s = solids()
    r, cx = diameter / 2, BLOCK[0] / 2
    side = r / math.sqrt(2)
    return s.fuse(_round(diameter, z), _prism([(cx - side, z + side), (cx, z + r * math.sqrt(2)), (cx + side, z + side)]))


def _diamond(diameter: float, z: float) -> Any:
    cx, r = BLOCK[0] / 2, diameter / 2
    return _prism([(cx - r, z), (cx, z - r), (cx + r, z), (cx, z + r)])


def _slot(width: float, z: float) -> Any:
    """A square hole: a flat roof of `width`, the bridge case."""
    cx = BLOCK[0] / 2
    return _prism([(cx - width / 2, z), (cx + width / 2, z), (cx + width / 2, z + width), (cx - width / 2, z + width)])


def _with_hole(hole: Any) -> Outcome:
    s = solids()
    return _verdict(s.cut(s.box(0, 0, 0, *BLOCK), hole))


def _round_or_teardrop(mutant: bool, diameter: float, z: float) -> Outcome:
    solids()  # first: it raises Skip when OCP is absent
    return _with_hole(_round(diameter, z) if mutant else _teardrop(diameter, z))


def round_roof_mid_height(mutant: bool) -> Outcome:
    """A mid-height bore of 8 mm: round (mutant) or with a 45 deg teardrop top (twin)."""
    return _round_or_teardrop(mutant, SMALL, MID)


def round_roof_bed_face(mutant: bool) -> Outcome:
    """The same 8 mm bore with its axis in the bed face, so it is a channel open to the bed."""
    return _round_or_teardrop(mutant, SMALL, 0.0)


def round_roof_large_mid_height(mutant: bool) -> Outcome:
    """The mid-height bore at 20 mm: round (mutant) or with a 45 deg teardrop top (twin)."""
    return _round_or_teardrop(mutant, LARGE, MID)


def diamond_roof_mid_height(mutant: bool) -> Outcome:
    """A mid-height 20 mm bore: round (mutant) or a diamond of the same width (twin)."""
    solids()
    return _with_hole(_round(LARGE, MID) if mutant else _diamond(LARGE, MID))


def square_roof_bridge(mutant: bool) -> Outcome:
    """A square horizontal hole whose flat roof spans 4 mm (inside the bridge calibration) or 12 mm (beyond it)."""
    solids()
    return _with_hole(_slot(12.0 if mutant else BRIDGE - 1.0, MID))


FAMILY = Family(
    id="fdm_horizontal_hole", check="cad-design form_check.probe + process_checks/additive.py support", owner="cad-design",
    pairs=(
        Pair("round_roof_mid_height", "8 mm mid-height bore left round where a 45 deg teardrop top avoids the overhang",
             round_roof_mid_height),
        Pair("round_roof_bed_face", "8 mm bed-face channel left round where a 45 deg teardrop top avoids the overhang",
             round_roof_bed_face),
        Pair("round_roof_large_mid_height", "20 mm mid-height bore left round where a 45 deg teardrop top avoids the overhang",
             round_roof_large_mid_height),
        Pair("diamond_roof_mid_height", "20 mm mid-height bore left round where a diamond top avoids the overhang",
             diamond_roof_mid_height),
        Pair("square_roof_bridge", "12 mm flat-roofed horizontal hole beyond the 5 mm bridge", square_roof_bridge),
    ))
