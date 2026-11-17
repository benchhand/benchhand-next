"""additive.orientation stability on the convex hull of the bed-contact faces, TEST profile, no supports or brim.

Judged on the fdm orientation obligation. Millimetres, bed frame, +Z up. The tower or stub is the only
difference between a mutant and its twin. The TEST profile calibrates a 20-25 mm2 minimum bed contact.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import printed_verdict, solids

ORIENTATION = "process.fdm.orientation@"


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(shape, ORIENTATION)


def diagonal_pads(mutant: bool) -> Outcome:
    """A plate on two feet at opposite corners of a 40 mm square. The hull of the feet is a band along the
    diagonal. A 16x16x40 tower sits on the band (twin) or at the other corner (mutant), still inside the bbox."""
    s = solids()
    feet = s.fuse(s.box(0, 0, 0, 10, 10, 2), s.box(30, 30, 0, 40, 40, 2))
    plate = s.fuse(feet, s.box(0, 0, 2, 40, 40, 4))
    return _verdict(s.fuse(plate, s.box(24, 0 if mutant else 24, 4, 40, 16 if mutant else 40, 44)))


def l_footprint(mutant: bool) -> Outcome:
    """An L-shaped foot (two 40x10 arms). A 15x15x40 block sits over the L's inner corner (twin) or over the
    empty far corner of the footprint's bounding box, outside the L's hull (mutant)."""
    s = solids()
    foot = s.fuse(s.box(0, 0, 0, 40, 10, 2), s.box(0, 0, 0, 10, 40, 2))
    plate = s.fuse(foot, s.box(0, 0, 2, 40, 40, 4))
    return _verdict(s.fuse(plate, s.box(25, 25, 4, 40, 40, 44) if mutant else s.box(12.5, 12.5, 4, 27.5, 27.5, 44)))


def tiny_contact(mutant: bool) -> Outcome:
    """A 30 mm block, centred over a stub: 3x3 mm of bed contact (9 mm2) or 8x8 mm (64 mm2) against a 25 mm2 minimum."""
    s = solids()
    half = 1.5 if mutant else 4.0
    return _verdict(s.fuse(s.box(15 - half, 15 - half, 0, 15 + half, 15 + half, 2), s.box(0, 0, 2, 30, 30, 12)))


FAMILY = Family(
    id="stability_contact_hull", check="cad-design form_check.probe + process_checks/additive.py orientation",
    owner="cad-design",
    pairs=(
        Pair("diagonal_pads", "centre of volume off the hull of two corner feet, inside their bounding box", diagonal_pads),
        Pair("l_footprint", "centre of volume off the hull of an L-shaped foot, inside its bounding box", l_footprint),
        Pair("tiny_contact", "bed contact below the calibrated minimum area", tiny_contact),
    ))
