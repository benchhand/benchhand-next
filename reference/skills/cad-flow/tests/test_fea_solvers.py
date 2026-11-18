#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""ccx and Gmsh resolution order (kernel-free) and the in-FreeCAD probe (FreeCAD-gated)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fea_solvers  # noqa: E402
import preflight  # noqa: E402

FREECADCMD = preflight.find_freecadcmd(os.environ)
FREECAD_PRESENT = FREECADCMD is not None and FREECADCMD.is_file() and os.access(FREECADCMD, os.X_OK)


class ResolutionOrder(unittest.TestCase):
    """A wrapper directory holds a FREECADCMD wrapper script and a stray ccx; the bundle holds FreeCAD's
    freecadcmd and its ccx; a symlink elsewhere points at the bundle's freecadcmd."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-fea-solvers-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.wrapper_dir, self.bundle = root / "wrapper", root / "bundle" / "usr" / "bin"
        for path in (self.wrapper_dir / "freecadcmd", self.wrapper_dir / "ccx",
                     self.bundle / "freecadcmd", self.bundle / "ccx", root / "override" / "ccx"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)
        self.link = root / "local" / "freecadcmd"
        self.link.parent.mkdir()
        self.link.symlink_to(self.bundle / "freecadcmd")
        self.root = root

    def test_each_source_is_used_only_when_the_earlier_ones_find_nothing(self) -> None:
        wrapper, bundle_ccx = str(self.wrapper_dir / "freecadcmd"), str(self.bundle / "ccx")
        override = str(self.root / "override" / "ccx")
        empty = str(self.root / "empty")
        cases = [
            # (environ, FreeCAD's lookup, freecadcmd, PATH) -> (path, source)
            ({"CCX": override}, bundle_ccx, wrapper, str(self.wrapper_dir), (override, "$CCX")),
            ({}, bundle_ccx, wrapper, str(self.wrapper_dir), (bundle_ccx, "FreeCAD's lookup")),
            ({}, None, str(self.link), str(self.wrapper_dir), (bundle_ccx, "beside freecadcmd")),
            ({}, None, wrapper, empty, (str(self.wrapper_dir / "ccx"), "beside freecadcmd")),
            ({}, None, str(self.root / "elsewhere" / "freecadcmd"), str(self.wrapper_dir),
             (str(self.wrapper_dir / "ccx"), "PATH")),
        ]
        for environ, lookup, freecadcmd, path, expected in cases:
            with self.subTest(environ=environ, lookup=lookup, freecadcmd=freecadcmd, path=path):
                self.assertEqual(fea_solvers.resolve("calculix", environ=environ, freecad_lookup=lookup,
                                                     freecadcmd=freecadcmd, search_path=path), expected)

    def test_an_unusable_override_is_reported_without_falling_back(self) -> None:
        missing = str(self.root / "missing" / "ccx")
        path, reason = fea_solvers.resolve("calculix", environ={"CCX": missing}, freecad_lookup=str(self.bundle / "ccx"),
                                           freecadcmd=str(self.link), search_path=str(self.wrapper_dir))
        self.assertIsNone(path)
        self.assertEqual(reason, f"$CCX={missing} is not an executable file")

    def test_nothing_found_names_every_place_looked(self) -> None:
        path, reason = fea_solvers.resolve("gmsh", environ={}, freecad_lookup=None, freecadcmd=str(self.link),
                                           search_path=str(self.root / "empty"))
        self.assertIsNone(path)
        for place in ("$GMSH is unset", "FreeCAD's lookup", str(self.bundle / "freecadcmd"), "PATH"):
            self.assertIn(place, reason)


class ProbeFailures(unittest.TestCase):
    def test_a_freecadcmd_that_cannot_start_is_a_probe_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-solvers-") as directory:
            wrapper = Path(directory) / "freecadcmd"
            wrapper.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
            wrapper.chmod(0o755)
            with self.assertRaisesRegex(fea_solvers.ProbeError, "cannot start FreeCAD"):
                fea_solvers.probe(wrapper)

    def test_a_probe_job_that_fails_reports_its_traceback(self) -> None:
        # A stand-in that runs the probe job in a plain Python, where `import FreeCAD` fails.
        with tempfile.TemporaryDirectory(prefix="cad-fea-solvers-") as directory:
            command = Path(directory) / "freecadcmd"
            command.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$1"\n', encoding="utf-8")
            command.chmod(0o755)
            with self.assertRaises(fea_solvers.ProbeError) as raised:
                fea_solvers.probe(command)
        self.assertIn("Traceback (most recent call last)", str(raised.exception))
        self.assertIn("No module named 'FreeCAD'", str(raised.exception))


@unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
class FreeCADProbe(unittest.TestCase):
    def test_probe_reports_the_solvers_and_resources_of_the_running_freecad(self) -> None:
        # The probe resolves only executables that exist in the FreeCAD process; an AppImage's paths are gone
        # once that process exits, so the host checks their form only.
        assert FREECADCMD is not None
        report = fea_solvers.probe(FREECADCMD)
        self.assertEqual(report["freecad"]["version"], "1.1.4")
        self.assertTrue(os.path.isabs(report["resource_dir"]), report)
        templates = report["techdraw_templates"]
        self.assertTrue(templates["dir"].startswith(report["resource_dir"].rstrip("/")), templates)
        self.assertTrue({"ISO/A4_Landscape_ISO5457_minimal.svg", "ASME/ANSIA_Landscape.svg"} <= set(templates["files"]))
        for tool in ("calculix", "gmsh"):
            with self.subTest(tool=tool):
                self.assertNotIn("error", report[tool])
                self.assertTrue(os.path.isabs(report[tool]["path"]), report[tool])
                self.assertRegex(report[tool]["version"], r"^\d+(\.\d+)+$")


if __name__ == "__main__":
    unittest.main()
