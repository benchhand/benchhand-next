#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Two-mesh stress study: reading .frd results, the settle rules, and the campaign's real mesh pairs.

The synthetic meshes are lines and clouds of nodes with a chosen stress, so each expected value is worked
out from the rules, not from the code. The real pairs come from the fast-bias campaign
(fb-2f0b457-r1 and fb-2f0b457-r2-finer on dev); `fixtures/trim_frd.py` documents how they were cut."""

from __future__ import annotations

import dataclasses
import gzip
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import fea_stress as fs

LENGTH = 100.0  # the bar runs from the fixed node at x=0 to the load node at x=100
H_COARSE, H_FINE = 1.0, 0.5  # exclusion cutoff = 3 x 1.0 = 3 mm, hot-spot tolerance 1 mm


def level(h, *, kept=200, excluded=20, peak=100.0, peak_x=50.0, disp=1.0, fallback=None,
          bad_stress=None, bad_disp=None):
    """A mesh of a node on each face, `excluded` nodes next to the fixed one, and `kept` nodes along the bar.

    One kept node sits at `peak_x` and carries `peak`; the others spread between x=10 and x=90 and carry
    half of it. The node on the load face has displacement `disp`, every other node half of it."""
    coords, stress, displacement = {1: (0.0, 0.0, 0.0), 2: (LENGTH, 0.0, 0.0)}, {}, {1: 0.0, 2: disp}
    for i in range(excluded):  # within 1 mm of the fixed node, with distinct positions
        coords[10 + i] = (1.0, 0.0001 * (i + 1), 0.0)
    for i in range(max(kept - 1, 0)):
        coords[100_000 + i] = (10.0 + 80.0 * i / max(kept - 2, 1), 0.0, 0.0)
    if kept:
        coords[99_999] = (peak_x, 0.0, 0.0)
    for node in coords:
        stress[node] = peak if node == 99_999 else peak / 2
        displacement.setdefault(node, disp / 2)
    if bad_stress is not None:
        stress[100_000] = bad_stress
    if bad_disp is not None:
        displacement[100_000] = bad_disp
    return fs.Level(h, fs.FrdResult(coords, stress, displacement), frozenset({1}), frozenset({2}), fallback)


def study(coarse_kw=None, fine_kw=None):
    # The fine mesh is denser: 2000 kept nodes against 200, so both floors hold unless a test lowers them.
    return fs.compare_levels(level(H_COARSE, **{"kept": 200, **(coarse_kw or {})}),
                             level(H_FINE, **{"kept": 2000, **(fine_kw or {})}))


def frd_text(nodes, disp, stress):
    def row(i, values):
        return " -1" + f"{i:10d}" + "".join(f"{v:12.5E}" for v in values)
    lines = ["    1C", "    2C                           %d                                     1" % len(nodes)]
    lines += [row(i, p) for i, p in nodes.items()] + [" -3", "  100CL  101 1.0", " -4  DISP        4    1"]
    lines += [row(i, v + (0.0,)) for i, v in disp.items()] + [" -3", "  100CL  101 1.0", " -4  STRESS      6    1"]
    lines += [row(i, v) for i, v in stress.items()] + [" -3", " 9999"]
    return "\n".join(lines) + "\n"


def without(lvl, block, node):
    """`lvl` with one node's entry removed from the `block` dictionary (coordinates, stress or displacement)."""
    r = lvl.result
    field = {"NODES": "coordinates", "STRESS": "von_mises", "DISP": "displacement"}[block]
    kept = {k: v for k, v in getattr(r, field).items() if k != node}
    return dataclasses.replace(lvl, result=dataclasses.replace(r, **{field: kept}))


def with_coordinates(lvl, node, point):
    r = lvl.result
    return dataclasses.replace(lvl, result=dataclasses.replace(r, coordinates={**r.coordinates, node: point}))


def level_as_frd(lvl):
    """Render a synthetic level as .frd text: displacement along x, uniaxial stress."""
    r = lvl.result
    return frd_text(r.coordinates, {n: (d, 0.0, 0.0) for n, d in r.displacement.items()},
                    {n: (v, 0.0, 0.0, 0.0, 0.0, 0.0) for n, v in r.von_mises.items()})


