#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""FEA stress mode: two curved meshes at h and 0.75 h, read back from the ccx results, compared by
fea_stress.compare_levels. The study reports settled (strength-eligible), settled_away_from_support
(information only) or UNKNOWN with a named reason, and never a stress number it cannot stand behind.

The FreeCAD process is replaced by a stand-in that writes, for each of the two solves, the run's completion
marker (from the job's own result fields), a ccx `.frd` result and the boundary sections of the ccx input. The
`.frd` files are the gzipped campaign fixtures of test_fea_stress, so the parent's handling, the comparison, the
engineering packet and the published bundle are the real ones. A fixture's own mesh size differs a little from
the 0.75 h of its solve: the comparison reads the sizes from the case, and the stress from the files."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent / "scripts"))

import fea_modes  # noqa: E402
import fea_static  # noqa: E402
import fea_stress  # noqa: E402
import fea_stress_study as study  # noqa: E402


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = sys.modules.get(name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


conditions_tests = _sibling("test_fea_conditions")
stress_tests = _sibling("test_fea_stress")
fast_tests = _sibling("test_fea_fast_mode")
PN = conditions_tests.PN

# Fixed and load plane of each fixture pair; the ccx input of a solve is written from the same node sets.
CANTILEVER_PLANES = (0.0, 100.0)
TRUSS_PLANES = (0.0, 320.0)


def frd_text(name: str) -> str:
    with gzip.open(FIXTURES / f"{name}.frd.gz", "rt") as handle:
        return handle.read()


def inp_text(fixed: list[int] | frozenset[int], load: list[int] | frozenset[int]) -> str:
    """The boundary sections of a FreeCAD-written ccx input, in its form."""
    return ("*NSET,NSET=FixedFaces\n" + "".join(f"{node},\n" for node in sorted(fixed))
            + "** FaceForce0\n*CLOAD\n** node loads on shape: SelectedPart:Face2\n"
            + "".join(f"{node},3,-1.0\n" for node in sorted(load)))


def plane_inp(frd: str, planes: tuple[float, float]) -> str:
    result = fea_stress.read_frd(frd)
    return inp_text(fea_stress.plane_node_ids(result, "x", planes[0]), fea_stress.plane_node_ids(result, "x", planes[1]))


def cantilever_plan() -> list[dict[str, Any]]:
    coarse, fine = frd_text("cantilever_r1_4.5mm"), frd_text("cantilever_r1_3mm")
    return [{"frd": coarse, "inp": (FIXTURES / "cantilever_r1_4.5mm.faces.inp").read_text(), "displacement": [0.0, 0.19]},
            {"frd": fine, "inp": (FIXTURES / "cantilever_r1_3mm.faces.inp").read_text(), "displacement": [0.0, 0.2]}]


def truss_plan() -> list[dict[str, Any]]:
    coarse, fine = frd_text("truss_r1_6mm"), frd_text("truss_r2_4.5mm")
    return [{"frd": coarse, "inp": plane_inp(coarse, TRUSS_PLANES), "displacement": [0.0, 0.4]},
            {"frd": fine, "inp": plane_inp(fine, TRUSS_PLANES), "displacement": [0.0, 0.41]}]


def interior_plan(coarse_peak: float = 99.0, fine_peak: float = 100.0) -> list[dict[str, Any]]:
    """Synthetic meshes whose peak sits at x=50, far from both faces: a strength-eligible settled study."""
    plan = []
    for lvl, peak in ((stress_tests.level(1.0, kept=200, peak=coarse_peak), 0.19),
                      (stress_tests.level(0.75, kept=2000, peak=fine_peak), 0.2)):
        plan.append({"frd": stress_tests.level_as_frd(lvl), "inp": inp_text([1], [2]), "displacement": [0.0, peak]})
    return plan


class StressCase(conditions_tests.SourcedFEACase):
    """A versioned stress case with a sourced stiffness criterion and an approved convergence study."""

    def setUp(self) -> None:
        super().setUp()
        self.jobs: list[dict[str, Any]] = []
        self.plan: list[dict[str, Any]] = []

    def freecad(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """The FreeCAD job's stand-in for the n-th solve of the case, from `self.plan[n]`."""
        job = fast_tests.job_of(Path(command[1]).read_text(encoding="utf-8"))
        position = len(self.jobs)
        self.jobs.append(job)
        plan = self.plan[position]
        run_dir = Path(job["run_directory"])
        if "error" in plan:
            marker: dict[str, Any] = {"status": "error", "run_id": job["run_id"], "error": plan["error"], "warnings": []}
            Path(job["output"]).write_text(json.dumps(marker), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        written = ["solver.dat", "GmshGeometry.brep", "GmshInput.geo"]
        for name in written:
            (run_dir / name).write_text(f"{name} of solve {position}\n", encoding="utf-8")
        for key, name in (("frd", "GmshMesh.frd"), ("inp", "GmshMesh.inp")):
            if plan.get(key) is not None:
                content = plan[key]
                (run_dir / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                written.append(name)
        marker = {"run_id": job["run_id"], "mode": job["mode"],
                  **fea_modes.reported(job["mode"], von_mises=[0.0, 1.0], displacement=plan["displacement"],
                                       yield_mpa=job["material"]["yield"], required_safety_factor=None),
                  "node_count": 1349 + position, "element_count": 600 + position, "solver_versions": job["solver_versions"],
                  "warnings": [], "retained_files": written,
                  "mesh_input_hashes": {"geometry_sha256": "a" * 64, "geo_sha256": "b" * 64},
                  "mesh_input_files": ["GmshGeometry.brep", "GmshInput.geo"],
                  "mesh_quality": plan.get("mesh_quality", {"elements": 600, "invalid_elements": 0,
                                                            "min_scaled_jacobian": 0.4, "high_order_optimize": 2})}
        Path(job["output"]).write_text(json.dumps(marker), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def call(self, case_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", return_value=conditions_tests.TOOLS), \
             patch("fea_static.lifecycle.run", side_effect=self.freecad), patch("sys.stdout", output):
            status = fea_static.main([str(case_path), "--hw", str(self.hw), "--version", "v1", *extra])
        return status, json.loads(output.getvalue())

    def stress_case(self, mesh_size: float, **extra: Any) -> Path:
        path = self.case({"conditions": conditions_tests.SERVICE}, mode="stress", mesh_size=mesh_size,
                         acceptance={"stiffness": "REQ-002"}, mesh_convergence={"decision": "DR-002"}, **extra)
        self.approve(self.study(path))
        return path

    def run_stress(self, plan: list[dict[str, Any]], mesh_size: float = 4.5, *,
                   replace: bool = False) -> tuple[int, dict[str, Any]]:
        self.plan = plan
        self.build(conditions_tests.documents())
        return self.call(self.stress_case(mesh_size), *(["--replace"] if replace else []))

    def published(self, report: dict[str, Any]) -> dict[str, Any]:
        return dict(json.loads((Path(report["bundle"]) / "results.json").read_text(encoding="utf-8")))


class Outcomes(StressCase):
    def test_a_peak_on_the_exclusion_boundary_settles_away_from_support_and_is_not_a_strength_value(self) -> None:
        # Cantilever 4.5 mm to 3 mm: the kept peaks are 102.7 and 103.9 MPa, 1.14% apart, on the 13.5 mm cutoff.
        status, report = self.run_stress(cantilever_plan())
        self.assertEqual(status, 0, report)
        for name, result in (("stdout", report), ("published results.json", self.published(report))):
            with self.subTest(name):
                found = result["stress_study"]
                self.assertEqual(found["outcome"], "settled_away_from_support")
                self.assertFalse(found["strength_eligible"])
                self.assertIsNone(found["sigma_mpa"])
                self.assertAlmostEqual(found["sigma_info_mpa"], 103.9, places=1)
                self.assertAlmostEqual(found["delta_sigma"], 0.0114, places=4)
                self.assertEqual(found["reasons"], ["exclusion_boundary"])
                self.assertIn("support stress is higher; see #209", found["message"])
                self.assertEqual(result["mode"], "stress")

    def test_a_pair_that_misses_the_criterion_is_unknown_and_reports_no_stress_number(self) -> None:
        # Truss member 6 mm to 4.5 mm: the kept peaks differ by 13.93%.
        status, report = self.run_stress(truss_plan(), mesh_size=6)
        self.assertEqual(status, 0, report)
        found = report["stress_study"]
        self.assertEqual((found["outcome"], found["reasons"]), ("unknown", ["stress_not_settled"]))
        self.assertFalse(found["strength_eligible"])
        self.assertIsNone(found["sigma_mpa"])
        self.assertIsNone(found["sigma_info_mpa"])
        self.assertAlmostEqual(found["delta_sigma"], 0.1393, places=4)
        for expected in ("h_coarse=6 mm h_fine=4.5 mm", "coarse=82.54 MPa", "fine=95.89 MPa", "change=13.93%"):
            self.assertIn(expected, found["message"])

    def test_an_interior_peak_that_converges_settles_and_is_strength_eligible(self) -> None:
        status, report = self.run_stress(interior_plan(), mesh_size=1.0)
        self.assertEqual(status, 0, report)
        found = report["stress_study"]
        self.assertEqual((found["outcome"], found["reasons"]), ("settled", []))
        self.assertTrue(found["strength_eligible"])
        self.assertEqual(found["sigma_mpa"], 100.0)
        self.assertIsNone(found["sigma_info_mpa"])

    def test_the_result_carries_the_run_status_scope_and_the_fine_mesh_displacement(self) -> None:
        _, report = self.run_stress(cantilever_plan())
        for name, result in (("stdout", report), ("published results.json", self.published(report))):
            with self.subTest(name):
                self.assertEqual((result["status"], result["status_scope"]), ("pass", "run"))
                self.assertEqual(result["max_displacement_mm"], 0.2)  # the fine solve's, not the coarse 0.19
                self.assertEqual(result["run_id"], self.jobs[1]["run_id"])  # the run that completed the study

    def test_an_unknown_study_still_passes_the_run_and_the_stiffness_check(self) -> None:
        # mesh_size 2 is the size the approved convergence study (DR-002) is bound to.
        status, report = self.run_stress(truss_plan(), mesh_size=2)
        self.assertEqual(status, 0, report)
        self.assertEqual((report["status"], report["status_scope"]), ("pass", "run"))
        self.assertEqual(self.outcomes(report)[f"engineering.stiffness@{PN}"], "pass")

    def test_no_study_outcome_gives_strength_a_verdict_before_the_conditions_module_reads_the_study(self) -> None:
        # fea_conditions reads safety_factor_yield; a stress result reports none, so strength stays unknown even
        # for a strength-eligible settled study. Mapping the study onto the obligation is the next change.
        for name, plan, size in (("settled", interior_plan(), 1.0), ("away", cantilever_plan(), 4.5),
                                 ("unknown", truss_plan(), 6)):
            with self.subTest(name):
                self.jobs.clear()
                status, report = self.run_stress(plan, size, replace=True)
                self.assertEqual(status, 0, report)
                self.assertEqual(self.outcomes(report)[f"engineering.strength@{PN}"], "unknown")
                self.assertEqual(stress_tests_keys(report) & {"max_von_mises_mpa", "safety_factor_yield"}, set())


def stress_tests_keys(value: Any) -> set[str]:
    return fast_tests.keys(value)


class StrengthAcceptance(StressCase):
    """A stress case that names a sourced acceptance.strength (REQ-001, yield safety factor at least 2): the
    criterion exists, the study yields a figure or none, and the strength obligation stays unknown because the
    result carries no yield safety factor. Nothing in the published result states one either."""

    STRESS_RESULT_KEYS = {"safety_factor_yield", "max_von_mises_mpa", "required_safety_factor", "sigma_away_mpa"}

    def strength_case(self, mesh_size: float) -> Path:
        path = self.case({"conditions": conditions_tests.SERVICE}, mode="stress", mesh_size=mesh_size,
                         acceptance={"strength": "REQ-001", "stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"})
        self.approve(self.study(path))
        return path

    def test_strength_stays_unknown_for_every_outcome_and_no_yield_safety_factor_is_published(self) -> None:
        for outcome, plan, size in (("settled", interior_plan(), 1.0),
                                    ("settled_away_from_support", cantilever_plan(), 4.5),
                                    ("unknown", truss_plan(), 6.0)):
            with self.subTest(outcome):
                self.jobs.clear()
                self.plan = plan
                self.build(conditions_tests.documents())
                status, report = self.call(self.strength_case(size), "--replace")
                self.assertEqual(status, 0, report)
                published = self.published(report)
                self.assertEqual(report["stress_study"]["outcome"], outcome)
                self.assertEqual(published["stress_study"]["outcome"], outcome)
                self.assertEqual(self.outcomes(report)[f"engineering.strength@{PN}"], "unknown")
                self.assertEqual(report["engineering"]["result"], "unknown")
                for name, result in (("stdout", report), ("published results.json", published)):
                    self.assertEqual(fast_tests.keys(result) & self.STRESS_RESULT_KEYS, set(), name)

    def test_the_strength_finding_names_the_sourced_criterion_and_states_no_measured_value(self) -> None:
        self.plan = interior_plan()
        self.build(conditions_tests.documents())
        status, report = self.call(self.strength_case(1.0))
        self.assertEqual(status, 0, report)
        finding = next(row for row in report["engineering"]["findings"] if row["code"] == "fea.strength.unverified")
        self.assertEqual(finding["measured"]["status"], "unknown")
        criterion = finding["criterion"]
        self.assertEqual((criterion["property"], criterion["operator"], criterion["value"]),
                         ("yield_safety_factor", ">=", 2.0))  # REQ-001's sourced criterion

    def test_the_sealed_check_packet_carries_the_same_unknown_strength_and_evidence_reads_it(self) -> None:
        self.plan = interior_plan()
        self.build(conditions_tests.documents())
        status, report = self.call(self.strength_case(1.0))
        self.assertEqual((status, report["check_bundle"]), (0, "hw/checks/v1/fea-bracket"), report)
        bundle = self.hw / "checks" / "v1" / "fea-bracket"
        packet = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(packet, report["engineering"])
        self.assertEqual({row["obligation"]: row["outcome"] for row in packet["outcomes"]}[f"engineering.strength@{PN}"],
                         "unknown")
        manifest_sha = hashlib.sha256((self.hw / "versions" / "v1" / "manifest.json").read_bytes()).hexdigest()
        packets, findings = conditions_tests.evidence_module().collect_packets(self.hw, "v1", manifest_sha)
        self.assertEqual((findings, [p.bundle for p in packets]), ([], ["hw/checks/v1/fea-bracket"]))


class Solves(StressCase):
    def test_the_study_solves_two_curved_meshes_at_h_and_three_quarters_of_h(self) -> None:
        self.run_stress(cantilever_plan(), mesh_size=4.5)
        self.assertEqual([job["mesh_size"] for job in self.jobs], [4.5, 3.375])
        self.assertEqual([job["mode"] for job in self.jobs], ["stress", "stress"])
        self.assertEqual(fea_modes.STRESS_STEP_RATIO, 0.75)

    def test_the_two_solves_use_distinct_run_directories_and_both_are_kept_as_evidence(self) -> None:
        _, report = self.run_stress(cantilever_plan())
        published = self.published(report)
        self.assertEqual(len({job["run_directory"] for job in self.jobs}), 2)
        bundle = Path(report["bundle"])
        frds = [name for name in published["retained_files"] if name.endswith("GmshMesh.frd")]
        self.assertEqual(len(frds), 2, published["retained_files"])
        self.assertEqual(len(published["mesh_input_files"]), 4)  # the BRep and the Gmsh input of each solve
        for name in published["retained_files"] + published["mesh_input_files"]:
            self.assertTrue((bundle / name).is_file(), name)
        self.assertEqual(set(published["stress_study"]["runs"]), {"coarse", "fine"})

    def test_a_failed_second_solve_is_an_error_result_that_names_the_fine_solve(self) -> None:
        failure = {"code": "mesh_invalid", "message": "Gmsh produced 3 elements with a nonpositive Jacobian"}
        plan = cantilever_plan()
        plan[1] = {"error": failure}
        status, report = self.run_stress(plan)
        self.assertEqual(status, 2, report)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["error"]["code"], "mesh_invalid")
        self.assertIn("fine solve", report["error"]["message"])
        self.assertIn("mesh_size 3.375 mm", report["error"]["message"])
        self.assertEqual(report["error"]["details"]["stress_study_solve"], "fine")
        self.assertNotIn("stress_study", report)
        self.assertEqual(len(self.jobs), 2)

    def test_a_failed_first_solve_stops_the_study_before_the_second_solve(self) -> None:
        self.plan = [{"error": {"code": "solver_failed", "message": "ccx stopped"}}]
        self.build(conditions_tests.documents())
        status, report = self.call(self.stress_case(4.5))
        self.assertEqual(status, 2, report)
        self.assertEqual(report["error"]["details"]["stress_study_solve"], "coarse")
        self.assertIn("coarse solve", report["error"]["message"])
        self.assertEqual(len(self.jobs), 1)

    def test_a_failed_study_publishes_no_bundle(self) -> None:
        plan = cantilever_plan()
        plan[1] = {"error": {"code": "solver_failed", "message": "ccx stopped"}}
        status, report = self.run_stress(plan)
        self.assertEqual(status, 2)
        self.assertNotIn("bundle", report)
        self.assertEqual(list(self.hw.glob("analysis/v1/*/results.json")), [])


class UnreadableResults(StressCase):
    """Results the study cannot read give UNKNOWN with a named reason: never a crash and never a number."""

    def assert_unknown(self, plan: list[dict[str, Any]], reason: str, fragment: str) -> dict[str, Any]:
        # A subtest repeats the case with other bytes. The recipe does not change, so a published bundle would be
        # reused and the solve skipped: remove what an earlier subtest published.
        for published in ("analysis", "checks"):
            shutil.rmtree(self.hw / published / "v1", ignore_errors=True)
        status, report = self.run_stress(plan)
        self.assertEqual(status, 0, report)
        found = report["stress_study"]
        self.assertEqual((found["outcome"], found["reasons"]), ("unknown", [reason]))
        self.assertIsNone(found["sigma_mpa"])
        self.assertIsNone(found["sigma_info_mpa"])
        self.assertFalse(found["strength_eligible"])
        self.assertIn(fragment, found["message"])
        return found

    def test_a_frd_cut_off_before_its_terminator_gives_unknown_not_an_error(self) -> None:
        plan = cantilever_plan()
        lines = plan[1]["frd"].splitlines()
        stress = max(i for i, line in enumerate(lines) if line.startswith(" -4  STRESS"))
        plan[1]["frd"] = "\n".join(lines[:stress + 500]) + "\n"  # the STRESS block stops without its terminator
        self.assert_unknown(plan, "malformed_frd", "fine mesh")

    def test_a_malformed_frd_record_in_the_coarse_solve_gives_unknown(self) -> None:
        plan = cantilever_plan()
        lines = plan[0]["frd"].splitlines()
        first = next(i for i, line in enumerate(lines) if line.startswith(" -1") and i > 20)
        lines[first] = lines[first][:20]
        plan[0]["frd"] = "\n".join(lines) + "\n"
        self.assert_unknown(plan, "malformed_frd", "coarse mesh")

    def test_a_missing_frd_gives_unknown(self) -> None:
        plan = cantilever_plan()
        plan[1]["frd"] = None
        self.assert_unknown(plan, "results_file_missing", "fine mesh")

    def test_a_ccx_input_without_boundary_nodes_gives_unknown(self) -> None:
        for name, text in (("no fixed set", "*CLOAD\n5,3,-1.0\n"), ("no load block", "*NSET,NSET=FixedFaces\n1,\n"),
                           ("empty fixed set", "*NSET,NSET=FixedFaces\n*CLOAD\n5,3,-1.0\n"),
                           ("garbled node", "*NSET,NSET=FixedFaces\n1,\nx,\n*CLOAD\n5,3,-1.0\n")):
            with self.subTest(name):
                self.jobs.clear()
                plan = cantilever_plan()
                plan[0]["inp"] = text
                self.assert_unknown(plan, "boundary_nodes_unreadable", "coarse mesh")

    def test_a_frd_that_is_not_utf8_text_gives_unknown_and_names_the_file(self) -> None:
        for position, label in ((0, "coarse"), (1, "fine")):
            with self.subTest(label):
                self.jobs.clear()
                plan = cantilever_plan()
                plan[position]["frd"] = b"\xff\xfe" + plan[position]["frd"].encode("utf-8")
                found = self.assert_unknown(plan, "malformed_frd", f"{label} mesh")
                self.assertIn("GmshMesh.frd is not UTF-8 text", found["message"])

    def test_a_ccx_input_that_is_not_utf8_text_gives_unknown_and_names_the_file(self) -> None:
        for position, label in ((0, "coarse"), (1, "fine")):
            with self.subTest(label):
                self.jobs.clear()
                plan = cantilever_plan()
                plan[position]["inp"] = plan[position]["inp"].encode("utf-8") + b"\n** \xe9\xff\n"
                found = self.assert_unknown(plan, "boundary_nodes_unreadable", f"{label} mesh")
                self.assertIn("GmshMesh.inp is not UTF-8 text", found["message"])

    def test_a_missing_ccx_input_gives_unknown(self) -> None:
        plan = cantilever_plan()
        plan[0]["inp"] = None
        self.assert_unknown(plan, "results_file_missing", "coarse mesh")

    def test_a_high_order_fallback_on_one_mesh_only_gives_unknown(self) -> None:
        plan = cantilever_plan()
        plan[1]["mesh_quality"] = {"elements": 600, "invalid_elements": 0, "min_scaled_jacobian": 0.4,
                                   "high_order_optimize": 2, "rejected": {"invalid_elements": 4}}
        self.assert_unknown(plan, "high_order_fallback_differs", "h_coarse=4.5 mm")


class Refusals(StressCase):
    def test_a_stress_case_that_asks_for_a_yield_safety_factor_is_refused_before_the_solve(self) -> None:
        self.build(conditions_tests.documents())
        status, report = self.call(self.case({"conditions": conditions_tests.DRY_23C}, mode="stress",
                                             required_safety_factor=2))
        self.assertEqual(status, 2, report)
        self.assertEqual(report["error"]["code"], "invalid_case")
        self.assertIn("required_safety_factor", report["error"]["message"])
        self.assertEqual(self.jobs, [])

    def test_a_mode_that_is_not_full_fast_or_stress_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "beam.step").write_bytes(b"ISO-10303-21; beam\n")
            path = root / "case.yaml"
            path.write_text("step: beam.step\nmode: strees\n" + fast_tests.EXPLICIT_TAIL, encoding="utf-8")
            with self.assertRaisesRegex(fea_static.CaseError, "mode must be one of full, fast, stress"):
                fea_static.load_case(path)

    def test_a_stress_case_accepts_a_strength_acceptance_for_the_later_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "beam.step").write_bytes(b"ISO-10303-21; beam\n")
            path = root / "case.yaml"
            path.write_text("step: beam.step\nmode: stress\nacceptance: {strength: REQ-001}\n"
                            + fast_tests.EXPLICIT_TAIL, encoding="utf-8")
            self.assertEqual(fea_static.load_case(path)["_mode"], "stress")


class OtherModesUnchanged(StressCase):
    def test_a_fast_case_runs_one_solve_at_its_own_mesh_size_and_reports_no_study(self) -> None:
        self.plan = [{"displacement": [0.0, 0.2]}]
        self.build(conditions_tests.documents())
        path = self.case({"conditions": conditions_tests.SERVICE}, mode="fast", mesh_size=4.5,
                         acceptance={"stiffness": "REQ-002"}, mesh_convergence={"decision": "DR-002"})
        self.approve(self.study(path))
        status, report = self.call(path)
        self.assertEqual(status, 0, report)
        self.assertEqual([(job["mode"], job["mesh_size"]) for job in self.jobs], [("fast", 4.5)])
        self.assertEqual(report["stress_study"], fea_modes.STRESS_STUDY)  # the fast text, not a study mapping
        self.assertIn("mesh_stability_indicator", report)

    def test_a_full_case_runs_one_solve_and_its_recipe_has_no_mode(self) -> None:
        self.build(conditions_tests.documents())
        path = self.case({"conditions": conditions_tests.SERVICE}, mesh_size=4.5, acceptance={"stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"})
        self.approve(self.study(path))
        self.plan = [{"displacement": [0.0, 0.2]}]
        status, report = self.call(path)
        self.assertEqual(status, 0, report)
        self.assertEqual([(job["mode"], job["mesh_size"]) for job in self.jobs], [("full", 4.5)])
        recipe = json.loads((Path(report["bundle"]) / "manifest.json").read_text(encoding="utf-8"))["recipe"]
        self.assertNotIn("mode", recipe["options"])

    def test_the_stress_recipe_names_its_mode_and_step_ratio(self) -> None:
        _, report = self.run_stress(cantilever_plan())
        recipe = json.loads((Path(report["bundle"]) / "manifest.json").read_text(encoding="utf-8"))["recipe"]
        self.assertEqual(recipe["options"]["mode"], "stress")
        self.assertEqual(recipe["options"]["stress_step_ratio"], 0.75)
        self.assertIn("fea_stress.py", recipe["producer_code_sha256"])
        self.assertIn("fea_stress_study.py", recipe["producer_code_sha256"])

    def test_a_fast_recipe_keeps_its_options(self) -> None:
        self.plan = [{"displacement": [0.0, 0.2]}]
        self.build(conditions_tests.documents())
        path = self.case({"conditions": conditions_tests.SERVICE}, mode="fast", mesh_size=4.5,
                         acceptance={"stiffness": "REQ-002"}, mesh_convergence={"decision": "DR-002"})
        self.approve(self.study(path))
        _, report = self.call(path)
        options = json.loads((Path(report["bundle"]) / "manifest.json").read_text(encoding="utf-8"))["recipe"]["options"]
        self.assertEqual(options["mode"], "fast")
        self.assertNotIn("stress_step_ratio", options)


class StudyWiring(unittest.TestCase):
    """fea_stress_study on its own: the comparison inputs, the ordering guard and the boundary-node reader."""

    def runs(self, coarse_h: float, fine_h: float) -> tuple[study.SolveRun, study.SolveRun]:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        plan = cantilever_plan()
        out = []
        for name, item, size in (("coarse", plan[0], coarse_h), ("fine", plan[1], fine_h)):
            folder = root / name
            folder.mkdir()
            (folder / "GmshMesh.frd").write_text(item["frd"])
            (folder / "GmshMesh.inp").write_text(item["inp"])
            out.append(study.SolveRun(folder, size, None))
        return out[0], out[1]

    def test_mesh_sizes_in_the_wrong_order_give_unknown_without_calling_the_comparison(self) -> None:
        coarse, fine = self.runs(3.375, 4.5)  # swapped: the "coarse" mesh is the smaller one
        with patch.object(fea_stress, "compare_levels", side_effect=AssertionError("compared")):
            found = study.run_study(coarse, fine)
        self.assertEqual((found["outcome"], found["reasons"]), ("unknown", ["mesh_sizes_not_ordered"]))
        self.assertIsNone(found["sigma_mpa"])
        self.assertIn("h_coarse=3.375 mm h_fine=4.5 mm", found["message"])

    def test_equal_mesh_sizes_give_unknown_too(self) -> None:
        coarse, fine = self.runs(4.5, 4.5)
        self.assertEqual(study.run_study(coarse, fine)["reasons"], ["mesh_sizes_not_ordered"])

    def test_mesh_sizes_that_are_not_finite_and_positive_reach_the_comparison_and_give_unknown(self) -> None:
        for h in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(h=h):
                coarse, fine = self.runs(4.5, h)
                found = study.run_study(coarse, fine)
                self.assertEqual(found["outcome"], "unknown")
                self.assertIn("invalid_mesh_size", found["reasons"])

    def test_a_correctly_ordered_pair_is_compared(self) -> None:
        coarse, fine = self.runs(4.5, 3.375)
        self.assertEqual(study.run_study(coarse, fine)["outcome"], "settled_away_from_support")

    def test_the_result_fields_hold_no_value_that_json_cannot_write(self) -> None:
        # A frd that lacks one node's stress ends the comparison early, with no kept peak and a nan displacement.
        coarse, fine = self.runs(4.5, 3.375)
        lines = (fine.run_dir / "GmshMesh.frd").read_text().splitlines()
        stress = max(i for i, line in enumerate(lines) if line.startswith(" -4  STRESS"))
        del lines[next(i for i in range(stress, len(lines)) if lines[i].startswith(" -1"))]
        (fine.run_dir / "GmshMesh.frd").write_text("\n".join(lines) + "\n")
        found = study.run_study(coarse, fine)
        self.assertEqual(found["reasons"], ["incomplete_results"])
        self.assertIsNone(found["coarse"]["max_displacement_mm"])
        self.assertEqual(json.loads(json.dumps(found, allow_nan=False)), found)

    def test_a_node_id_with_more_digits_than_python_converts_is_not_a_node_record(self) -> None:
        # int() refuses a string of more than 4300 digits with a ValueError of its own.
        with self.assertRaises(study.BoundaryNodesError):
            study.boundary_nodes("*NSET,NSET=FixedFaces\n" + "9" * 5000 + ",\n*CLOAD\n5,3,-1.0\n")

    def test_a_node_id_written_in_other_digits_is_not_a_node_record(self) -> None:
        with self.assertRaises(study.BoundaryNodesError):
            study.boundary_nodes("*NSET,NSET=FixedFaces\n\u0661\u0662,\n*CLOAD\n5,3,-1.0\n")

    def test_a_results_file_that_is_a_directory_gives_unknown_and_names_the_file(self) -> None:
        coarse, fine = self.runs(4.5, 3.375)
        (fine.run_dir / "GmshMesh.frd").unlink()
        (fine.run_dir / "GmshMesh.frd").mkdir()
        found = study.run_study(coarse, fine)
        self.assertEqual(found["reasons"], ["results_file_missing"])
        self.assertIn("GmshMesh.frd", found["message"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_a_results_file_the_study_may_not_read_gives_unknown_and_names_the_file(self) -> None:
        coarse, fine = self.runs(4.5, 3.375)
        (coarse.run_dir / "GmshMesh.inp").chmod(0)
        self.addCleanup((coarse.run_dir / "GmshMesh.inp").chmod, 0o644)
        found = study.run_study(coarse, fine)
        self.assertEqual(found["reasons"], ["results_file_missing"])
        self.assertIn("GmshMesh.inp", found["message"])

    def test_the_boundary_nodes_of_a_freecad_written_input_are_its_fixed_and_cload_nodes(self) -> None:
        fixed, load = study.boundary_nodes((FIXTURES / "cantilever_r1_4.5mm.faces.inp").read_text())
        planes = fea_stress.read_frd(frd_text("cantilever_r1_4.5mm"))
        self.assertEqual(fixed, fea_stress.plane_node_ids(planes, "x", 0.0))
        self.assertEqual(load, fea_stress.plane_node_ids(planes, "x", 100.0))
        self.assertEqual((len(fixed), len(load)), (39, 39))

    def test_every_cload_block_adds_its_nodes_and_a_zero_load_node_still_counts(self) -> None:
        fixed, load = study.boundary_nodes("*NSET,NSET=FixedFaces\n1,\n2,\n** FaceForce0\n*CLOAD\n5,3,-0\n6,3,-1.5\n"
                                           "** FaceForce1\n*CLOAD\n7,1,2.0\n*STEP\n")
        self.assertEqual((fixed, load), (frozenset({1, 2}), frozenset({5, 6, 7})))

    def test_the_fallback_level_is_the_optimisation_level_only_when_a_fallback_ran(self) -> None:
        self.assertIsNone(study.fallback_level({"high_order_optimize": 2}))
        self.assertEqual(study.fallback_level({"high_order_optimize": 3, "rejected": {"invalid_elements": 1}}), 3)
        self.assertIsNone(study.fallback_level({}))


if __name__ == "__main__":
    unittest.main()
