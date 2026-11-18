"""Test fixture: swing arm whose one solid has a reversed face, build123d. A closed shell that is still one solid, but an invalid B-rep."""

from build123d import Align, Box, Pos, Solid
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid

KERNEL = "build123d"
PARAMS = {"length": 60.0, "width": 20.0, "thickness": 5.0, "z0": 20.0}


def build(params: dict):
    w, t, z0 = params["width"], params["thickness"], params["z0"]
    box = Pos(-w / 2, -w / 2, z0) * Box(params["length"] + w / 2, w, t, align=(Align.MIN, Align.MIN, Align.MIN))
    builder = BRep_Builder()
    shell, solid = TopoDS_Shell(), TopoDS_Solid()
    builder.MakeShell(shell)
    for index, face in enumerate(list(box.faces())):
        builder.Add(shell, face.wrapped.Reversed() if index == 0 else face.wrapped)
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return Solid(solid)
