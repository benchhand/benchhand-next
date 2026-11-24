# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0"]
# ///
"""Probe small OCP shapes with form_check's manufacturing-state probe and print the facts per case.

Shapes (mm, the frame they are probed in):
  shelf   a 10 x 10 x 30 post on the bed with a 20 x 10 x 5 shelf at z 20..25 on its +X side
  seat    a 30 x 20 x 20 block on the bed with a horizontal 10 mm bore along Y at x 15, z 10
  pocket  a 40 x 30 x 25 block with a 20 x 10 pocket 20 deep from the top, its vertical corners R2
  plate   a 40 x 30 x 3 plate with a through 6 mm hole at x 20, y 15
  disc    a 100 mm disc, 5 mm thick, on the bed; its cylinder seam is turned 5.625 degrees off +X
  slot    a 40 x 30 x 30 block on the bed with a 4 mm wide, 30 mm long square slot through it along Y, its flat roof at z 14
  beam_*  a beam at z 20..25 over posts, its flat roof at z 20: long (a 4 x 30 roof held by two posts), three (the same
          with an end wall), ends (a 4 x 30 roof held by two end posts), corner (an 18 x 18 roof held by two adjacent walls),
          split_long and split_four (long and a 4 x 26 roof held on four sides, each post made of two boxes so the roof
          edge along it is two contiguous edges)
  pocket_* a 60 x 60 x 30 block with a pocket open to the bed, its flat roof at z 10: l (two 30 x 4 arms), trapezoid
          (parallel sides 10 and 6), ring (an annulus around a pillar), boss (a 30 x 6 roof around a 7.5 x 4 boss),
          notch (a 30 x 4 roof with a 3 x 2 notch in a short end), stadium (a 30 x 4 roof with round ends), hole (a 30 x 4
          roof with a 3 mm vertical hole through it), rounded (a 30 x 4 roof with R1 corners), stadium_hole (the stadium
          with a 1 mm hole through a round end), stadium_notch (the stadium with a notch confined to a round end),
          flared (a 30 x 4 roof whose one end flares out in two concave R1 arcs), scooped (the same roof with the corner
          arcs not tangent), oversize (the same roof with corner radii 2.5 and 0.5 at one end, 2.5 above gap / 2),
          elliptic (a 30 x 4 roof with a half-ellipse end), elliptic_thin (the same at a width of 0.0015 mm), reversed
          (a plain 30 x 4 roof whose second long edge runs back toward the first)
  pair    two 10 x 10 x 2 plates 20 mm apart: one component of two equivalent members
Usage: uv run --script process_probe.py
stdout: {case: probe facts (process_checks Geometry)}.
"""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "cad-model" / "scripts"))
spec = importlib.util.spec_from_file_location("cad_design_form_check", SCRIPTS / "form_check.py")
form_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(form_check)

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse  # noqa: E402
from OCP.BRepBuilderAPI import (  # noqa: E402
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet  # noqa: E402
from OCP.GC import GC_MakeArcOfCircle  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec  # noqa: E402
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain  # noqa: E402
import math  # noqa: E402
from OCP.TopAbs import TopAbs_EDGE  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from cadmodel import occ  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def cylinder(point, direction, radius, height):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*point), gp_Dir(*direction)), radius, height).Shape()


def prism(points, z0, z1):
    """A closed (x, y) polygon extruded from z0 to z1."""
    wire = BRepBuilderAPI_MakePolygon()
    for x, y in points:
        wire.Add(gp_Pnt(x, y, z0))
    wire.Close()
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire.Wire()).Face(), gp_Vec(0, 0, z1 - z0)).Shape()


def outline(start, *parts):
    """A closed (x, y) outline from `start`: each part is a line to (x, y) or an arc through a middle point to (x, y)."""
    wire, here = BRepBuilderAPI_MakeWire(), start
    for part in parts:
        end = part[-1]
        if len(part) == 1:
            edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*here, 0), gp_Pnt(*end, 0)).Edge()
        else:
            edge = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(gp_Pnt(*here, 0), gp_Pnt(*part[0], 0), gp_Pnt(*end, 0)).Value()).Edge()
        wire.Add(edge)
        here = end
    return wire.Wire()


