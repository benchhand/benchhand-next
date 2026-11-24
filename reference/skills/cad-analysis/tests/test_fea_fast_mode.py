#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""FEA fast mode: a fast case reports the peak displacement, the stiffness check and a labelled mesh-stability
indicator (the 95th-percentile von Mises stress over all mesh nodes), and no stress figure, safety factor or
stress verdict. The FreeCAD process is replaced by a stand-in that writes the job's completion marker from the
job's own result fields (fea_modes.reported), so the parent's handling, the engineering packet and the published
bundle are the real ones."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import fea_modes  # noqa: E402
import fea_static  # noqa: E402

_spec = importlib.util.spec_from_file_location("test_fea_conditions", HERE / "test_fea_conditions.py")
assert _spec is not None and _spec.loader is not None
conditions_tests = sys.modules.get(_spec.name)
if conditions_tests is None:
    conditions_tests = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = conditions_tests
    _spec.loader.exec_module(conditions_tests)

PN = conditions_tests.PN
# Nodal von Mises stress of the stand-in solve: 0 to 60 MPa in steps of 6, shuffled. Its p95 value sits at
# rank position (11 - 1) * 0.95 = 9.5, halfway between 54 and 60: 57 MPa. A full solve would give a yield safety
# factor of 250 / 60 = 4.2, above REQ-001's 2.
VON_MISES = [12.0, 30.0, 18.0, 60.0, 24.0, 6.0, 42.0, 48.0, 36.0, 54.0, 0.0]
DISPLACEMENT = [0.0, 0.05, 0.2, 0.12]  # peak 0.2 mm, within REQ-002's 0.5 mm
# Result fields that state a stress figure, a safety factor or a stress verdict.
STRESS_KEYS = {"max_von_mises_mpa", "safety_factor_yield", "required_safety_factor", "sigma_away_mpa"}


