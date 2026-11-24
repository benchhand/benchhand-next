# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""STEP output carries AP242 geometric validation properties: volume, area and centroid per product."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "fixtures" / "step_header_probe.py"

VALIDATION = re.compile(r"PROPERTY_DEFINITION\('geometric validation property',\s*'([a-z ]+)'")
KINDS = ["centroid", "surface area", "volume"]
CENTRE = re.compile(r"'centre point',\s*\(([^)]*)\)")
VOLUME = re.compile(r"VOLUME_MEASURE\(\s*([-0-9.E+]+)\)")
AREA = re.compile(r"AREA_MEASURE\(\s*([-0-9.E+]+)\)")
REL = 1e-9  # the adaptive integration is within 1e-10 of the exact value, the fixed-order rule is not
# a torus of major radius 20 and minor radius 5 has volume 2 pi^2 * 20 * 5^2, so the half has pi^2 * 500
HALF_TORUS_VOLUME = 500 * math.pi**2


@unittest.skipUnless(shutil.which("uv"), "uv is required to write STEP through OCP")
class StepValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_probe(self, name: str, *mode: str) -> tuple[Path, str]:
        out = self.root / name
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(PROBE), str(out), *mode],
                              capture_output=True, text=True, check=False, timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return out, proc.stdout

    def write(self, name: str, *mode: str) -> str:
        return self.run_probe(name, *mode)[0].read_text(encoding="utf-8")

    def values(self, text: str) -> tuple[float, float, list[float]]:
        volume, area, centre = VOLUME.search(text), AREA.search(text), CENTRE.search(text)
        assert volume is not None and area is not None and centre is not None
        return float(volume.group(1)), float(area.group(1)), [float(v) for v in centre.group(1).split(",")]

    def assertValues(self, text: str, volume: float, area: float | None, centre: list[float] | None) -> None:
        got_volume, got_area, got_centre = self.values(text)
        self.assertAlmostEqual(got_volume / volume, 1.0, delta=REL)
        if area is not None:
            self.assertAlmostEqual(got_area / area, 1.0, delta=REL)
        for got, want in zip(got_centre, centre or got_centre, strict=True):
            self.assertAlmostEqual(got, want, delta=1e-6)

    def test_part_step_has_validation_entities_with_the_box_values(self) -> None:
        text = self.write("part.step")
        self.assertEqual(sorted(VALIDATION.findall(text)), KINDS)
        # the 10 x 20 x 30 box: 10 * 20 * 30 mm3, 2 * (10 * 20 + 10 * 30 + 20 * 30) mm2, center at its middle
        self.assertValues(text, 6000.0, 2200.0, [5.0, 10.0, 15.0])

    def test_located_part_is_validated_too(self) -> None:
        # a shape that carries a placement becomes an instance of its definition
        text = self.write("located.step", "located")
        self.assertEqual(sorted(VALIDATION.findall(text)), KINDS)
        # the properties describe the geometry as written: the box moved 50 along x
        self.assertValues(text, 6000.0, 2200.0, [55.0, 10.0, 15.0])

    def test_component_placement_does_not_move_the_definition_properties(self) -> None:
        # a definition built 50 along x, under a component placed 100 along y: the definition keeps (55, 10, 15) and the
        # component placement is separate, so the placed center is (55, 110, 15)
        text = self.write("placed.step", "placed")
        self.assertEqual(sorted(VALIDATION.findall(text)), KINDS)
        self.assertValues(text, 6000.0, 2200.0, [55.0, 10.0, 15.0])
        self.assertEqual(len(re.findall(r"CARTESIAN_POINT\('',\(0\.,100\.,0\.\)\)", text)), 2)

    def test_curved_part_has_the_exact_volume_area_and_centroid(self) -> None:
        # half a torus cut through its axis. Volume pi^2 * 500. Area half the torus, 2 pi^2 * 20 * 5, plus two
        # discs of radius 5. Centroid 2 * (20^2 + 5^2 / 4) / (pi * 20) from the axis, along the normal (1, 2, 0).
        text = self.write("halftorus.step", "halftorus")
        reach = 2 * (400 + 25 / 4) / (math.pi * 20)
        unit = math.sqrt(5)
        self.assertValues(text, HALF_TORUS_VOLUME, 2 * math.pi**2 * 100 + 50 * math.pi,
                          [reach / unit, 2 * reach / unit, 0.0])

    def test_tilted_cut_keeps_the_adaptive_volume(self) -> None:
        # the same half torus cut by a tilted plane through its center is still exactly half. The fixed-order
        # Gauss rule is 7e-8 off on it, the adaptive one 6e-11.
        self.assertValues(self.write("tilted.step", "tilted"), HALF_TORUS_VOLUME, None, None)

    def test_assembly_step_validates_the_one_definition_and_keeps_its_structure(self) -> None:
        text = self.write("assembly.step", "assembly")
        self.assertEqual(sorted(VALIDATION.findall(text)), KINDS)
        self.assertEqual(len(re.findall(r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(", text)), 2)

    def test_assembly_writer_refuses_a_located_definition(self) -> None:
        # a located definition would export without validation properties, so the writer names the PN instead
        out, stdout = self.run_probe("located-assembly.step", "located-assembly")
        self.assertIn("MotionError: ", stdout)
        self.assertIn("TST-0001", stdout)
        self.assertIn("unlocated", stdout)
        self.assertIn("component", stdout)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
