#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""scripts/agreement_timing.py: the fixed reference pair that the agreement timing runs on is the same on every run.

A change to the generator (seed, grids, radii, noise) moves the digest or the counts here, so a timing taken before
and after it is never compared by mistake. The expected values below were taken from the script's first run.

Run: python3 -m unittest discover -s skills/cad-model/tests -p test_agreement_reference.py -v
Needs `uv`; the script's environment holds only numpy.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "fixtures" / "agreement_timing_probe.py"
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "agreement_timing.py"
DIGEST = "a2575c0fcc3f21af8aa00007c25049d2715da12297c5747ec9cede1ee72b68f3"


class AgreementReferenceTests(unittest.TestCase):
    result: dict

    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), "--runs", "1", "--json"],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr[-2000:]
        cls.result = json.loads(proc.stdout)

    def test_the_reference_has_the_fixed_triangle_counts(self) -> None:
        """A 400 x 200 quad grid is 2 x 80000 triangles, a 512 x 256 grid is 2 x 131072."""
        self.assertEqual(self.result["glb_triangles"], 160000)
        self.assertEqual(self.result["step_triangles"], 262144)

    def test_the_reference_arrays_are_unchanged(self) -> None:
        self.assertEqual(self.result["seed"], 20260429)
        self.assertEqual(self.result["digest"], DIGEST)

    def test_compare_agrees_on_the_reference(self) -> None:
        self.assertEqual(self.result["status"], "pass")


class MeasureTests(unittest.TestCase):
    """`measure` with a fake clock that ticks 0, 1, 1, 3, 3, 6 s: three runs of 1, 2 and 3 s."""

    probe: dict

    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(PROBE)],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr[-2000:]
        cls.probe = json.loads(proc.stdout.splitlines()[-1])

    def test_it_runs_compare_as_often_as_asked(self) -> None:
        self.assertEqual(self.probe["compare_calls"], 3)
        self.assertEqual(self.probe["result"]["runs"], 3)

    def test_it_reports_the_median_and_the_range_of_the_durations(self) -> None:
        result = self.probe["result"]
        self.assertEqual((result["median_s"], result["min_s"], result["max_s"]), (2.0, 1.0, 3.0))


if __name__ == "__main__":
    unittest.main()
