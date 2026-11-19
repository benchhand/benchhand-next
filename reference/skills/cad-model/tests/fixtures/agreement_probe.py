# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0", "numpy==2.5.5"]
# ///
"""Run `cadmodel.agreement` on shapes built here and on a GLB written here; print the verdicts as JSON.

Every case compares a GLB mesh (the tessellation of one shape at the exporter's deflection) with the
STEP shape it should depict (a second shape, or the same one). Usage: uv run --script agreement_probe.py DIR
"""

import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeSphere
from OCP.collections import Array1_gp_Pnt, Array2_gp_Pnt
from OCP.GeomAPI import GeomAPI_PointsToBSpline, GeomAPI_PointsToBSplineSurface
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import agreement, mesh, occ  # noqa: E402

LINEAR = 0.04  # the exporter's deflection in these cases, mm: what a 40 mm part gets (0.0005 of its diagonal)
LARGE_LINEAR = 0.05  # the deflection of a large assembly's GLB, such as examples/lamp-arm's, mm
EMPTY_POINTS, EMPTY_TRIANGLES = np.empty((0, 3)), np.empty((0, 3), dtype=np.int64)
ROT = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def block(size: float = 40.0, height: float = 20.0, hole_x: float | None = 0.0, hole_d: float = 6.0) -> Any:
    """A size x size x height block centered on the Z axis with a through hole of diameter hole_d at (hole_x, 0)."""
    body = BRepPrimAPI_MakeBox(gp_Pnt(-size / 2, -size / 2, 0), size, size, height).Shape()
    if hole_x is None:
        return body
    axis = gp_Ax2(gp_Pnt(hole_x, 0, 0), gp_Dir(0, 0, 1))
    return BRepAlgoAPI_Cut(body, BRepPrimAPI_MakeCylinder(axis, hole_d / 2, height).Shape()).Shape()


def round_block(height: float = 20.0) -> Any:
    """A cylinder of the 40 x 40 block's plan area and height, with the same 6 mm hole: the same volume."""
    radius = 40.0 / math.sqrt(math.pi)
    body = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), radius, height).Shape()
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 3.0, height).Shape()
    return BRepAlgoAPI_Cut(body, hole).Shape()


def moved(mesh: Any, dx: float) -> Any:
    return agreement.placed(mesh, ROT, (dx, 0.0, 0.0))


def verdict(drawn: Any, depicted: Any, *, shift: float = 0.0, linear: float = LINEAR) -> dict[str, Any]:
    mesh = moved(agreement.reference(drawn, linear), shift)
    return agreement.compare(mesh, agreement.reference(depicted, linear / 4), linear)


def cases() -> dict[str, Any]:
    clean = block()
    plain = block(hole_x=None)  # flat faces only: the tessellation is exact, so the floor is not blurred by chords
    return {
        "same_shape": verdict(clean, clean),
        "equal_volume_cylinder": verdict(round_block(), clean),
        "shifted_3_mm": verdict(clean, clean, shift=3.0),
        "flat_shifted_just_above_floor": verdict(plain, plain, shift=0.13),
        "flat_shifted_just_below_floor": verdict(plain, plain, shift=0.12),
        "flat_shifted_above_large_floor": verdict(plain, plain, shift=0.16, linear=LARGE_LINEAR),
        "flat_shifted_below_large_floor": verdict(plain, plain, shift=0.15, linear=LARGE_LINEAR),
        "hole_moved_8_mm": verdict(block(hole_x=8.0), clean),
        "hole_missing_in_mesh": verdict(block(hole_x=None), clean),
        "extra_hole_in_mesh": verdict(clean, block(hole_x=None)),
        "hole_6_vs_6_5": verdict(block(hole_d=6.5), clean),
        "mesh_empty": agreement.compare(agreement.Mesh(EMPTY_POINTS, EMPTY_TRIANGLES), agreement.reference(clean, LINEAR), LINEAR),
        "step_empty": agreement.compare(agreement.reference(clean, LINEAR), agreement.Mesh(EMPTY_POINTS, EMPTY_TRIANGLES), LINEAR),
        "thousand_times_larger": agreement.compare(
            agreement.Mesh(agreement.reference(clean, LINEAR).points * 1000, agreement.reference(clean, LINEAR).triangles),
            agreement.reference(clean, LINEAR), LINEAR),
    }


