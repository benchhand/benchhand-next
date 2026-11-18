#!/usr/bin/env python3
"""Print the reuse keys of the cad-motion producers in a skills tree, as JSON.

Usage: python recipe_keys.py SKILLS_TREE

Loads play.py, sweep.py, merge_sweeps.py and spot_check.py from SKILLS_TREE/cad-motion/scripts, so a test
can copy the skills tree, edit one file of the copy and compare the keys.

- play: a real publication. `play.main` checks a sealed version of a record version 2 project that has no
  motion.play obligation (cad-record's TST record with its rotating functions made `other`), so no kernel
  runs. The key is the recipe_sha256 of the published bundle's manifest.
- sweep, its equivalence and merge_sweeps: layout's recipe_sha256 of recipe_of, equivalence_of and
  merged_recipe for a stand-in version.
- spot_check: of the provenance its report prints.
Kernel-free.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock


def load(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def no_play_record(fx: Any) -> dict[str, Any]:
    """cad-record's TST record without a motion.play obligation: no interface or part function rotates or slides."""
    docs = fx.tst_record()
    for item in docs["interfaces.yaml"]["interfaces"]:
        item["functional"].pop("play", None)
        for entry in item["functional"].get("functions") or []:
            if isinstance(entry, dict) and entry.get("function") in ("rotating", "sliding"):
                entry["function"] = "other"
    for name, document in docs.items():
        if name.startswith("parts/"):
            for entry in (document.get("intent") or {}).get("functions") or []:
                if isinstance(entry, dict) and entry.get("function") in ("rotating", "sliding"):
                    entry["function"] = "other"
    return docs


def sealed_version(hw: Path) -> None:
    """versions/v1 of `hw`: its record snapshot and a manifest that inventories every file, as cad-model seals one."""
    version = hw / "versions" / "v1"
    for path in sorted(hw.rglob("*")):
        relative = path.relative_to(hw)
        if path.is_file() and relative.parts[0] != "versions":
            (version / "record" / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, version / "record" / relative)
    files = {path.relative_to(version).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(version.rglob("*")) if path.is_file()}
    (version / "manifest.json").write_text(json.dumps({"label": "v1", "files": files}), encoding="utf-8")


def play_key(tree: Path, play: Any) -> str:
    fx = load("cad_record_mi_fixtures", tree / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
    with tempfile.TemporaryDirectory() as folder:
        hw = fx.write_record(Path(folder) / "hw", no_play_record(fx))
        sealed_version(hw)
        with contextlib.redirect_stdout(io.StringIO()):
            code = play.main(["--hw", str(hw), "--version", "v1"])
        assert code == 0, f"play exited {code}"
        manifest = json.loads((hw / "checks" / "v1" / play.SUBJECT / "manifest.json").read_text(encoding="utf-8"))
        return str(manifest["recipe_sha256"])


def main(tree: Path) -> dict[str, str]:
    scripts = tree / "cad-motion" / "scripts"
    pose = load("cad_motion_pose", scripts / "pose.py")
    sweep = load("cad_motion_sweep", scripts / "sweep.py")
    play = load("cad_motion_play", scripts / "play.py")
    merge_sweeps = load("cad_motion_merge_sweeps", scripts / "merge_sweeps.py")
    spot_check = load("cad_motion_spot_check", scripts / "spot_check.py")
    key = pose.LAYOUT.recipe_sha256
    with tempfile.TemporaryDirectory() as hw, mock.patch.object(pose, "input_sha256", return_value="0" * 64):
        args = sweep.build_parser().parse_args(["--hw", hw, "--version", "v1"])
        recipe = sweep.recipe_of(SimpleNamespace(args=args, change=None, version_dir=Path(hw)),
                                 SimpleNamespace(digest=b"rule"))
    inputs = [SimpleNamespace(manifest_sha256="1" * 64), SimpleNamespace(manifest_sha256="2" * 64)]
    return {"play": play_key(tree, play), "sweep": key(recipe), "sweep_equivalence": key(sweep.equivalence_of(recipe)),
            "merge_sweeps": key(merge_sweeps.merged_recipe({"equivalence": sweep.equivalence_of(recipe)}, "sweep", inputs)),
            "spot_check": key(spot_check.audit_provenance({"rule_sha256": "0" * 64}, SimpleNamespace(digest=b"audit")))}


if __name__ == "__main__":
    json.dump(main(Path(sys.argv[1]).resolve()), sys.stdout)
