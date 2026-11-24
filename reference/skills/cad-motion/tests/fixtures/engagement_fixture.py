# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0"]
# ///
"""Write the engagement test geometry as STEP AP242: a pin pressed into a sleeve that sits in a housing.

Usage: uv run --script engagement_fixture.py OUT_DIR

All parts are modelled in place (assembly_zero, identity placement), millimetres:
  TST-0101 housing  x, y -30..30, z 0..20, a bore r 11 from z 8 up
  TST-0102 sleeve   a ring r 5..11, z 8..16, seated on the bore floor
  TST-0104 pin      z 8..14 at the installed pose; the variants differ in the interfering part of the pin
OUT_DIR/press/parts/ has a pin of r 5.05 over its whole length. It interferes with the sleeve bore (r 5) for 8 mm
of travel back from the installed pose, the sleeve top (z 16) minus the pin foot (z 8).
OUT_DIR/long/parts/ has a pin of r 5.05 from z 8 to 16.3: its press band runs 0.3 mm above the bore mouth (z 16), like
a pin with a head gap. Its interference lasts 8 mm of travel, the same as the press pin's.
OUT_DIR/bead/parts/ has a shank of r 4.9 (0.1 mm clear of the bore) and a 0.2 mm press bead of r 5.05 at z 9..9.2.
Its interference with the sleeve lasts 7 mm of travel, the sleeve top minus the bead foot.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).resolve().with_name("access_fixture.py")
_spec = importlib.util.spec_from_file_location("cad_motion_access_fixture", _path)
assert _spec and _spec.loader
base = importlib.util.module_from_spec(_spec)
sys.modules["cad_motion_access_fixture"] = base
_spec.loader.exec_module(base)

TITLES = {"TST-0101": "Housing", "TST-0102": "Sleeve", "TST-0104": "Pin"}


def pins() -> dict[str, object]:
    return {"press": base.cylinder(0, 0, 8, 5.05, 6), "long": base.cylinder(0, 0, 8, 5.05, 8.3),
            "bead": base.fuse(base.cylinder(0, 0, 8, 4.9, 6), base.cylinder(0, 0, 9, 5.05, 0.2))}


def main(out: Path) -> int:
    housing = base.cut(base.box(-30, -30, 0, 30, 30, 20), base.cylinder(0, 0, 8, 11, 13))
    sleeve = base.cut(base.cylinder(0, 0, 8, 11, 8), base.cylinder(0, 0, 7, 5, 10))
    for variant, pin in pins().items():
        folder = out / variant / "parts"
        folder.mkdir(parents=True, exist_ok=True)
        for pn, shape in (("TST-0101", housing), ("TST-0102", sleeve), ("TST-0104", pin)):
            base.pose.write_part_step(folder / f"{pn}.step", base.pose.Part(pn, f"{pn} {TITLES[pn]}", shape))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
