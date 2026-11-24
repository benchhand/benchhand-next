# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0", "jsonschema>=4.0", "defusedxml>=0.7.1"]
# ///
"""Probe the FDM overhang verdict on real B-rep for test_overhang_boundary.py and print it as JSON.

  wedges  a 10 x 10 mm foot on the bed under a block whose side undercuts at 45.0, 45.4 and 45.6 degrees from vertical,
          judged by the fdm support obligation on the TEST profile (overhang limit 45 degrees, no supports planned)
  twins   the process.fdm.overhang findings of the five corpus twins that once failed it (outcome and severity)
Usage: uv run --script overhang_boundary_probe.py
stdout: {"wedges": {degrees: verdict}, "twins": {"family/pair": [[severity, outcome], ...]}}
"""

import json
import math
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "mfg_corpus"
sys.path.insert(0, str(CORPUS))
import corpus  # noqa: E402
import support  # noqa: E402

ANGLES = (45.0, 45.4, 45.6)
TWINS = {"additive_support_overhang_bridge": ("bore_roof",), "fdm_horizontal_hole": ("square_roof_bridge",),
         "stability_contact_hull": ("diagonal_pads", "l_footprint", "tiny_contact")}


def wedge(degrees: float):
    """A 10 mm post on the bed, 10 mm tall, with a block on top whose +X side runs out 20 mm up at `degrees` from vertical."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    run = 20 * math.tan(math.radians(degrees))
    profile = BRepBuilderAPI_MakePolygon()
    for x, z in ((0, 0), (10, 0), (10, 10), (10 + run, 30), (0, 30)):
        profile.Add(gp_Pnt(x, 0, z))
    profile.Close()
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(profile.Wire()).Face(), gp_Vec(0, 10, 0)).Shape()


captured = []
judge = support.release_verdict


def spy(record, packet, *prefixes, **kwargs):
    captured.append(packet)
    return judge(record, packet, *prefixes, **kwargs)


support.release_verdict = spy
report = {"wedges": {str(degrees): support.printed_verdict(wedge(degrees), "process.fdm.support@") for degrees in ANGLES},
          "twins": {}}
families = {family.id: family for family in corpus.load_families(corpus.FAMILIES_DIR)}
for family_id, pair_ids in TWINS.items():
    for pair in families[family_id].pairs:
        if pair.id in pair_ids:
            captured.clear()
            pair.run(False)
            report["twins"][f"{family_id}/{pair.id}"] = [[f["severity"], f["outcome"]] for packet in captured
                                                         for f in packet["findings"] if f["code"] == "process.fdm.overhang"]
print(json.dumps(report))
