"""form_check overhang and bridge detection, judged by the fdm support obligation (additive.support) on the TEST profile.

The calibrated limits are overhang 45 deg and bridge 5 mm. Every case plans no supports, so a face that needs them fails.
Geometry is real B-rep probed by form_check.probe, never hand-written facts. Millimetres, bed frame, +Z up.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import printed_verdict, solids

SUPPORT = "process.fdm.support@"


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(shape, SUPPORT)


def flat_shelf(mutant: bool) -> Outcome:
    s = solids()
    z0 = 20 if mutant else 0  # the shelf hangs 20 mm above the bed, or sits on it
    return _verdict(s.fuse(s.box(0, 0, 0, 10, 10, 30), s.box(10, 0, z0, 30, 10, z0 + 5)))


def bridge_span(mutant: bool) -> Outcome:
    s = solids()
    span = 12 if mutant else 4  # the gap between the posts under the beam
    return _verdict(s.fuse(s.fuse(s.box(0, 0, 0, 10, 10, 20), s.box(10 + span, 0, 0, 20 + span, 10, 20)),
                           s.box(0, 0, 20, 20 + span, 10, 25)))


def gusset_under_shelf(mutant: bool) -> Outcome:
    """A shelf off a post. The twin adds a gusset under it. The underside then slopes 37 deg from vertical, inside the 45 deg limit."""
    s = solids()  # first: it raises Skip when OCP is absent
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    shape = s.fuse(s.box(0, 0, 0, 10, 10, 30), s.box(10, 0, 20, 25, 10, 25))
    if not mutant:
        triangle = BRepBuilderAPI_MakePolygon()
        for x, z in ((10, 20), (10, 0), (25, 20)):
            triangle.Add(gp_Pnt(x, 0, z))
        triangle.Close()
        gusset = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(triangle.Wire()).Face(), gp_Vec(0, 10, 0)).Shape()
        shape = s.fuse(shape, gusset)
    return _verdict(shape)


def horizontal_bore_roof(mutant: bool) -> Outcome:
    """A horizontal bore along Y through a block: a 20 mm round roof against a 3 mm one."""
    s = solids()  # first: it raises Skip when OCP is absent
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    radius = 10.0 if mutant else 1.5
    bore = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20, -1, 20), gp_Dir(0, 1, 0)), radius, 32).Shape()
    return _verdict(s.cut(s.box(0, 0, 0, 40, 30, 40), bore))


FAMILY = Family(
    id="additive_support_overhang_bridge", check="cad-design form_check.probe + process_checks/additive.py support",
    owner="cad-design",
    pairs=(
        Pair("flat_shelf", "flat shelf underside 20 mm above the bed, no supports", flat_shelf),
        Pair("bridge_span", "12 mm bridge between posts, past the 5 mm calibration", bridge_span),
        Pair("bore_roof", "20 mm horizontal bore whose round roof exceeds the bridge calibration", horizontal_bore_roof),
        Pair("shelf_without_gusset", "flat shelf underside where a gusset would make it steep", gusset_under_shelf),
    ))
