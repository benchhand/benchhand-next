#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A sweep bundle that fails its seal is stale: spot_check and merge_sweeps refuse it with a
`stale: <reason>` message and say to run the sweep again. Kernel-free."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module as load  # noqa: E402

spot_check = load("cad_motion_spot_check", SCRIPTS / "spot_check.py")
merge_sweeps = load("cad_motion_merge_sweeps", SCRIPTS / "merge_sweeps.py")


def seal(folder: Path, files: dict[str, str]) -> None:
    """Write `files` below `folder` and a manifest.json that inventories them."""
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    inventory = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    (folder / "manifest.json").write_text(json.dumps({"files": inventory}), encoding="utf-8")


class StaleSweepBundle(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-motion-stale-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "hw"
        seal(self.hw / "versions" / "v1", {"part.txt": "built\n", "record/product.yaml": "id: TST\n"})
        self.bundle = self.hw / "motion" / "v1" / "whole"
        seal(self.bundle, {"result.json": "{}\n"})
        (self.bundle / "result.json").write_text("edited\n", encoding="utf-8")

    def test_spot_check_refuses_a_stale_bundle_and_says_to_sweep_again(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = spot_check.main(["--hw", str(self.hw), "--version", "v1", "--result", str(self.bundle)])
        self.assertEqual(code, 2)
        self.assertIn("stale: result.json changed after it was sealed; run the sweep again", err.getvalue())

    def test_merge_sweeps_refuses_a_stale_input_and_says_to_sweep_again(self) -> None:
        with self.assertRaisesRegex(merge_sweeps.MergeError,
                                    "stale: result.json changed after it was sealed; run the sweep again"):
            merge_sweeps.read_input(self.bundle)


if __name__ == "__main__":
    unittest.main()
