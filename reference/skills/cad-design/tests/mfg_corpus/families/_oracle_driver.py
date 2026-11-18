#!/usr/bin/env -S uv run --script

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "jsonschema>=4.23", "pyyaml>=6.0", "trimesh==4.*", "numpy==2.5.5", "python-fcl==0.7.0.11"]
# ///
"""Build one corpus case with cad-model and run `cad_model.py check`'s function on it; print the verdict as JSON.

A case is `{"model": {...}, "fault": {...} | null, "changed_only": bool}`; with `changed_only` the clean default
project is built as v1 first, then `model` as v2, and v2 gets a changed-only check against v1. `model` sets the
parameters of the three fixture parts
(base, plate, insert) and the heat-set declaration; `fault` is the one honest exporter slip the sealed
assembly.glb carries instead of the mesh of the sealed assembly.step (the GLB is the only output that
differs; the STEP, the manifest and the metrics are the kernel's own). Fault kinds:

  stale    the mesh of the same project built with `variant` model overrides (an exporter run on an old model)
  scale    every root node scaled by `factor` (a metre/millimetre slip)
  offset   the `occurrence`'s node moved by `metres` along glTF [x, y, z]
  rotate   the `occurrence`'s node turned by `degrees` about the glTF vertical axis through the scene origin

Verdict: fail when `check` fails, unknown when no check fails and one abstains, else pass. Usage:
  _oracle_driver.py CASE.json WORKDIR
"""

from __future__ import annotations

import copy
import json
import math
import shutil
import struct
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent
SKILLS = CORPUS.parents[2]
sys.path.insert(0, str(SKILLS / "cad-model" / "scripts"))
sys.path.insert(0, str(CORPUS))
from cadmodel import build, check, mesh  # noqa: E402
from corpus import OUTCOMES  # noqa: E402
from support import verdict as shared_verdict  # noqa: E402

FIXTURES = CORPUS / "fixtures" / "oracles"
PARTS = {"TST-0001": ("Base block", "base", "block.py"), "TST-0002": ("Mounting plate", "plate", "plate.py"),
         "TST-0003": ("Heat-set insert", "insert", "insert.py")}
DEFAULT = {"base": {}, "plate": {}, "insert": {}, "hole_d": 7.77}
# Record version 2 documents. The project is a bare synthetic record: every manufacturing-intent field is an explicit
# unknown, because the oracles read the model and its exports, never the manufacturing intent.
UNKNOWN = {"status": "unknown", "reason": "not recorded in the oracle corpus"}
USE_CASE_GROUPS = {"environment": ("temperature", "heat_sources", "moisture", "chemicals", "uv", "corrosion"),
                   "loads": (), "motion": ("speed", "range", "duty_cycle", "friction", "wear", "service_life"),
                   "accuracy": ("tolerance", "repeatability", "surface_finish", "dimensional_stability"),
                   "consequences": ("failure", "severity", "forbidden_outcomes", "standards", "supervision",
                                    "approval_authority"),
                   "logistics": ("quantity", "budget", "lead_time", "maintenance", "repair"),
                   "capability": ("equipment", "operator", "outsourcing"),
                   "release_scope": ("purpose", "operating_limits", "exclusions")}
REQUIREMENTS = {"requirements": [{"id": "REQ-001", "text": "corpus requirement", "rationale": "corpus",
                                  "source": "corpus", "priority": "must",
                                  "verification": {"method": "T", "criteria": "corpus"}}],
                "preferences": [], "assumptions": [], "open_questions": []}
MANUFACTURING = {"capabilities.yaml": {"profiles": []}, "materials.yaml": {"profiles": []},
                 "selection.yaml": {"status": "not_assessed", "candidates": []}}
