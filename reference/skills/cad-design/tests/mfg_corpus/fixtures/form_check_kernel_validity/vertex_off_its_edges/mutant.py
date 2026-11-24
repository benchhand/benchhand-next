"""Corpus fixture: a 20 mm cube whose first corner vertex sits 1e-5 mm off its three edges, CadQuery. The vertex
keeps its 1e-7 mm tolerance, so the in-memory B-rep is invalid (BRepCheck). The faces keep their exact bounds, so the
kernel volume is the cube's. The STEP read-back heals the vertex and moves the volume by about 1.7e-7 relative, inside
the read-back tolerance. Only the in-memory validity check sees the defect. The twin leaves the vertex in place.
"""

import cadquery as cq
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.gp import gp_Pnt

KERNEL = "cadquery"
PARAMS = {"size": 20.0, "vertex_offset": 1e-5, "vertex_tolerance": 1e-7}


def build(params: dict) -> cq.Shape:
    p = {**PARAMS, **params}
    cube = cq.Workplane("XY").box(p["size"], p["size"], p["size"], centered=False).val()
    corner = cube.Vertices()[0]
    point, d = BRep_Tool.Pnt_s(corner.wrapped), p["vertex_offset"]
    moved = gp_Pnt(point.X() + d, point.Y() + d, point.Z() + d)
    BRep_Builder().UpdateVertex(corner.wrapped, moved, p["vertex_tolerance"])
    return cube
