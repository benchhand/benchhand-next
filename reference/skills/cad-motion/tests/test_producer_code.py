#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A producer's reuse key covers its own script, the modules it loads and the data it reads (#128).

Each motion producer that publishes, or reports what decided a result, takes the sha256 of its code
and of its declared VERDICT_DATA from code_shas.closure. Editing either must change the recipe a
rerun is matched by, so the rerun refuses (another recipe needs --replace) or recomputes instead of
returning the old bundle. The tests copy the skills tree, edit one file of the copy and read every
producer's key from the copy (fixtures/recipe_keys.py). A guard checks that each producer's
VERDICT_DATA covers every data file its code names. Kernel-free.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
SKILLS = HERE.parents[1]
PROBE = HERE / "fixtures" / "recipe_keys.py"
sys.path.insert(0, str(SKILLS.parent / "scripts"))
from modload import load_module as load  # noqa: E402

code_shas = load("cad_motion_code_shas", SCRIPTS / "code_shas.py")
pose = load("cad_motion_pose", SCRIPTS / "pose.py")
sweep = load("cad_motion_sweep", SCRIPTS / "sweep.py")
spot_check = load("cad_motion_spot_check", SCRIPTS / "spot_check.py")
merge_sweeps = load("cad_motion_merge_sweeps", SCRIPTS / "merge_sweeps.py")
play = load("cad_motion_play", SCRIPTS / "play.py")

ISO286 = "cad-fits/data/iso286.json"
ISO286_IT6_EDIT = (b'"6": [6, ', b'"6": [7, ')  # one table value: IT6 up to 3 mm, 6 um -> 7 um
# A valid JSON Schema (2020-12) that a test adds to the folder play declares (cad-record/schemas).
ADDED_SCHEMA = (b'{"$schema": "https://json-schema.org/draft/2020-12/schema", '
                b'"$id": "https://srobroek.com/cad/schemas/zz-added.schema.json", "type": "object"}\n')
PROBE_TIMEOUT_S = 300
ALL = ("play", "sweep", "sweep_equivalence", "merge_sweeps", "spot_check")
# Each edit of the copied tree: (how, path, the producer keys it must change). `append` adds a comment line,
# `space` a newline (for JSON), `iso` changes one ISO 286 value, `add` writes ADDED_SCHEMA, `delete` removes the file.
EDITS = {
    "play.py": ("append", "cad-motion/scripts/play.py", ("play",)),
    "plan.py": ("append", "cad-motion/scripts/plan.py", ("play",)),
    "sweep.py": ("append", "cad-motion/scripts/sweep.py", ALL),
    "fits.py": ("append", "cad-fits/scripts/fits.py", ALL),
    "assembly_data.py": ("append", "cad-record/scripts/assembly_data.py", ALL),
    "merge_sweeps.py": ("append", "cad-motion/scripts/merge_sweeps.py", ("merge_sweeps",)),
    "spot_check.py": ("append", "cad-motion/scripts/spot_check.py", ("spot_check",)),
    "iso286.json value": ("iso", ISO286, ALL),
    "schema edited": ("space", "cad-record/schemas/bom-row.schema.json", ("play",)),
    "schema added": ("add", "cad-record/schemas/zz-added.schema.json", ("play",)),
    "schema deleted": ("delete", "cad-record/schemas/release-manifest.schema.json", ("play",)),
}


def probe(tree: Path) -> dict[str, str]:
    done = subprocess.run([sys.executable, "-B", str(PROBE), str(tree)], capture_output=True, text=True,
                          check=False, timeout=PROBE_TIMEOUT_S)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def apply(path: Path, how: str) -> bytes | None:
    """Make edit `how` to `path` and return the bytes that undo it. An added file returns None."""
    original = path.read_bytes() if path.exists() else None
    if how == "append":
        path.write_bytes(original + b"\n# edited\n")
    elif how == "space":
        path.write_bytes(original + b"\n")
    elif how == "iso":
        assert original is not None and original.count(ISO286_IT6_EDIT[0]) == 1, "the ISO 286 edit no longer matches"
        path.write_bytes(original.replace(*ISO286_IT6_EDIT))
    elif how == "add":
        assert original is None, f"{path} exists already"
        path.write_bytes(ADDED_SCHEMA)
    else:
        assert how == "delete" and original is not None, (how, path)
        path.unlink()
    return original


