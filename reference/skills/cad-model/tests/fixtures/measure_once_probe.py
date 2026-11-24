# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "jsonschema>=4.23", "pyyaml>=6.0", "trimesh==4.*", "numpy==2.5.5", "python-fcl==0.7.0.11"]
# ///
"""Judge the manufacturing outputs of a built version and print which shapes the check measured twice.

Usage: uv run --script measure_once_probe.py HW LABEL
(stdout: {"blocking_failures": [...], "bbox": {"passes": n, "repeated": n}, "volume": {...}})
"""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cadmodel import build, manufacture, occ  # noqa: E402

hw, label = Path(sys.argv[1]).resolve(), sys.argv[2]
seen: dict[str, list] = {"bbox": [], "volume": []}


def counted(name: str):
    real = getattr(occ, name)

    def measure(shape):
        seen[name].append(shape)
        return real(shape)
    return measure


folder = build.version_dir(hw, label)
manifest = build.read_json(folder / "manifest.json")
with mock.patch.object(occ, "bbox", counted("bbox")), mock.patch.object(occ, "volume", counted("volume")):
    section, _ = manufacture.version_check(folder, manifest)
report = {"blocking_failures": section["blocking_failures"]}
for name, shapes in seen.items():
    report[name] = {"passes": len(shapes),
                    "repeated": sum(1 for i, a in enumerate(shapes) if any(a.IsEqual(b) for b in shapes[:i]))}
print(json.dumps(report))
