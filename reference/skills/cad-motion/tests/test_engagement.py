#!/usr/bin/env python3
"""The fitted-partner engagement classifier (scripts/engagement.py): which sampled positions of a path an
interference-type fit may exempt, and which are collisions. Pure arithmetic on shared-volume samples, no geometry.

Samples map the distance s back from the end of a leg (mm) to the shared volume with the fitted partner (mm3).
Run: python3 -m unittest discover -s skills/cad-motion/tests -p test_engagement.py
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

engagement = load("cad_motion_engagement", Path(__file__).resolve().parents[1] / "scripts" / "engagement.py")

HIT, CLEAR = 5.0, 0.0
THRESHOLD = 1e-3


def classify(samples: dict[float, float | None], *, cap: float | None, min_step: float = 0.5, tail: float = 0.0,
             engaged: bool = True):
    return engagement.classify(samples, tail_mm=tail, engaged=engaged, cap_mm=cap, min_step_mm=min_step,
                               threshold=THRESHOLD)


class ClassifyTests(unittest.TestCase):
    def test_a_run_ending_inside_the_cap_is_exempt_once_its_edge_is_resolved(self) -> None:
        samples = {0.0: HIT, 1.0: HIT, 2.0: HIT, 3.0: CLEAR}
        first = classify(samples, cap=3.0, min_step=1.0)
        self.assertEqual((first.needs, first.collisions, first.unknown), ([], [], False))
        self.assertEqual(first.exempt, frozenset({0.0, 1.0, 2.0}))
        wide = classify(samples, cap=3.0, min_step=0.5)
        self.assertEqual(wide.needs, [0.5, 1.5, 2.5])  # each segment of the run needs a midpoint
        refined = classify({**samples, 0.5: HIT, 1.5: HIT, 2.5: HIT}, cap=3.0, min_step=0.5)
        self.assertEqual((refined.needs, refined.collisions), ([], []))
        self.assertEqual(refined.extent, 2.5)

    def test_interference_past_the_cap_by_more_than_one_step_is_a_collision_at_that_sample(self) -> None:
        result = classify({0.0: HIT, 1.0: HIT, 2.0: HIT, 2.75: HIT, 3.0: CLEAR}, cap=2.0, min_step=0.5)
        self.assertEqual(result.collisions, [2.75])
        self.assertEqual(result.exempt, frozenset({0.0, 1.0, 2.0}))

    def test_interference_at_exactly_the_cap_plus_one_step_is_still_exempt(self) -> None:
        dense = {0.0: HIT, 0.5: HIT, 1.0: HIT, 1.5: HIT, 2.0: HIT, 2.5: HIT, 3.0: CLEAR}
        result = classify(dense, cap=2.0, min_step=0.5)
        self.assertEqual((result.needs, result.collisions), ([], []))
        self.assertEqual(result.exempt, frozenset({0.0, 0.5, 1.0, 1.5, 2.0, 2.5}))

    def test_a_run_without_a_declared_length_is_unknown_and_not_a_collision(self) -> None:
        result = classify({0.0: HIT, 1.0: HIT, 2.0: CLEAR}, cap=None)
        self.assertEqual((result.unknown, result.collisions, result.needs), (True, [], []))

    def test_interference_that_does_not_start_at_the_end_pose_is_a_collision_even_without_a_length(self) -> None:
        result = classify({0.0: CLEAR, 1.0: HIT, 2.0: HIT}, cap=None)
        self.assertEqual((result.collisions, result.unknown, result.exempt), ([1.0, 2.0], False, frozenset()))

    def test_a_leg_the_engagement_never_reached_exempts_nothing(self) -> None:
        result = classify({0.0: HIT, 1.0: HIT}, cap=10.0, engaged=False)
        self.assertEqual((result.collisions, result.exempt), ([0.0, 1.0], frozenset()))

    def test_a_gap_between_samples_ends_the_run_and_later_interference_collides(self) -> None:
        result = classify({0.0: HIT, 1.0: HIT, 1.5: CLEAR, 2.0: HIT, 3.0: CLEAR}, cap=3.0, min_step=1.0)
        self.assertEqual((result.needs, result.collisions), ([], [2.0]))
        self.assertEqual(result.exempt, frozenset({0.0, 1.0}))

    def test_the_cap_counts_from_the_installed_pose_across_legs(self) -> None:
        samples = {0.0: HIT, 1.0: HIT, 2.0: HIT, 3.0: HIT}  # a 3 mm leg with engagement at its far end
        inside = classify(samples, cap=8.0, min_step=1.0, tail=5.0)
        self.assertEqual((inside.collisions, inside.reached_start), ([], True))
        past = classify(samples, cap=8.0, min_step=1.0, tail=6.5)
        self.assertEqual(past.collisions, [3.0])
        self.assertEqual(past.exempt, frozenset({0.0, 1.0, 2.0}))

    def test_a_run_that_ends_inside_a_leg_does_not_reach_its_start(self) -> None:
        result = classify({0.0: HIT, 1.0: CLEAR, 2.0: CLEAR}, cap=5.0, min_step=1.0)
        self.assertEqual((result.reached_start, result.collisions), (False, []))

    def test_an_unmeasured_sample_inside_the_engagement_does_not_turn_later_interference_into_a_collision(self) -> None:
        result = classify({0.0: HIT, 1.0: None, 2.0: HIT}, cap=5.0, min_step=1.0)
        self.assertEqual((result.exempt, result.collisions, result.reached_start), (frozenset({0.0, 2.0}), [], True))

    def test_only_a_measured_clearance_ends_the_run_after_an_unmeasured_sample(self) -> None:
        result = classify({0.0: HIT, 1.0: None, 2.0: CLEAR, 3.0: HIT}, cap=5.0, min_step=1.0)
        self.assertEqual((result.exempt, result.collisions), (frozenset({0.0}), [3.0]))

    def test_an_unmeasured_sample_does_not_excuse_interference_past_the_cap(self) -> None:
        result = classify({0.0: HIT, 1.0: None, 2.0: HIT, 3.0: HIT}, cap=1.0, min_step=0.5)
        self.assertEqual((result.exempt, result.collisions), (frozenset({0.0}), [2.0, 3.0]))

    def test_an_unmeasured_end_pose_does_not_turn_the_interference_after_it_into_collisions(self) -> None:
        result = classify({0.0: None, 1.0: HIT, 2.0: HIT, 3.0: CLEAR}, cap=5.0, min_step=1.0)
        self.assertEqual((result.exempt, result.collisions), (frozenset({1.0, 2.0}), []))

    def test_an_unmeasured_midpoint_is_not_asked_for_again(self) -> None:
        result = classify({0.0: HIT, 0.5: None, 1.0: HIT}, cap=5.0, min_step=0.25)
        self.assertEqual((result.needs, result.collisions), ([], []))


if __name__ == "__main__":
    unittest.main()