def drop_terminator(text, header):
    """`text` without the ` -3` line that ends the block opened by the line starting with `header`."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith(" -3"))
    return "\n".join(lines[:end] + lines[end + 1:]) + "\n"


def real_level(name, h, load_x):
    with gzip.open(FIXTURES / name, "rt") as handle:
        result = fs.read_frd(handle.read())
    return fs.Level(h, result, fs.plane_node_ids(result, "x", 0.0), fs.plane_node_ids(result, "x", load_x))


class ReadFrdTests(unittest.TestCase):
    def test_reads_coordinates_von_mises_and_displacement_magnitude(self) -> None:
        text = frd_text({1: (0.0, 0.0, 0.0), 2: (5.0, -2.0, 1.5)},
                        {1: (3.0, 4.0, 0.0), 2: (0.0, 0.0, 0.0)},
                        {1: (100.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0, 10.0, 0.0, 0.0)})
        result = fs.read_frd(text)
        self.assertEqual(result.coordinates, {1: (0.0, 0.0, 0.0), 2: (5.0, -2.0, 1.5)})
        self.assertAlmostEqual(result.displacement[1], 5.0)  # 3-4-5
        self.assertAlmostEqual(result.von_mises[1], 100.0)  # uniaxial: von Mises is the stress
        self.assertAlmostEqual(result.von_mises[2], 10.0 * math.sqrt(3.0))  # pure shear: sqrt(3) x tau

    def test_a_file_without_results_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            fs.read_frd("    1C\n    2C  1\n -1         1 0.00000E+00 0.00000E+00 0.00000E+00\n -3\n")

    def test_a_block_without_its_terminator_is_refused(self) -> None:
        text = level_as_frd(level(H_COARSE, kept=5, excluded=2))
        for header in ("    2C", " -4  DISP", " -4  STRESS"):
            with self.subTest(header):
                with self.assertRaises(fs.FrdError):
                    fs.read_frd(drop_terminator(text, header))

    def test_a_terminated_stress_block_with_a_short_record_is_refused_as_an_frd_error(self) -> None:
        # Five of the six components: the block is complete, so only the record itself is wrong.
        text = frd_text({1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
                        {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0)},
                        {1: (100.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (100.0, 0.0, 0.0, 0.0, 0.0)})
        with self.assertRaises(fs.FrdError):
            fs.read_frd(text)

    def test_a_stress_block_cut_off_by_the_end_of_the_file_is_refused(self) -> None:
        text = level_as_frd(level(H_COARSE, kept=5, excluded=2))
        cut = text[:text.index(" 9999")].rstrip("\n").rsplit("\n", 2)[0] + "\n"  # no terminator, last rows gone
        with self.assertRaises(fs.FrdError):
            fs.read_frd(cut)

    def test_plane_node_ids_select_by_coordinate(self) -> None:
        result = fs.FrdResult({1: (0.0, 1.0, 2.0), 2: (0.0000001, 5.0, 5.0), 3: (4.0, 0.0, 0.0)}, {}, {})
        self.assertEqual(fs.plane_node_ids(result, "x", 0.0, 1e-6), frozenset({1, 2}))
        self.assertEqual(fs.plane_node_ids(result, "x", 4.0), frozenset({3}))


class MalformedRecordTests(unittest.TestCase):
    """Every malformed record of a block `read_frd` parses raises FrdError, never IndexError or ValueError."""

    BLOCKS = (("node", "    2C"), ("DISP", " -4  DISP"), ("STRESS", " -4  STRESS"))
    FIELD = 12  # width of one value; a record is ` -1`, a 10-character node id, then values

    @staticmethod
    def corrupt(text, header, change):
        """`text` with the first record of the block opened by `header` replaced by `change(record)`."""
        lines = text.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(header))
        record = next(i for i in range(start, len(lines)) if lines[i].startswith(" -1"))
        lines[record] = change(lines[record])
        return "\n".join(lines) + "\n"

    def good(self):
        return frd_text({1: (0.0, 0.0, 0.0), 2: (1.0, 2.0, 3.0)},
                        {1: (1.0, 2.0, 2.0), 2: (0.0, 0.0, 0.0)},
                        {1: (5.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)})

    def assert_refused(self, block, header, change, label):
        with self.subTest(block=block, malformed=label):
            with self.assertRaisesRegex(fs.FrdError, block):
                fs.read_frd(self.corrupt(self.good(), header, change))

    def test_the_unchanged_text_parses(self) -> None:
        result = fs.read_frd(self.good())
        self.assertEqual(result.coordinates[2], (1.0, 2.0, 3.0))
        self.assertAlmostEqual(result.displacement[1], 3.0)
        self.assertAlmostEqual(result.von_mises[1], 5.0)

    def test_a_record_with_too_few_values_is_refused(self) -> None:
        f = self.FIELD
        for block, header in self.BLOCKS:
            wanted = 6 if block == "STRESS" else 3
            for have in (0, 1, wanted - 1):
                self.assert_refused(block, header, lambda r, have=have: r[:13 + have * f], f"{have} values")

    def test_a_value_that_is_not_a_number_is_refused(self) -> None:
        f = self.FIELD
        for block, header in self.BLOCKS:
            for position in (0, 2):
                self.assert_refused(block, header,
                                    lambda r, position=position: r[:13 + position * f] + "xxxxxxxxxxxx" + r[13 + (position + 1) * f:],
                                    f"value {position + 1}")

    def test_a_node_id_that_is_not_a_number_or_is_blank_is_refused(self) -> None:
        for block, header in self.BLOCKS:
            self.assert_refused(block, header, lambda r: r[:3] + "abcdefghij" + r[13:], "text id")
            self.assert_refused(block, header, lambda r: r[:3] + " " * 10 + r[13:], "blank id")

    def test_a_record_cut_off_inside_a_field_is_refused(self) -> None:
        for block, header in self.BLOCKS:
            self.assert_refused(block, header, lambda r: r[:-5], "cut inside the last field")

    def test_a_value_too_large_to_square_is_refused_with_its_block_and_node(self) -> None:
        # 1.0E+200 squared overflows a float: Python raises OverflowError for `**`, which must not escape.
        f = self.FIELD
        for block, header, position in (("DISP", " -4  DISP", 0), ("DISP", " -4  DISP", 2),
                                        ("STRESS", " -4  STRESS", 0), ("STRESS", " -4  STRESS", 3)):
            with self.subTest(block=block, position=position):
                text = self.corrupt(self.good(), header, lambda r: r[:13 + position * f] + "1.00000E+200" + r[13 + (position + 1) * f:])
                with self.assertRaisesRegex(fs.FrdError, rf"{block} record of node 1 "):
                    fs.read_frd(text)

    def three(self):
        return frd_text({1: (0.0, 0.0, 0.0), 2: (1.0, 2.0, 3.0), 3: (4.0, 5.0, 6.0)},
                        {1: (1.0, 2.0, 2.0), 2: (0.0, 0.0, 0.0), 3: (3.0, 0.0, 4.0)},
                        {1: (5.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
                         3: (2.0, 0.0, 0.0, 0.0, 0.0, 0.0)})

    @staticmethod
    def reid(text, header, which, node):
        """`text` with the `which`-th record (0-based) of the block opened by `header` renumbered to `node`."""
        lines = text.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(header))
        record = [i for i in range(start, len(lines)) if lines[i].startswith(" -1")][which]
        lines[record] = lines[record][:3] + f"{node:>10}" + lines[record][13:]
        return "\n".join(lines) + "\n"

    def test_a_node_id_repeated_inside_one_block_is_refused_with_its_block_and_id(self) -> None:
        for block, header in self.BLOCKS:
            for label, which, node in (("adjacent", 1, 1), ("non-adjacent", 2, 1), ("last two", 2, 2)):
                with self.subTest(block=block, repeat=label):
                    text = self.reid(self.three(), header, which, node)
                    with self.assertRaisesRegex(fs.FrdError, rf"{block} block repeats node {node}\b"):
                        fs.read_frd(text)

    def test_the_same_node_ids_in_different_blocks_are_accepted(self) -> None:
        result = fs.read_frd(self.three())
        self.assertEqual(set(result.coordinates), {1, 2, 3})
        self.assertEqual(set(result.displacement), {1, 2, 3})
        self.assertEqual(set(result.von_mises), {1, 2, 3})

    def test_the_checked_in_fixtures_parse(self) -> None:
        for path in sorted(FIXTURES.glob("*.frd.gz")):
            with self.subTest(path.name), gzip.open(path, "rt") as handle:
                result = fs.read_frd(handle.read())
                self.assertTrue(result.coordinates)
                self.assertEqual(set(result.von_mises), set(result.coordinates))

    def test_a_node_id_of_ten_digits_is_accepted_and_a_longer_or_infinite_one_is_not(self) -> None:
        widest = self.corrupt(self.good(), "    2C", lambda r: r[:3] + "9999999999" + r[13:])
        self.assertIn(9_999_999_999, fs.read_frd(widest).coordinates)
        for label, field in (("inf", "       inf"), ("nan", "       nan"), ("exponent", "     1.0e10")):
            with self.subTest(label):
                with self.assertRaisesRegex(fs.FrdError, "node record has no node id"):
                    fs.read_frd(self.corrupt(self.good(), "    2C", lambda r, field=field: r[:3] + field[:10] + r[13:]))

    def test_inf_and_nan_values_are_accepted_for_the_finiteness_screen_to_judge(self) -> None:
        f = self.FIELD
        def put(text, header, position, word):
            return self.corrupt(text, header, lambda r: r[:13 + position * f] + word.rjust(f) + r[13 + (position + 1) * f:])
        text = put(put(put(self.good(), "    2C", 0, "inf"), " -4  DISP", 1, "nan"), " -4  STRESS", 0, "inf")
        result = fs.read_frd(text)
        self.assertTrue(math.isinf(result.coordinates[1][0]))
        self.assertTrue(math.isnan(result.displacement[1]))
        self.assertFalse(math.isfinite(result.von_mises[1]))
        self.assertTrue(math.isinf(result.stress[1].sxx))

    def test_inf_and_nan_text_in_a_result_gives_unknown_not_a_number(self) -> None:
        f = self.FIELD
        def inject(lvl, header, word):
            lines = level_as_frd(lvl).splitlines()
            start = max(i for i, line in enumerate(lines) if line.startswith(header))
            row = next(i for i in range(start, len(lines)) if lines[i].startswith(f" -1{99_999:10d}"))
            lines[row] = lines[row][:13] + word.rjust(f) + lines[row][13 + f:]
            return dataclasses.replace(lvl, result=fs.read_frd("\n".join(lines) + "\n"))
        coarse, fine = level(H_COARSE, kept=200), level(H_FINE, kept=2000)
        for word in ("inf", "nan"):
            for header, reason in ((" -4  STRESS", "non_finite_stress"), (" -4  DISP", "non_finite_stress"),
                                   ("    2C", "non_finite_coordinates")):
                with self.subTest(word=word, header=header):
                    result = fs.compare_levels(inject(coarse, header, word), fine)
                    self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, (reason,)))
                    self.assertIsNone(result.sigma_mpa)

    def test_a_record_marker_without_an_id_is_refused(self) -> None:
        for block, header in self.BLOCKS:
            self.assert_refused(block, header, lambda r: r[:3], "marker only")

    def test_a_component_line_after_a_block_record_is_refused_with_its_block(self) -> None:
        # A ` -5` line describes a component, so it belongs before the first record; after one it would go unread.
        late = " -5  SXY         1    4    1    2"
        for block, header in self.BLOCKS:
            with self.subTest(block=block):
                text = self.corrupt(self.good(), header, lambda r: r + "\n" + late)
                with self.assertRaisesRegex(fs.FrdError, rf"{block} block has a component line after its first record"):
                    fs.read_frd(text)


class StressTensorTests(unittest.TestCase):
    """`read_frd` keeps each node's six stress components, in the order ccx 2.23 writes them."""

    # The component lines of a STRESS block as ccx 2.23 writes them (copied from the fixtures): the name, then the
    # tensor indices, so SZX is component (3, 1).
    CCX_COMPONENTS = (" -5  SXX         1    4    1    1", " -5  SYY         1    4    2    2",
                      " -5  SZZ         1    4    3    3", " -5  SXY         1    4    1    2",
                      " -5  SYZ         1    4    2    3", " -5  SZX         1    4    3    1")

    @staticmethod
    def with_components(text, components):
        """`text` with `components` as the ` -5` lines after every STRESS header."""
        out = []
        for line in text.splitlines():
            out.append(line)
            if line.startswith(" -4  STRESS"):
                out += components
        return "\n".join(out) + "\n"

    @staticmethod
    def one_node(stress):
        return frd_text({1: (0.0, 0.0, 0.0)}, {1: (0.0, 0.0, 0.0)}, {1: stress})

    @staticmethod
    def von_mises(t):
        """sqrt(3 J2) from the deviatoric stress: another form of the code's formula."""
        mean = (t.sxx + t.syy + t.szz) / 3.0
        deviator = ((t.sxx - mean) ** 2 + (t.syy - mean) ** 2 + (t.szz - mean) ** 2
                    + 2.0 * (t.sxy ** 2 + t.syz ** 2 + t.szx ** 2))
        return math.sqrt(1.5 * deviator)

    def test_each_component_is_read_into_the_field_ccx_names_it(self) -> None:
        # Each value encodes its tensor indices, so a component read into another field shows.
        text = self.with_components(self.one_node((11.0, 22.0, 33.0, 12.0, 23.0, 31.0)), self.CCX_COMPONENTS)
        self.assertEqual(fs.read_frd(text).stress[1]._asdict(),
                         {"sxx": 11.0, "syy": 22.0, "szz": 33.0, "sxy": 12.0, "syz": 23.0, "szx": 31.0})

    def test_the_tensor_of_every_fixture_node_gives_its_von_mises_stress(self) -> None:
        for path in sorted(FIXTURES.glob("*.frd.gz")):
            with self.subTest(path.name), gzip.open(path, "rt") as handle:
                result = fs.read_frd(handle.read())
                self.assertEqual(set(result.stress), set(result.von_mises))
                worst = max(abs(self.von_mises(t) - result.von_mises[n]) / max(result.von_mises[n], 1.0)
                            for n, t in result.stress.items())
                self.assertLess(worst, 1e-12)

    def test_the_last_stress_block_gives_the_tensor_as_it_gives_von_mises(self) -> None:
        first = frd_text({1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)}, {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0)},
                         {1: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0, 0.0, 0.0, 0.0)})
        last = ["  100CL  101 1.0", " -4  STRESS      6    1", " -1         1" + f"{7.0:12.5E}" + f"{0.0:12.5E}" * 5, " -3"]
        result = fs.read_frd(first.replace(" 9999\n", "\n".join(last) + "\n 9999\n"))
        self.assertEqual(result.stress, {1: (7.0, 0.0, 0.0, 0.0, 0.0, 0.0)})

    def test_a_stress_record_with_more_than_six_values_is_refused_with_its_node(self) -> None:
        text = frd_text({1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)}, {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0)},
                        {1: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 9.0)})
        with self.assertRaisesRegex(fs.FrdError, r"STRESS record of node 2 has 7 values, not 6"):
            fs.read_frd(text)

    def test_components_named_in_another_order_or_number_are_refused(self) -> None:
        sxx, syy, szz, sxy, syz, szx = self.CCX_COMPONENTS
        abaqus = tuple(line.replace(old, new) for line, (old, new) in zip(
            (sxx, syy, szz, sxy, szx, syz), (("SXX", "S11"), ("SYY", "S22"), ("SZZ", "S33"), ("SXY", "S12"),
                                             ("SZX", "S13"), ("SYZ", "S23"))))
        for label, components in (("SYZ and SZX swapped", (sxx, syy, szz, sxy, szx, syz)),
                                  ("shear first", (sxy, syz, szx, sxx, syy, szz)),
                                  ("Abaqus names", abaqus),
                                  ("five components", (sxx, syy, szz, sxy, syz)),
                                  ("seven components", (*self.CCX_COMPONENTS, szx))):
            with self.subTest(label):
                text = self.with_components(self.one_node((1.0, 2.0, 3.0, 4.0, 5.0, 6.0)), components)
                with self.assertRaisesRegex(fs.FrdError, "STRESS block names its components"):
                    fs.read_frd(text)


