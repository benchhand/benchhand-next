# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["trimesh==4.*", "numpy==2.5.5", "networkx", "lxml>=5", "lib3mf>=2.4; sys_platform != 'linux' or platform_machine == 'x86_64'"]
# ///
"""Read a part.3mf with trimesh, validate its XML parts against the 3MF schemas and read it with lib3mf.

Usage: uv run --script threemf_probe.py PART.3mf
Stdout: {"trimesh": {...}, "schema": {entry: [error, ...]}, "lib3mf": {...} or {"skipped": why}} as JSON.
lib3mf ships no wheel for Linux aarch64, so it is skipped there.
"""

import json
import sys
import zipfile
from pathlib import Path

import trimesh
from lxml import etree

SCHEMAS = Path(__file__).resolve().parent / "3mf-schema"
# Each entry and its schema: the Core 1.4.0 model and the two OPC parts.
SCHEMA_OF = {"3D/3dmodel.model": "3mf-core.xsd", "[Content_Types].xml": "opc-contentTypes.xsd",
             "_rels/.rels": "opc-relationships.xsd"}


def read_with_trimesh(path: Path) -> dict:
    scene = trimesh.load(str(path), file_type="3mf", process=False)
    meshes = list(scene.geometry.values())
    (name,) = scene.graph.nodes_geometry
    transform, _ = scene.graph[name]
    mesh = trimesh.util.concatenate(meshes)
    return {"units": scene.units, "geometries": len(meshes), "transform": [[float(v) for v in row] for row in transform],
            "watertight": bool(mesh.is_watertight), "winding_consistent": bool(mesh.is_winding_consistent),
            "volume_mm3": float(mesh.volume)}


def validate(path: Path) -> dict:
    errors = {}
    with zipfile.ZipFile(path) as archive:
        for entry, schema in SCHEMA_OF.items():
            validator = etree.XMLSchema(etree.parse(str(SCHEMAS / schema)))
            document = etree.fromstring(archive.read(entry))
            validator.validate(document)
            errors[entry] = [str(error) for error in validator.error_log]
    return errors


def read_with_lib3mf(path: Path) -> dict:
    try:
        import lib3mf
    except ImportError as error:
        return {"skipped": f"no lib3mf wheel for this platform: {error}"}
    wrapper = lib3mf.Wrapper()
    model = wrapper.CreateModel()
    reader = model.QueryReader("3mf")
    reader.SetStrictModeActive(True)
    reader.ReadFromFile(str(path))
    meshes = model.GetMeshObjects()
    count = triangles = vertices = 0
    while meshes.MoveNext():
        mesh = meshes.GetCurrentMeshObject()
        count += 1
        vertices += mesh.GetVertexCount()
        triangles += mesh.GetTriangleCount()
    return {"warnings": reader.GetWarningCount(), "meshes": count, "vertices": vertices, "triangles": triangles}


target = Path(sys.argv[1])
print(json.dumps({"trimesh": read_with_trimesh(target), "schema": validate(target), "lib3mf": read_with_lib3mf(target)}))
