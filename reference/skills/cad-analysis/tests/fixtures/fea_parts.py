# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = ["cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "vtk==9.6.2"]
# ///
"""Realistic FEA test parts, built with the kernel cad-model's run_cadquery.py uses.

Usage: uv run --script fea_parts.py NAME OUT.step [PN]   write one part and print its metadata as JSON; with PN
                                                         the solid carries that product number as its STEP name
       uv run --script fea_parts.py --list             print the part names

Benchmark and test geometry only: sizes are typical of the part type, not a design. All lengths are in mm.
Each part is one solid in its own frame, so a case selects faces by plane or by index.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cadquery as cq


def l_bracket() -> cq.Workplane:
    """Sheet-metal L-bracket, 2 mm: a 60 x 40 base and a 40 high flange, 2 mm inner and 4 mm outer bend radius,
    two 5 mm holes in the base and two in the flange."""
    thickness, width = 2.0, 40.0
    base = cq.Workplane("XY").box(60, width, thickness, centered=False)
    flange = cq.Workplane("XY").box(thickness, width, 40, centered=False)
    part = base.union(flange)
    part = part.edges(cq.selectors.NearestToPointSelector((thickness, width / 2, thickness))).fillet(2.0)
    part = part.edges(cq.selectors.NearestToPointSelector((0, width / 2, 0))).fillet(4.0)
    base_holes = cq.Workplane("XY").workplane(offset=-1).pushPoints([(30, 10), (30, 30)]).circle(2.5).extrude(thickness + 2)
    flange_holes = cq.Workplane("YZ").workplane(offset=-1).pushPoints([(10, 25), (30, 25)]).circle(2.5).extrude(thickness + 2)
    return part.cut(base_holes).cut(flange_holes)


def moulded_housing() -> cq.Workplane:
    """Ribbed moulded housing, 80 x 60 x 30 with 2.5 mm walls and floor, open at the top: four screw bosses (7 mm,
    2.8 mm pilot hole) that stop 2 mm below the rim, and three 1.5 mm ribs on the floor."""
    wall, length, width, height = 2.5, 80.0, 60.0, 30.0
    shell = cq.Workplane("XY").box(length, width, height, centered=False)
    cavity = cq.Workplane("XY").box(length - 2 * wall, width - 2 * wall, height, centered=False).translate((wall, wall, wall))
    part = shell.cut(cavity)
    corners = [(9, 9), (length - 9, 9), (9, width - 9), (length - 9, width - 9)]
    bosses = cq.Workplane("XY").workplane(offset=wall - 0.5).pushPoints(corners).circle(3.5).extrude(height - 2 - wall + 0.5)
    part = part.union(bosses)
    pilots = cq.Workplane("XY").workplane(offset=height - 2 - 14).pushPoints(corners).circle(1.4).extrude(15)
    part = part.cut(pilots)
    ribs = [cq.Workplane("XY").box(60, 1.5, 12, centered=False).translate((10, width / 2 - 0.75, wall - 0.5)),
            cq.Workplane("XY").box(1.5, 40, 10, centered=False).translate((length / 3 - 0.75, 10, wall - 0.5)),
            cq.Workplane("XY").box(1.5, 40, 10, centered=False).translate((2 * length / 3 - 0.75, 10, wall - 0.5))]
    for rib in ribs:
        part = part.union(rib)
    return part


def pillow_block() -> cq.Workplane:
    """Machined pillow block: a 100 x 40 x 14 base with four 9 mm mounting holes, a 50 x 40 body to z = 50 and a
    25 mm bearing bore along Y at z = 32."""
    base = cq.Workplane("XY").box(100, 40, 14, centered=(True, True, False))
    body = cq.Workplane("XY").workplane(offset=14).box(50, 40, 36, centered=(True, True, False))
    part = base.union(body)
    bore = cq.Workplane("XZ").workplane(offset=-25).center(0, 32).circle(12.5).extrude(50)
    holes = cq.Workplane("XY").workplane(offset=-1).pushPoints([(-38, -12), (38, -12), (-38, 12), (38, 12)]).circle(4.5).extrude(16)
    return part.cut(bore).cut(holes)


def pipe_flange() -> cq.Workplane:
    """Weld-neck style pipe flange: a 150 mm disc, 18 mm thick, a 90 mm neck to z = 40, a 60.3 mm bore and eight
    18 mm bolt holes on a 110 mm circle."""
    disc = cq.Workplane("XY").circle(75).extrude(18)
    neck = cq.Workplane("XY").circle(45).extrude(40)
    part = disc.union(neck)
    bore = cq.Workplane("XY").workplane(offset=-1).circle(30.15).extrude(42)
    bolts = cq.Workplane("XY").workplane(offset=-1).polarArray(55, 0, 360, 8).circle(9).extrude(20)
    return part.cut(bore).cut(bolts)


def keyed_shaft() -> cq.Workplane:
    """Stepped shaft along X: 30 mm for 40, a 40 mm shoulder for 60 and 35 mm for 40, with an 8 mm wide, 4 mm deep
    keyway 32 mm long on the 30 mm section."""
    first = cq.Workplane("YZ").circle(15).extrude(40)
    shoulder = cq.Workplane("YZ").workplane(offset=40).circle(20).extrude(60)
    last = cq.Workplane("YZ").workplane(offset=100).circle(17.5).extrude(40)
    part = first.union(shoulder).union(last)
    keyway = cq.Workplane("XY").box(32, 8, 6, centered=(False, True, False)).translate((4, 0, 11))
    return part.cut(keyway)


def sprocket() -> cq.Workplane:
    """Sixteen-tooth sprocket-like gear, 8 mm thick, root radius 34 and tip radius 40 (straight trapezoid teeth, not
    an involute), a 20 mm bore with a 6 mm keyway."""
    teeth, root, tip = 16, 34.0, 40.0
    pitch = 2 * math.pi / teeth
    points = []
    for i in range(teeth):
        base = i * pitch
        for angle, radius in ((-0.30, root), (-0.12, tip), (0.12, tip), (0.30, root)):
            points.append(((radius * math.cos(base + angle * pitch)), radius * math.sin(base + angle * pitch)))
    blank = cq.Workplane("XY").polyline(points).close().extrude(8)
    bore = cq.Workplane("XY").workplane(offset=-1).circle(10).extrude(10)
    keyway = cq.Workplane("XY").workplane(offset=-1).center(10.5, 0).rect(5.6, 6).extrude(10)
    return blank.cut(bore).cut(keyway)


def truss_member() -> cq.Workplane:
    """Warren-truss frame member in solid square bar: 320 long chords 100 apart (16 mm bars) joined by four 12 mm
    diagonals."""
    chord, depth, length, gusset = 16.0, 100.0, 320.0, 12.0
    bottom = cq.Workplane("XY").box(length, chord, chord, centered=False)
    top = cq.Workplane("XY").box(length, chord, chord, centered=False).translate((0, 0, depth - chord))
    part = bottom.union(top)
    nodes = [(0, 0), (80, 1), (160, 0), (240, 1), (320, 0)]   # alternate bottom (0) and top (1) joints
    centre = chord / 2
    for (x0, lo), (x1, hi) in zip(nodes, nodes[1:]):
        z0 = centre if lo == 0 else depth - centre
        z1 = centre if hi == 0 else depth - centre
        x1 = min(x1, length)
        dx, dz = x1 - x0, z1 - z0
        norm = math.hypot(dx, dz)
        nx, nz = -dz / norm * gusset / 2, dx / norm * gusset / 2
        strip = [(x0 + nx, z0 + nz), (x1 + nx, z1 + nz), (x1 - nx, z1 - nz), (x0 - nx, z0 - nz)]
        diagonal = cq.Workplane("XZ").polyline(strip).close().extrude(-chord)   # XZ normal is -Y: extrude(-n) runs +Y
        part = part.union(diagonal)
    return part.intersect(cq.Workplane("XY").box(length, chord, depth, centered=False))   # square off the chord ends


PARTS = {"l_bracket": l_bracket, "moulded_housing": moulded_housing, "pillow_block": pillow_block,
         "pipe_flange": pipe_flange, "keyed_shaft": keyed_shaft, "sprocket": sprocket, "truss_member": truss_member}


def describe(name: str, shape: cq.Workplane) -> dict[str, object]:
    solid = shape.val()
    box = solid.BoundingBox()
    return {"name": name, "solids": len(shape.solids().vals()), "volume_mm3": round(solid.Volume(), 3),
            "bbox_mm": [round(box.xmin, 3), round(box.ymin, 3), round(box.zmin, 3),
                        round(box.xmax, 3), round(box.ymax, 3), round(box.zmax, 3)],
            "faces": len(shape.faces().vals())}


def main(argv: list[str]) -> int:
    if argv == ["--list"]:
        print(json.dumps(sorted(PARTS)))
        return 0
    if len(argv) not in (2, 3) or argv[0] not in PARTS:
        print(f"usage: fea_parts.py NAME OUT.step [PN] | --list (names: {', '.join(sorted(PARTS))})", file=sys.stderr)
        return 2
    shape = PARTS[argv[0]]()
    if len(argv) == 3:   # a versioned case names the part it analyzes, so the STEP names its solid by product number
        cq.Assembly().add(shape, name=argv[2]).save(str(Path(argv[1])), exportType="STEP")
    else:
        cq.exporters.export(shape, str(Path(argv[1])), exportType="STEP")
    print(json.dumps(describe(argv[0], shape)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
