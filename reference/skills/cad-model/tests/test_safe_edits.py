#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Safe edits, occ Booleans and the diff volume split: bounds, slack, refusals and edge cases.

Run: python3 -m unittest discover -s cad/skills/cad-model/tests -p test_safe_edits.py -v
Needs `uv`. Each kernel environment runs one probe (fixtures/safe_edit*_probe.py, cases in
fixtures/safe_cases_lib.py) that calls the public functions and prints a JSON report; the tests assert
on volumes, exception types and message text. A Boolean fault is injected by replacing occ.boolean
(looked up at call time), so a bound or a result check is reached without a kernel that misbehaves.
Boxes: A is 10 mm cubed (1000), B is A moved +5 along X, FAR is A moved +100 along X, SMALL is 2 mm cubed in A.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
from cadmodel import check, occ  # noqa: E402 - stdlib-only imports; OCP loads on first use
from cadmodel.safe import SafeEditError, __all__ as SAFE_ALL  # noqa: E402

IMPOSSIBLE = " rejected an impossible result: "
EMPTY = " rejected an empty result: no solid remains; no result was accepted"
KIND = "must be a TopoDS_Shape or a CadQuery/build123d shape, got "
NO_OVERLAP = "safe_intersect rejected an empty result: the inputs do not overlap; no result was accepted"


class SlackTests(unittest.TestCase):
    """occ.volume_slack: 1e-7 relative to the largest magnitude passed, never below 1e-6 mm^3. It needs no OCP."""

    def test_the_floor_holds_for_small_volumes_and_for_none(self) -> None:
        for volumes in ((), (0.0,), (1.0,), (9.0,), (5.0, 0.5), (-0.5, 2.0)):
            with self.subTest(volumes=volumes):
                self.assertAlmostEqual(occ.volume_slack(*volumes), 1e-6, places=15)

    def test_the_relative_part_scales_with_the_largest_magnitude(self) -> None:
        for volumes, want in (((100.0,), 1e-5), ((1e6,), 0.1), ((3e6, 1e6, 2e6), 0.3), ((1e9,), 100.0)):
            with self.subTest(volumes=volumes):
                self.assertAlmostEqual(occ.volume_slack(*volumes) / want, 1.0, places=12)

    def test_a_negative_volume_counts_by_its_magnitude(self) -> None:
        self.assertAlmostEqual(occ.volume_slack(-1e6, 5.0) / 0.1, 1.0, places=12)

    def test_volumes_are_not_summed(self) -> None:
        self.assertAlmostEqual(occ.volume_slack(1e6, 1e6) / 0.1, 1.0, places=12)

    def test_the_relative_part_overtakes_the_floor_above_ten_cubic_millimetres(self) -> None:
        self.assertGreater(occ.volume_slack(11.0), 1.05e-6)


class ContractTests(unittest.TestCase):
    """The exported names, the exception hierarchy and the import rule. They need no OCP."""

    def test_the_public_names_are_the_three_edits_and_the_error(self) -> None:
        self.assertEqual(sorted(SAFE_ALL), ["SafeEditError", "safe_cut", "safe_fuse", "safe_intersect"])

    def test_a_refused_edit_is_a_value_error_but_not_a_geometry_error(self) -> None:
        self.assertTrue(issubclass(SafeEditError, ValueError))
        self.assertFalse(issubclass(SafeEditError, occ.GeometryError))
        self.assertTrue(issubclass(occ.GeometryError, ValueError))

    def test_a_face_below_one_thousandth_of_a_square_millimetre_is_a_sliver(self) -> None:
        self.assertEqual(check.SLIVER_FACE_MM2, 1e-3)

    def test_the_modules_import_without_loading_a_kernel(self) -> None:
        code = ("import sys; sys.path.insert(0, %r); import cadmodel.occ, cadmodel.safe, cadmodel.diff; "
                "bad = [m for m in ('OCP', 'cadquery', 'build123d') if m in sys.modules]; sys.exit(','.join(bad) or 0)"
                % str(SCRIPTS))
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-1000:])


