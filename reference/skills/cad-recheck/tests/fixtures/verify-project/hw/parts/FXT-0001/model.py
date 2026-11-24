"""FXT-0001 Test block: a 20 x 20 x 10 mm block, the only part of the verify fixture project."""

import cadquery as cq

KERNEL = "cadquery"
PARAMS = {"length": 20.0, "width": 20.0, "height": 10.0}


def build(params: dict) -> cq.Shape:
    p = {**PARAMS, **params}
    return cq.Workplane("XY").box(p["length"], p["width"], p["height"], centered=(True, True, False)).val()
