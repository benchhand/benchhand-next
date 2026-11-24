# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0"]
# ///
"""Write one box part as STEP with pose.write_part_step.

Usage: uv run --script step_header_probe.py OUT.step [MODE]
MODE is `box` (default), `located` (the box carries a placement of its own), `assembly` (two occurrences),
`placed` (two occurrences of a box built 50 along x, each placed 100 along y),
`located-assembly` (two occurrences of the located box; prints the error the writer raises), `halftorus` or `tilted`
(a half torus cut by a plane through its axis or by a tilted plane).
The FILE_NAME time is fixed, whatever the environment holds.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_spec = importlib.util.spec_from_file_location("cad_motion_pose", Path(__file__).resolve().parents[2] / "scripts" / "pose.py")
assert _spec is not None and _spec.loader is not None
pose = importlib.util.module_from_spec(_spec)
sys.modules["cad_motion_pose"] = pose
_spec.loader.exec_module(pose)


def torus_half(normal: tuple[float, float, float]) -> Any:
    """A torus of major radius 20 and minor radius 5 about Z, cut to the half on the `normal` side of the plane
    through its center."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace, BRepPrimAPI_MakeTorus
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pln, gp_Pnt

    torus = BRepPrimAPI_MakeTorus(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 20, 5).Shape()
    plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(*normal))).Face()
    drop = BRepPrimAPI_MakeHalfSpace(plane, gp_Pnt(*(-v for v in normal))).Solid()
    return BRepAlgoAPI_Cut(torus, drop).Shape()


def moved(shape: Any, x: float) -> Any:
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    move = gp_Trsf()
    move.SetTranslation(gp_Vec(x, 0, 0))
    return shape.Moved(TopLoc_Location(move))


def main() -> int:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    mode = sys.argv[2] if sys.argv[2:] else "box"
    box = BRepPrimAPI_MakeBox(10, 20, 30).Shape()
    shapes = {"box": box, "located": moved(box, 50), "located-assembly": moved(box, 50),
              "placed": BRepPrimAPI_MakeBox(gp_Pnt(50, 0, 0), 10, 20, 30).Shape(),
              "halftorus": torus_half((1, 2, 0)), "tilted": torus_half((1, 2, 0.5))}
    part = pose.Part("TST-0001", "TST-0001 Box", shapes.get(mode, box))
    if mode in ("assembly", "placed", "located-assembly"):
        occurrences = [SimpleNamespace(id=name, pn=part.pn, explicit=True) for name in ("a", "b")]
        shift = pose.Rigid(pose.Rigid.identity().rot, (0.0, 100.0, 0.0)) if mode == "placed" else pose.Rigid.identity()
        placements = {"a": shift, "b": shift}
        try:
            pose.write_assembly_step(Path(sys.argv[1]), "TST-TOP", {part.pn: part}, occurrences, placements)
        except pose.MotionError as error:
            print(f"MotionError: {error}")
        else:
            print("no error")
    else:
        pose.write_part_step(Path(sys.argv[1]), part)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
