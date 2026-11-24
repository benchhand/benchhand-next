"""Corpus fixture: base block with one through bore, CadQuery. `shape` "round" keeps the plan area
(size squared) and so the volume, but is a cylinder. `bore_x` moves the bore along X."""

import math

import cadquery as cq

KERNEL = "cadquery"
PARAMS = {"size": 40.0, "height": 20.0, "bore": 7.77, "bore_x": 0.0, "shape": "box"}


def build(params: dict) -> cq.Shape:
    s, h = params["size"], params["height"]
    if params["shape"] == "round":
        body = cq.Solid.makeCylinder(s / math.sqrt(math.pi), h, cq.Vector(0, 0, 0))
    else:
        body = cq.Solid.makeBox(s, s, h, cq.Vector(-s / 2, -s / 2, 0))
    bore = cq.Solid.makeCylinder(params["bore"] / 2, h, cq.Vector(params["bore_x"], 0, 0))
    return body.cut(bore)
