"""Test fixture: a 20 mm tall disc whose top rim carries a 1.2 mm fillet, CadQuery.

The fillet is a torus of R44.85 mm and r1.2 mm, the shape of lamp-arm's worst face (LMP-0004, face 28)."""

import cadquery as cq

KERNEL = "cadquery"
PARAMS = {"radius": 46.05, "height": 20.0, "fillet": 1.2}


def build(params: dict) -> cq.Shape:
    disc = cq.Workplane("XY").circle(params["radius"]).extrude(params["height"])
    return disc.faces(">Z").edges().fillet(params["fillet"]).val()
