# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "jsonschema>=4.23", "pyyaml>=6.0", "trimesh==4.*", "numpy==2.5.5", "python-fcl==0.7.0.11"]
# ///
"""Judge a part whose components hold different shapes with `manufacture.inspect` and print what it read back.

The part TST-0001 is a 1 x 1 x 1 box. Its components, each in its own STEP file, are that box (A), a
2 x 3 x 4 box (B) and a unit box at X 5 to 6 (C).
Usage: uv run --script inspect_probe.py DIR  (stdout: {"part": {...}, "components": {id: {...}}})
"""

import json
import sys
from pathlib import Path

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import manufacture  # noqa: E402
from cadmodel.motion import load_pose  # noqa: E402

PN, PRODUCT = "TST-0001", "TST-0001 Box"
pose = load_pose()
target = Path(sys.argv[1])
unit = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
shapes = {"A": unit, "B": BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape(),
          "C": BRepPrimAPI_MakeBox(gp_Pnt(5.0, 0.0, 0.0), 1.0, 1.0, 1.0).Shape()}
volumes = {"A": 1.0, "B": 24.0, "C": 1.0}
placement = {"transform": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], "frame": "model"}

files = ["part.step"]
(target / "components").mkdir(parents=True)
pose.write_part_step(target / "part.step", pose.Part(PN, PRODUCT, unit))
components = {}
for ident, shape in shapes.items():
    (target / "components" / ident).mkdir()
    pose.write_part_step(target / "components" / ident / "part.step", pose.Part(PN, PRODUCT, shape))
    files.append(f"components/{ident}/part.step")
    components[ident] = {"binding": "witness", "points_mm": [], "multiplicity": 1, "volume_mm3": volumes[ident],
                         "files": [f"components/{ident}/part.step"], "placement": placement}
facts = {"kernel_volume_mm3": 1.0, "kernel_valid": True, "kernel_solids": 1}
record = {"PN": PN, "rev": "X1", "material": "PETG", "process": "fdm", "finish": "none"}
entry = {**record, "product": PRODUCT, "native": facts, "installed": facts, "tolerance": {"allowed_mm3": 1.0},
         "outputs": ["part.step", "manufacturing.json"], "mesh": None, "placement": placement,
         "components": components}
row, _ = manufacture.inspect(target, entry, record, files)
checks = row["checks"]
print(json.dumps({
    "part": {"step": checks["step"], "placement": checks["placement"]},
    "components": {ident: {"step": r["checks"]["step"], "placement": r["checks"]["placement"]}
                   for ident, r in checks["components"]["components"].items()}}))
