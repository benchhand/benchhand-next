"""additive.orientation (first-layer contact and stability) on probed B-rep, TEST profile, no supports or brim.

Judged on the fdm orientation obligation. Millimetres, bed frame, +Z up.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import printed_verdict, solids

ORIENTATION = "process.fdm.orientation@"


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(shape, ORIENTATION)


def off_centre_mass(mutant: bool) -> Outcome:
    """A 30 mm block on a foot: the foot spans the block's footprint, or covers only its end."""
    s = solids()
    foot_end = 10 if mutant else 40
    return _verdict(s.fuse(s.box(0, 0, 0, foot_end, 10, 2), s.box(0, 0, 2, 40, 10, 30)))


def line_contact(mutant: bool) -> Outcome:
    """A 10 mm rod lying on its side touches the bed along a line. Standing, it has a flat end."""
    s = solids()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    axis = gp_Dir(1, 0, 0) if mutant else gp_Dir(0, 0, 1)
    shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 5 if mutant else 0), axis), 5.0, 30.0).Shape()
    del s
    return _verdict(shape)


def no_flat_face(mutant: bool) -> Outcome:
    """A box balanced on an edge (rotated 45 deg about X) against the same box flat."""
    s = solids()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

    box = s.box(0, 0, 0, 20, 20, 20)
    if not mutant:
        return _verdict(box)
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), 0.7853981633974483)
    return _verdict(BRepBuilderAPI_Transform(box, turn, True).Shape())


def slender_tower(mutant: bool) -> Outcome:
    """A 4 mm square tower on a 30 mm plate: 80 mm tall (aspect 20) against 20 mm. Its center of volume stays over the footprint."""
    s = solids()
    return _verdict(s.fuse(s.box(0, 0, 0, 30, 30, 2), s.box(13, 13, 2, 17, 17, 82 if mutant else 22)))


FAMILY = Family(
    id="additive_stability", check="cad-design form_check.probe + process_checks/additive.py orientation",
    owner="cad-design",
    pairs=(
        Pair("off_centre_mass", "centre of volume outside the bed contact footprint", off_centre_mass),
        Pair("line_contact", "rod on its side: no planar first layer", line_contact),
        Pair("edge_balance", "box balanced on an edge: no planar first layer", no_flat_face),
        Pair("slender_tower", "80 mm tall 4 mm tower: wobble, not a centre-of-volume fault", slender_tower),
    ))