INTERFACES = """interfaces:
  - id: IF-001
    from: base
    to: insert
    type: mounting
    description: "Heat-set insert pressed into the base bore."
    limits:
      heat_set:
        - {{pair: [TST-0001, TST-0003], hole_d: {hole_d}, hole_tol: [-0.04, 0.04], insert: "M4 x 8", source: "corpus", feature: seat}}
    functional:
      critical: {{status: unknown, reason: not recorded in the oracle corpus}}
      functions: {{status: unknown, reason: not recorded in the oracle corpus}}
"""
ASSEMBLY = """joints:
  - {id: J-001, type: fixed, parent: TST-0001, child: TST-0002, axis: [0, 0, 1], origin: [0, 0, 0], min: 0, max: 0, nominal: 0}
  - {id: J-002, type: fixed, parent: TST-0001, child: TST-0003, axis: [0, 0, 1], origin: [0, 0, 0], min: 0, max: 0, nominal: 0}
operations: {status: unknown, reason: not recorded in the oracle corpus}
"""


def product_record() -> dict[str, Any]:
    use_case: dict[str, Any] = {**UNKNOWN, "service_class": UNKNOWN, "purpose": UNKNOWN, "users": UNKNOWN}
    for group, names in USE_CASE_GROUPS.items():
        use_case[group] = {name: UNKNOWN for name in names} if names else UNKNOWN
    use_case["evidence_policy"] = UNKNOWN
    return {"id": "oracles", "record_version": 2, "use_case": use_case}


def write_project(hw: Path, model: dict[str, Any]) -> None:
    hw.mkdir(parents=True)
    (hw / "product.yaml").write_text(yaml.safe_dump(product_record(), sort_keys=False), encoding="utf-8")
    (hw / "requirements.yaml").write_text(yaml.safe_dump(REQUIREMENTS, sort_keys=False), encoding="utf-8")
    (hw / "assembly.yaml").write_text(ASSEMBLY, encoding="utf-8")
    (hw / "manufacturing").mkdir()
    for name, document in MANUFACTURING.items():
        (hw / "manufacturing" / name).write_text(yaml.safe_dump(document), encoding="utf-8")
    write_models(hw, model)


def write_models(hw: Path, model: dict[str, Any]) -> None:
    """The heat-set declaration and the three part models and records of `model`, over any earlier ones."""
    import re

    (hw / "interfaces.yaml").write_text(INTERFACES.format(hole_d=model["hole_d"]), encoding="utf-8")
    for pn, (title, key, template) in PARTS.items():
        source = (FIXTURES / template).read_text(encoding="utf-8")
        match = re.search(r"^PARAMS = (.*)$", source, flags=re.M)
        assert match
        params = {**eval(match.group(1), {}), **model[key]}  # noqa: S307 - a literal dict of this repo's own fixture
        source = source.replace(match.group(0), f"PARAMS = {params!r}", 1)
        folder = hw / "parts" / pn
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.py").write_text(source, encoding="utf-8")
        part = {"PN": pn, "rev": "X1", "title": title, "material": "PETG", "process": "cnc", "finish": "none",
                "mass_target": 100, "make_buy": "make", "supplier": None,
                "intent": {name: UNKNOWN for name in ("functions", "material_profile", "service", "critical_surfaces",
                                                      "route")}}
        (folder / "part.yaml").write_text(yaml.safe_dump(part, sort_keys=False), encoding="utf-8")


def with_defaults(model: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT)
    for key, value in (model or {}).items():
        merged[key] = {**merged[key], **value} if isinstance(value, dict) else value
    return merged


def read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    binary = data[20 + json_length + 8:] if len(data) > 20 + json_length else b""
    return gltf, binary