class SettleTests(unittest.TestCase):
    def test_an_interior_peak_that_converges_is_strength_eligible_and_reports_the_larger_peak(self) -> None:
        result = study({"peak": 99.0}, {"peak": 100.0})
        self.assertEqual(result.status, fs.SETTLED)
        self.assertEqual(result.sigma_mpa, 100.0)
        self.assertTrue(result.strength_eligible)
        self.assertIsNone(result.sigma_info_mpa)
        self.assertEqual(result.reasons, ())

    def test_the_larger_peak_is_reported_when_the_coarse_one_is_higher(self) -> None:
        self.assertEqual(study({"peak": 101.0}, {"peak": 100.0}).sigma_mpa, 101.0)

    def test_stress_change_of_exactly_two_percent_settles_and_just_above_does_not(self) -> None:
        self.assertEqual(study({"peak": 98.0}, {"peak": 100.0}).status, fs.SETTLED)
        over = study({"peak": 97.9}, {"peak": 100.0})  # 2.1%
        self.assertEqual(over.status, fs.UNKNOWN)
        self.assertEqual(over.reasons, ("stress_not_settled",))
        self.assertIsNone(over.sigma_mpa)
        self.assertIsNone(over.sigma_info_mpa)
        self.assertFalse(over.strength_eligible)

    def test_displacement_change_of_exactly_two_percent_settles_and_just_above_does_not(self) -> None:
        self.assertEqual(study({"disp": 98.0}, {"disp": 100.0}).status, fs.SETTLED)
        over = study({"disp": 97.9}, {"disp": 100.0})
        self.assertEqual((over.status, over.reasons), (fs.UNKNOWN, ("displacement_not_settled",)))

    def test_hot_spot_shift_of_exactly_h_coarse_settles_and_beyond_it_does_not(self) -> None:
        self.assertEqual(study({"peak_x": 50.0}, {"peak_x": 51.0}).status, fs.SETTLED)  # ~1 mm, mesh spacing
        moved = study({"peak_x": 50.0}, {"peak_x": 60.0})
        self.assertEqual((moved.status, moved.reasons), (fs.UNKNOWN, ("hot_spot_moved",)))

    def test_kept_share_of_ten_percent_on_the_coarse_mesh_passes_and_just_below_fails(self) -> None:
        # 1000 nodes in all (two faces, the excluded nodes and the kept ones): 100 kept is exactly 10%.
        self.assertEqual(study({"kept": 100, "excluded": 898}).status, fs.SETTLED)
        low = study({"kept": 99, "excluded": 899})
        self.assertEqual((low.status, low.reasons), (fs.UNKNOWN, ("kept_region_too_small",)))

    def test_kept_share_below_ten_percent_on_the_fine_mesh_fails(self) -> None:
        low = study(None, {"kept": 1000, "excluded": 9000})  # 1000 of 10002 nodes
        self.assertEqual((low.status, low.reasons), (fs.UNKNOWN, ("kept_region_too_small",)))

    def test_fine_mesh_with_1000_kept_nodes_passes_and_999_fails(self) -> None:
        self.assertEqual(study(None, {"kept": 1000}).status, fs.SETTLED)
        few = study(None, {"kept": 999})
        self.assertEqual((few.status, few.reasons), (fs.UNKNOWN, ("kept_region_too_small",)))

    def test_the_node_floor_does_not_apply_to_the_coarse_mesh(self) -> None:
        coarse = level(H_COARSE, kept=150, excluded=20)  # 150 kept nodes, well under 1000
        self.assertEqual(fs.compare_levels(coarse, level(H_FINE, kept=2000)).status, fs.SETTLED)

    def test_an_empty_kept_region_is_unknown_with_no_number(self) -> None:
        result = study({"kept": 0}, {"kept": 0})
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("kept_region_too_small",)))
        self.assertIsNone(result.sigma_mpa)
        self.assertIsNone(result.sigma_info_mpa)
        self.assertIn("0 nodes (0.0%)", result.message)

    def test_a_fallback_that_differs_between_levels_is_unknown(self) -> None:
        mismatch = study({"fallback": None}, {"fallback": 2})
        self.assertEqual((mismatch.status, mismatch.reasons), (fs.UNKNOWN, ("high_order_fallback_differs",)))
        self.assertEqual(study({"fallback": 2}, {"fallback": 2}).status, fs.SETTLED)

    def test_a_value_that_is_not_finite_is_unknown(self) -> None:
        for name, coarse_kw in (("nan stress", {"bad_stress": math.nan}), ("inf stress", {"bad_stress": math.inf}),
                                ("nan displacement", {"bad_disp": math.nan})):
            with self.subTest(name):
                result = study(coarse_kw)
                self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("non_finite_stress",)))
                self.assertIsNone(result.sigma_mpa)

    def test_a_coarse_mesh_that_is_not_coarser_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            fs.compare_levels(level(0.5), level(1.0))

    def test_the_reason_names_both_sizes_peaks_change_hot_spot_face_and_kept_region(self) -> None:
        message = study({"peak": 90.0, "peak_x": 60.0}, {"peak": 100.0, "peak_x": 60.0}).message
        for expected in ("h_coarse=1 mm", "h_fine=0.5 mm", "coarse=90 MPa", "fine=100 MPa", "change=10.00%",
                         "hot spot=(60.0, 0.0, 0.0) moved 0 mm", "nearest face (fine)=load face at 40 mm", "kept region coarse=200 nodes (",
                         "fine=2000 nodes (", "floor 10% on both, 1000 nodes on fine"):
            with self.subTest(expected):
                self.assertIn(expected, message)


