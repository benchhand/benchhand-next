"""Test fixture: swing arm whose one solid has a reversed face, CadQuery. A closed shell that is still one solid, but an invalid B-rep."""

import cadquery as cq
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid

KERNEL = "cadquery"
PARAMS = {"length": 60.0, "width": 20.0, "thickness": 5.0, "z0": 20.0}


def build(params: dict) -> cq.Shape:
    w, t, z0 = params["width"], params["thickness"], params["z0"]
    box = cq.Solid.makeBox(params["length"] + w / 2, w, t, cq.Vector(-w / 2, -w / 2, z0))
    builder = BRep_Builder()
    shell, solid = TopoDS_Shell(), TopoDS_Solid()
    builder.MakeShell(shell)
    for index, face in enumerate(box.Faces()):
        builder.Add(shell, face.wrapped.Reversed() if index == 0 else face.wrapped)
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return cq.Shape.cast(solid)
