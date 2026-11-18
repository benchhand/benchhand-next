"""additive.orientation stability on the convex hull of the bed-contact faces, TEST profile, no supports or brim.

Judged on the fdm orientation obligation. Millimetres, bed frame, +Z up. The tower or stub is the only
difference between a mutant and its twin, bar the plate noted on l_footprint. The TEST profile calibrates a 20-25 mm2
minimum bed contact. Every twin is self-supporting (no flat ceiling, no overhang past 45 deg), so the support
obligation has nothing to say about it and the plan can stay at support strategy none.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import printed_verdict, solids

ORIENTATION = "process.fdm.orientation@"


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(shape, ORIENTATION)


Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


def _taper(bottom: Rect, top: Rect, z0: float, z1: float) -> Any:
    """A straight-sided solid from the rectangle `bottom` at z0 to the rectangle `top` at z1. A side that moves out as far as
    it rises is a 45 deg underside, and a side that stays put is a wall. Neither needs support."""
    solids()  # first: it raises Skip when OCP is absent
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.gp import gp_Pnt

    loft = BRepOffsetAPI_ThruSections(True, True)  # solid, ruled
    for (x0, y0, x1, y1), z in ((bottom, z0), (top, z1)):
        wire = BRepBuilderAPI_MakePolygon()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            wire.Add(gp_Pnt(x, y, z))
        wire.Close()
        loft.AddWire(wire.Wire())
    loft.Build()
    return loft.Shape()


def diagonal_pads(mutant: bool) -> Outcome:
    """Two 10 mm feet at opposite corners of a 40 mm square. Each widens at 45 deg toward the other, to 21 mm at 11 mm up, where
    the two overlap. A 16x16x60 tower sits on the far foot (twin) or at the other corner (mutant), still inside the bbox."""
    s = solids()
    rise = 11
    near = _taper((0, 0, 10, 10), (0, 0, 10 + rise, 10 + rise), 0, rise)
    far = _taper((30, 30, 40, 40), (30 - rise, 30 - rise, 40, 40), 0, rise)
    tower = s.box(20, 0, rise, 36, 16, rise + 60) if mutant else s.box(24, 24, rise, 40, 40, rise + 60)
    return _verdict(s.fuse(s.fuse(near, far), tower))


def l_footprint(mutant: bool) -> Outcome:
    """An L-shaped foot (two 40x10 arms), each arm widening at 45 deg on its inner side to 16 mm at 6 mm up. A 10x10x40 block sits
    over the L's inner corner (twin). The mutant puts a 15x15x60 block over the empty far corner of the footprint's bounding
    box, outside the L's hull, carried on a 2 mm plate."""
    s = solids()
    rise = 6
    foot = s.fuse(_taper((0, 0, 40, 10), (0, 0, 40, 10 + rise), 0, rise), _taper((0, 0, 10, 40), (0, 0, 10 + rise, 40), 0, rise))
    if mutant:
        return _verdict(s.fuse(s.fuse(foot, s.box(0, 0, rise, 40, 40, rise + 2)), s.box(25, 25, rise + 2, 40, 40, rise + 62)))
    return _verdict(s.fuse(foot, s.box(6, 6, rise, 16, 16, rise + 40)))


def tiny_contact(mutant: bool) -> Outcome:
    """A 30 mm block, centred over a stub that widens at 45 deg to meet it: 3x3 mm of bed contact (9 mm2) or 8x8 mm (64 mm2)
    against a 25 mm2 minimum."""
    s = solids()
    half = 1.5 if mutant else 4.0
    rise = 15 - half
    stub = _taper((15 - half, 15 - half, 15 + half, 15 + half), (0, 0, 30, 30), 0, rise)
    return _verdict(s.fuse(stub, s.box(0, 0, rise, 30, 30, rise + 10)))


FAMILY = Family(
    id="stability_contact_hull", check="cad-design form_check.probe + process_checks/additive.py orientation",
    owner="cad-design",
    pairs=(
        Pair("diagonal_pads", "centre of volume off the hull of two corner feet, inside their bounding box", diagonal_pads),
        Pair("l_footprint", "centre of volume off the hull of an L-shaped foot, inside its bounding box", l_footprint),
        Pair("tiny_contact", "bed contact below the calibrated minimum area", tiny_contact),
    ))