class ProbeChecks:
    """The safe-edit cases in one kernel environment."""

    script: ClassVar[str]
    report: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / cls.script)],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr[-2000:])
        cls.report = json.loads(proc.stdout)

    def edit(self, name: str) -> dict[str, Any]:
        return self.report["edits"][name]

    def assertVolume(self, name: str, want: float, section: str = "edits") -> None:
        row = self.report[section][name]
        self.assertNotIn("error", row, row)
        self.assertAlmostEqual(row["value"], want, places=6, msg=name)

    def assertRefused(self, name: str, kind: str, message: str, calls: int | None = None) -> None:
        row = self.edit(name)
        self.assertEqual((row.get("type"), row.get("error")), (kind, message), name)
        if calls is not None:
            self.assertEqual(len(row["boolean_calls"]), calls, name)

    # accepted results

    def test_real_edits_return_the_expected_volumes(self) -> None:
        for name, want in (("cut_real", 500.0), ("cut_small_tool", 992.0), ("cut_two_tools", 400.0), ("fuse_real", 1500.0),
                           ("fuse_three", 2500.0), ("intersect_real", 500.0), ("intersect_three", 200.0)):
            with self.subTest(name=name):
                self.assertVolume(name, want)

    def test_results_on_a_bound_are_accepted(self) -> None:
        for name, want in (("cut_disjoint_tool", 1000.0), ("fuse_contained", 1000.0), ("fuse_disjoint", 2000.0),
                           ("intersect_contained", 8.0)):
            with self.subTest(name=name):
                self.assertVolume(name, want)

    def test_overlapping_members_of_an_input_count_once(self) -> None:
        self.assertVolume("compound_source_counted_once", 1500.0)
        self.assertVolume("compound_tool_counted_once", 1500.0)

    def test_the_inputs_are_not_modified(self) -> None:
        before, after = self.edit("inputs_after_fuse")
        self.assertEqual(before, after)

    def test_one_boolean_serves_a_cut_or_fuse_with_several_tools(self) -> None:
        """The safe.py module docstring states it: each operation runs one Boolean on copies of its inputs."""
        self.assertEqual(self.edit("cut_two_tools")["boolean_calls"], ["cut"])
        self.assertEqual(self.edit("fuse_three")["boolean_calls"], ["fuse"])

    # bounds

    def test_a_cut_cannot_remove_more_than_its_tools_hold(self) -> None:
        self.assertRefused("cut_below_lower", "SafeEditError", "safe_cut" + IMPOSSIBLE + "remaining volume 8 mm^3 is outside "
                           "[992, 1000] mm^3; no result was accepted")

    def test_a_cut_cannot_add_volume(self) -> None:
        self.assertRefused("cut_above_upper", "SafeEditError", "safe_cut" + IMPOSSIBLE + "remaining volume 1500 mm^3 is outside "
                           "[0, 1000] mm^3; no result was accepted")

    def test_the_cut_lower_bound_sums_the_volumes_of_overlapping_tools(self) -> None:
        self.assertVolume("cut_overlapping_tools_sum", 100.0)

    def test_the_cut_lower_bound_is_the_source_minus_the_tool_sum(self) -> None:
        self.assertRefused("cut_disjoint_tools_sum", "SafeEditError", "safe_cut" + IMPOSSIBLE + "remaining volume 50 mm^3 is "
                           "outside [100, 1000] mm^3; no result was accepted")

    def test_a_fuse_cannot_be_smaller_than_its_largest_input(self) -> None:
        self.assertRefused("fuse_below_largest", "SafeEditError", "safe_fuse" + IMPOSSIBLE + "union volume 500 mm^3 is outside "
                           "[1000, 2000] mm^3; no result was accepted")

    def test_a_fuse_between_the_smallest_and_the_largest_input_is_refused(self) -> None:
        self.assertRefused("fuse_below_largest_unequal", "SafeEditError", "safe_fuse" + IMPOSSIBLE +
                           "union volume 750 mm^3 is outside [1000, 1500] mm^3; no result was accepted")

    def test_a_fuse_cannot_be_larger_than_the_sum_of_its_inputs(self) -> None:
        self.assertRefused("fuse_above_sum", "SafeEditError", "safe_fuse" + IMPOSSIBLE + "union volume 2500 mm^3 is outside "
                           "[1000, 2000] mm^3; no result was accepted")

    def test_an_intersection_cannot_be_larger_than_its_smallest_input(self) -> None:
        self.assertRefused("intersect_above_smallest", "SafeEditError", "safe_intersect" + IMPOSSIBLE +
                           "intersection volume 1500 mm^3 is outside [0, 1000] mm^3; no result was accepted")

    def test_an_intersection_between_the_smallest_and_the_largest_input_is_refused(self) -> None:
        self.assertRefused("intersect_above_smallest_unequal", "SafeEditError", "safe_intersect" + IMPOSSIBLE +
                           "intersection volume 750 mm^3 is outside [0, 500] mm^3; no result was accepted")

    def test_every_step_of_an_intersection_is_checked(self) -> None:
        self.assertVolume("intersect_later_step_checked", 1.0)
        self.assertRefused("intersect_third_disjoint", "SafeEditError", "safe_intersect" + EMPTY)

    # slack

    def test_the_slack_is_relative_on_a_large_part(self) -> None:
        self.assertVolume("slack_relative_upper_inside", 1e9 + 50)
        self.assertVolume("slack_relative_lower_inside", 1e9 - 50)
        upper, lower = self.edit("slack_relative_upper_outside"), self.edit("slack_relative_lower_outside")
        self.assertEqual((upper["type"], lower["type"]), ("SafeEditError", "SafeEditError"))
        self.assertIn("safe_cut" + IMPOSSIBLE + "remaining volume", upper["error"])
        self.assertIn("safe_fuse" + IMPOSSIBLE + "union volume", lower["error"])

    def test_the_slack_has_a_floor_of_one_millionth_of_a_cubic_millimetre(self) -> None:
        self.assertVolume("slack_floor_upper_inside", 1 + 5e-7)
        self.assertVolume("slack_floor_lower_inside", 1 - 5e-7)
        self.assertIn("remaining volume 1.00001 mm^3 is outside [0.984375, 1] mm^3", self.edit("slack_floor_upper_outside")["error"])
        self.assertIn("union volume 0.999995 mm^3 is outside [1, 1.01563] mm^3", self.edit("slack_floor_lower_outside")["error"])

    def test_an_intersection_within_the_slack_of_the_inputs_is_empty(self) -> None:
        self.assertRefused("result_tiny_intersection", "SafeEditError", NO_OVERLAP)
        self.assertRefused("result_just_below_floor", "SafeEditError", NO_OVERLAP)
        self.assertVolume("result_just_above_floor", 0.05 ** 3)
        self.assertVolume("result_small_intersection", 1e-3)

    # refusals of the result

    def test_a_kernel_error_is_a_safe_edit_error_chained_from_it(self) -> None:
        for name, edit in (("error_cut", "safe_cut"), ("error_fuse", "safe_fuse"), ("error_intersect", "safe_intersect")):
            with self.subTest(edit=edit):
                self.assertRefused(name, "SafeEditError", f"{edit}: boom")
                self.assertEqual(self.edit(name)["cause"], "GeometryError")

    def test_other_errors_from_the_kernel_pass_through(self) -> None:
        self.assertRefused("error_other", "RuntimeError", "odd")

    def test_no_refusal_is_a_python_warning(self) -> None:
        rows = {**self.report["edits"], **self.report["occ"]}
        loud = {name: row["warnings"] for name, row in rows.items() if isinstance(row, dict) and row.get("warnings")}
        self.assertEqual(loud, {})

    def test_an_invalid_result_is_refused(self) -> None:
        row = self.edit("result_invalid")
        self.assertEqual(row["type"], "SafeEditError")
        self.assertRegex(row["error"], r"^safe_fuse returned an invalid B-rep \(.+\); no result was accepted$")

    def test_an_empty_result_is_refused_by_each_edit(self) -> None:
        for name, edit in (("result_empty_cut", "safe_cut"), ("result_empty_fuse", "safe_fuse"),
                           ("result_empty_intersect", "safe_intersect"), ("cut_everything", "safe_cut")):
            with self.subTest(edit=edit):
                self.assertRefused(name, "SafeEditError", edit + EMPTY)

    def test_disjoint_inputs_have_no_intersection(self) -> None:
        self.assertRefused("intersect_disjoint", "SafeEditError", "safe_intersect" + EMPTY)

    def test_a_result_whose_members_overlap_is_refused(self) -> None:
        self.assertRefused("result_overlapping_fuse", "SafeEditError",
                           "safe_fuse returned overlapping solid members (2000 mm^3 counted, 1500 occupied)")
        self.assertRefused("result_overlapping_cut", "SafeEditError",
                           "safe_cut returned overlapping solid members (2000 mm^3 counted, 1500 occupied)")

    # refusals of the inputs

    def test_a_value_that_is_no_shape_is_a_type_error_naming_its_role(self) -> None:
        for name, label, kind in (("type_source", "safe_cut source", "str"), ("type_tool_1", "safe_cut tool 1", "int"),
                                  ("type_tool_2", "safe_cut tool 2", "NoneType"), ("type_fuse_source", "safe_fuse source", "float"),
                                  ("type_fuse_input_2", "safe_fuse input 2", "object"),
                                  ("type_intersect_source", "safe_intersect source", "list"),
                                  ("type_intersect_input_1", "safe_intersect input 1", "bytes")):
            with self.subTest(name=name):
                self.assertRefused(name, "TypeError", f"{label} {KIND}{kind}", calls=0)

    def test_a_null_shape_is_refused_before_any_boolean(self) -> None:
        for name, label in (("null_source", "safe_cut source"), ("null_tool", "safe_cut tool 1"),
                            ("null_fuse_input_1", "safe_fuse input 1"), ("null_intersect_source", "safe_intersect source")):
            with self.subTest(name=name):
                self.assertRefused(name, "SafeEditError", f"{label} is a null shape", calls=0)

    def test_an_invalid_shape_is_refused_before_any_boolean(self) -> None:
        for name, label in (("invalid_source", "safe_cut source"), ("invalid_tool_2", "safe_cut tool 2"),
                            ("invalid_fuse_input_1", "safe_fuse input 1"), ("invalid_intersect_input_1", "safe_intersect input 1")):
            with self.subTest(name=name):
                row = self.edit(name)
                self.assertEqual((row["type"], len(row["boolean_calls"])), ("SafeEditError", 0))
                self.assertRegex(row["error"], rf"^{label} is not a valid B-rep \(.+\); repair it first$")

    def test_a_shape_without_a_solid_is_refused_before_any_boolean(self) -> None:
        for name, label in (("no_solid_source", "safe_cut source"), ("no_solid_tool", "safe_cut tool 1"),
                            ("no_solid_face", "safe_fuse input 1"), ("no_solid_intersect_source", "safe_intersect source")):
            with self.subTest(name=name):
                self.assertRefused(name, "SafeEditError", f"{label} contains no solid", calls=0)

    def test_an_inside_out_solid_is_refused_for_its_negative_volume(self) -> None:
        for name, label in (("inside_out_source", "safe_cut source"), ("inside_out_tool", "safe_cut tool 1"),
                            ("inside_out_fuse_input_1", "safe_fuse input 1"),
                            ("inside_out_intersect_source", "safe_intersect source")):
            with self.subTest(name=name):
                self.assertRefused(name, "SafeEditError", f"{label} has non-positive volume -1000 mm^3 (inside-out solid?)",
                                   calls=0)

    def test_the_first_bad_input_in_argument_order_is_the_one_reported(self) -> None:
        self.assertRefused("first_failure_wins", "SafeEditError", "safe_cut tool 1 is a null shape", calls=0)

    def test_too_few_inputs_is_a_plain_value_error_raised_first(self) -> None:
        for name, message in (("arity_cut", "safe_cut needs at least one tool"),
                              ("arity_fuse", "safe_fuse needs at least two shapes"),
                              ("arity_intersect", "safe_intersect needs at least two shapes")):
            with self.subTest(name=name):
                self.assertRefused(name, "ValueError", message, calls=0)

    # occ.boolean

    def test_boolean_returns_the_raw_result_of_each_operation(self) -> None:
        for name, want in (("bool_cut", 500.0), ("bool_fuse", 1500.0), ("bool_common", 500.0), ("bool_positional_fuzzy", 500.0)):
            with self.subTest(name=name):
                self.assertVolume(name, want, "occ")
                self.assertTrue(self.report["occ"][name]["raw"])

    def test_boolean_takes_its_tools_from_any_iterable(self) -> None:
        self.assertVolume("bool_generator_tools", 400.0, "occ")
        self.assertVolume("bool_tuple_tools", 400.0, "occ")

    def test_a_common_of_disjoint_shapes_is_empty_and_not_an_error(self) -> None:
        self.assertEqual(self.report["occ"]["bool_disjoint_common"], {"solids": 0, "volume": 0.0})

    def test_boolean_does_not_run_an_unknown_operation(self) -> None:
        self.assertIn("error", self.report["occ"]["bool_unknown_operation"])

    def test_boolean_leaves_its_inputs_unchanged(self) -> None:
        row = self.report["occ"]["bool_inputs_unchanged"]
        self.assertAlmostEqual(row["volume"], 1000.0, places=6)
        self.assertAlmostEqual(row["tool_volume"], 1000.0, places=6)
        self.assertEqual(row["faces"], [6, 6])

    def test_boolean_leaves_the_binary_brep_of_its_inputs_unchanged(self) -> None:
        self.assertEqual({name: ok for name, ok in self.report["occ"]["bool_inputs_bytes_unchanged"].items() if not ok}, {})

    # occ.occupied

    def test_occupied_counts_the_space_of_overlapping_members_once(self) -> None:
        for name, counted, occupied in (("overlap", 2000.0, 1500.0), ("contained", 1008.0, 1000.0), ("three", 3000.0, 2000.0),
                                        ("disjoint", 2000.0, 2000.0), ("touching", 2000.0, 2000.0)):
            with self.subTest(name=name):
                row = self.report["occ"][f"occupied_{name}"]
                self.assertAlmostEqual(row["counted"], counted, places=6)
                self.assertAlmostEqual(row["volume"], occupied, places=6)
                self.assertTrue(row["valid"])
                self.assertAlmostEqual(row["input_after"], counted, places=6)

    def test_occupied_returns_a_single_or_empty_shape_itself(self) -> None:
        row = self.report["occ"]["occupied_single"]
        self.assertTrue(row["same_object"])
        self.assertAlmostEqual(row["volume"], 1000.0, places=6)
        self.assertEqual(self.report["occ"]["occupied_none"], {"same_object": True, "volume": 0.0})

    def test_occupied_takes_the_fuzzy_value_positionally(self) -> None:
        self.assertAlmostEqual(self.report["occ"]["occupied_positional_fuzzy"]["volume"], 1500.0, places=6)

    # diff

    def test_diff_splits_identical_parts_into_shared_only(self) -> None:
        for name in ("identical", "identical_copies"):
            with self.subTest(name=name):
                row = self.report["diff"][name]
                self.assertEqual(row["status"], "unchanged")
                self.assertAlmostEqual(row["shared_mm3"], 1000.0, places=6)
                self.assertAlmostEqual(row["a_only_mm3"], 0.0, places=6)
                self.assertAlmostEqual(row["b_only_mm3"], 0.0, places=6)

    def test_diff_splits_disjoint_parts_into_their_own_volumes(self) -> None:
        row = self.report["diff"]["disjoint"]
        self.assertEqual(row["status"], "changed")
        self.assertAlmostEqual(row["shared_mm3"], 0.0, places=6)
        self.assertAlmostEqual(row["a_only_mm3"], 1000.0, places=6)
        self.assertAlmostEqual(row["b_only_mm3"], 1000.0, places=6)

    def test_diff_splits_overlapping_and_nested_parts(self) -> None:
        for name, want in (("overlap", [500.0, 500.0, 500.0]), ("contained", [8.0, 992.0, 0.0]), ("contains", [8.0, 0.0, 992.0])):
            with self.subTest(name=name):
                row = self.report["diff"][name]
                self.assertEqual(row["status"], "changed")
                self.assertEqual([round(row[k], 6) for k in ("shared_mm3", "a_only_mm3", "b_only_mm3")], want)

    def test_diff_counts_overlapping_members_of_a_part_once(self) -> None:
        row = self.report["diff"]["overlapping_members"]
        self.assertEqual(row["status"], "unchanged")
        self.assertAlmostEqual(row["shared_mm3"], 1500.0, places=6)

    def test_diff_of_an_empty_part_neither_raises_nor_invents_volume(self) -> None:
        for name, only in (("a_empty", "b_only_mm3"), ("b_empty", "a_only_mm3")):
            with self.subTest(name=name):
                row = self.report["diff"][name]
                self.assertNotIn("raised", row)
                if row["status"] != "error":
                    self.assertEqual(row["status"], "changed")
                    self.assertAlmostEqual(row["shared_mm3"], 0.0, places=6)
                    self.assertAlmostEqual(row[only], 1000.0, places=6)
        both = self.report["diff"]["both_empty"]
        self.assertNotIn("raised", both)
        if both["status"] != "error":
            self.assertEqual((both["status"], both["shared_mm3"], both["a_only_mm3"], both["b_only_mm3"]),
                             ("unchanged", 0.0, 0.0, 0.0))

    def test_diff_reports_any_failure_as_an_error_row_and_keeps_going(self) -> None:
        for name, text in (("error_text", "kernel said no"), ("error_no_text", "Opaque"), ("error_other_type", "'k'")):
            with self.subTest(name=name):
                row = self.report["diff"][name]
                self.assertEqual((row["status"], row["shared_mm3"], row["a_only_mm3"], row["b_only_mm3"], row["error"]),
                                 ("error", None, None, None, text))


