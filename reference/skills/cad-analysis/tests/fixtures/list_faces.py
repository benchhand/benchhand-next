"""FreeCAD job: list the faces of a part's STEP in the order fea_static numbers them (1-based).

Run with `freecadcmd list_faces.py`. It reads FEA_FACES_STEP and writes JSON to FEA_FACES_OUT. Each row has the
surface kind, the center of mass, the area, the bounding box and, for a cylinder, its radius and axis.
"""

import json
import os

import FreeCAD as App
import Import

doc = App.newDocument("Faces")
Import.insert(os.environ["FEA_FACES_STEP"], doc.Name)
doc.recompute()
solids = [solid for obj in doc.Objects if obj.isDerivedFrom("Part::Feature") and not obj.Shape.isNull() for solid in obj.Shape.Solids]
if len(solids) != 1:
    raise RuntimeError(f"expected one solid, found {len(solids)}")
rows = []
for index, face in enumerate(solids[0].Faces, 1):
    surface = face.Surface
    kind = type(surface).__name__
    box = face.BoundBox
    row = {"index": index, "kind": kind, "area": face.Area,
           "centre": [face.CenterOfMass.x, face.CenterOfMass.y, face.CenterOfMass.z],
           "bbox": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]}
    if kind == "Cylinder":
        row["radius"] = surface.Radius
        row["axis"] = [surface.Axis.x, surface.Axis.y, surface.Axis.z]
    if kind == "Plane":
        row["normal"] = [surface.Axis.x, surface.Axis.y, surface.Axis.z]
    rows.append(row)
with open(os.environ["FEA_FACES_OUT"], "w", encoding="utf-8") as stream:
    json.dump(rows, stream)
