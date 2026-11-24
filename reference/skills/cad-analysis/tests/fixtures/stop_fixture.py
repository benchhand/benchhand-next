# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0"]
# ///
"""Write the latch stop test geometry as STEP AP242: an OCP copy of the small-mechanism latch lever.

Usage: uv run --script stop_fixture.py OUT_DIR [LATCHED_GAP_MM [VARIANT]]

Every part is modelled in place (assembly zero, identity placement), millimetres. The pivot axis is the Y axis
through the origin; the lever turns about -Y from 0 deg (latched, lying along +X) to 75 deg (open, pointing up):
  TST-0301 bracket  a base plate, a latched stop block under the lever (x 7..13, its top face at z -3) and an
                    open stop block above it (a box standing on the lever's top face at 75 deg, x 0..7 along the
                    lever), joined by a post
  TST-0302 lever    x 0..80, y -4..4, z -3..3

The latched stop is touched across arms 7..13 mm from the axis, the open stop across arms 0..7 mm, as in the
latch lever whose hand-estimated stop reaction (240 N, mid-span) hid that the nearest edge carries 2400/7 N.

LATCHED_GAP_MM (default 0) lowers the latched stop's top face by that much, so the lever at 0 deg stops short of it.

VARIANT changes one thing:
  ring   adds TST-0303, a small ring at the lever's tip, for a second joint
  disk   a bracket with the latched stop only, a disc of radius 10 centered at x 10, y 2 and 5 mm thick (z -8 to -3).
         Its rim touches the axis line at x 0, so its nearest arm is exactly 0, at a rim point that is no vertex and
         falls between the 64 samples of a sampled outline. Its lever starts at x -2, past the axis line, so that
         rim point lies inside the lever's underside and the zero-arm line crosses no edge of the contact patch.
  disk3  the same disc centered at x 13, so its rim is nearest the axis line at x 3, at the rim point (3, 2)
  round  the lever ends in a cylinder of radius 10 centered at x 70, so its farthest point from the axis, at x 80,
         is on an arc between sampled points
  pieces two separate overlaps of the lever at 0 deg, of different depths. The latched block's top is at z -2.5, so
         the lever's underside (z -3) enters it over x 7..13, y -4..4, z -3..-2.5: depth 0.5 mm, volume 24 mm3. A side
         block at x 30..40, y 2.5..10 cuts the lever's side face over x 30..40, y 2.5..4, z -3..3: depth 1.5 mm
         (its thinnest side), volume 90 mm3. The deepest piece (1.5 mm) differs from the shallowest (0.5 mm) and from
         the pieces taken together: their thinnest planar width is the lever's thickness, 6 mm.
  curved a sphere of radius 5 (the moving part, centered at (40, 0, 0)) pushed 3 mm into a cylinder of radius 10 (the
         bracket, axis along Y through (40, y, -12), y -30..30): the sphere's lowest point is at z -5 and the cylinder's
         top at z -2. The overlap is a sphere cap under the cylinder's surface, with spherical and cylindrical faces
         and no planar face. Its thinnest width is the 3 mm along z.
  contained a bracket that is a compound of two separate solids: a block x -20..120, y -20..20, z -20..110, which
         holds the whole lever at 0 and at 75 deg, and a small block far away. The lever is wholly inside one solid
         of the compound, 16 mm from its nearest face, so the boundary distance is large while the shared volume is
         the lever's own 80 * 8 * 6 = 3840 mm3.

The disc variants have no open stop and no post. They model a round latched stop on its own. At d7e4c0bf they still
carried the open-stop block, and the lever's extension to x -2 ran into it at 20 deg: the probe reported an overlap
depth of 1.47 mm and a volume of 1.2642 mm3 (the same volume as cad-motion's sweep), against 0.181 mm by hand. The
code's output showed the mismatch. The geometry then explained it: at 20 deg the lever's back-top corner is at
(x, z) = (-2.905, 2.135), and the block's inner face passes x = -2.534 at that height, so the corner is 0.37 mm inside
the block. The block is no part of what the disc variants model, so it was removed.

Pivot ranges of the records that use the disc variants, from the geometry (the pivot turns about -Y, so a point
(x, z) moves to (x cos t - z sin t, x sin t + z cos t)):
  0 to 75 deg, the latch's own travel, for the tangent and posed-reaction cases. At 75 deg the lever's back-bottom
         corner (-2, -3) is at z = -2.71, 0.29 mm above the disc top, which is more than the 0.15 mm contact tolerance,
         so only the 0 deg limit is a stop.
  0 to 20 deg for the overlap case. The posed underside is the plane z = x tan t - 3 / cos t. At t = 20 deg that is
         z = 0.36397 x - 3.19253, and it is below the disc top (z -3) for x < 0.19253 / 0.36397 = 0.529 mm. So the
         lever enters the disc over x from the rim to 0.529 mm: 0.529 mm is the run of that wedge along the disc top, and
         its thickness is the run times tan t. The deepest point is the rim point (0, 2): 3 / cos t - 3 = 0.19253 mm
         below the disc top, and 0.19253 * cos t = 3 (1 - cos t) = 0.18092 mm from the underside plane. The shared
         volume is (tan t / 2) * the integral of (0.529 - u^2 / 20)^2 du over u = y - 2 from -3.25 to 2, which is about
         0.1675 mm3 (the Boolean gives 0.1668).

OUT_DIR/parts/<PN>.step.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

POSE_PATH = Path(__file__).resolve().parents[3] / "cad-motion" / "scripts" / "pose.py"
_spec = importlib.util.spec_from_file_location("cad_motion_pose", POSE_PATH)
assert _spec and _spec.loader
pose = importlib.util.module_from_spec(_spec)
sys.modules["cad_motion_pose"] = pose
_spec.loader.exec_module(pose)

TITLES = {"TST-0301": "Bracket", "TST-0302": "Lever", "TST-0303": "Ring"}
HALF_SAMPLE = math.pi / 128  # half the step of 64 samples round a circle
OPEN_DEGREES = 75.0


def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def cylinder(x: float, y: float, z: float, axis: str, radius: float, length: float):
    """A cylinder from (x, y, z) along +Z or +Y with its seam turned by HALF_SAMPLE, so the rim point that matters
    (nearest -X for axis z, farthest +X for axis y) is half a step from a sample."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    cos, sin = math.cos(HALF_SAMPLE), math.sin(HALF_SAMPLE)
    along, seam = (gp_Dir(0, 0, 1), gp_Dir(cos, sin, 0)) if axis == "z" else (gp_Dir(0, 1, 0), gp_Dir(cos, 0, sin))
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, z), along, seam), radius, length).Shape()