class IncompleteInputTests(unittest.TestCase):
    """A result that lacks a node's stress or displacement, or has a non-finite position, is never settled."""

    def test_a_node_missing_from_the_stress_block_makes_the_study_unknown(self) -> None:
        # Node 99999 carries the peak on both meshes; without it both would report the half-peak 50 MPa.
        result = fs.compare_levels(without(level(H_COARSE, kept=200), "STRESS", 99_999),
                                   without(level(H_FINE, kept=2000), "STRESS", 99_999))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("incomplete_results",)))
        self.assertIsNone(result.sigma_mpa)
        self.assertIsNone(result.sigma_info_mpa)
        self.assertIn("incomplete results: block STRESS missing 1 nodes (coarse mesh)", result.message)
        self.assertIn("block STRESS missing 1 nodes (fine mesh)", result.message)
        self.assertIn("h_coarse=1 mm h_fine=0.5 mm", result.message)

    def test_a_node_missing_from_the_displacement_block_makes_the_study_unknown(self) -> None:
        result = fs.compare_levels(level(H_COARSE, kept=200), without(level(H_FINE, kept=2000), "DISP", 100_000))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("incomplete_results",)))
        self.assertIn("incomplete results: block DISP missing 1 nodes (fine mesh)", result.message)
        self.assertNotIn("(coarse mesh)", result.message)

    def test_a_stress_row_missing_from_the_frd_text_makes_the_study_unknown(self) -> None:
        def parse(lvl, drop=None):
            lines = level_as_frd(lvl).splitlines()
            if drop is not None:
                # the STRESS rows come last; drop the row of one node
                index = max(i for i, line in enumerate(lines) if line.startswith(f" -1{drop:10d}"))
                del lines[index]
            result = fs.read_frd("\n".join(lines) + "\n")
            return dataclasses.replace(lvl, result=result)
        result = fs.compare_levels(parse(level(H_COARSE, kept=200), 99_999), parse(level(H_FINE, kept=2000), 99_999))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("incomplete_results",)))
        self.assertIn("block STRESS missing 1 nodes", result.message)

    def test_a_position_that_is_not_finite_makes_the_study_unknown_without_an_error(self) -> None:
        for name, point in (("nan", (math.nan, 0.0, 0.0)), ("inf", (math.inf, 0.0, 0.0)),
                            ("-inf", (0.0, -math.inf, 0.0)), ("nan z", (1.0, 1.0, math.nan))):
            with self.subTest(name):
                result = fs.compare_levels(with_coordinates(level(H_COARSE, kept=200), 100_000, point),
                                           level(H_FINE, kept=2000))
                self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("non_finite_coordinates",)))
                self.assertIsNone(result.sigma_mpa)
                self.assertIn("h_coarse=1 mm h_fine=0.5 mm", result.message)
                self.assertIn("coarse mesh", result.message)


