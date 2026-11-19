#!/usr/bin/env python3
"""The static check's readback recipe key and code fingerprint in a skills tree, or one readback publication.

Usage: python check_recipe_key.py SKILLS_TREE
       python check_recipe_key.py SKILLS_TREE publish HW LABEL RESULT_JSON

Loads cadmodel from SKILLS_TREE/cad-model/scripts, so a test can copy the skills tree, edit one file of the
copy and compare. The first form prints {"readback": layout's recipe_sha256 of readback_recipe for a fixed
packet, "code_sha256": the digest the check reports in evaluation.code_sha256}. The second runs
publish_readback for built version LABEL of HW with the checks and occurrences of the check result in RESULT_JSON
and prints {"reused": ..., "recipe_sha256": the sealed bundle's recipe}. Kernel-free.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> dict[str, object]:
    tree = Path(argv[0]).resolve()
    sys.path.insert(0, str(tree / "cad-model" / "scripts"))
    spec = importlib.util.spec_from_file_location("cad_motion_code_shas", tree / "cad-motion" / "scripts" / "code_shas.py")
    assert spec is not None and spec.loader is not None
    code_shas = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = code_shas   # the module check.py loads under this name
    spec.loader.exec_module(code_shas)
    from cadmodel import check, record

    layout = record.load_layout()
    if argv[1:2] == ["publish"]:
        hw, label, result = Path(argv[2]), argv[3], json.loads(Path(argv[4]).read_text(encoding="utf-8"))
        folder = hw / "versions" / label
        published = check.publish_readback(hw, label, folder, folder / "record", result["checks"], result["occurrences"])
        assert published is not None, "a record version 2 version publishes a readback packet"
        manifest = json.loads((hw / "checks" / label / "cad" / "manifest.json").read_text(encoding="utf-8"))
        return {"reused": published["reused"], "recipe_sha256": manifest["recipe_sha256"]}
    packet = {"producer": check.READBACK_PRODUCER, "complete": True, "outcomes": []}
    return {"readback": layout.recipe_sha256(check.readback_recipe(layout, packet)),
            "code_sha256": code_shas.digest(Path(check.__file__), check.VERDICT_DATA)}


if __name__ == "__main__":
    json.dump(main(sys.argv[1:]), sys.stdout)