def turned(shape, degrees: float):
    """`shape` with its geometry rotated by `degrees` about -Y through the origin."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    rigid = pose.Rigid.rotation((0.0, -1.0, 0.0), degrees, (0.0, 0.0, 0.0))
    return BRepBuilderAPI_Transform(shape, pose.to_trsf(rigid), True).Shape()


def fused(*shapes):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

    result = shapes[0]
    for other in shapes[1:]:
        result = BRepAlgoAPI_Fuse(result, other).Shape()
    return BRepBuilderAPI_Copy(result).Shape()


def compound(*shapes):
    """The shapes as one compound, unfused: separate solids that stay separate."""
    from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

    result, builder = TopoDS_Compound(), TopoDS_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def sphere_into_cylinder() -> dict[str, object]:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    cylinder_ = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(40, -30, -12), gp_Dir(0, 1, 0)), 10, 60).Shape()
    return {"TST-0301": cylinder_, "TST-0302": BRepPrimAPI_MakeSphere(gp_Pnt(40, 0, 0), 5).Shape()}


def shapes(latched_gap: float = 0.0, variant: str = "") -> dict[str, object]:
    if variant == "curved":
        return sphere_into_cylinder()
    if variant == "contained":
        return {"TST-0301": compound(box(-20, -20, -20, 120, 20, 110), box(200, 200, 200, 210, 210, 210)),
                "TST-0302": box(0, -4, -3, 80, 4, 3)}
    base = box(-30, -14, -16, 30, 14, -8)
    if variant == "pieces":
        return {"TST-0301": fused(base, box(7, -4, -8, 13, 4, -2.5), box(30, 2.5, -8, 40, 10, 10)),
                "TST-0302": box(0, -4, -3, 80, 4, 3)}
    discs = variant in ("disk", "disk3")
    if discs:
        latched_stop = cylinder(10 if variant == "disk" else 13, 2, -8, "z", 10, 5 - latched_gap)
    else:
        latched_stop = box(7, -4, -8, 13, 4, -3 - latched_gap)  # top face at z -3: the lever's underside rests on it at 0 deg
    if discs:  # the disc variants have the latched stop only, since their lever runs past the axis line
        bracket = fused(base, latched_stop)
    else:
        open_stop = turned(box(0, -4, 3, 7, 4, 9), OPEN_DEGREES)  # its face lies in the lever's top plane at 75 deg
        bracket = fused(base, latched_stop, open_stop, box(-12, -4, -8, -4, 4, 10))
    lever = box(-2 if variant == "disk" else 0, -4, -3, 80, 4, 3)
    if variant == "round":
        lever = fused(box(0, -4, -3, 70, 4, 3), cylinder(70, -4, 0, "y", 10, 8))
    parts = {"TST-0301": bracket, "TST-0302": lever}
    if variant == "ring":
        parts["TST-0303"] = box(84, -3, -3, 90, 3, 3)
    return parts


def main(out: Path, latched_gap: float = 0.0, variant: str = "") -> int:
    (out / "parts").mkdir(parents=True, exist_ok=True)
    for pn, shape in shapes(latched_gap, variant).items():
        pose.write_part_step(out / "parts" / f"{pn}.step", pose.Part(pn, f"{pn} {TITLES[pn]}", shape))
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3, 4):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 0.0, sys.argv[3] if len(sys.argv) > 3 else ""))
