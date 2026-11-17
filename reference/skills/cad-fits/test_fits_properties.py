#!/usr/bin/env python3
"""Property tests of the ISO 286 limits in fits.py over every covered size, grade and deviation letter.

Each property names the rule of the standard it asserts. ISO 286-1:2010 is the source; the tolerance
values below are its Table 1 (IT6 to IT11, up to 120 mm), typed apart from ../data/iso286.json so a typo
in the data shows up.

Run: uv run --no-project --with hypothesis==6.170.15 python -B scripts/ci_shards.py run rest skills/cad-fits/test_fits_properties.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from hypothesis import example, given, strategies as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
import property_profile  # noqa: E402,F401  (registers and loads the profile)

SPEC = importlib.util.spec_from_file_location("cad_fits_props", HERE / "scripts" / "fits.py")
assert SPEC and SPEC.loader
fits = importlib.util.module_from_spec(SPEC)
sys.modules["cad_fits_props"] = fits
SPEC.loader.exec_module(fits)

# ISO 286-1:2010 Table 1: size ranges "over A up to and including B" (mm) and IT tolerances (um).
RANGE_UPPER_MM = (3, 6, 10, 18, 30, 50, 80, 120)
IT_UM = {
    6: (6, 8, 9, 11, 13, 16, 19, 22),
    7: (10, 12, 15, 18, 21, 25, 30, 35),
    8: (14, 18, 22, 27, 33, 39, 46, 54),
    9: (25, 30, 36, 43, 52, 62, 74, 87),
    10: (40, 48, 58, 70, 84, 100, 120, 140),
    11: (60, 75, 90, 110, 130, 160, 190, 220),
}
GRADES = sorted(IT_UM)
SHAFT_LETTERS = ("c", "d", "f", "g", "h", "js", "k", "m", "n", "p", "s")
# clause 4 and Figure 3: shafts a to h lie at or below the zero line, k to zc at or above it
BELOW_ZERO = ("c", "d", "f", "g", "h")
ABOVE_ZERO = ("k", "m", "n", "p", "s")

sizes = st.decimals(min_value=Decimal("0.001"), max_value=120, places=3)
grades = st.sampled_from(GRADES)
letters = st.sampled_from(SHAFT_LETTERS)
BOUNDARIES = [Decimal(bound) for bound in RANGE_UPPER_MM] + [Decimal(b) + Decimal("0.001") for b in RANGE_UPPER_MM[:-1]]


def tolerance_um(size: Decimal, grade: int) -> int:
    return IT_UM[grade][next(i for i, upper in enumerate(RANGE_UPPER_MM) if size <= upper)]


class LimitProperties(unittest.TestCase):
    @given(sizes, grades, st.sampled_from(("H", *SHAFT_LETTERS)))
    @example(Decimal("3"), 6, "H")
    @example(Decimal("120"), 11, "s")
    def test_upper_deviation_is_above_lower_by_the_it_tolerance_of_the_size_range(
        self, size: Decimal, grade: int, letter: str
    ) -> None:
        # ISO 286-1 clause 3 (terms): tolerance = upper - lower limit = ES - EI (es - ei); Table 1 give
        # the IT value per grade and size range; the range is "over A up to and including B".
        limits = fits.tolerance_class(size, f"{letter}{grade}")
        self.assertGreater(limits.upper, limits.lower)
        self.assertEqual(limits.upper - limits.lower, tolerance_um(size, grade))

    @given(sizes, grades, st.sampled_from(("H", *SHAFT_LETTERS)))
    def test_the_limits_of_size_differ_by_the_tolerance(self, size: Decimal, grade: int, letter: str) -> None:
        # ISO 286-1 clause 3 (terms): the upper and lower limits of size are the nominal size plus ES/EI (es/ei).
        result = fits.evaluate(size, f"{letter}{grade}")
        side = result.get("hole") or result["shaft"]
        self.assertAlmostEqual(side["max_mm"] - side["min_mm"], tolerance_um(size, grade) / 1000, places=9)

    @given(sizes, grades)
    def test_the_basic_hole_starts_at_the_zero_line(self, size: Decimal, grade: int) -> None:
        # ISO 286-1 clause 4 and Figure 3: hole H has fundamental deviation EI = 0, so ES = +IT.
        hole = fits.tolerance_class(size, f"H{grade}")
        self.assertTrue(hole.is_hole)
        self.assertEqual((hole.lower, hole.upper), (0, tolerance_um(size, grade)))

    @given(sizes, grades, st.sampled_from(BELOW_ZERO))
    def test_shafts_c_to_h_lie_at_or_below_the_zero_line(self, size: Decimal, grade: int, letter: str) -> None:
        # ISO 286-1 clause 4 and Figure 3: for a to h the fundamental deviation is es <= 0.
        shaft = fits.tolerance_class(size, f"{letter}{grade}")
        self.assertFalse(shaft.is_hole)
        self.assertLessEqual(shaft.upper, 0)

    @given(sizes, grades, st.sampled_from(ABOVE_ZERO))
    def test_shafts_k_to_s_lie_at_or_above_the_zero_line(self, size: Decimal, grade: int, letter: str) -> None:
        # ISO 286-1 clause 4 and Figure 3: for k to zc the fundamental deviation is ei >= 0.
        self.assertGreaterEqual(fits.tolerance_class(size, f"{letter}{grade}").lower, 0)

    @given(sizes, grades)
    def test_js_is_symmetric_about_the_zero_line(self, size: Decimal, grade: int) -> None:
        # ISO 286-1 4.1.2.5 and Figure 9: js has es = +IT/2 and ei = -IT/2.
        shaft = fits.tolerance_class(size, f"js{grade}")
        self.assertEqual(shaft.upper, -shaft.lower)


class GradeProperties(unittest.TestCase):
    @given(sizes, st.sampled_from(GRADES[:-1]))
    def test_it_grows_with_the_grade_at_one_size(self, size: Decimal, grade: int) -> None:
        # ISO 286-1 clause 4, Table 1: for a size range the IT values increase with the grade number
        # (IT6 = 10i, IT7 = 16i, IT8 = 25i, ... with i > 0), so H's upper limit rises and h's lower falls.
        finer, coarser = grade, grade + 1
        self.assertLess(fits.tolerance_class(size, f"H{finer}").upper, fits.tolerance_class(size, f"H{coarser}").upper)
        self.assertGreater(fits.tolerance_class(size, f"h{finer}").lower, fits.tolerance_class(size, f"h{coarser}").lower)

    @given(sizes, st.sampled_from(("c", "d", "f", "g", "h")), grades, grades)
    def test_the_upper_deviation_of_shafts_c_to_h_does_not_depend_on_the_grade(
        self, size: Decimal, letter: str, one: int, other: int
    ) -> None:
        # ISO 286-1 clause 4: the fundamental deviation (here es) is independent of the IT grade.
        self.assertEqual(
            fits.tolerance_class(size, f"{letter}{one}").upper, fits.tolerance_class(size, f"{letter}{other}").upper
        )

    @given(sizes, st.sampled_from(("m", "n", "p", "s")), grades, grades)
    def test_the_lower_deviation_of_shafts_m_to_s_does_not_depend_on_the_grade(
        self, size: Decimal, letter: str, one: int, other: int
    ) -> None:
        # ISO 286-1 clause 4: the fundamental deviation (here ei) is independent of the IT grade.
        self.assertEqual(
            fits.tolerance_class(size, f"{letter}{one}").lower, fits.tolerance_class(size, f"{letter}{other}").lower
        )

    @given(sizes, st.sampled_from((6, 7)), st.sampled_from((8, 9, 10, 11)))
    def test_k_takes_ei_zero_above_it7_and_a_fixed_value_for_it4_to_it7(
        self, size: Decimal, within: int, above: int
    ) -> None:
        # ISO 286-1 Table 5: k is the one letter whose ei depends on the grade; it is 0 above IT7
        # and, for IT4 to IT7, the same value in every grade.
        self.assertEqual(fits.tolerance_class(size, f"k{above}").lower, 0)
        self.assertEqual(fits.tolerance_class(size, "k6").lower, fits.tolerance_class(size, f"k{within}").lower)

    @given(grades, st.integers(min_value=0, max_value=len(RANGE_UPPER_MM) - 2))
    def test_it_does_not_shrink_into_a_larger_size_range(self, grade: int, index: int) -> None:
        # ISO 286-1 clause 4: IT = k * i with i = 0.45 * cbrt(D) + 0.001 * D, rising with the geometric mean D of
        # the size range, so a larger range never has a smaller tolerance of the same grade.
        smaller, larger = Decimal(RANGE_UPPER_MM[index]), Decimal(RANGE_UPPER_MM[index + 1])
        self.assertLessEqual(
            fits.tolerance_class(smaller, f"H{grade}").upper, fits.tolerance_class(larger, f"H{grade}").upper
        )

    @given(grades, st.sampled_from(BOUNDARIES))
    def test_a_size_on_a_range_bound_belongs_to_the_range_that_ends_there(self, grade: int, size: Decimal) -> None:
        # ISO 286-1 Table 1: ranges are "over A up to and including B".
        self.assertEqual(fits.tolerance_class(size, f"H{grade}").upper, tolerance_um(size, grade))


class FitProperties(unittest.TestCase):
    @given(sizes, grades, grades, letters)
    def test_the_fit_type_agrees_with_the_signs_of_the_clearances(
        self, size: Decimal, hole_grade: int, shaft_grade: int, letter: str
    ) -> None:
        # ISO 286-1 3.3.1-3.3.2: clearance fit when the smallest clearance is >= 0 (hole never smaller than
        # shaft), interference fit when the largest clearance is <= 0, transition fit otherwise.
        # Clearances are worked out from the limits of size, not from the deviations fits.py combines.
        result = fits.evaluate(size, f"H{hole_grade}/{letter}{shaft_grade}")
        hole, shaft = result["hole"], result["shaft"]
        largest = Decimal(str(hole["max_mm"])) - Decimal(str(shaft["min_mm"]))
        smallest = Decimal(str(hole["min_mm"])) - Decimal(str(shaft["max_mm"]))
        expected = "clearance" if smallest >= 0 else "interference" if largest <= 0 else "transition"
        self.assertEqual(result["fit"]["type"], expected)
        self.assertEqual(Decimal(str(result["fit"]["max_clearance_um"])), largest * 1000)
        self.assertEqual(Decimal(str(result["fit"]["min_clearance_um"])), smallest * 1000)

    @given(sizes, grades, grades, letters)
    def test_the_variation_of_the_fit_is_the_sum_of_the_two_tolerances(
        self, size: Decimal, hole_grade: int, shaft_grade: int, letter: str
    ) -> None:
        # ISO 286-1 clause 3 (fits): max clearance - min clearance = (ES - ei) - (EI - es) = T_hole + T_shaft.
        fit = fits.evaluate(size, f"H{hole_grade}/{letter}{shaft_grade}")["fit"]
        self.assertGreater(fit["max_clearance_um"], fit["min_clearance_um"])
        self.assertEqual(
            Decimal(str(fit["max_clearance_um"])) - Decimal(str(fit["min_clearance_um"])),
            tolerance_um(size, hole_grade) + tolerance_um(size, shaft_grade),
        )

    @given(sizes, grades, grades)
    def test_the_basic_hole_on_the_basic_shaft_never_has_interference(
        self, size: Decimal, hole_grade: int, shaft_grade: int
    ) -> None:
        # ISO 286-1 3.3.1 with clause 4: H has EI = 0 and h has es = 0, so the smallest clearance is exactly 0
        # and the fit is a clearance fit.
        fit = fits.evaluate(size, f"H{hole_grade}/h{shaft_grade}")["fit"]
        self.assertEqual(fit["min_clearance_um"], 0)
        self.assertEqual(fit["type"], "clearance")


if __name__ == "__main__":
    unittest.main()