def write_glb(path: Path, nodes: list[dict[str, Any]], mesh_index: int | None) -> None:
    """A one-triangle glTF: points (0,0,0), (0.001,0,0), (0,0.001,0) meters in mesh 0."""
    points = struct.pack("<9f", 0, 0, 0, 0.001, 0, 0, 0, 0.001, 0)
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
        "meshes": [{"name": "TST", "primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "bufferViews": [{"buffer": 0, "byteLength": len(points)}], "buffers": [{"byteLength": len(points)}]}
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(points), b"BIN\0") + points
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def glb_case(folder: Path) -> dict[str, Any]:
    """A parent translated (0.01, 0.02, 0.03) m holding a child turned +90 degrees about glTF Y that holds the mesh."""
    quarter = math.sin(math.pi / 4)
    write_glb(folder / "nested.glb",
              [{"name": "outer", "translation": [0.01, 0.02, 0.03], "children": [1]},
               {"name": "inner", "rotation": [0.0, quarter, 0.0, quarter], "mesh": 0}], 0)
    read = agreement.read_glb(folder / "nested.glb")
    return {"names": sorted(read), "points": read["inner"].points.tolist(), "triangles": read["inner"].triangles.tolist()}


def fillet_ring(radius: float = 46.05) -> Any:
    """A 10 mm tall disc of `radius` mm whose top rim carries a 1.2 mm fillet. At the default radius that is a torus of
    R44.85 mm, r1.2 mm, the shape of lamp-arm's worst face (LMP-0004, face 28)."""
    body = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), radius, 10.0).Shape()
    fillet = BRepFilletAPI_MakeFillet(body)
    for edge in occ.subshapes(body, "EDGE"):
        curve = BRepAdaptor_Curve(occ.downcast(edge, "EDGE"))
        if str(curve.GetType()).endswith("Circle") and abs(curve.Circle().Location().Z() - 10.0) < 1e-6:
            fillet.Add(1.2, occ.downcast(edge, "EDGE"))
    return fillet.Shape()


def write_mesh_glb(path: Path, triangles: Any, name: str) -> None:
    """A glTF holding one node `name` with the mesh `triangles` (a `Mesh` of the agreement code, mm, Z up), the inverse of
    `agreement.read_glb`: (x, y, z) -> (x, z, -y) / 1000 m, 32-bit indices."""
    points = (triangles.points[:, [0, 2, 1]] * np.array([1.0, 1.0, -1.0]) / 1000.0).astype("<f4").tobytes()
    indices = triangles.triangles.astype("<u4").reshape(-1).tobytes()
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(triangles.points), "type": "VEC3"},
                      {"bufferView": 1, "componentType": 5125, "count": len(triangles.triangles) * 3, "type": "SCALAR"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(points)},
                        {"buffer": 0, "byteOffset": len(points), "byteLength": len(indices)}],
        "buffers": [{"byteLength": len(points) + len(indices)}]}
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary = points + indices
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def attempt(call: Any) -> Any:
    """`call()`, or the failure as data: one missing behavior then fails its own test, not the whole probe."""
    try:
        return call()
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"}


def sphere(radius: float) -> Any:
    """A ball: BRepMesh bounds a sphere by its angular deflection, so the radius sets the reference's sag."""
    return BRepPrimAPI_MakeSphere(radius).Shape()


def extrusion(points: list[tuple[float, float]], height: float) -> Any:
    """The profile through `points` (a spline) closed by a straight edge, extruded `height` mm: its spline side is a
    surface of extrusion, curved when the points bend and flat when they are collinear."""
    array = Array1_gp_Pnt(1, len(points))
    for number, (x, y) in enumerate(points, 1):
        array.SetValue(number, gp_Pnt(x, y, 0))
    spline = BRepBuilderAPI_MakeEdge(GeomAPI_PointsToBSpline(array).Curve()).Edge()
    (x0, y0), (x1, y1) = points[0], points[-1]
    closing = BRepBuilderAPI_MakeEdge(gp_Pnt(x1, y1, 0), gp_Pnt(x0, y0, 0)).Edge()
    face = BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(spline, closing).Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape()


def bspline_patch() -> Any:
    """A 30 x 30 mm face on a B-spline surface that bulges 4 mm over a 4 x 4 grid of points."""
    grid = Array2_gp_Pnt(1, 4, 1, 4)
    for i in range(4):
        for j in range(4):
            grid.SetValue(i + 1, j + 1, gp_Pnt(10.0 * i, 10.0 * j, 4.0 if i in (1, 2) and j in (1, 2) else 0.0))
    return BRepBuilderAPI_MakeFace(GeomAPI_PointsToBSplineSurface(grid).Surface(), 1e-6).Face()


