#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The view tokens of a drawing intent: the scale string and the projection relation, no FreeCAD needed.

Run: uv run --no-project --with-requirements harness/test-requirements.txt python -B -m unittest discover -s skills/cad-drawings/tests -p test_view_tokens.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

from hypothesis import example, given, strategies as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import part_views  # noqa: E402
import property_profile  # noqa: E402,F401  (registers and loads the profile)

# drawing.schema.json $defs/scale: "auto" or two positive integers around a colon
terms = st.integers(min_value=1, max_value=10**6)
RELATIONS = ("front", "above", "below", "right_side", "left_side", "rear")


class ScaleTokenTests(unittest.TestCase):
    def test_a_scale_with_a_zero_term_is_a_value_error(self) -> None:
        # a scale is a ratio of positive terms; 1:0 would divide by zero and 0:1 would draw nothing
        for text in ("1:0", "0:1", "0:0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                part_views.parse_scale(text)

    def test_a_spelling_the_schema_forbids_is_a_value_error(self) -> None:
        # drawing.schema.json: ^[1-9][0-9]*:[1-9][0-9]*$ - no padding, sign, decimal point, exponent or non-ASCII digit
        for text in ("01:2", "1.5:2", "1:2.5", "1e2:1", "+1:2", "-1:2", " 1:2", "1:2 ", "1:2\n", "\uff11:2", "inf:1", "1:2:3", "1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                part_views.parse_scale(text)

    def test_auto_means_no_fixed_scale(self) -> None:
        self.assertIsNone(part_views.parse_scale("auto"))

    @given(terms, terms)
    @example(1, 2)
    def test_a_ratio_of_positive_integers_parses_to_their_quotient(self, a: int, b: int) -> None:
        self.assertEqual(part_views.parse_scale(f"{a}:{b}"), a / b)

    @given(st.text())
    @example("1:0")
    @example("inf:1")
    @example("-1:2")
    @example("1:2:3")
    @example("1")
    @example("")
    @example("1" + "0" * 400 + ":1")
    @example("1:1" + "0" * 400)
    def test_any_text_is_auto_a_positive_finite_ratio_or_a_value_error(self, text: str) -> None:
        # the contract of parse_scale: what the drawing schema allows, and a ValueError for everything else
        try:
            scale = part_views.parse_scale(text)
        except ValueError:
            return
        self.assertTrue(scale is None or (math.isfinite(scale) and scale > 0))


class RelationTokenTests(unittest.TestCase):
    @given(st.one_of(st.none(), st.sampled_from(RELATIONS), st.text()), st.one_of(st.sampled_from(("first_angle", "third_angle")), st.text()))
    def test_any_relation_and_projection_give_a_cell_or_none(self, relation: str | None, projection: str) -> None:
        cell = part_views.grid_cell(relation, projection)
        self.assertTrue(cell is None or (len(cell) == 2 and all(isinstance(n, int) for n in cell)))

    @given(st.sampled_from(RELATIONS))
    def test_third_angle_mirrors_first_angle_except_for_the_rear_view(self, relation: str) -> None:
        # ISO 5456-2: the two projection methods swap the views across the principal view (the view from
        # above sits below it in first angle and above it in third); front and rear keep their place.
        first = part_views.grid_cell(relation, "first_angle")
        third = part_views.grid_cell(relation, "third_angle")
        assert first is not None and third is not None
        if relation in ("front", "rear"):
            self.assertEqual(third, first)
        else:
            self.assertEqual(third, (-first[0], -first[1]))


if __name__ == "__main__":
    unittest.main()
