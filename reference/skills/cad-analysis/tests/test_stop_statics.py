#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Rigid statics of a hard stop: the design reaction is the applied moment over the smallest arm of the contact."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stop_statics import STOP_ARM_EPSILON_MM, Patch, reaction  # noqa: E402

# A 30 N handle load 80 mm from the pivot is a moment of 2400 N*mm. The expected figures below are worked
# by hand from M / arm: a strip with arms 7..13 mm (the latched stop) and one with arms 0..7 mm (the open stop).
# Uniform pressure: R = M / mean arm. A compliant stop, whose pressure grows with the arm:
# R = M * (integral of arm) / (integral of arm squared), 2400 * 60 / 618 and 2400 * 24.5 / 114.333.


class DesignReaction(unittest.TestCase):
    def test_a_latched_stop_is_bounded_by_its_nearest_edge(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(7.0, 13.0))
        self.assertEqual((result.status, result.outcome, result.severity), ("bounded", "pass", "info"))
        self.assertAlmostEqual(result.design_n, 342.857142857, places=6)
        self.assertGreaterEqual(result.design_n, 342.857)
        self.assertAlmostEqual(result.rigid_lower_n, 184.615384615, places=6)  # 2400 / 13
        self.assertAlmostEqual(result.uniform_n, 240.0, places=9)  # 2400 / 10
        self.assertAlmostEqual(result.compliant_n, 233.009708738, places=6)  # 144000 / 618
        self.assertAlmostEqual(result.pin_load_n, 372.857142857, places=6)  # reaction + the 30 N applied force

    def test_an_open_stop_whose_near_edge_is_on_the_axis_is_unbounded(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(0.0, 7.0))
        self.assertEqual((result.status, result.outcome, result.severity), ("unbounded", "unknown", "critical"))
        self.assertIsNone(result.design_n)
        self.assertIsNone(result.pin_load_n)
        self.assertAlmostEqual(result.uniform_n, 685.714285714, places=6)  # 2400 / 3.5
        self.assertAlmostEqual(result.compliant_n, 514.285714286, places=6)  # 58800 / 114.333
        self.assertIn("FEA contact case", result.message)
        self.assertIn("design record", result.message)

    def test_an_edge_on_the_axis_within_rounding_is_unbounded_on_both_sides_of_zero(self) -> None:
        # Posing and the Boolean carry rounding of order 1e-15 mm, so a smallest arm of -7e-16 or +7e-16 is the
        # same edge on the axis. Up to the epsilon (1e-6 mm, 1 nm) the reaction is unbounded.
        self.assertEqual(STOP_ARM_EPSILON_MM, 1e-6)
        for arm in (0.0, -7e-16, 7e-16, 1e-9, -1e-9, STOP_ARM_EPSILON_MM):
            with self.subTest(arm=arm):
                result = reaction(30.0, 80.0, Patch.strip(arm, 7.0))
                self.assertEqual((result.status, result.outcome), ("unbounded", "unknown"))

    def test_an_arm_above_the_epsilon_gives_a_finite_reaction(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(1e-3, 7.0))
        self.assertEqual((result.status, result.outcome), ("bounded", "pass"))
        self.assertAlmostEqual(result.design_n, 2400.0 / 1e-3, places=6)

    def test_an_arm_past_the_axis_is_unbounded_too(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(-2.0, 5.0))
        self.assertEqual((result.status, result.outcome), ("unbounded", "unknown"))
        self.assertAlmostEqual(result.rigid_lower_n, 480.0, places=9)  # 2400 / 5

    def test_a_patch_wholly_behind_the_axis_has_no_lower_bound_either(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(-5.0, -2.0))
        self.assertEqual((result.status, result.outcome, result.rigid_lower_n), ("unbounded", "unknown", None))
        self.assertIsNone(result.uniform_n)
        self.assertIsNone(result.compliant_n)

    def test_an_unbounded_stop_stays_unknown_whatever_is_recorded(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(0.0, 7.0), recorded_n=900.0)
        self.assertEqual((result.status, result.outcome), ("unbounded", "unknown"))


class RecordedLoad(unittest.TestCase):
    def test_a_recorded_figure_below_the_design_reaction_is_understated(self) -> None:
        result = reaction(30.0, 80.0, Patch.strip(7.0, 13.0), recorded_n=240.0)
        self.assertEqual((result.status, result.outcome, result.severity), ("understated", "fail", "major"))
        self.assertAlmostEqual(result.design_n, 342.857142857, places=6)
        self.assertIn("240", result.message)
        self.assertIn("342.9", result.message)

    def test_a_recorded_figure_at_or_above_the_design_reaction_passes(self) -> None:
        for recorded in (342.857142857, 343.0, 1000.0):
            with self.subTest(recorded=recorded):
                result = reaction(30.0, 80.0, Patch.strip(7.0, 13.0), recorded_n=recorded)
                self.assertEqual((result.status, result.outcome), ("bounded", "pass"))


class Inputs(unittest.TestCase):
    def test_a_force_or_load_arm_that_is_not_positive_is_refused(self) -> None:
        for force, arm in ((0.0, 80.0), (-1.0, 80.0), (30.0, 0.0), (30.0, float("nan"))):
            with self.subTest(force=force, arm=arm), self.assertRaises(ValueError):
                reaction(force, arm, Patch.strip(7.0, 13.0))


if __name__ == "__main__":
    unittest.main()