def extruded(wire, z0, z1):
    """`wire` (drawn at z 0) moved to z0 and extruded to z1."""
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    move = gp_Trsf()
    move.SetTranslation(gp_Vec(0, 0, z0))
    placed = BRepBuilderAPI_Transform(BRepBuilderAPI_MakeFace(wire).Face(), move).Shape()
    return BRepPrimAPI_MakePrism(placed, gp_Vec(0, 0, z1 - z0)).Shape()


def filleted_pocket(x0, y0, z0, x1, y1, z1, radii):
    """A pocket tool box with a fillet of the mapped radius on each vertical edge at an (x, y) corner of `radii`."""
    shape = box(x0, y0, z0, x1, y1, z1)
    fillet = BRepFilletAPI_MakeFillet(shape)
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = occ.downcast(explorer.Current(), "EDGE")
        low, high = occ.bbox(edge)
        if abs(low[0] - high[0]) < 1e-9 and abs(low[1] - high[1]) < 1e-9 and (round(low[0], 6), round(low[1], 6)) in radii:
            fillet.Add(radii[(round(low[0], 6), round(low[1], 6))], edge)
        explorer.Next()
    return fillet.Shape()


def elliptic_strip(x0, y0, x1, width, bulge, z0, z1):
    """A strip tool from x0 to x1 and y0 to y0 + width, its x0 end a half ellipse that bulges `bulge` toward -x."""
    from math import pi

    from OCP.gp import gp_Elips

    def edge(p, q):
        return BRepBuilderAPI_MakeEdge(gp_Pnt(*p, 0), gp_Pnt(*q, 0)).Edge()

    ellipse = gp_Elips(gp_Ax2(gp_Pnt(x0, y0 + width / 2, 0), gp_Dir(0, 0, 1), gp_Dir(-1, 0, 0)), bulge, width / 2)
    wire = BRepBuilderAPI_MakeWire()
    for part in (edge((x0, y0), (x1, y0)), edge((x1, y0), (x1, y0 + width)), edge((x1, y0 + width), (x0, y0 + width)),
                 BRepBuilderAPI_MakeEdge(ellipse, -pi / 2, pi / 2).Edge()):
        wire.Add(part)
    return extruded(wire.Wire(), z0, z1)


def unified(shape):
    """`shape` with coplanar and co-cylindrical faces merged."""
    merge = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    merge.Build()
    return merge.Shape()


def fuse(a, b):
    return BRepAlgoAPI_Fuse(a, b).Shape()


def cut(a, b):
    return BRepAlgoAPI_Cut(a, b).Shape()


def rounded_pocket(x0, y0, z0, x1, y1, z1, radius):
    """A pocket tool box whose vertical edges are rounded to `radius`."""
    shape = box(x0, y0, z0, x1, y1, z1)
    fillet = BRepFilletAPI_MakeFillet(shape)
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = occ.downcast(explorer.Current(), "EDGE")
        low, high = occ.bbox(edge)
        if abs(low[0] - high[0]) < 1e-9 and abs(low[1] - high[1]) < 1e-9:
            fillet.Add(radius, edge)
        explorer.Next()
    return fillet.Shape()


def plane(ident, point, normal, kind="face"):
    return {ident: {"kind": kind, "frame": "manufacture",
                    "patches": [{"support_type": "plane", "point_mm": list(point), "normal": list(normal)}]}}


def bore(ident, point, normal, kind="bore"):
    return {ident: {"kind": kind, "frame": "manufacture",
                    "patches": [{"support_type": "cylinder", "point_mm": list(point), "normal": list(normal)}]}}


# a 30 x 4 stadium pocket tool: a 26 x 4 box with a R2 cylinder at each end, from z -1 to 10
STADIUM = unified(fuse(fuse(box(12, 10, -1, 38, 14, 10), cylinder((12, 12, -1), (0, 0, 1), 2, 11)),
                       cylinder((38, 12, -1), (0, 0, 1), 2, 11)))

def turned_disc(radius, height, seam_degrees):
    seam = math.radians(seam_degrees)
    axes = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1), gp_Dir(math.cos(seam), math.sin(seam), 0))
    return BRepPrimAPI_MakeCylinder(axes, radius, height).Shape()