@unittest.skipUnless(shutil.which("uv"), "uv is required for the OCP environment")
class RawOcpTests(ProbeChecks, unittest.TestCase):
    script = "safe_edit_probe.py"

    def test_a_raw_shape_gets_a_raw_shape_back(self) -> None:
        for name in ("cut_real", "fuse_real", "intersect_real"):
            self.assertTrue(self.edit(name)["raw"], name)


class WrapChecks(ProbeChecks):
    """The result comes back at the abstraction level of the first input."""

    raw_cases: ClassVar[tuple[str, ...]]

    def wrap(self, name: str) -> dict[str, Any]:
        return self.report["wrap"][name]

    def test_a_raw_first_input_gets_a_raw_result_whatever_the_tools(self) -> None:
        for name in self.raw_cases:
            with self.subTest(name=name):
                self.assertEqual(self.wrap(name)["type"], "TopoDS_Shape")
                self.assertAlmostEqual(self.wrap(name)["volume"], 500.0, places=6)

    def test_an_unknown_wrapper_of_a_raw_shape_gets_a_raw_result(self) -> None:
        self.assertEqual(self.wrap("unknown_wrapper")["type"], "TopoDS_Shape")


@unittest.skipUnless(shutil.which("uv"), "uv is required for the CadQuery environment")
class CadQueryTests(WrapChecks, unittest.TestCase):
    script = "safe_edit_cadquery_probe.py"
    raw_cases = ("raw_first", "raw_first_with_cadquery_tool")

    def test_a_shape_gets_a_cast_shape_back(self) -> None:
        for name in ("shape_cut", "shape_fuse", "shape_intersect", "compound_shape", "shape_with_workplane_tool"):
            with self.subTest(name=name):
                self.assertIn(self.wrap(name)["type"], ("Compound", "Solid"))
        self.assertAlmostEqual(self.wrap("shape_fuse")["volume"], 1500.0, places=6)
        self.assertAlmostEqual(self.wrap("shape_cut")["volume"], 500.0, places=6)

    def test_a_workplane_gets_one_new_workplane_with_one_object_back(self) -> None:
        for name, volume in (("workplane_cut", 500.0), ("workplane_fuse", 1500.0), ("workplane_intersect", 500.0),
                             ("workplane_with_shape_tool", 500.0), ("workplane_two_objects", 1500.0)):
            with self.subTest(name=name):
                self.assertEqual((self.wrap(name)["type"], self.wrap(name)["stack"]), ("Workplane", 1))
                self.assertAlmostEqual(self.wrap(name)["volume"], volume, places=6)

    def test_the_template_workplane_is_left_as_it_was(self) -> None:
        self.assertEqual(self.wrap("workplane_template_unchanged"),
                         {"stack_before": 1, "stack_after": 1, "same_object": False})


