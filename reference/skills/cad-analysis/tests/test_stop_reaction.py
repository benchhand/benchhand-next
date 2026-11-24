#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Stop reaction (engineering.stop_reaction): the reaction of a latch lever's stops derived from the modelled
contact, on the stop_fixture.py geometry. The latched stop is touched across arms 7..13 mm, the open stop across
arms 0..7 mm, under a 30 N handle load at the lever's farthest point (80 mm along it, 3 mm off its axis line).

Expected figures are worked by hand. M = 30 N * sqrt(80^2 + 3^2) mm = 2401.687 N*mm.
Latched: nearest edge M / 7 = 343.098 N, uniform pressure M / 10 = 240.169 N, compliant stop M * 60 / 618 = 233.171 N.
Open: its nearest edge is on the axis, so the rigid reaction is unbounded; uniform M / 3.5 = 686.196 N and
compliant M * 24.5 / 114.333 = 514.647 N are estimates.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
SCRIPT = HERE.parent / "scripts" / "stop_reaction.py"
FIXTURES = HERE / "fixtures"

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

fx = load("cad_record_mi_fixtures", SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
sys.path.insert(0, str(SCRIPT.parent))  # stop_reaction imports its siblings by name
code_shas = load("cad_motion_code_shas", SKILLS / "cad-motion" / "scripts" / "code_shas.py")
stop_reaction = load("cad_analysis_stop_reaction", SCRIPT)
ISO286 = "cad-fits/data/iso286.json"

JOINT = {"id": "J-001", "type": "revolute", "parent": "TST-0301", "child": "TST-0302", "axis": [0, -1, 0],
         "origin": [0, 0, 0], "min": 0, "max": 75, "nominal": 0}


def load_entry(ident: str, newtons: float = 30.0) -> dict:
    return {"id": ident, "kind": "static", "magnitude": fx.known(fx.quantity(newtons, "N")), "direction": [0, 0, -1],
            "requirements": ["REQ-001"]}


def documents(contact_load: float | None = None, joint: dict | None = None, kind: str = "other",
              limits: dict | None = None, *, joints: list[dict] | None = None, ends: tuple[str, str] = ("TST-0302", "TST-0301"),
              pns: tuple[str, ...] = ("TST-0301", "TST-0302"), loads: str = "known") -> dict:
    """A record of the fixture parts: IF-006 the lever-to-bracket stops, critical and structural, under two 30 N loads.
    `joint` replaces the pivot (`joints`, all the joints), `kind` is the interface type, `limits` its declared fits,
    `ends` its from and to, and `loads` is "known", "unknown" (named, magnitude unknown) or "none" (not named)."""
    functional = {"critical": fx.known(True), "functions": [{"function": "locating"}, {"function": "structural"}]}
    if loads != "none":
        functional["loads"] = ["handle_close_at_latched_stop", "handle_open_at_open_stop"]
    if contact_load is not None:
        unknown = {"status": "unknown", "reason": "not needed by the fixture"}
        functional["contact"] = {"materials": [unknown, unknown], "load": fx.known(fx.quantity(contact_load, "N"))}
    entries = [load_entry("handle_close_at_latched_stop"), load_entry("handle_open_at_open_stop")]
    if loads == "unknown":
        for entry in entries:
            entry["magnitude"] = fx.unknown("the handle force is not measured")
    use = fx.use_case("draft", loads=entries)
    titles = {"TST-0301": "Bracket", "TST-0302": "Lever", "TST-0303": "Ring"}
    docs = fx.record(product_data=fx.product(use), parts=[fx.part(pn, titles[pn], process="cnc") for pn in pns],
                     interfaces=[fx.interface("IF-006", ends[0], ends[1], kind, functional,
                                              **({"limits": limits} if limits else {}))])
    docs["assembly.yaml"]["joints"] = [dict(j) for j in (joints or [joint or JOINT])]
    return docs


def validator(definition: str):
    return fx.ref_validator(f"https://srobroek.com/cad/schemas/manufacturing.schema.json#/$defs/{definition}")


def covered(path: Path, declared: tuple[Path, ...]) -> bool:
    path = path.resolve()
    return any(path == entry.resolve() or path.is_relative_to(entry.resolve()) for entry in declared)


class DeclaredDataTests(unittest.TestCase):
    """The recipe names the data that decides the verdict as well as the code (#128, #140). Kernel-free."""

    def test_the_verdict_data_covers_every_data_file_the_code_names(self) -> None:
        missing = sorted(str(path.relative_to(SKILLS)) for path in code_shas.referenced_data(SCRIPT)
                         if not covered(path, stop_reaction.VERDICT_DATA))
        self.assertEqual(missing, [], "add these to stop_reaction.VERDICT_DATA")

    def test_the_recipe_hashes_the_declared_data_with_the_code(self) -> None:
        table = code_shas.closure(SCRIPT, stop_reaction.VERDICT_DATA)
        self.assertIn(ISO286, table)
        self.assertIn("cad-analysis/scripts/stop_reaction.py", table)
        self.assertIn("cad-analysis/scripts/stop_extrema.py", table)
        self.assertNotIn(ISO286, code_shas.closure(SCRIPT), "the table is data, not code")


class StopGeometryTests(unittest.TestCase):
    """stop_reaction.py on built geometry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name).resolve()
        build = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / "stop_fixture.py"),
                                str(cls.root / "geometry")], capture_output=True, text=True, timeout=900, check=False)
        if build.returncode != 0:
            raise RuntimeError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    @classmethod
    def built(cls, gap: float, variant: str = "") -> Path:
        """The fixture parts with the latched stop `gap` mm below the lever, built once."""
        folder = cls.root / f"geometry-{gap}-{variant}"
        if not folder.exists():
            build = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / "stop_fixture.py"), str(folder), str(gap),
                                    variant], capture_output=True, text=True, timeout=900, check=False)
            if build.returncode != 0:
                raise RuntimeError(build.stdout + build.stderr)
        return folder

    def run_stop(self, name: str, contact_load: float | None = None, joint: dict | None = None,
                 kind: str = "other", gap: float | None = None, limits: dict | None = None, variant: str = "",
                 **record: Any) -> tuple[int, dict]:
        hw = fx.write_record(self.root / name / "hw", documents(contact_load, joint, kind, limits, **record))
        geometry = self.root / "geometry" if gap is None and not variant else self.built(gap or 0.0, variant)
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), "--hw", str(hw), "--parts-dir",
                               str(geometry / "parts")], capture_output=True, text=True, timeout=1800, check=False)
        self.assertIn(proc.returncode, (0, 1), proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        finding, outcome = validator("finding"), validator("obligation_outcome")
        for item in result["findings"]:
            self.assertEqual(list(finding.iter_errors(item)), [], item["id"])
        for row in result["outcomes"]:
            self.assertEqual(list(outcome.iter_errors(row)), [], row["obligation"])
        self.assertEqual([o["id"] for o in result["expected"]], ["engineering.stop_reaction@IF-006"])
        return proc.returncode, result

    def test_the_latched_stop_is_bounded_by_its_nearest_edge_and_the_open_stop_is_unbounded(self) -> None:
        code, result = self.run_stop("modelled")
        ends = result["detail"]["interfaces"]["IF-006"]["ends"]
        latched, opened = ends["min"], ends["max"]
        self.assertEqual((latched["touching"], opened["touching"]), (True, True))
        self.assertAlmostEqual(latched["farthest_point_from_axis_mm"], 80.0562, places=3)
        self.assertAlmostEqual(latched["patch"]["min_arm_mm"], 7.0, places=6)
        self.assertAlmostEqual(latched["patch"]["max_arm_mm"], 13.0, places=6)
        reaction = latched["reaction"]
        self.assertEqual(reaction["status"], "bounded")
        self.assertAlmostEqual(reaction["design_reaction_n"], 343.098, places=2)
        self.assertGreaterEqual(reaction["design_reaction_n"], 343.0)
        self.assertAlmostEqual(reaction["uniform_pressure_n"], 240.169, places=2)
        self.assertAlmostEqual(reaction["compliant_stop_n"], 233.171, places=2)
        self.assertAlmostEqual(reaction["pin_load_bound_n"], 373.098, places=2)
        self.assertAlmostEqual(opened["patch"]["min_arm_mm"], 0.0, places=6)
        self.assertAlmostEqual(opened["patch"]["max_arm_mm"], 7.0, places=6)
        self.assertEqual(opened["reaction"]["status"], "unbounded")
        self.assertIsNone(opened["reaction"]["design_reaction_n"])
        self.assertAlmostEqual(opened["reaction"]["uniform_pressure_n"], 686.196, places=2)
        self.assertAlmostEqual(opened["reaction"]["compliant_stop_n"], 514.647, places=2)
        [row] = result["outcomes"]
        self.assertEqual((code, result["result"], row["outcome"]), (1, "unknown", "unknown"))
        [unbounded] = result["findings"]
        self.assertEqual((unbounded["code"], unbounded["severity"], unbounded["outcome"]),
                         ("engineering.stop_reaction_unbounded", "critical", "unknown"))
        self.assertIn("FEA contact case", unbounded["remedy"])
        self.assertIn("design record", unbounded["remedy"])

    def test_a_recorded_240_n_is_understated_against_the_latched_stop(self) -> None:
        code, result = self.run_stop("recorded", contact_load=240.0)
        self.assertEqual((code, result["result"]), (1, "fail"))
        codes = {f["code"]: f for f in result["findings"]}
        self.assertEqual(set(codes), {"engineering.stop_reaction_understated", "engineering.stop_reaction_unbounded"})
        understated = codes["engineering.stop_reaction_understated"]
        self.assertEqual((understated["severity"], understated["outcome"]), ("major", "fail"))
        self.assertEqual(understated["measured"], {"value": 240.0, "units": "N"})
        self.assertAlmostEqual(understated["criterion"]["value"], 343.098, places=2)
        self.assertEqual(understated["criterion"]["source"]["origin"], "benchhand")

    def test_a_recorded_figure_that_covers_the_latched_stop_leaves_only_the_open_stop_unbounded(self) -> None:
        code, result = self.run_stop("covered", contact_load=400.0)
        self.assertEqual((code, result["result"]), (1, "unknown"))
        self.assertEqual([f["code"] for f in result["findings"]], ["engineering.stop_reaction_unbounded"])

    def test_a_loaded_mounting_interface_with_no_movable_joint_is_not_a_stop(self) -> None:
        fixed = {**JOINT, "type": "fixed", "min": 0, "max": 0}
        code, result = self.run_stop("mounting", joint=fixed, kind="mounting")
        [row] = result["outcomes"]
        self.assertEqual((code, result["result"], row["outcome"], result["findings"]), (0, "pass", "not_applicable", []))
        self.assertIn("no movable joint", row["coverage"])

    def test_a_pivot_whose_limits_touch_nothing_is_not_a_stop(self) -> None:
        free = {**JOINT, "min": 10, "max": 30, "nominal": 10}
        code, result = self.run_stop("free-swing", joint=free)
        [row] = result["outcomes"]
        self.assertEqual((code, result["result"], row["outcome"], result["findings"]), (0, "pass", "not_applicable", []))
        self.assertIn("not in contact at either limit of J-001", row["coverage"])
        ends = result["detail"]["interfaces"]["IF-006"]["ends"]
        self.assertEqual((ends["min"]["touching"], ends["max"]["touching"]), (False, False))

    # The latched stop stands `gap` mm below the lever. The pivot stops at 30 deg, well clear of the open stop.
    LATCHED_ONLY = {**JOINT, "max": 30}

    def latched_end(self, result: dict) -> dict:
        return result["detail"]["interfaces"]["IF-006"]["ends"]["min"]

    def test_a_limit_a_tenth_of_a_millimetre_off_is_still_the_stop(self) -> None:
        code, result = self.run_stop("gap-0.1", joint=self.LATCHED_ONLY, gap=0.1)
        latched = self.latched_end(result)
        self.assertAlmostEqual(latched["gap_mm"], 0.1, places=6)
        self.assertEqual(latched["reaction"]["status"], "bounded")
        self.assertAlmostEqual(latched["reaction"]["design_reaction_n"], 343.098, places=2)
        self.assertEqual((code, result["result"]), (0, "pass"))
        self.assertEqual(result["detail"]["interfaces"]["IF-006"]["contact_tolerance"], {"mm": 0.15, "source": "constant"})

    def test_a_limit_half_a_millimetre_off_is_not_a_stop(self) -> None:
        code, result = self.run_stop("gap-0.5", joint=self.LATCHED_ONLY, gap=0.5)
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"], result["findings"]), (0, "not_applicable", []))
        evidence = result["detail"]["interfaces"]["IF-006"]
        self.assertAlmostEqual(evidence["ends"]["min"]["gap_mm"], 0.5, places=6)
        self.assertEqual(evidence["contact_tolerance"], {"mm": 0.15, "source": "constant"})
        self.assertIn("tolerance 0.15 mm", row["coverage"])

    def test_a_declared_fit_clearance_above_the_constant_raises_the_tolerance(self) -> None:
        # 20 H11/c11: ES 0.130 and ei -0.240 (ISO 286, 18 to 30 mm), so the largest clearance is 0.370 mm.
        fit = {"running_fit": {"fit": "20 H11/c11", "pair": ["TST-0302", "TST-0301"]}}
        _, plain = self.run_stop("gap-0.3-plain", joint=self.LATCHED_ONLY, gap=0.3)
        self.assertEqual(plain["outcomes"][0]["outcome"], "not_applicable", "0.3 mm is above the 0.15 mm constant")
        code, result = self.run_stop("gap-0.3-fit", joint=self.LATCHED_ONLY, gap=0.3, limits=fit)
        latched = self.latched_end(result)
        self.assertAlmostEqual(latched["gap_mm"], 0.3, places=6)
        self.assertEqual(latched["reaction"]["status"], "bounded")
        self.assertEqual((code, result["result"]), (0, "pass"))
        tolerance = result["detail"]["interfaces"]["IF-006"]["contact_tolerance"]
        self.assertAlmostEqual(tolerance["mm"], 0.37, places=6)
        self.assertEqual(tolerance["source"], "fit 20 H11/c11 clearance")
        _, beyond = self.run_stop("gap-0.5-fit", joint=self.LATCHED_ONLY, gap=0.5, limits=fit)
        self.assertEqual(beyond["outcomes"][0]["outcome"], "not_applicable", "0.5 mm is above the 0.37 mm clearance")

    def test_a_gap_exactly_at_the_tolerance_is_a_stop(self) -> None:
        code, result = self.run_stop("gap-at-tolerance", joint=self.LATCHED_ONLY, gap=0.15)
        latched = self.latched_end(result)
        self.assertEqual(latched["reaction"]["status"], "bounded")
        self.assertEqual((code, result["result"]), (0, "pass"))
        self.assertEqual(result["detail"]["interfaces"]["IF-006"]["contact_tolerance"], {"mm": 0.15, "source": "constant"})

    def test_a_gap_two_microns_above_the_tolerance_is_not_a_stop(self) -> None:
        code, result = self.run_stop("gap-above-tolerance", joint=self.LATCHED_ONLY, gap=0.152)
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"], result["findings"]), (0, "not_applicable", []))

    def test_the_same_boundary_holds_at_a_tolerance_raised_by_a_fit(self) -> None:
        fit = {"running_fit": {"fit": "20 H11/c11", "pair": ["TST-0302", "TST-0301"]}}  # clearance 0.370 mm
        code, at = self.run_stop("fit-at-tolerance", joint=self.LATCHED_ONLY, gap=0.37, limits=fit)
        self.assertEqual(self.latched_end(at)["reaction"]["status"], "bounded")
        self.assertEqual((code, at["result"]), (0, "pass"))
        _, above = self.run_stop("fit-above-tolerance", joint=self.LATCHED_ONLY, gap=0.372, limits=fit)
        self.assertEqual(above["outcomes"][0]["outcome"], "not_applicable")

    def test_a_tilted_face_within_the_tolerance_has_no_parallel_pair_and_stays_unknown(self) -> None:
        # At 0.5 deg the lever's underside is 7 * sin(0.5 deg) = 0.061 mm off the stop at its nearest edge, and tilted.
        tilted = {**JOINT, "min": 0.5, "max": 30, "nominal": 0.5}
        code, result = self.run_stop("tilted", joint=tilted)
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"]), (1, "unknown"))
        self.assertIn("no parallel opposite-facing planar faces", row["uncertainty"])
        self.assertAlmostEqual(self.latched_end(result)["gap_mm"], 0.0611, places=3)

    def test_an_ambiguous_reference_is_unknown_never_a_quiet_not_applicable(self) -> None:
        # TST-0302 has two occurrences, so a bare TST-0302 names two of them: absence and ambiguity differ.
        documents_ = documents(ends=("TST-0302", "TST-0301"), joints=[
            {**JOINT, "child": "@lever-a"},
            {"id": "J-002", "type": "fixed", "parent": "TST-0301", "child": "@lever-b", "axis": [0, 0, 1],
             "origin": [0, 20, 0], "min": 0, "max": 0, "nominal": 0}])
        documents_["assembly.yaml"]["subassemblies"] = [{"id": "main", "title": "Main", "parts": ["TST-0301"],
                                                         "occurrences": ["@lever-a", "@lever-b"]}]
        documents_["assembly.yaml"]["occurrences"] = [
            {"id": "lever-a", "PN": "TST-0302"},
            {"id": "lever-b", "PN": "TST-0302", "placement": {"translation_mm": [0, 20, 0]}}]
        documents_["parts/TST-0302/part.yaml"]["model_frame"] = "part_local"  # a part with two occurrences uses its own origin
        hw = fx.write_record(self.root / "ambiguous" / "hw", documents_)
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), "--hw", str(hw), "--parts-dir",
                               str(self.root / "geometry" / "parts")], capture_output=True, text=True, timeout=1800, check=False)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        [row] = result["outcomes"]
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("ambiguous", row["uncertainty"])
        self.assertEqual([f["code"] for f in result["findings"]], ["engineering.stop_reaction_unknown"])

    def test_a_part_outside_the_assembly_is_absent_and_not_applicable(self) -> None:
        code, result = self.run_stop("absent", ends=("TST-0302", "a 3 mm steel panel"))
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"], result["findings"]), (0, "not_applicable", []))
        self.assertIn("names no occurrence", row["coverage"])

    def test_a_free_swinging_pivot_is_not_a_stop_whatever_is_known_of_the_load(self) -> None:
        free = {**JOINT, "min": 10, "max": 30, "nominal": 10}
        for name, options in (("free-unknown-loads", {"loads": "unknown"}),
                              ("free-contact-load-only", {"loads": "none", "contact_load": 240.0})):
            with self.subTest(case=name):
                code, result = self.run_stop(name, joint=free, **options)
                [row] = result["outcomes"]
                self.assertEqual((code, row["outcome"], result["findings"]), (0, "not_applicable", []))

    def test_a_stop_with_no_known_force_is_unknown(self) -> None:
        for name, options in (("stop-unknown-loads", {"loads": "unknown"}), ("stop-contact-load-only", {"loads": "none", "contact_load": 240.0})):
            with self.subTest(case=name):
                code, result = self.run_stop(name, joint={**JOINT, "max": 30}, **options)
                [row] = result["outcomes"]
                self.assertEqual((code, row["outcome"]), (1, "unknown"))
                self.assertRegex(row["uncertainty"], "force|use-case load")
                self.assertEqual([f["code"] for f in result["findings"]], ["engineering.stop_reaction_unknown"])

    def assertUnknownPivot(self, name: str, reason: str, **options: Any) -> None:
        code, result = self.run_stop(name, **options)
        [row] = result["outcomes"]
        self.assertEqual((code, result["result"], row["outcome"]), (1, "unknown", "unknown"))
        self.assertIn(reason, row["uncertainty"])
        [finding] = result["findings"]
        self.assertEqual((finding["code"], finding["severity"], finding["outcome"]),
                         ("engineering.stop_reaction_unknown", "major", "unknown"))
        self.assertIn(reason, finding["uncertainty"])

    def test_several_movable_joints_between_the_parts_leave_the_stop_unknown(self) -> None:
        second = {"id": "J-002", "type": "revolute", "parent": "TST-0302", "child": "TST-0303", "axis": [0, -1, 0],
                  "origin": [84, 0, 0], "min": 0, "max": 10, "nominal": 0}
        self.assertUnknownPivot("several", "several movable joints", variant="ring", pns=("TST-0301", "TST-0302", "TST-0303"),
                                joints=[dict(JOINT), second], ends=("TST-0303", "TST-0301"))

    def test_a_coupled_pivot_leaves_the_stop_unknown(self) -> None:
        driver = {"id": "J-002", "type": "revolute", "parent": "TST-0301", "child": "TST-0303", "axis": [0, -1, 0],
                  "origin": [84, 0, 0], "min": 0, "max": 10, "nominal": 0}
        driven = {key: value for key, value in JOINT.items() if key != "nominal"}
        driven["coupling"] = {"type": "linear", "driver": "J-002", "ratio": 1}
        self.assertUnknownPivot("coupled", "driven through a coupling", variant="ring", pns=("TST-0301", "TST-0302", "TST-0303"),
                                joints=[driver, driven])

    def test_a_prismatic_pivot_leaves_the_stop_unknown(self) -> None:
        slide = {"id": "J-001", "type": "prismatic", "parent": "TST-0301", "child": "TST-0302", "axis": [1, 0, 0],
                 "origin": [0, 0, 0], "min": 0, "max": 5, "nominal": 0}
        self.assertUnknownPivot("prismatic", "only a revolute stop is derived", joint=slide)

    def test_a_round_stop_face_tangent_to_the_axis_line_is_unbounded(self) -> None:
        # By hand: the disc (center (10, 2), radius 10, top at z -3) meets the lever's underside (z -3 at 0 deg,
        # x from -2, |y| <= 4) in the part of the disc with |y| <= 4. The arm of a point is its x, and the rim reaches
        # x = 0 at (0, 2), inside the lever's width. So the smallest arm is 0 at a point that is no vertex and that
        # no 64-sample outline of the clipped rim hits: the sampled outline gave 5.6e-5 mm and a "bounded" reaction.
        # The pivot runs 0 to 75 deg, the latch travel: at 75 deg the lever is 0.29 mm clear of the disc (fixture docstring).
        code, result = self.run_stop("disk", variant="disk")
        latched = self.latched_end(result)
        self.assertLess(abs(latched["patch"]["min_arm_mm"]), 1e-6)
        self.assertEqual(latched["reaction"]["status"], "unbounded")
        self.assertEqual((code, result["result"]), (1, "unknown"))

    def test_a_round_stop_face_gives_the_reaction_from_its_exact_nearest_point(self) -> None:
        # By hand: the disc (center (13, 2), radius 10) has its nearest rim point to the pivot at (3, 2), arm 3 mm,
        # and its far rim point at (23, 2), arm 23 mm. M = 30 N * sqrt(80^2 + 3^2) mm = 2401.687 N*mm, so the design
        # reaction is M / 3 = 800.562 N. A sampled rim gave a smallest arm above 3 and a reaction about 0.01 N short.
        code, result = self.run_stop("disk3", variant="disk3")
        latched = self.latched_end(result)
        self.assertAlmostEqual(latched["patch"]["min_arm_mm"], 3.0, places=9)
        self.assertAlmostEqual(latched["patch"]["max_arm_mm"], 23.0, places=9)
        self.assertEqual(latched["reaction"]["status"], "bounded")
        self.assertAlmostEqual(latched["reaction"]["design_reaction_n"], 2401.687 / 3.0, places=3)

    def test_parts_that_overlap_at_a_limit_are_a_design_defect_with_their_depth(self) -> None:
        # By hand, at 20 deg: the lever's underside is the plane z = x tan(20) - 3 / cos(20) in the posed frame, and
        # it crosses the disc's top plane z = -3 at x = 3 (1 - cos 20) / sin 20 = 0.529 mm. For x between 0 and 0.529 the
        # lever dips below z = -3 inside the disc, which starts at the rim point (0, 2). The deepest point is that rim
        # point, 3 (1 - cos 20) = 0.181 mm from the underside plane (0.192 mm below z = -3). The lever tilts 20 deg to
        # the disc top, so no parallel pair exists, but the cause is the overlap and the reason must say so. The disc
        # variant has no open stop, so this sliver is the only overlap: the shared volume there is 0.17 mm3.
        code, result = self.run_stop("overlap", joint={**JOINT, "max": 20}, variant="disk")
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"]), (1, "unknown"))
        self.assertRegex(row["uncertainty"], r"the parts overlap by 0\.[12]\d* mm at the max limit \(20 deg\)")
        self.assertIn("a design defect, not a stop", row["uncertainty"])
        self.assertNotIn("no parallel", row["uncertainty"])
        end = result["detail"]["interfaces"]["IF-006"]["ends"]["max"]
        self.assertGreater(end["overlap_volume_mm3"], 0.001)
        self.assertTrue(0.17 <= end["overlap_depth_mm"] <= 0.20, end["overlap_depth_mm"])

    def test_a_round_lever_end_gives_the_exact_reach(self) -> None:
        # The farthest point, (80, +-4, 0), lies on the rim of the end cylinder, half a sample step from the nearest sample.
        code, result = self.run_stop("round", joint={**JOINT, "max": 30}, variant="round")
        reach = self.latched_end(result)["farthest_point_from_axis_mm"]
        self.assertGreaterEqual(reach, 80.0 - 1e-9)
        self.assertLessEqual(reach, 80.0 + 1e-6)
        self.assertEqual(self.latched_end(result)["reaction"]["status"], "bounded")

    def test_two_separate_overlaps_report_the_deeper_one(self) -> None:
        # By hand, at 0 deg, the lever is x 0..80, y -4..4, z -3..3. Piece 1: the latched block's top is z -2.5, so the
        # lever's underside enters it over x 7..13, y -4..4, z -3..-2.5. Its sides are 6, 8 and 0.5 mm, so its thinnest
        # width is 0.5 mm and its volume 6 * 8 * 0.5 = 24 mm3. Piece 2: a side block at x 30..40, y 2.5..10 cuts the
        # lever's side face over x 30..40, y 2.5..4, z -3..3. Its sides are 10, 1.5 and 6 mm, so its thinnest width is
        # 1.5 mm and its volume 10 * 1.5 * 6 = 90 mm3. The deepest piece is 1.5 mm. The shallowest would give 0.5 mm.
        # Both pieces taken together span z -3..3 (6 mm), y -4..4 (8 mm) and x 7..40 (33 mm), so their thinnest
        # planar width is 6 mm. The depth is the deepest piece's 1.5 mm, and the total volume 24 + 90 = 114 mm3.
        code, result = self.run_stop("pieces", variant="pieces")
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"]), (1, "unknown"))
        self.assertIn("overlap by 1.5 mm at the min limit (0 deg): a design defect", row["uncertainty"])
        ends = result["detail"]["interfaces"]["IF-006"]["ends"]
        self.assertAlmostEqual(ends["min"]["overlap_depth_mm"], 1.5, places=9)
        self.assertAlmostEqual(ends["min"]["overlap_volume_mm3"], 114.0, places=6)
        self.assertEqual(ends["max"]["overlap_volume_mm3"], 0.0)

    def test_a_fully_curved_overlap_reports_its_thinnest_width(self) -> None:
        # By hand: a sphere of radius 5 centered at (40, 0, 0) and a cylinder of radius 10 with its axis along Y
        # through (40, y, -12). The sphere's lowest point is z = -5 and the cylinder's top is z = -12 + 10 = -2, so the
        # sphere pushes 3 mm into the cylinder along z. The overlap is a sphere cap under the cylinder's surface, with
        # spherical and cylindrical faces and no planar face. Its thinnest width is that 3 mm. Its other extents are
        # about 9 mm (a chord of the sphere at 2 mm from its center is 2 * sqrt(25 - 4) = 9.2 mm). The volume is below
        # that of the cap cut by the plane z = -2: pi * 3^2 * (3 * 5 - 3) / 3 = 113.1 mm3. The depth comes from the
        # smallest side of an oriented box round the overlap. The box encloses it, so that side is at least 3 mm, and
        # for a cap whose axes match the box it stays within 10% of the width, so the bound checked is 3.0 to 3.3 mm.
        code, result = self.run_stop("curved", variant="curved")
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"]), (1, "unknown"))
        self.assertIn("a design defect, not a stop", row["uncertainty"])
        end = result["detail"]["interfaces"]["IF-006"]["ends"]["min"]
        self.assertGreaterEqual(end["overlap_depth_mm"], 3.0 - 1e-6)
        self.assertLessEqual(end["overlap_depth_mm"], 3.3)
        self.assertTrue(50.0 < end["overlap_volume_mm3"] < 113.2, end["overlap_volume_mm3"])
        # The sphere moves, and a sphere is no plane, cylinder or cone, so the corners of its bounding box give its
        # reach bound. Its true farthest point from the Y axis is 40 + 5 = 45 mm out. The box x 35..45, y -5..5, z -5..5
        # has corners sqrt(45^2 + 5^2) = 45.277 mm from the axis. The bound is at least 45 and here at most 45.28.
        self.assertGreaterEqual(end["farthest_point_from_axis_mm"], 45.0)
        self.assertLessEqual(end["farthest_point_from_axis_mm"], 45.28)

    def test_a_part_wholly_inside_one_solid_of_a_compound_is_an_overlap_defect(self) -> None:
        # By hand: the bracket is a compound of a block x -20..120, y -20..20, z -20..110 and a small block far away.
        # The lever (x 0..80, y -4..4, z -3..3 at 0 deg) sits inside the large block, 16 mm from its nearest face
        # (y: 20 - 4), and at 75 deg its farthest corner is at x 23.6, z 78.1, still inside. A boundary distance
        # of 16 mm is far above the tolerance, so a distance that ignores containment calls the limit clear. The shared
        # volume is the lever's own 80 * 8 * 6 = 3840 mm3, and its thinnest planar width is its 6 mm thickness.
        code, result = self.run_stop("contained", variant="contained")
        [row] = result["outcomes"]
        self.assertEqual((code, row["outcome"]), (1, "unknown"))
        self.assertIn("overlap by 6 mm at the min limit (0 deg) and at the max limit (75 deg): a design defect", row["uncertainty"])
        ends = result["detail"]["interfaces"]["IF-006"]["ends"]
        for label in ("min", "max"):
            self.assertAlmostEqual(ends[label]["overlap_volume_mm3"], 3840.0, places=2)
            self.assertAlmostEqual(ends[label]["overlap_depth_mm"], 6.0, places=6)


class VersionedPublicationTests(unittest.TestCase):
    """stop_reaction.py on a sealed version: an unchanged rerun finds the published bundle and reuses it, and
    replaced (with --replace) when the producer's code or a fit-table value does. Each case runs a copy of the skills
    tree, so an edit never touches the repository."""

    FIT = {"running_fit": {"fit": "20 H11/c11", "pair": ["TST-0302", "TST-0301"]}}  # clearance 0.370 mm
    CODE = ("cad-analysis/scripts/stop_reaction.py", "cad-analysis/scripts/stop_statics.py",
            "cad-motion/scripts/pose.py", "cad-record/scripts/check_packet.py", "cad-fits/scripts/fits.py")

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name).resolve()
        build = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / "stop_fixture.py"),
                                str(cls.root / "geometry")], capture_output=True, text=True, timeout=900, check=False)
        if build.returncode != 0:
            raise RuntimeError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def project(self, name: str, **options: Any) -> tuple[Path, Path]:
        """(a copy of the skills tree, a project hw/ with version v1 sealed from the fixture parts)."""
        skills = self.root / name / "skills"
        shutil.copytree(SKILLS, skills, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
        hw = fx.write_record(self.root / name / "project" / "hw", documents(joint={**JOINT, "max": 30}, **options))
        folder = hw / "versions" / "v1"
        for path in sorted(hw.rglob("*")):
            relative = path.relative_to(hw)
            if path.is_file() and relative.parts[0] not in ("versions", "decisions") and relative.name not in ("bom.csv", "verification.csv"):
                (folder / "record" / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, folder / "record" / relative)
        shutil.copytree(self.root / "geometry" / "parts", folder / "parts")
        files = {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(folder.rglob("*")) if path.is_file()}
        (folder / "manifest.json").write_text(json.dumps({"schema_version": 2, "label": "v1", "files": files}), encoding="utf-8")
        (hw / "versions" / "latest.json").write_text(json.dumps({"label": "v1"}), encoding="utf-8")
        return skills, hw

    def run_version(self, skills: Path, hw: Path, *extra: str) -> tuple[int, dict, str]:
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(skills / "cad-analysis" / "scripts" / "stop_reaction.py"),
                               "--hw", str(hw), "--version", "v1", *extra], capture_output=True, text=True, timeout=1800, check=False)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {}), proc.stderr

    def test_an_unchanged_rerun_reuses_the_published_bundle(self) -> None:
        skills, hw = self.project("reuse")
        code, first, _ = self.run_version(skills, hw)
        self.assertEqual((code, first["result"], first["reused"]), (0, "pass", False))
        code, second, _ = self.run_version(skills, hw)
        self.assertEqual((code, second["reused"], second["bundle"]), (0, True, first["bundle"]))

    def test_an_edit_to_any_module_the_producer_loads_replaces_the_bundle_only_with_replace(self) -> None:
        for relative in self.CODE:
            with self.subTest(module=relative):
                skills, hw = self.project("code-" + relative.replace("/", "-"))
                self.run_version(skills, hw)
                with (skills / relative).open("a", encoding="utf-8") as module:
                    module.write("\n# edited\n")
                code, _, error = self.run_version(skills, hw)
                self.assertEqual(code, 2, "the recipe changed, so the old bundle is a conflict and is not reused: " + error)
                code, replaced, _ = self.run_version(skills, hw, "--replace")
                self.assertEqual((code, replaced["reused"]), (0, False))

    def test_a_change_of_the_tolerance_constant_replaces_the_bundle_with_the_new_evidence(self) -> None:
        skills, hw = self.project("constant")
        _, first, _ = self.run_version(skills, hw)
        self.assertEqual(first["detail"]["interfaces"]["IF-006"]["contact_tolerance"]["mm"], 0.15)
        script = skills / "cad-analysis" / "scripts" / "stop_reaction.py"
        script.write_text(script.read_text(encoding="utf-8").replace("STOP_CONTACT_TOLERANCE_MM = 0.15", "STOP_CONTACT_TOLERANCE_MM = 0.05"),
                          encoding="utf-8")
        code, replaced, _ = self.run_version(skills, hw, "--replace")
        self.assertEqual((code, replaced["reused"]), (0, False))
        self.assertEqual(replaced["detail"]["interfaces"]["IF-006"]["contact_tolerance"]["mm"], 0.05)

    def test_an_edit_to_a_fit_table_value_replaces_the_bundle(self) -> None:
        skills, hw = self.project("table", limits=self.FIT)
        _, first, _ = self.run_version(skills, hw)
        self.assertAlmostEqual(first["detail"]["interfaces"]["IF-006"]["contact_tolerance"]["mm"], 0.37, places=6)
        table = skills / "cad-fits" / "data" / "iso286.json"
        data = json.loads(table.read_text(encoding="utf-8"))
        data["shaft_es"]["c"][4] = -100  # the 18 to 30 mm band: c11 clearance falls from 0.370 to 0.360 mm
        table.write_text(json.dumps(data), encoding="utf-8")
        code, _, error = self.run_version(skills, hw)
        self.assertEqual(code, 2, "the fit table changed, so the old bundle is a conflict and is not reused: " + error)
        code, replaced, _ = self.run_version(skills, hw, "--replace")
        self.assertEqual((code, replaced["reused"]), (0, False))
        self.assertAlmostEqual(replaced["detail"]["interfaces"]["IF-006"]["contact_tolerance"]["mm"], 0.36, places=6)


if __name__ == "__main__":
    unittest.main()
