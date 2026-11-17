#!/usr/bin/env python3
"""layout_check.parse_transform: the SVG transform-list grammar, no FreeCAD needed.

Run: uv run --no-project --with-requirements harness/test-requirements.txt python -B -m unittest discover -s skills/cad-drawings/tests -p test_layout_transform.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import layout_check  # noqa: E402

from hypothesis import example, given, strategies as st  # noqa: E402

sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import property_profile  # noqa: E402,F401  (registers and loads the profile)

# magnitudes a drawing can reach (mm, degrees) and keep float round-off far below the tolerance used
coordinates = st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
factors = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
separators = st.sampled_from((" ", ",", ", ", " ,", "\t", "\n"))
FRAGMENTS = ("translate", "scale", "rotate", "matrix", "skewX", "(", ")", ",", " ", "1", "-2.5", ".5e3", "1e999", "nan", "-", "+", "x")


class EmptyArgumentTests(unittest.TestCase):
    def test_a_function_without_arguments_is_a_value_error_not_an_index_error(self) -> None:
        # SVG 1.1 7.6 / CSS Transforms 1 section 10: translate and scale take at least one number and
        # rotate takes one or three, so "translate()" is a grammar error; the parser's one error type is ValueError.
        for text in ("translate()", "translate( )", "scale()", "rotate()", "translate(1) scale()"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                layout_check.parse_transform(text)

    def test_a_wrong_number_of_arguments_is_a_value_error(self) -> None:
        # SVG 1.1 7.6: translate and scale take 1 or 2 numbers, rotate 1 or 3, matrix exactly 6
        for text in (
            "rotate(1 2)", "rotate(1 2 3 4)", "translate(1 2 3)", "scale(1 2 3)",
            "matrix(1 2 3 4 5)", "matrix(1 2 3 4 5 6 7)", "matrix()",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                layout_check.parse_transform(text)


def close(actual: tuple[float, ...], expected: tuple[float, ...]) -> bool:
    return all(abs(a - e) <= 1e-9 * max(1.0, abs(e)) for a, e in zip(actual, expected, strict=True))


class ParserProperties(unittest.TestCase):
    @given(st.one_of(st.text(), st.lists(st.sampled_from(FRAGMENTS), max_size=12).map("".join)))
    @example("translate()")
    @example("rotate(1e999)")
    def test_any_text_gives_a_six_number_matrix_or_a_value_error(self, text: str) -> None:
        # the documented contract of parse_transform: a matrix, or ValueError for what it cannot read
        try:
            matrix = layout_check.parse_transform(text)
        except ValueError:
            return
        self.assertEqual(len(matrix), 6)

    @given(coordinates, coordinates, factors, separators, separators)
    def test_translate_then_scale_is_the_matrix_s_0_0_s_a_b(
        self, a: float, b: float, s: float, inner: str, outer: str
    ) -> None:
        # SVG 1.1 7.6: a list multiplies left to right, so the rightmost function is applied to a point first;
        # x' = s*x + a and y' = s*y + b is therefore (s, 0, 0, s, a, b) in matrix(a b c d e f) order.
        matrix = layout_check.parse_transform(f"translate({a!r}{inner}{b!r}){outer}scale({s!r})")
        self.assertTrue(close(matrix, (s, 0.0, 0.0, s, a, b)), matrix)

    @given(coordinates, coordinates, factors)
    def test_scale_then_translate_scales_the_offset(self, a: float, b: float, s: float) -> None:
        # same rule, other order: x' = s*(x + a), y' = s*(y + b), matrix (s, 0, 0, s, s*a, s*b)
        matrix = layout_check.parse_transform(f"scale({s!r}) translate({a!r},{b!r})")
        self.assertTrue(close(matrix, (s, 0.0, 0.0, s, s * a, s * b)), matrix)

    @given(*[coordinates] * 6)
    def test_matrix_returns_its_six_numbers(self, a: float, b: float, c: float, d: float, e: float, f: float) -> None:
        # SVG 1.1 7.6: matrix(a b c d e f) is the matrix itself
        self.assertEqual(layout_check.parse_transform(f"matrix({a!r} {b!r} {c!r} {d!r} {e!r} {f!r})"), (a, b, c, d, e, f))

    @given(st.floats(min_value=-720, max_value=720), coordinates, coordinates, coordinates, coordinates)
    def test_rotation_about_a_centre_leaves_the_centre_fixed(
        self, angle: float, cx: float, cy: float, x: float, y: float
    ) -> None:
        # SVG 1.1 7.6: rotate(a cx cy) is translate(cx cy) rotate(a) translate(-cx -cy); it fixes (cx, cy) and
        # keeps the distance of every point from it.
        matrix = layout_check.parse_transform(f"rotate({angle!r} {cx!r} {cy!r})")
        self.assertTrue(close(layout_check._apply(matrix, cx, cy), (cx, cy)))
        px, py = layout_check._apply(matrix, x, y)
        self.assertAlmostEqual(
            ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5, delta=1e-6 * (1 + abs(x) + abs(y) + abs(cx) + abs(cy))
        )


if __name__ == "__main__":
    unittest.main()
