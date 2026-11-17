"""additive.geometry: calibrated minimum wall and smallest pin on probed B-rep, TEST profile (min_wall 1.6, min_feature 2.4 mm).

Judged on the fdm geometry obligation. Millimetres, bed frame, +Z up.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import assess_printed, printed_verdict, solids

GEOMETRY = "process.fdm.geometry@"


def _verdict(shape: Any) -> Outcome:
    return printed_verdict(assess_printed(shape), GEOMETRY)


def thin_plate(mutant: bool) -> Outcome:
    s = solids()
    return _verdict(s.box(0, 0, 0, 30, 20, 0.8 if mutant else 2.0))


def thin_wall_on_base(mutant: bool) -> Outcome:
    s = solids()
    t = 0.8 if mutant else 2.0  # an upright wall on a thick base
    return _verdict(s.fuse(s.box(0, 0, 0, 30, 20, 4), s.box(0, 0, 4, 30, t, 24)))


def thin_pin(mutant: bool) -> Outcome:
    s = solids()
    return _verdict(s.fuse(s.box(0, 0, 0, 20, 20, 3), s.cylinder(10, 10, 3, 0.75 if mutant else 2.0, 10)))


def tiny_hole(mutant: bool) -> Outcome:
    """A vertical through hole of 0.5 mm against 4 mm in a 10 mm block (the profile calibrates no minimum hole)."""
    s = solids()
    return _verdict(s.cut(s.box(0, 0, 0, 20, 20, 10), s.cylinder(10, 10, -1, 0.25 if mutant else 2.0, 12)))


FAMILY = Family(
    id="additive_min_feature", check="process_checks/additive.py geometry (wall_check, small_feature_check)",
    owner="cad-design",
    pairs=(
        Pair("thin_plate", "0.8 mm plate against a 1.6 mm calibrated minimum wall", thin_plate),
        Pair("thin_wall", "0.8 mm upright wall on a base", thin_wall_on_base),
        Pair("tiny_hole", "0.5 mm hole: no minimum-hole calibration exists", tiny_hole),
        Pair("thin_pin", "1.5 mm pin against a 2.4 mm calibrated minimum feature", thin_pin),
    ))