class ExtremeInputTests(unittest.TestCase):
    """`compare_levels` returns UNKNOWN, never raises, for mesh sizes and coordinates the grid cannot index."""

    NAN, INF = math.nan, math.inf

    def compare(self, coarse_h, fine_h, *, coarse_move=None, fine_move=None):
        coarse, fine = level(coarse_h, kept=200), level(fine_h, kept=2000)
        if coarse_move is not None:
            coarse = with_coordinates(coarse, 100_000, coarse_move)
        if fine_move is not None:
            fine = with_coordinates(fine, 100_000, fine_move)
        return fs.compare_levels(coarse, fine)

    def test_a_mesh_size_that_is_not_finite_and_positive_gives_unknown(self) -> None:
        cases = (("coarse zero", 0.0, 0.5), ("coarse negative", -1.0, 0.5), ("coarse nan", self.NAN, 0.5),
                 ("coarse inf", self.INF, 0.5), ("fine zero", 1.0, 0.0), ("fine negative", 1.0, -0.5),
                 ("fine nan", 1.0, self.NAN), ("fine inf", 1.0, self.INF), ("both zero", 0.0, 0.0))
        for name, coarse_h, fine_h in cases:
            with self.subTest(name):
                result = self.compare(coarse_h, fine_h)
                self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("invalid_mesh_size",)))
                self.assertIsNone(result.sigma_mpa)
                self.assertIsNone(result.sigma_info_mpa)
                self.assertIn(f"h_coarse={coarse_h:g} mm h_fine={fine_h:g} mm", result.message)

    def test_a_valid_mesh_size_that_is_not_coarser_is_still_refused_as_a_caller_error(self) -> None:
        with self.assertRaises(ValueError):
            self.compare(0.5, 1.0)
        with self.assertRaises(ValueError):
            self.compare(1.0, 1.0)

    def test_a_coordinate_far_larger_than_the_mesh_size_gives_unknown_not_an_error(self) -> None:
        # 1e305 / (4 x 2e-9) overflows to infinity inside the grid hash.
        result = self.compare(2e-9, 1e-9, coarse_move=(1e305, 0.0, 0.0))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("grid_out_of_range",)))
        self.assertIsNone(result.sigma_mpa)
        self.assertIn("coarse mesh", result.message)
        self.assertIn("h_coarse=2e-09 mm h_fine=1e-09 mm", result.message)

    def test_a_cell_index_beyond_float_precision_gives_unknown_even_when_it_is_finite(self) -> None:
        # 100 / (4 x 1e-15) = 2.5e16 cells, above 2**53: the quotient is finite but no longer exact.
        result = self.compare(1e-15, 5e-16)
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("grid_out_of_range",)))

    def test_the_largest_cell_index_is_accepted_and_one_binade_more_is_not(self) -> None:
        # With h_coarse = 1 the cell edge is 4, so the limit is 4 x 2**53 = 2**55.
        at_limit = self.compare(1.0, 0.5, coarse_move=(2.0 ** 55, 0.0, 0.0))
        self.assertNotIn("grid_out_of_range", at_limit.reasons)
        beyond = self.compare(1.0, 0.5, coarse_move=(2.0 ** 56, 0.0, 0.0))
        self.assertEqual((beyond.status, beyond.reasons), (fs.UNKNOWN, ("grid_out_of_range",)))
        negative = self.compare(1.0, 0.5, coarse_move=(0.0, -(2.0 ** 56), 0.0))
        self.assertEqual(negative.reasons, ("grid_out_of_range",))

    def test_a_coordinate_beyond_the_grid_on_the_fine_mesh_names_the_fine_mesh(self) -> None:
        result = self.compare(1.0, 0.5, fine_move=(2.0 ** 56, 0.0, 0.0))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("grid_out_of_range",)))
        self.assertIn("(fine mesh)", result.message)
        self.assertNotIn("(coarse mesh)", result.message)

    def test_a_cell_edge_that_overflows_gives_unknown(self) -> None:
        # 4 x 1e308 is not a float, so the grid has no finite cell edge.
        result = self.compare(1e308, 1.0)
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("grid_out_of_range",)))

    def test_a_zero_stress_peak_on_the_fine_mesh_does_not_divide_by_zero(self) -> None:
        both_zero = fs.compare_levels(level(H_COARSE, peak=0.0), level(H_FINE, kept=2000, peak=0.0))
        self.assertEqual(both_zero.status, fs.SETTLED)
        self.assertEqual(both_zero.sigma_mpa, 0.0)
        coarse_only = fs.compare_levels(level(H_COARSE, peak=5.0), level(H_FINE, kept=2000, peak=0.0))
        self.assertEqual(coarse_only.status, fs.UNKNOWN)
        self.assertIn("stress_not_settled", coarse_only.reasons)