class EditTests(unittest.TestCase):
    """The keys of the producers in a copy of the skills tree, unedited and after each edit in EDITS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        tree = Path(shutil.copytree(SKILLS, Path(cls.tmp.name) / "skills", ignore=shutil.ignore_patterns("__pycache__")))
        cls.before, cls.again = probe(tree), probe(tree)
        cls.after: dict[str, dict[str, str]] = {}
        for label, (how, relative, _) in EDITS.items():
            path = tree / relative
            original = apply(path, how)
            try:
                cls.after[label] = probe(tree)
            finally:
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def assert_changes(self, producer: str) -> None:
        self.assertEqual(self.again[producer], self.before[producer], "the key is not stable without an edit")
        edits = [label for label, (_, _, producers) in EDITS.items() if producer in producers]
        self.assertIn("iso286.json value", edits)
        for label in edits:
            with self.subTest(edited=label):
                self.assertNotEqual(self.after[label][producer], self.before[producer])

    def test_editing_play_its_modules_or_its_data_changes_its_packet_recipe(self) -> None:
        """Through a real publication: its data folder counts too, so editing, adding or deleting a schema in it
        changes the sealed recipe."""
        self.assert_changes("play")

    def test_editing_sweep_its_modules_or_its_data_changes_its_bundle_recipe(self) -> None:
        self.assert_changes("sweep")

    def test_editing_sweep_its_modules_or_its_data_changes_the_equivalence_a_merge_checks(self) -> None:
        self.assert_changes("sweep_equivalence")

    def test_editing_merge_sweeps_or_its_data_changes_the_merged_bundle_recipe(self) -> None:
        self.assert_changes("merge_sweeps")

    def test_editing_spot_check_or_its_data_changes_what_its_report_says_decided_it(self) -> None:
        self.assert_changes("spot_check")


def covered(path: Path, declared: tuple[Path, ...]) -> bool:
    path = path.resolve()
    return any(path == entry.resolve() or path.is_relative_to(entry.resolve()) for entry in declared)


class DeclaredDataTests(unittest.TestCase):
    def test_each_producer_declares_every_data_file_its_code_names(self) -> None:
        for module, script in ((play, "play.py"), (sweep, "sweep.py"), (merge_sweeps, "merge_sweeps.py"),
                               (spot_check, "spot_check.py")):
            with self.subTest(producer=script):
                missing = sorted(str(path.relative_to(SKILLS)) for path in code_shas.referenced_data(SCRIPTS / script)
                                 if not covered(path, module.VERDICT_DATA))
                self.assertEqual(missing, [], f"add these to {script} VERDICT_DATA")

    def test_a_data_file_a_module_names_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(dir=SKILLS / "cad-motion") as folder:
            data = Path(folder) / "table.json"
            data.write_text("{}", encoding="utf-8")
            script = Path(folder) / "producer.py"
            script.write_text('from pathlib import Path\nTABLE = Path(__file__).resolve().parent / "table.json"\n',
                              encoding="utf-8")
            self.assertEqual(code_shas.referenced_data(script), {data.resolve()})


class ClosureTests(unittest.TestCase):
    def test_a_script_covers_itself_and_the_sibling_files_it_loads(self) -> None:
        table = code_shas.closure(SCRIPTS / "play.py")
        for name in ("cad-motion/scripts/play.py", "cad-motion/scripts/pose.py", "cad-motion/scripts/sweep.py",
                     "cad-fits/scripts/fits.py", "cad-record/scripts/yaml_loader.py"):
            self.assertIn(name, table)

    def test_declared_data_is_hashed_with_the_code(self) -> None:
        table = code_shas.closure(SCRIPTS / "sweep.py", sweep.VERDICT_DATA)
        self.assertIn(ISO286, table)
        self.assertNotIn(ISO286, code_shas.closure(SCRIPTS / "sweep.py"))

    def test_an_import_code_shas_cannot_place_is_an_error(self) -> None:
        for source, message in (("import no_such_module_anywhere\n", "no_such_module_anywhere"),
                                ("from . import pose\n", "relative import")):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as folder:
                script = Path(folder) / "producer.py"
                script.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(code_shas.CodeShaError, message):
                    code_shas.closure(script)

    def test_a_script_imported_from_another_skill_folder_is_followed(self) -> None:
        table = code_shas.closure(SKILLS / "cad-model" / "scripts" / "cadmodel" / "fonts.py")
        self.assertIn("cad-flow/scripts/preflight.py", table)

    def test_a_path_to_a_missing_module_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "producer.py"
            script.write_text('from pathlib import Path\nHERE = Path(__file__).resolve().parent\n'
                              'GONE = HERE / "renamed_away.py"\n', encoding="utf-8")
            with self.assertRaisesRegex(code_shas.CodeShaError, "renamed_away.py"):
                code_shas.closure(script)


if __name__ == "__main__":
    unittest.main()