def keys(value: Any) -> set[str]:
    """Every mapping key anywhere in `value`."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


def p95_sites(value: Any) -> list[dict[str, Any]]:
    """Every mapping in `value` that holds a key naming a p95 value."""
    if isinstance(value, dict):
        here = [value] if any("p95" in key for key in value) else []
        return here + [site for item in value.values() for site in p95_sites(item)]
    if isinstance(value, list):
        return [site for item in value for site in p95_sites(item)]
    return []


class Percentile95(unittest.TestCase):
    def test_the_95th_percentile_interpolates_between_the_two_nearest_ranks(self) -> None:
        # The value at rank position (n - 1) * 0.95 in ascending order, linear between the two ranks around it.
        cases = {
            "eleven values, position 9.5 between 54 and 60": (VON_MISES, 57.0),
            "four values, position 2.85 between 3 and 4": ([4.0, 1.0, 3.0, 2.0], 3.85),
            "twenty-one values, position 19 on the 20": ([float(v) for v in range(21, 0, -1)], 20.0),
        }
        for name, (values, expected) in cases.items():
            with self.subTest(name):
                self.assertAlmostEqual(fea_modes.percentile_95(values), expected, places=9)


class CaseMode(unittest.TestCase):
    def test_a_mode_other_than_full_or_fast_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "beam.step").write_bytes(b"ISO-10303-21; beam\n")
            for mode in ("quick", "", 1, True):
                with self.subTest(mode=mode):
                    path = root / "case.yaml"
                    path.write_text(f"step: beam.step\nmode: {json.dumps(mode)}\n{EXPLICIT_TAIL}", encoding="utf-8")
                    with self.assertRaisesRegex(fea_static.CaseError, "mode"):
                        fea_static.load_case(path)


EXPLICIT_TAIL = ("material: {E: 69000, nu: 0.33, density: 2700, yield: 276}\n"
                 "fixed_faces: {indices: [1]}\nloads: [{selector: {indices: [2]}, force: [0, 0, -50]}]\nmesh_size: 5\n")


class FastCase(conditions_tests.SourcedFEACase):
    """A versioned fast case with a sourced stiffness criterion, covered loads and an approved convergence study:
    everything a full solve needs to pass the stiffness check."""

    def setUp(self) -> None:
        super().setUp()
        self.jobs: list[dict[str, Any]] = []

    def freecad(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """The FreeCAD job's stand-in: its completion marker, from the job's own result fields."""
        job = job_of(Path(command[1]).read_text(encoding="utf-8"))
        self.jobs.append(job)
        run_dir = Path(job["run_directory"])
        (run_dir / "solver.dat").write_text("solver output\n", encoding="utf-8")
        marker = {"run_id": job["run_id"], "mode": job["mode"],
                  **fea_modes.reported(job["mode"], von_mises=VON_MISES, displacement=DISPLACEMENT,
                                       yield_mpa=job["material"]["yield"],
                                       required_safety_factor=job["required_safety_factor"]),
                  "node_count": len(VON_MISES), "element_count": 4, "solver_versions": job["solver_versions"],
                  "warnings": [], "retained_files": ["solver.dat"]}
        Path(job["output"]).write_text(json.dumps(marker), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def call(self, case_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", return_value=conditions_tests.TOOLS), \
             patch("fea_static.lifecycle.run", side_effect=self.freecad), patch("sys.stdout", output):
            status = fea_static.main([str(case_path), "--hw", str(self.hw), "--version", "v1", *extra])
        return status, json.loads(output.getvalue())

    def fast_case(self) -> Path:
        path = self.case({"conditions": conditions_tests.SERVICE}, mode="fast", acceptance={"stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"})
        self.approve(self.study(path))
        return path

    def fast_results(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The fast case's stdout report and its published results.json."""
        self.build(conditions_tests.documents())
        status, report = self.call(self.fast_case())
        self.assertEqual(status, 0, report)
        return report, dict(json.loads((Path(report["bundle"]) / "results.json").read_text(encoding="utf-8")))

    def test_a_fast_result_passes_the_stiffness_check_and_leaves_strength_unknown(self) -> None:
        report, _ = self.fast_results()
        self.assertEqual(self.outcomes(report), {f"engineering.stiffness@{PN}": "pass",
                                                 f"engineering.strength@{PN}": "unknown"})
        self.assertEqual(report["engineering"]["result"], "unknown")

    def test_a_fast_strength_reason_names_the_stress_study_and_not_acceptance_strength(self) -> None:
        # A fast case refuses acceptance.strength, so a reason that asks for it sends the reader into a refusal (#218).
        report, _ = self.fast_results()
        row = next(row for row in report["engineering"]["outcomes"] if row["obligation"] == f"engineering.strength@{PN}")
        self.assertIn("mode: stress", row["uncertainty"])
        self.assertIn("stress study", row["uncertainty"])
        self.assertNotIn("acceptance.strength", row["uncertainty"])

    def test_a_fast_run_reports_the_peak_displacement_and_no_stress_figure_or_stress_verdict(self) -> None:
        for name, result in zip(("stdout", "published results.json"), self.fast_results()):
            with self.subTest(name):
                self.assertEqual(result["max_displacement_mm"], 0.2)
                self.assertEqual(keys(result) & STRESS_KEYS, set())

    def test_a_fast_run_states_that_its_status_is_the_runs_and_not_a_strength_verdict(self) -> None:
        for name, result in zip(("stdout", "published results.json"), self.fast_results()):
            with self.subTest(name):
                self.assertEqual((result["status"], result["status_scope"]), ("pass", "run"))

    def test_every_p95_the_run_reports_carries_the_mesh_stability_label(self) -> None:
        for name, result in zip(("stdout", "published results.json"), self.fast_results()):
            with self.subTest(name):
                sites = p95_sites(result)
                self.assertTrue(sites, "a fast result reports the p95 von Mises stress")
                for site in sites:
                    self.assertIn("mesh-stability indicator", site.get("label", ""), site)
                    self.assertIn("not a strength value", site.get("label", ""), site)

    def test_a_fast_run_points_to_the_separate_stress_study_for_any_stress_figure(self) -> None:
        for name, result in zip(("stdout", "published results.json"), self.fast_results()):
            with self.subTest(name):
                self.assertIn("separate stress study", result.get("stress_study", ""), result)

    def test_a_fast_bundle_is_keyed_by_its_mode_and_the_full_mode_mesh(self) -> None:
        report, _ = self.fast_results()
        options = json.loads((Path(report["bundle"]) / "manifest.json").read_text(encoding="utf-8"))["recipe"]["options"]
        self.assertEqual(options["mode"], "fast")
        self.assertEqual(options["mesh_settings"]["high_order_optimize"], fea_static.HIGH_ORDER["optimize"])
        self.assertNotIn("second_order_linear", options["mesh_settings"])

    def test_a_fast_case_that_asks_for_a_strength_verdict_is_refused_before_the_solve(self) -> None:
        self.build(conditions_tests.documents())
        for name, extra in (("required_safety_factor", {"required_safety_factor": 2}),
                            ("acceptance.strength", {"acceptance": {"strength": "REQ-001", "stiffness": "REQ-002"}})):
            with self.subTest(name):
                self.jobs.clear()
                status, report = self.call(self.case({"conditions": conditions_tests.DRY_23C}, mode="fast", **extra))
                self.assertEqual(status, 2, report)
                self.assertEqual(report["error"]["code"], "invalid_case")
                self.assertIn(name, report["error"]["message"])
                self.assertEqual(self.jobs, [], "a refused case must never reach the solver")


def job_of(script: str) -> dict[str, Any]:
    """The job data a generated fea_job.py carries."""
    import ast
    import re

    match = re.search(r"^JOB=json[.]loads\((.*)\)$", script, flags=re.M)
    assert match is not None
    return dict(json.loads(ast.literal_eval(match.group(1))))


if __name__ == "__main__":
    unittest.main()