@unittest.skipUnless(shutil.which("uv"), "uv is required for the build123d environment")
class Build123dTests(WrapChecks, unittest.TestCase):
    script = "safe_edit_build123d_probe.py"
    raw_cases = ("raw_first_with_part_tool",)

    def test_a_part_or_a_builder_gets_a_part_back(self) -> None:
        for name, volume in (("part_cut", 500.0), ("part_fuse", 1500.0), ("part_intersect", 500.0), ("builder_cut", 500.0),
                             ("part_with_solid_tool", 500.0)):
            with self.subTest(name=name):
                self.assertEqual(self.wrap(name)["type"], "Part")
                self.assertAlmostEqual(self.wrap(name)["volume"], volume, places=6)

    def test_a_solid_or_a_compound_gets_a_shape_that_is_not_a_part_back(self) -> None:
        for name, volume in (("solid_cut", 500.0), ("solid_fuse", 1500.0), ("solid_intersect", 500.0), ("compound_cut", 500.0),
                             ("solid_with_part_tool", 500.0)):
            with self.subTest(name=name):
                self.assertIn(self.wrap(name)["type"], ("Compound", "Solid"))
                self.assertAlmostEqual(self.wrap(name)["volume"], volume, places=6)


if __name__ == "__main__":
    unittest.main()