def reference_checks(folder: Path) -> dict[str, Any]:
    """The reference mesh's own error. Each shape's GLB is its mesh at the exporter's deflections, judged by
    `occurrences`: a small fillet disc (R4.8 mm torus), the large fillet ring (R44.85 mm, r1.2 mm), a ball of
    R5 mm whose 0.25 rad reference sags between the requested 0.025 mm and the reach's 0.05 mm share. With the
    mesher holding its deflection no solid sags past 0.05 mm, so the probe also judges the ring against a 0.01 mm budget."""
    placements = {"r": agreement.Placement("PART", ROT, (0.0, 0.0, 0.0))}
    reference_linear = LARGE_LINEAR * agreement.REFERENCE_FACTOR
    report: dict[str, Any] = {"reference_share_mm": reference_linear,
                              "budget_mm": agreement.REACH_MARGIN * reference_linear}
    for name, shape in (("disc", fillet_ring(6.0)), ("ring", fillet_ring(46.05)), ("mid", sphere(5.0)),
                        ("curved", extrusion([(0, 0), (10, 4), (20, 6), (30, 4), (40, 0)], 5.0)),
                        ("flat", extrusion([(0, 0), (10, 0), (20, 0), (30, 0), (40, 0)], 5.0)),
                        ("cylinder", BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10.0, 20.0).Shape()),
                        ("bspline", bspline_patch())):
        glb = folder / f"{name}.glb"
        write_mesh_glb(glb, agreement.reference(shape, LARGE_LINEAR), "part")

        def judged(shape: Any = shape, glb: Path = glb, **options: Any) -> dict[str, Any]:
            row: dict[str, Any] = agreement.occurrences(
                glb, {"r": "part"}, {"PART": shape}, placements, LARGE_LINEAR, **options)["r"]
            return row

        def deviation(shape: Any = shape) -> dict[str, Any] | None:
            found = agreement.reference_deviation(shape, reference_linear)
            return None if found is None else {"error_mm": found.error_mm, "face": found.face, "surface": found.surface}

        report[name] = {"verdict": attempt(judged), "deviation": attempt(deviation)}
        if name == "ring":
            report["tight"] = {"verdict": attempt(lambda: judged(reference_budget_mm=0.01)), "deviation": report[name]["deviation"]}
        if name in ("curved", "flat", "bspline"):
            report[name]["tight_verdict"] = attempt(lambda: judged(reference_budget_mm=0.001))
    return report


def abstentions(folder: Path) -> dict[str, Any]:
    """`occurrences` on the nested GLB: what it cannot judge it calls unknown, and says why."""
    shape = block()
    place = agreement.Placement
    placements = {"has_node": place("X", ROT, (0.0, 0.0, 0.0)), "no_node": place("X", ROT, (0.0, 0.0, 0.0)),
                  "no_shape": place("Y", ROT, (0.0, 0.0, 0.0))}
    nodes = {"has_node": "inner", "no_shape": "inner", "no_node": "absent"}
    glb = folder / "nested.glb"
    rows = agreement.occurrences(glb, nodes, {"X": shape}, placements, LINEAR)
    undeflected = agreement.occurrences(glb, nodes, {"X": shape}, placements, None)
    return {"rows": rows, "no_deflection": {oid: row["status"] for oid, row in undeflected.items()}}


def exporter_deflections() -> dict[str, float]:
    """What the exporter's `mesh.deflection` gives a 60 mm-diagonal part and a 1.2 m-diagonal assembly."""
    large = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 1000.0, 600.0, 300.0).Shape()
    return {"small": mesh.deflection(block()), "large": mesh.deflection(large)}


