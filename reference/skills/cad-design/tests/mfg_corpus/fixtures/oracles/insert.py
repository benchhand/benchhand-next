"""Corpus fixture: heat-set insert, a 7.97 mm cylinder 8 mm long standing in the base bore, CadQuery."""

import cadquery as cq

KERNEL = "cadquery"
PARAMS = {"diameter": 7.97, "length": 8.0, "x": 0.0}


def build(params: dict) -> cq.Shape:
    return cq.Solid.makeCylinder(params["diameter"] / 2, params["length"], cq.Vector(params["x"], 0, 0))
