# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "trimesh==4.*", "numpy==2.5.5", "pyyaml>=6.0"]
# ///
"""Write a drilled plate and a ball to STEP, tessellate their read-back into part.3mf and part.stl, and judge
the 3MF with manufacture.inspect (its threemf row), also after deliberate faults.

TST-0001: 40 x 30 x 8 plate with a through hole of diameter 5 (the cut gives the hole reversed faces).
TST-0002: a ball of radius 5 (BRepMesh emits a collapsed triangle at each pole).
Usage: uv run --script threemf_occ_probe.py DIR
Stdout: {PN: {"step_volume_mm3", "threemf_volume_mm3", "stl_volume_mm3", "good": judge, "faults": {name: judge}}} as JSON.
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import manufacture, mesh, occ, threemf  # noqa: E402
from cadmodel.motion import load_pose  # noqa: E402

MESH = {"linear_deflection_mm": 0.05, "angular_deflection_rad": 0.1}
MATERIAL = "PETG"
MODEL_PLACEMENT = {"transform": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], "frame": "model"}

plate = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40.0, 30.0, 8.0).Shape(),
                        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20, 15, -1), gp_Dir(0, 0, 1)), 2.5, 10.0).Shape()).Shape()
ball = BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 5), 5.0).Shape()

folder = Path(sys.argv[1])
pose = load_pose()
report = {}
for pn, title, shape in (("TST-0001", "Drilled plate", plate), ("TST-0002", "Ball", ball)):
    entry = {"PN": pn, "product": f"{pn} {title}", "material": MATERIAL, "mesh": MESH}
    step = folder / f"{pn}.step"
    pose.write_part_step(step, pose.Part(pn, entry["product"], shape))
    written, problem = manufacture.read_part(step, pn)
    assert written is not None, problem
    vertices, triangles = mesh.surface(written.shape, MESH["linear_deflection_mm"], MESH["angular_deflection_rad"])
    target = folder / f"{pn}.3mf"
    threemf.write(target, vertices, triangles, name=entry["product"], material=MATERIAL)
    stl = folder / f"{pn}.stl"
    mesh.write_stl(written.shape, stl, MESH["linear_deflection_mm"], MESH["angular_deflection_rad"])

    def judged(package: Path, declared: dict, color: str | None = None) -> dict:
        """The threemf row of manufacture.inspect for `package` laid out as the part's part.3mf beside its STEP,
        for a part whose record declares intent.color `color`."""
        part_folder = folder / f"{package.stem}-folder"
        part_folder.mkdir()
        shutil.copy(step, part_folder / "part.step")
        shutil.copy(package, part_folder / "part.3mf")
        record = {"PN": pn, "rev": "X1", "material": declared["material"], "process": "fdm", "finish": "none",
                  "intent": {"color": color} if color else {}}
        facts = {"kernel_volume_mm3": 1.0, "kernel_valid": True, "kernel_solids": 1}
        files = ["part.step", "part.3mf"]
        full = {**record, **declared, "native": facts, "installed": facts, "tolerance": {"allowed_mm3": 1.0},
                "outputs": files, "placement": MODEL_PLACEMENT}
        row, _ = manufacture.inspect(part_folder, full, record, files)
        return row["checks"]["threemf"]["files"]["part.3mf"]

    def variant(name: str, verts, tris, material=MATERIAL, color=None, expected=None) -> dict:
        path = folder / f"{pn}-{name}.3mf"
        threemf.write(path, verts, tris, name=entry["product"], material=material, color=color)
        return judged(path, entry, expected)

    def edited(name: str, old: str, new: str) -> dict:
        """The good package with `old` replaced by `new` in its model part, judged."""
        path = folder / f"{pn}-{name}.3mf"
        model = threemf.MODEL_PART
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(path, "w") as out:
            for info in source.infolist():
                data = source.read(info.filename)
                out.writestr(info, data.decode().replace(old, new, 1).encode() if info.filename == model else data)
        return judged(path, entry)

    item = '<item objectid="1"/>'
    faults = {
        "transformed": edited("transformed", item, '<item objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"/>'),
        "two_items": edited("two_items", item, item + item),
        "two_objects": edited("two_objects", "</resources>", '<object id="2" type="model"><mesh><vertices/><triangles/></mesh></object></resources>'),
        "colour_declared_not_written": variant("c1", vertices, triangles, expected="#336699"),
        "colour_written_not_declared": variant("c2", vertices, triangles, color="#336699"),
        "other_colour": variant("c3", vertices, triangles, color="#336698", expected="#336699"),
        "cracked": variant("cracked", vertices, triangles[:-1]),
        "inward": variant("inward", vertices, [(a, c, b) for a, b, c in triangles]),
        "scaled": variant("scaled", [(x * 1.1, y * 1.1, z * 1.1) for x, y, z in vertices], triangles),
        "other_material": variant("other_material", vertices, triangles, material="ABS"),
        "no_material": variant("no_material", vertices, triangles, material=None),
    }
    report[pn] = {"step_volume_mm3": occ.volume(written.shape),
                  "threemf_volume_mm3": threemf.measure(vertices, triangles)["volume_mm3"],
                  "stl_volume_mm3": mesh.stl_report(stl)["volume_mm3"],
                  "good": judged(target, entry),
                  "good_colour": variant("c4", vertices, triangles, color="#336699", expected="#336699"),
                  "faults": faults}
print(json.dumps(report))