def filleted_disc() -> tuple[Any, Any]:
    """(a disc whose top rim has a 1.2 mm fillet, that fillet's torus face): a torus of major radius 44.85 mm,
    as on LMP-0004's face 28."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Torus

    from cadmodel import occ

    height = 10.0
    disc = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 44.85 + 1.2, height).Shape()
    fillet = BRepFilletAPI_MakeFillet(disc)
    for edge in (occ.downcast(e, "EDGE") for e in occ.subshapes(disc, "EDGE")):
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() == GeomAbs_Circle and abs(curve.Circle().Location().Z() - height) < 1e-6:
            fillet.Add(1.2, edge)
    shape = fillet.Shape()
    (torus,) = [f for f in occ.subshapes(shape, "FACE")
                if BRepAdaptor_Surface(occ.downcast(f, "FACE")).GetType() == GeomAbs_Torus]
    return shape, torus


def worst_distance(points: np.ndarray, target: Any, sample: int | None = 600) -> float:
    """The largest exact distance of `points` to `target`: of an even sample of about `sample` points, or of all
    of them when `sample` is None."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    tool = BRepExtrema_DistShapeShape()
    tool.LoadS2(target)
    worst = 0.0
    for point in points[::1 if sample is None else max(1, len(points) // sample)]:
        tool.LoadS1(BRepBuilderAPI_MakeVertex(gp_Pnt(*[float(c) for c in point])).Vertex())
        tool.Perform()
        worst = max(worst, tool.Value())
    return worst


def reference_torus_error(sag: float = 0.0) -> dict[str, float]:
    """The reference mesh of the filleted disc's torus face at the reference budget: the largest exact distance of a
    triangle center to that face, over an even sample of the centers. `sag` moves every vertex that far inward along
    the fillet's normal: a reference that sags into the solid."""
    _, torus = filleted_disc()
    budget = agreement.REFERENCE_FACTOR * LARGE_LINEAR
    reference = agreement.reference(torus, budget)
    points = reference.points.copy()
    radial = np.hypot(points[:, 0], points[:, 1])
    tube = np.stack([points[:, 0] / radial * 44.85, points[:, 1] / radial * 44.85, np.full(len(points), 10.0 - 1.2)], axis=1)
    normals = (points - tube) / np.linalg.norm(points - tube, axis=1)[:, None]
    centres = (points - sag * normals)[reference.triangles].mean(axis=1)
    return {"budget_mm": budget, "worst_mm": worst_distance(centres, torus), "triangles": float(len(centres))}


def glb_torus_error(folder: Path) -> dict[str, float]:
    """The exported GLB of the filleted disc, judged on the fillet face's own triangles. The exporter reads the STEP
    into an XCAF document and meshes its shape with `mesh.tessellate`. This code repeats both steps, finds the torus
    face of the shape it reads, and measures every one of the face's triangle centers, seam edges included,
    against that face. `matched` is the share of those centers that the exported GLB holds as a triangle center."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.collections import Sequence_TDF_Label
    from OCP.GeomAbs import GeomAbs_Torus
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    from cadmodel import occ

    shape, _ = filleted_disc()
    step = folder / "disc.step"
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    assert writer.Write(str(step)) == IFSelect_RetDone
    info = mesh.write_glb(step, folder / "disc.glb")
    glb_centres = np.concatenate([m.points[m.triangles].mean(axis=1)
                                  for m in agreement.read_glb(folder / "disc.glb").values()])

    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    assert reader.ReadFile(str(step)) == IFSelect_RetDone and reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = Sequence_TDF_Label()
    tool.GetFreeShapes(roots)
    read = tool.GetShape_s(roots.Value(1))
    mesh.tessellate(read, info["linear_deflection_mm"])
    (torus,) = [f for f in occ.subshapes(read, "FACE")
                if BRepAdaptor_Surface(occ.downcast(f, "FACE")).GetType() == GeomAbs_Torus]
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(occ.downcast(torus, "FACE"), location)
    transform = location.Transformation()
    nodes = [triangulation.Node(i).Transformed(transform) for i in range(1, triangulation.NbNodes() + 1)]
    centres = np.array([np.mean([[nodes[k - 1].X(), nodes[k - 1].Y(), nodes[k - 1].Z()]
                                 for k in triangulation.Triangle(i).Get()], axis=0)
                        for i in range(1, triangulation.NbTriangles() + 1)])
    nearest = np.array([np.linalg.norm(glb_centres - c, axis=1).min() for c in centres])
    return {"linear_mm": info["linear_deflection_mm"], "worst_mm": worst_distance(centres, torus, sample=None),
            "triangles": float(len(centres)), "matched": float((nearest < 1e-3).mean())}


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    glb = glb_case(folder)
    print(json.dumps({"cases": cases(), "glb": glb, "abstentions": abstentions(folder),
                      "reference": reference_checks(folder), "exporter_deflection_mm": exporter_deflections(),
                      "reference_torus": reference_torus_error(), "sagging_torus": reference_torus_error(0.1),
                      "glb_torus": glb_torus_error(folder)}))
