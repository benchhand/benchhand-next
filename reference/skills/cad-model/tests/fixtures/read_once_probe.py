# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "jsonschema>=4.23", "pyyaml>=6.0", "trimesh==4.*", "numpy==2.5.5", "python-fcl==0.7.0.11"]
# ///
"""Count the STEP reads of two `manufacture.inspect` calls on a part with component outputs, 3MF included.

The part TST-0001 is a 1 x 1 x 1 box with part.step and part.3mf. Its components A (the unit box) and B (a
2 x 3 x 4 box) each hold their own part.step and part.3mf, so the step check and the 3MF check of a component
both need that STEP. `manufacture.read_part` is spied on, and `inspect` runs twice on the same folder.
Usage: uv run --script read_once_probe.py DIR
Stdout: {"first": {path: reads}, "second": {path: reads}, "threemf": {path: judged}} as JSON, paths below DIR.
"""

import json
import sys
from pathlib import Path
from unittest import mock

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import manufacture, mesh, threemf  # noqa: E402
from cadmodel.motion import load_pose  # noqa: E402

PN, PRODUCT, MATERIAL = "TST-0001", "TST-0001 Box", "PETG"
MESH = {"linear_deflection_mm": 0.05, "angular_deflection_rad": 0.1}
pose = load_pose()
target = Path(sys.argv[1])
shapes = {"A": BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), "B": BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()}
volumes = {"A": 1.0, "B": 24.0}
placement = {"transform": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], "frame": "model"}


def lay_out(folder: Path, shape) -> None:
    """part.step and the part.3mf tessellated from its read-back, in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    pose.write_part_step(folder / "part.step", pose.Part(PN, PRODUCT, shape))
    written, problem = manufacture.read_part(folder / "part.step", PN)
    assert written is not None, problem
    vertices, triangles = mesh.surface(written.shape, MESH["linear_deflection_mm"], MESH["angular_deflection_rad"])
    threemf.write(folder / "part.3mf", vertices, triangles, name=PRODUCT, material=MATERIAL)


lay_out(target, shapes["A"])
components = {}
files = ["part.step", "part.3mf"]
for ident, shape in shapes.items():
    lay_out(target / "components" / ident, shape)
    files += [f"components/{ident}/part.step", f"components/{ident}/part.3mf"]
    components[ident] = {"binding": "witness", "points_mm": [], "multiplicity": 1, "volume_mm3": volumes[ident],
                         "files": [f"components/{ident}/part.step"], "placement": placement}
facts = {"kernel_volume_mm3": 1.0, "kernel_valid": True, "kernel_solids": 1}
record = {"PN": PN, "rev": "X1", "material": MATERIAL, "process": "fdm", "finish": "none"}
entry = {**record, "product": PRODUCT, "color": None, "native": facts, "installed": facts,
         "tolerance": {"allowed_mm3": 1.0}, "outputs": ["part.step", "part.3mf", "manufacturing.json"],
         "component_outputs": [name for name in files if name.startswith("components/")],
         "mesh": MESH, "placement": placement, "components": components}
expected = [*files, "manufacturing.json"]
(target / "manufacturing.json").write_text("{}", encoding="utf-8")

real = manufacture.read_part
reads: dict[str, int] = {}


def spy(path, pn):
    key = Path(path).relative_to(target).as_posix()
    reads[key] = reads.get(key, 0) + 1
    return real(path, pn)


report = {}
with mock.patch.object(manufacture, "read_part", spy):
    for call in ("first", "second"):
        reads.clear()
        row, _ = manufacture.inspect(target, entry, record, expected)
        report[call] = dict(reads)
        judged = row["checks"]["threemf"]["files"]
        report["threemf"] = {name: "step_volume_mm3" in r for name, r in judged.items()}
print(json.dumps(report))