def write_glb(path: Path, gltf: dict[str, Any], binary: bytes) -> None:
    text = json.dumps(gltf, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<I4s", len(text), b"JSON") + text
    if binary:
        chunks += struct.pack("<I4s", len(binary), b"BIN\0") + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def matrix(node: dict[str, Any]) -> list[float]:
    """Column-major 4x4 of the local transform of the node."""
    if "matrix" in node:
        return [float(v) for v in node["matrix"]]
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    sx, sy, sz = node.get("scale", [1.0, 1.0, 1.0])
    tx, ty, tz = node.get("translation", [0.0, 0.0, 0.0])
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    cols = [[r[row][0] * sx for row in range(3)], [r[row][1] * sy for row in range(3)],
            [r[row][2] * sz for row in range(3)]]
    return [*cols[0], 0.0, *cols[1], 0.0, *cols[2], 0.0, tx, ty, tz, 1.0]


def multiply(a: list[float], b: list[float]) -> list[float]:
    """a @ b for column-major 4x4 matrices."""
    return [sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4)) for col in range(4) for row in range(4)]


def moved(by: list[float]) -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, *by, 1.0]


def turned(degrees: float) -> list[float]:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c, 0.0, -s, 0.0, 0.0, 1.0, 0.0, 0.0, s, 0.0, c, 0.0, 0.0, 0.0, 0.0, 1.0]


def apply(fault: dict[str, Any], glb: Path, variant_glb: Path | None) -> None:
    kind = fault["kind"]
    if kind == "stale":
        assert variant_glb is not None
        shutil.copyfile(variant_glb, glb)
        return
    gltf, binary = read_glb(glb)
    nodes = gltf["nodes"]
    if kind == "scale":
        factor = fault["factor"]
        for index in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
            nodes[index] = {k: v for k, v in nodes[index].items() if k not in ("translation", "rotation", "scale")}
            nodes[index]["matrix"] = multiply([factor, 0, 0, 0, 0, factor, 0, 0, 0, 0, factor, 0, 0, 0, 0, 1.0],
                                              matrix(nodes[index]))
    else:
        by = moved(fault["metres"]) if kind == "offset" else turned(fault["degrees"])
        named = [n for n in nodes if n.get("name", "").startswith(fault["occurrence"])]
        assert named, f"no node of {fault['occurrence']}"
        for node in named:
            node["matrix"] = multiply(by, matrix(node))
            for key in ("translation", "rotation", "scale"):
                node.pop(key, None)
    write_glb(glb, gltf, binary)


def verdict(result: dict[str, Any]) -> str:
    """The check's rows as one corpus verdict (support.verdict): a warn or skipped row says nothing either way."""
    return shared_verdict(c["status"] if c["status"] in OUTCOMES else "pass" for c in result["checks"].values())


def main(case_path: Path, work: Path) -> int:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    fault = case.get("fault")
    model = with_defaults(case.get("model"))
    variant_glb = None
    if fault and fault["kind"] == "stale":
        variant_hw = work / "variant"
        write_project(variant_hw, with_defaults({**(case.get("model") or {}), **fault["variant"]}))
        build.run(variant_hw, "v1", "auto", [])
        variant_glb = variant_hw / "versions" / "v1" / "assembly.glb"
    hw = work / "hw"
    changed_only = bool(case.get("changed_only"))
    label = "v2" if changed_only else "v1"
    write_project(hw, with_defaults(None) if changed_only else model)
    if changed_only:  # v1 is the clean default project. v2 comes from `model`, and the check compares it with v1
        build.run(hw, "v1", "auto", [])
        write_models(hw, model)
    real = mesh.write_glb

    def faulty(step: Path, glb: Path) -> dict[str, Any]:
        info: dict[str, Any] = real(step, glb)
        if fault:
            apply(fault, glb, variant_glb)
        return info

    with mock.patch.object(mesh, "write_glb", faulty):
        code, built = build.run(hw, label, "auto", [])
    if code != 0:
        print(json.dumps({"error": "build failed", "build": built}), file=sys.stderr)
        return 2
    _code, result = check.check(hw, label, None, [], {}, changed_only=changed_only)
    flagged = sorted(n for n, c in result["checks"].items() if c["status"] in ("fail", "unknown"))
    print(json.dumps({"outcome": verdict(result), "blocking": result["blocking_failures"],
                      "flagged": {n: result["checks"][n]["status"] for n in flagged}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
