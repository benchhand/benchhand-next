"""Corpus fixture: mounting plate on the base, CadQuery, with one 3 mm hole at `hole_x`."""

import cadquery as cq

KERNEL = "cadquery"
PARAMS = {"length": 60.0, "width": 20.0, "thickness": 5.0, "z0": 20.0, "hole": 3.0, "hole_x": 25.0, "drilled": True}


def build(params: dict) -> cq.Shape:
    w, t = params["width"], params["thickness"]
    plate = cq.Solid.makeBox(params["length"], w, t, cq.Vector(-10, -w / 2, params["z0"]))
    if not params["drilled"]:
        return plate
    return plate.cut(cq.Solid.makeCylinder(params["hole"] / 2, t, cq.Vector(params["hole_x"], 0, params["z0"])))