class BoundaryTests(unittest.TestCase):
    """Peaks near a face, near the exclusion cutoff (3 mm), and beyond it."""

    def test_a_peak_just_beyond_the_cutoff_band_is_interior_and_strength_eligible(self) -> None:
        result = study({"peak_x": 4.25}, {"peak_x": 4.25})  # 4.25 > cutoff 3 + h_coarse 1
        self.assertEqual(result.status, fs.SETTLED)
        self.assertTrue(result.strength_eligible)

    def test_a_peak_within_h_coarse_of_the_cutoff_is_settled_away_from_support_and_not_strength(self) -> None:
        result = study({"peak": 99.0, "peak_x": 4.0}, {"peak": 100.0, "peak_x": 4.0})
        self.assertEqual(result.status, fs.SETTLED_AWAY_FROM_SUPPORT)
        self.assertEqual(result.sigma_info_mpa, 100.0)
        self.assertIsNone(result.sigma_mpa)
        self.assertFalse(result.strength_eligible)
        self.assertIn("governed by the exclusion boundary, the support stress is higher; see #209",
                      result.message)

    def test_the_hot_spot_is_not_compared_when_a_peak_is_on_the_cutoff(self) -> None:
        # The coarse peak is interior at x=50 and the fine one sits on the cutoff, 46 mm away.
        result = study({"peak_x": 50.0}, {"peak_x": 4.0})
        self.assertEqual(result.status, fs.SETTLED_AWAY_FROM_SUPPORT)

    def test_a_peak_on_the_cutoff_still_needs_every_convergence_criterion(self) -> None:
        stress = study({"peak": 97.0, "peak_x": 4.0}, {"peak": 100.0, "peak_x": 4.0})
        self.assertEqual((stress.status, stress.reasons), (fs.UNKNOWN, ("stress_not_settled",)))
        disp = study({"peak_x": 4.0, "disp": 97.0}, {"peak_x": 4.0, "disp": 100.0})
        self.assertEqual((disp.status, disp.reasons), (fs.UNKNOWN, ("displacement_not_settled",)))

    def test_a_peak_within_h_coarse_of_a_face_is_boundary_governed(self) -> None:
        # With K >= 1 every kept node is at least h_coarse from a face, so the guard is reached by lowering K:
        # a 0.5 mm cutoff keeps the nodes at 0.75 mm and 1.0 mm from the fixed node.
        with patch.object(fs, "K_EXCLUSION", 0.5):
            for x in (0.75, 1.0):
                with self.subTest(x=x):
                    result = study({"peak_x": x}, {"peak_x": x})
                    self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("boundary_governed",)))
                    self.assertIsNone(result.sigma_mpa)
            beyond = study({"peak_x": 1.25}, {"peak_x": 1.25})  # 1.25 > h_coarse: on the cutoff band, not at a face
            self.assertEqual(beyond.status, fs.SETTLED_AWAY_FROM_SUPPORT)


