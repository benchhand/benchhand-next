"""Build documentation: fasteners and the holes for them in the bill of materials.

The lamp's base mounts with two M6 screws through slotted counterbored holes (IF-004, requirement REQ-005) and its
BOM lists none: the drawing even excludes them. The twin adds the screws. The reverse pair adds a screw the record
has no hole for. No release obligation compares the screws with the holes. The joint obligations of the fasten operations stay
unknown on both sides. See GAP.
"""

from pathlib import Path

from corpus import Family, Pair
from doc_support import add_fastener, lamp_verdict

JOINT = "assembly.joint@"
GAP = "#134: no release obligation ties a BOM fastener to a hole. The joint obligations stay unknown on unsourced retention."

M6 = ("SCR-0001", "Hexagon socket head cap screw M6 x 16", "ISO 4762", 2)
M3 = ("SCR-0002", "Hexagon socket button head screw M3 x 8", "ISO 7380-1", 4)


def hole_without_fastener(hw: Path, mutant: bool) -> None:
    if not mutant:
        add_fastener(hw, *M6[:3], M6[3])


def fastener_without_hole(hw: Path, mutant: bool) -> None:
    add_fastener(hw, *M6[:3], M6[3])
    if mutant:
        add_fastener(hw, *M3[:3], M3[3])


FAMILY = Family(
    id="doc_fastener_bom", check="cad-record evidence: assembly.joint obligations of the fasten operations", owner="cad-bom",
    pairs=(
        Pair("hole_without_fastener", "the two M6 mounting holes (IF-004) have no screw in the BOM", lamp_verdict(hole_without_fastener, JOINT), known_gap=GAP),
        Pair("fastener_without_hole", "four M3 screws are in the BOM and no hole takes them", lamp_verdict(fastener_without_hole, JOINT), known_gap=GAP),
    ))
