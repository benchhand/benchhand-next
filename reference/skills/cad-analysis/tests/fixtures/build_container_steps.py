"""Write two STEP files through FreeCAD into the directory that CAD_FIXTURE_OUT names.

Usage: CAD_FIXTURE_OUT=DIR freecadcmd cad-analysis/tests/fixtures/build_container_steps.py

two-roots.step is written from two root objects: the Part::Feature "TST-0401 Plate" (a 40 x 40 x 4 mm
plate at y 200..240) and the App::Part "TST-0402 Beam" holding one unnamed child "SOLID", the
100 x 10 x 5 mm cantilever beam. FreeCAD writes both under a top product named after the document and
imports "TST-0402 Beam" as a container whose own shape repeats its child's solid, the form in which
cad-model's part STEP of a located shape (LMP-0008) imports. The container is turned 90 degrees about
+Z and moved (200, 50, 0): the child's own shape stays at the origin, while the beam it places spans
x 190..200, y 50..150, z 0..5, with its end faces on y = 50 and y = 150.

multi-solid.step holds the Part::Feature "TST-0403 Pair": one shape of two disjoint solids, a
10 x 10 x 10 mm cube (1000 mm^3) and a 20 x 10 x 10 mm block (2000 mm^3). FreeCAD imports it as the
container "TST-0403 Pair002" around two leaves named after the part, as it imports cad-model's part
STEP of a two-solid compound.
"""

import os

import FreeCAD as App
import Import
import Part

out = os.environ["CAD_FIXTURE_OUT"]
doc = App.newDocument("ContainerFixtures")
plate = doc.addObject("Part::Feature", "Plate")
plate.Label = "TST-0401 Plate"
plate.Shape = Part.makeBox(40, 40, 4, App.Vector(0, 200, 0))
container = doc.addObject("App::Part", "Beam")
container.Label = "TST-0402 Beam"
beam = doc.addObject("Part::Feature", "SOLID")
beam.Shape = Part.makeBox(100, 10, 5)
container.addObject(beam)
container.Placement = App.Placement(
    App.Vector(200, 50, 0), App.Rotation(App.Vector(0, 0, 1), 90)
)
pair = doc.addObject("Part::Feature", "Pair")
pair.Label = "TST-0403 Pair"
pair.Shape = Part.makeCompound(
    [Part.makeBox(10, 10, 10), Part.makeBox(20, 10, 10, App.Vector(50, 0, 0))]
)
doc.recompute()
Import.export([plate, container], os.path.join(out, "two-roots.step"))
Import.export([pair], os.path.join(out, "multi-solid.step"))
App.closeDocument(doc.Name)