CASES = {
    "shelf": (fuse(box(0, 0, 0, 10, 10, 30), box(10, 0, 20, 30, 10, 25)), "bed",
              {**plane("shelf_underside", (20, 5, 20), (0, 0, -1)), **plane("shelf_top", (20, 5, 25), (0, 0, 1))}, {}),
    "seat": (cut(box(0, 0, 0, 30, 20, 20), cylinder((15, -1, 10), (0, 1, 0), 5, 22)), "bed",
             bore("bearing_seat", (15, 10, 15), (0, 0, -1)), {}),
    "pocket": (cut(box(0, 0, 0, 40, 30, 25), rounded_pocket(10, 10, 5, 30, 20, 26, 2.0)), "model",
               plane("pocket_floor", (20, 15, 5), (0, 0, 1)), {"directions": {"+z": [0.0, 0.0, 1.0]}}),
    "plate": (cut(box(0, 0, 0, 40, 30, 3), cylinder((20, 15, -1), (0, 0, 1), 3, 5)), "model",
              bore("ream_bore", (23, 15, 1.5), (-1, 0, 0)), {"directions": {"+z": [0.0, 0.0, 1.0], "-x": [-1.0, 0.0, 0.0]}}),
    "disc": (turned_disc(50.0, 5.0, 5.625), "bed", {}, {}),
    "slot": (cut(box(0, 0, 0, 40, 30, 30), box(18, -1, 10, 22, 31, 14)), "bed", plane("roof", (20, 15, 14), (0, 0, -1)), {}),
    "beam_long": (fuse(fuse(box(0, 0, 0, 10, 30, 20), box(14, 0, 0, 24, 30, 20)), box(0, 0, 20, 24, 30, 25)), "bed",
                  plane("roof", (12, 15, 20), (0, 0, -1)), {}),
    "beam_three": (fuse(fuse(fuse(box(0, 0, 0, 10, 30, 20), box(14, 0, 0, 24, 30, 20)), box(10, 0, 0, 14, 2, 20)),
                        box(0, 0, 20, 24, 30, 25)), "bed", plane("roof", (12, 15, 20), (0, 0, -1)), {}),
    "beam_ends": (fuse(fuse(box(0, 0, 0, 4, 10, 20), box(0, 40, 0, 4, 50, 20)), box(0, 0, 20, 4, 50, 25)), "bed",
                  plane("roof", (2, 25, 20), (0, 0, -1)), {}),
    "beam_corner": (fuse(fuse(box(0, 0, 0, 2, 20, 20), box(0, 0, 0, 20, 2, 20)), box(0, 0, 20, 20, 20, 25)), "bed",
                    plane("roof", (10, 10, 20), (0, 0, -1)), {}),
    "beam_split_long": (fuse(fuse(fuse(fuse(box(0, 0, 0, 10, 15, 20), box(0, 15, 0, 10, 30, 20)), box(14, 0, 0, 24, 15, 20)),
                                box(14, 15, 0, 24, 30, 20)), box(0, 0, 20, 24, 30, 25)), "bed",
                        plane("roof", (12, 7, 20), (0, 0, -1)), {}),
    "beam_split_four": (fuse(fuse(fuse(fuse(fuse(fuse(box(0, 0, 0, 10, 15, 20), box(0, 15, 0, 10, 30, 20)),
                                                box(14, 0, 0, 24, 15, 20)), box(14, 15, 0, 24, 30, 20)),
                                      box(10, 0, 0, 14, 2, 20)), box(10, 28, 0, 14, 30, 20)), box(0, 0, 20, 24, 30, 25)), "bed",
                        plane("roof", (12, 7, 20), (0, 0, -1)), {}),
    "pocket_l": (cut(box(0, 0, 0, 60, 60, 30), prism([(10, 10), (40, 10), (40, 14), (14, 14), (14, 40), (10, 40)], -1, 10)),
                 "bed", plane("roof", (12, 12, 10), (0, 0, -1)), {}),
    "pocket_trapezoid": (cut(box(0, 0, 0, 60, 60, 30), prism([(10, 10), (20, 10), (18, 14), (12, 14)], -1, 10)), "bed",
                         plane("roof", (15, 12, 10), (0, 0, -1)), {}),
    "pocket_ring": (cut(box(0, 0, 0, 60, 60, 30), cut(cylinder((30, 30, -1), (0, 0, 1), 10, 11),
                                                      cylinder((30, 30, -2), (0, 0, 1), 5, 13))),
                    "bed", plane("roof", (37.5, 30, 10), (0, 0, -1)), {}),
    "pocket_notch": (cut(box(0, 0, 0, 60, 60, 30), prism([(10, 10), (40, 10), (40, 14), (10, 14), (10, 13), (13, 13), (13, 11),
                                                          (10, 11)], -1, 10)), "bed", plane("roof", (30, 12, 10), (0, 0, -1)), {}),
    "pocket_stadium": (cut(box(0, 0, 0, 60, 60, 30), STADIUM), "bed", plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_hole": (cut(cut(box(0, 0, 0, 60, 60, 30), box(10, 10, -1, 40, 14, 10)), cylinder((25, 12, 5), (0, 0, 1), 1.5, 30)), "bed",
                    plane("roof", (12, 12, 10), (0, 0, -1)), {}),
    "pocket_rounded": (cut(box(0, 0, 0, 60, 60, 30), rounded_pocket(10, 10, -1, 40, 14, 10, 1.0)), "bed",
                       plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_stadium_hole": (cut(cut(box(0, 0, 0, 60, 60, 30), STADIUM), cylinder((39, 12, 5), (0, 0, 1), 0.5, 30)), "bed",
                            plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_stadium_notch": (cut(box(0, 0, 0, 60, 60, 30), cut(STADIUM, box(39.2, 11, -2, 41, 13, 12))), "bed",
                             plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_flared": (cut(box(0, 0, 0, 60, 60, 30),
                          extruded(outline((11, 10), ((40, 10),), ((40, 14),), ((11, 14),), ((10.292893, 14.292893), (10, 15)),
                                           ((10, 9),), ((10.292893, 9.707107), (11, 10))), -1, 10)), "bed",
                      plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_scooped": (cut(box(0, 0, 0, 60, 60, 30),
                           extruded(outline((11, 10), ((40, 10),), ((40, 14),), ((11, 14),), ((10.707107, 13.292893), (10, 13)),
                                            ((10, 11),), ((10.707107, 10.707107), (11, 10))), -1, 10)), "bed",
                       plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_oversize": (cut(box(0, 0, 0, 60, 60, 30), filleted_pocket(10, 10, -1, 40, 14, 10, {(10.0, 10.0): 2.5, (10.0, 14.0): 0.5})),
                        "bed", plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_reversed": (cut(box(0, 0, 0, 60, 60, 30), extruded(outline((10, 10), ((40, 10),), ((40, 14),), ((10, 14),), ((10, 10),)), -1, 10)),
                        "bed", plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_bowtie": (cut(box(0, 0, 0, 60, 60, 30), extruded(outline((10, 10), ((40, 10),), ((10, 14),), ((40, 14),), ((10, 10),)), -1, 10)),
                      "bed", plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_elliptic": (cut(box(0, 0, 0, 60, 60, 30), elliptic_strip(10, 10, 40, 4.0, 3.0, -1, 10)), "bed",
                        plane("roof", (25, 12, 10), (0, 0, -1)), {}),
    "pocket_elliptic_thin": (cut(box(0, 0, 0, 60, 60, 30), elliptic_strip(10, 10, 40, 0.0015, 1.0, -1, 10)), "bed",
                             plane("roof", (25, 10.00075, 10), (0, 0, -1)), {}),
    "pocket_boss": (cut(box(0, 0, 0, 60, 60, 30), cut(box(10, 27, -1, 40, 33, 10), box(21.25, 28, -2, 28.75, 32, 11))), "bed",
                    plane("roof", (12, 28, 10), (0, 0, -1)), {}),
    "pair": (occ.compound([box(0, 0, 0, 10, 10, 2), box(30, 0, 0, 40, 10, 2)]), "bed", {}, {}),
}

report = {}
for name, (shape, frame, locators, plan) in CASES.items():
    report[name] = form_check.probe(shape, frame=frame, locators=locators, plan=plan)
print(json.dumps(report))