class CampaignPairTests(unittest.TestCase):
    def test_cantilever_4_5_to_3_mm_settles_away_from_support(self) -> None:
        # Campaign fb-2f0b457-r1 cantilever curved-4.5mm and curved-3mm: fixed plane x=0, load plane x=100.
        result = fs.compare_levels(real_level("cantilever_r1_4.5mm.frd.gz", 4.5, 100.0),
                                   real_level("cantilever_r1_3mm.frd.gz", 3.0, 100.0))
        self.assertEqual(result.status, fs.SETTLED_AWAY_FROM_SUPPORT)
        self.assertAlmostEqual(result.sigma_info_mpa, 103.9, places=1)
        self.assertIsNone(result.sigma_mpa)
        self.assertFalse(result.strength_eligible)
        self.assertAlmostEqual(result.delta_sigma, 0.0114, places=4)

    def test_truss_member_6_to_4_5_mm_is_unknown_at_13_93_percent(self) -> None:
        # Campaign fb-2f0b457-r1 curved-6mm and fb-2f0b457-r2-finer curved-4.5mm: fixed x=0, load x=320.
        result = fs.compare_levels(real_level("truss_r1_6mm.frd.gz", 6.0, 320.0),
                                   real_level("truss_r2_4.5mm.frd.gz", 4.5, 320.0))
        self.assertEqual((result.status, result.reasons), (fs.UNKNOWN, ("stress_not_settled",)))
        self.assertAlmostEqual(result.delta_sigma, 0.1393, places=4)
        self.assertIsNone(result.sigma_mpa)
        self.assertIsNone(result.sigma_info_mpa)
        for expected in ("h_coarse=6 mm", "h_fine=4.5 mm", "coarse=82.54 MPa", "fine=95.89 MPa", "change=13.93%",
                         "hot spot=(257.077, 8.929, 84.0)", "nearest face (fine)=load face at 62.9 mm",
                         "kept region coarse=2689 nodes (83.2%)"):
            with self.subTest(expected):
                self.assertIn(expected, result.message)


if __name__ == "__main__":
    unittest.main()
