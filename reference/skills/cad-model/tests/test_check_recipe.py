#!/usr/bin/env python3
"""The static check's cad.readback bundle is matched by a recipe that covers the check's code and data (#128).

publish_readback reuses a sealed bundle whose recipe equals the new one. The recipe names the check
code (check.py and the modules it loads, manufacture.py among them) and VERDICT_DATA, so after an
edit to either a rerun republishes the packet instead of keeping the bundle the old code sealed.
Each test copies the skills tree, edits one file of the copy and reads readback_recipe and the
reported code fingerprint from the copy (fixtures/check_recipe_key.py). Kernel-free; the publication
itself is covered in test_cad_model.ManufacturingInputCacheTests.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
SKILLS = HERE.parents[1]
PROBE = HERE / "fixtures" / "check_recipe_key.py"
sys.path.insert(0, str(SCRIPTS))
from cadmodel import check  # noqa: E402 - imports without the kernel

_spec = importlib.util.spec_from_file_location("cad_motion_code_shas", SKILLS / "cad-motion" / "scripts" / "code_shas.py")
assert _spec is not None and _spec.loader is not None
code_shas = sys.modules.get(_spec.name)
if code_shas is None:
    code_shas = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = code_shas
    _spec.loader.exec_module(code_shas)

ISO286_IT6_EDIT = (b'"6": [6, ', b'"6": [7, ')  # one table value: IT6 up to 3 mm, 6 um -> 7 um
# A valid JSON Schema (2020-12) that a test adds to the folder the check declares (cad-record/schemas).
ADDED_SCHEMA = (b'{"$schema": "https://json-schema.org/draft/2020-12/schema", '
                b'"$id": "https://srobroek.com/cad/schemas/zz-added.schema.json", "type": "object"}\n')
PROBE_TIMEOUT_S = 300


def copy_skills(root: Path) -> Path:
    """A copy of the skills tree under `root`."""
    return Path(shutil.copytree(SKILLS, root / "skills", ignore=shutil.ignore_patterns("__pycache__")))


@contextlib.contextmanager
def edited(tree: Path, relative: str, change: tuple[bytes, bytes] | None = None) -> Iterator[None]:
    """`relative` in the copy `tree` edited for the duration: one comment line appended, or `change` (old, new)
    applied once."""
    path = tree / relative
    original = path.read_bytes()
    if change is None:
        path.write_bytes(original + b"\n# edited\n")
    else:
        assert original.count(change[0]) == 1, f"{relative} does not hold {change[0]!r} once"
        path.write_bytes(original.replace(*change))
    try:
        yield
    finally:
        path.write_bytes(original)


@contextlib.contextmanager
def schema_changed(tree: Path, how: str) -> Iterator[None]:
    """One file of the declared cad-record/schemas folder in the copy `tree` edited, added or deleted for the duration."""
    folder = tree / "cad-record" / "schemas"
    if how == "added":
        path = folder / "zz-added.schema.json"
        path.write_bytes(ADDED_SCHEMA)
        try:
            yield
        finally:
            path.unlink()
        return
    path = folder / ("bom-row.schema.json" if how == "edited" else "release-manifest.schema.json")
    original = path.read_bytes()
    if how == "edited":
        path.write_bytes(original + b"\n")
    else:
        path.unlink()
    try:
        yield
    finally:
        path.write_bytes(original)


def probe(tree: Path, *args: str) -> dict:
    done = subprocess.run([sys.executable, "-B", str(PROBE), str(tree), *args], capture_output=True, text=True,
                          check=False, timeout=PROBE_TIMEOUT_S)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def covered(path: Path, declared: tuple[Path, ...]) -> bool:
    path = path.resolve()
    return any(path == entry.resolve() or path.is_relative_to(entry.resolve()) for entry in declared)


class ReadbackRecipeTests(unittest.TestCase):
    def test_editing_the_check_code_or_its_data_changes_the_readback_recipe_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = copy_skills(Path(folder))
            before = probe(tree)
            self.assertEqual(probe(tree), before, "the recipe is not stable without an edit")
            for relative, change in (("cad-model/scripts/cadmodel/check.py", None),
                                     ("cad-model/scripts/cadmodel/manufacture.py", None),
                                     ("cad-model/scripts/cadmodel/occ.py", None),
                                     ("cad-fits/data/iso286.json", ISO286_IT6_EDIT)):
                with self.subTest(edited=relative), edited(tree, relative, change):
                    after = probe(tree)
                    self.assertNotEqual(after["readback"], before["readback"])
                    self.assertNotEqual(after["code_sha256"], before["code_sha256"])

    def test_a_schema_edited_added_or_deleted_in_a_declared_folder_changes_the_readback_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = copy_skills(Path(folder))
            before = probe(tree)
            for how in ("edited", "added", "deleted"):
                with self.subTest(schema=how), schema_changed(tree, how):
                    after = probe(tree)
                    self.assertNotEqual(after["readback"], before["readback"])
                    self.assertNotEqual(after["code_sha256"], before["code_sha256"])

    def test_the_declared_data_covers_every_data_file_the_check_code_names(self) -> None:
        missing = sorted(str(path.relative_to(SKILLS)) for path in code_shas.referenced_data(Path(check.__file__))
                         if not covered(path, check.VERDICT_DATA))
        self.assertEqual(missing, [], "add these to check.VERDICT_DATA")


if __name__ == "__main__":
    unittest.main()
