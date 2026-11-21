#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Strength near a support or a load: linearised stress on SCLs a zone's depth inside the part, each gated by a
section-resultant cross-check.

The meshes are C3D10 bars built by test_fea_linearise.plate. Each node carries the stress of Euler-Bernoulli beam
theory with its parabolic shear, a quadratic field a C3D10 mesh holds exactly, so every expected value below comes
from the beam formulae, not from the code. The bar is 30 mm long (x), 10 mm wide (y) and 5 mm deep (z), clamped at
x = 0 and loaded with P = 50 N in -z over the nodes at x = 30. With I = 10 * 5^3 / 12 = 104.1667 mm^4, the moment at
x is M = P (30 - x) and the bending stress at the surfaces (z = 0 and 5) is M * 2.5 / I. The shear is
tau = -P (2.5^2 - zeta^2) / (2 I) on the x face, zeta = z - 2.5, which integrates to -P over the section.

Mesh size h = 1 mm, so the zone is max(t_local, 3 h) = max(5, 3) = 5 mm deep: the SCLs sit at x = 5 (root) and
x = 25 (load). Root: M = 1250 N mm, bending 30.0 MPa, mean shear 1.0 MPa. Load: M = 250 N mm, bending 6.0 MPa.
The membrane plus bending von Mises stress is sqrt(bending^2 + 3 * shear^2): sqrt(903) = 30.0500 at the root and
sqrt(39) = 6.2450 at the load.
"""

from __future__ import annotations

import gzip
import importlib.util
import math
import shutil
import sys
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent / "scripts"))

# The imports below need scripts/ on sys.path first, so they cannot sit above the sys.path line (E402).
import fea_conditions as conditions  # noqa: E402
import fea_near_support as ns  # noqa: E402
import fea_stress as fs  # noqa: E402
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


linearise_tests = _sibling("test_fea_linearise")

Point = tuple[float, float, float]
LENGTH, WIDTH, DEPTH = 30.0, 10.0, 5.0
LOAD = 50.0
INERTIA = WIDTH * DEPTH ** 3 / 12.0


def bar(cells_x: int = 30) -> tuple[dict[int, Point], dict[int, study.Element]]:
    return linearise_tests.plate("C3D10", (cells_x, 2, 2), (LENGTH, WIDTH, DEPTH))


def beam_field(load: float = LOAD, bending: float = 1.0, shear: float = 1.0
               ) -> Callable[[Point], tuple[float, float, float, float, float, float]]:
    """The beam-theory tensor at a point, in the order ccx writes it; `bending` and `shear` scale the two parts."""
    def field(p: Point) -> tuple[float, float, float, float, float, float]:
        zeta = p[2] - DEPTH / 2
        sxx = bending * load * (LENGTH - p[0]) * zeta / INERTIA
        szx = -shear * load * (DEPTH ** 2 / 4 - zeta ** 2) / (2 * INERTIA)
        return (sxx, 0.0, 0.0, 0.0, 0.0, szx)
    return field


def result_of(coordinates: Mapping[int, Point], field: Callable[[Point], tuple[float, ...]]) -> fs.FrdResult:
    return fs.FrdResult(dict(coordinates), {}, {}, {n: fs.StressTensor(*field(p)) for n, p in coordinates.items()})


def nodes_at(coordinates: Mapping[int, Point], axis: int, value: float) -> frozenset[int]:
    return frozenset(n for n, p in coordinates.items() if abs(p[axis] - value) < 1e-9)


def force_on(nodes: frozenset[int], fz: float) -> dict[int, tuple[float, float, float]]:
    """`fz` newtons in z, shared equally by `nodes`."""
    return {n: (0.0, 0.0, fz / len(nodes)) for n in nodes}


class Cantilever(unittest.TestCase):
    """The bar of the module docstring, clamped at x = 0 and loaded at x = 30."""

    def setUp(self) -> None:
        self.coordinates, self.elements = bar()
        self.fixed = nodes_at(self.coordinates, 0, 0.0)
        self.loads = [force_on(nodes_at(self.coordinates, 0, LENGTH), -LOAD)]

    def assess(self, field: Callable[[Point], tuple[float, ...]] | None = None, **kwargs: Any) -> ns.NearSupport:
        given: dict[str, Any] = {"fixed": self.fixed, "loads": self.loads, "h_coarse": 1.0, "h_mesh": 1.0}
        given.update(kwargs)
        return ns.assess(result_of(self.coordinates, field or beam_field()), self.elements, **given)

    def section(self, found: ns.NearSupport, face: str) -> ns.Section:
        return next(s for s in found.sections if s.face == face)

    def test_the_root_section_gives_the_beam_theory_membrane_plus_bending_stress(self) -> None:
        found = self.assess()
        self.assertEqual((found.status, found.reasons), ("linearised", ()))
        root = self.section(found, "fixed")
        self.assertAlmostEqual(root.section_mm, 5.0, places=9)
        self.assertAlmostEqual(root.sigma_mpa, math.sqrt(30.0 ** 2 + 3 * 1.0 ** 2), places=3)

    def test_a_load_face_is_treated_as_a_fixed_face_with_its_own_section(self) -> None:
        found = self.assess()
        tip = self.section(found, "load")
        self.assertAlmostEqual(tip.section_mm, 25.0, places=9)
        self.assertAlmostEqual(tip.sigma_mpa, math.sqrt(6.0 ** 2 + 3 * 1.0 ** 2), places=3)

    def test_the_strength_stress_is_the_largest_of_the_sections_and_no_shape_factor_credits_the_bending(self) -> None:
        # 1.5 times the root bending would give 20 MPa from 30.05: the full 30.05 is the figure.
        found = self.assess()
        assert found.sigma_mpa is not None
        self.assertAlmostEqual(found.sigma_mpa, 30.0500, places=3)

    def test_the_peak_stress_at_the_section_ends_is_reported_and_is_not_the_strength_stress(self) -> None:
        # The exact field is linear in the bending, so the quadratic remainder is the shear's: at a surface the
        # total von Mises is the bending alone, 30.0 MPa, below the linearised 30.05, and it is reported as is.
        root = self.section(self.assess(), "fixed")
        self.assertAlmostEqual(root.peak_mpa, 30.0, places=3)

    def test_the_residuals_of_an_exact_field_are_zero(self) -> None:
        for section in self.assess().sections:
            with self.subTest(section.face):
                self.assertLess(section.force_residual, 1e-4)
                self.assertLess(section.moment_residual, 1e-4)

    def test_the_cross_check_passes_a_moment_inside_its_tolerance_and_refuses_one_outside(self) -> None:
        # The moment scale is sum |r x f|, about 0.8% above P * 25 at the root, so 4% passes and 6% does not.
        self.assertEqual(self.assess(beam_field(bending=1.04)).status, "linearised")
        refused = self.assess(beam_field(bending=1.06))
        self.assertEqual((refused.status, refused.reasons, refused.sigma_mpa), ("unknown", ("cross_check_failed",), None))

    def test_the_cross_check_refuses_a_section_whose_shear_does_not_carry_the_load(self) -> None:
        # Half the shear: the section force is 25 N against 50 N applied, 50% of the force scale.
        refused = self.assess(beam_field(shear=0.5))
        self.assertEqual((refused.status, refused.reasons), ("unknown", ("cross_check_failed",)))
        self.assertIn("force", refused.message)

    def test_a_cross_check_failure_names_the_face_and_both_residuals(self) -> None:
        refused = self.assess(beam_field(bending=1.2))
        self.assertIn("fixed face", refused.message)
        self.assertRegex(refused.message, r"moment residual 1[89]\.\d+%")

    def test_a_part_with_a_second_fixed_face_is_statically_indeterminate_and_abstains(self) -> None:
        # Clamped at both ends and loaded across the mid-plane x = 15: the reactions are not statics' to give.
        self.fixed = nodes_at(self.coordinates, 0, 0.0) | nodes_at(self.coordinates, 0, LENGTH)
        self.loads = [force_on(nodes_at(self.coordinates, 0, 15.0), -LOAD)]
        found = self.assess()
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("statically_indeterminate",), None))

    def test_a_refusal_of_the_linearisation_is_unknown_with_its_reason_and_never_a_figure(self) -> None:
        # No element between x = 4 and 6: the root SCL at x = 5 runs through a void.
        self.elements = {i: e for i, e in self.elements.items()
                         if not 4.0 < sum(self.coordinates[n][0] for n in e.nodes[:4]) / 4 < 6.0}
        found = self.assess()
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("scl_outside_mesh",), None))

    def test_a_result_without_a_stress_tensor_is_unknown_with_the_linearisations_reason(self) -> None:
        bare = fs.FrdResult(dict(self.coordinates), {}, {}, {})
        found = ns.assess(bare, self.elements, fixed=self.fixed, loads=self.loads, h_coarse=1.0, h_mesh=1.0)
        self.assertEqual((found.status, found.reasons), ("unknown", ("scl_tensor_missing",)))

    def test_two_load_entries_on_one_node_and_degree_of_freedom_abstain(self) -> None:
        node = next(iter(self.loads[0]))
        self.loads = [*self.loads, {node: (0.0, 0.0, -1.0)}]
        self.assertEqual(self.assess().reasons, ("load_nodes_overlap",))

    def test_a_non_finite_applied_force_never_linearises(self) -> None:
        # A nan has no residual to compare: it must abstain, not slip through a comparison that is false for nan.
        node = next(iter(self.loads[0]))
        found = self.assess(loads=[{**self.loads[0], node: (0.0, 0.0, math.nan)}])
        self.assertEqual((found.status, found.sigma_mpa), ("unknown", None))
        self.assertEqual(found.reasons, ("load_not_finite",))

    def test_a_nan_moment_residual_beside_a_clean_force_residual_abstains(self) -> None:
        # hypot keeps a 3e153 N load finite, so no honest field reaches nan; the comparison is pinned by giving it
        # one. max(0.0, nan) is 0.0, which would pass.
        with patch.object(ns, "_residuals", return_value=(0.0, math.nan)):
            found = self.assess()
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("cross_check_failed",), None))

    def test_a_node_or_mesh_size_that_is_not_finite_abstains(self) -> None:
        # min() and max() over a nan depend on the order of their arguments, so the inputs are screened first.
        self.coordinates[next(iter(self.coordinates))] = (math.nan, 0.0, 0.0)
        self.assertEqual(self.assess().reasons, ("mesh_not_finite",))
        self.coordinates, self.elements = bar()
        self.fixed = nodes_at(self.coordinates, 0, 0.0)
        self.assertEqual(self.assess(h_coarse=math.nan).reasons, ("mesh_not_finite",))

    def test_a_case_without_an_applied_force_abstains(self) -> None:
        self.loads = [{n: (0.0, 0.0, 0.0) for n in self.loads[0]}]
        self.assertEqual(self.assess().reasons, ("no_applied_load",))

    def test_a_fixed_face_that_is_not_flat_abstains(self) -> None:
        stray = next(n for n, p in self.coordinates.items() if abs(p[0] - 1.0) < 1e-9)
        self.fixed = self.fixed | {stray}
        self.assertEqual(self.assess().reasons, ("support_not_axis_planar",))

    def test_a_part_shorter_than_the_zone_finds_no_section(self) -> None:
        self.assertEqual(self.assess(h_coarse=20.0).reasons, ("section_outside_part",))

    def axial_tip_load(self) -> list[dict[int, tuple[float, float, float]]]:
        """50 N along x on the tip centre, with a zero entry on every other tip node, as FreeCAD writes a face. The
        load has no moment about any point of the line of action, so the nodal moment scale is exactly zero."""
        tip = nodes_at(self.coordinates, 0, LENGTH)
        centre = next(n for n in tip if self.coordinates[n][1:] == (WIDTH / 2, DEPTH / 2))
        return [{n: (LOAD if n == centre else 0.0, 0.0, 0.0) for n in tip}]

    def test_zero_moment_scale_rejects_unbalanced_bending(self) -> None:
        # 1 MPa over the 50 mm^2 section balances the 50 N exactly. The bending 2 MPa/mm * (z - 2.5) adds a couple
        # sigma_b t^2 / 6 per unit width, 5 * 25 / 6 * 10 = 208.3 N mm, to a load that has no moment: 208.3 against
        # the floor F * L = 50 * 10 = 500 N mm is 41.7%, over the 5% limit.
        found = self.assess(lambda p: (1.0 + 2.0 * (p[2] - DEPTH / 2), 0, 0, 0, 0, 0), loads=self.axial_tip_load())
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("cross_check_failed",), None))
        self.assertRegex(found.message, r"moment residual 4[01]\.\d%")

    def test_zero_moment_scale_still_accepts_a_balanced_membrane(self) -> None:
        found = self.assess(lambda p: (1.0, 0, 0, 0, 0, 0), loads=self.axial_tip_load())
        self.assertEqual((found.status, found.reasons), ("linearised", ()))

    def eccentric_tip_load(self, shift: float) -> list[dict[int, tuple[float, float, float]]]:
        """The tip load of the cantilever, 50 N in -z, with its resultant `shift` mm off the tip centre along y: the
        nodal weights 1 + a (y - 5) with a = shift / mean((y - 5)^2) move the centroid by exactly `shift`."""
        tip = sorted(nodes_at(self.coordinates, 0, LENGTH))
        offsets = [self.coordinates[n][1] - WIDTH / 2 for n in tip]
        slope = shift / (sum(o * o for o in offsets) / len(tip))
        return [{n: (0.0, 0.0, -LOAD * (1 + slope * o) / len(tip)) for n, o in zip(tip, offsets)}]

    def test_small_torsion_abstains_below_aggregate_tolerance(self) -> None:
        # 0.1 mm of eccentricity is 5 N mm of torque about the section normal, 0.4% of the 1250 N mm root moment, so
        # the aggregate residual passes. The torque floor is 1e-3 * F * L = 0.5 N mm.
        found = self.assess(loads=self.eccentric_tip_load(0.1))
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("torsion_on_section",), None))
        self.assertRegex(found.message, r"torque 5 N mm about the section normal")

    def twisting(self, gradient: float) -> Callable[[Point], tuple[float, ...]]:
        """The beam field plus a shear tau_xz = gradient * (y - 5) MPa, which the applied loads do not balance."""
        base = beam_field()

        def field(p: Point) -> tuple[float, ...]:
            sxx, syy, szz, sxy, syz, szx = base(p)
            return (sxx, syy, szz, sxy, syz, szx + gradient * (p[1] - WIDTH / 2))
        return field

    def test_stress_side_torsion_abstains_when_the_applied_torque_is_zero(self) -> None:
        # tau_xz = 0.012 (y - 5) over the 10 x 5 mm section: torque = 0.012 * 5 * the integral of (y - 5)^2 over 0..10
        # = 0.012 * 5 * 83.33 = 5.0 N mm about x (4.94 on the nine strips), against the floor 1e-3 * 50 * 10 = 0.5 N mm.
        # The force balances and the moment residual is 0.4%, so only a screen of the section's own torque sees it.
        found = self.assess(self.twisting(0.012))
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("torsion_on_section",), None))
        self.assertRegex(found.message, r"section stresses.*torque 4\.9\d* N mm")

    def test_the_first_moment_of_a_shear_across_the_thickness_is_a_torque_the_annex_split_discards(self) -> None:
        # tau_xy = 0.01 (z - 2.5) has no mean, so the membrane shear and the force are zero. Its torque about x is
        # -0.01 * 10 * the integral of (z - 2.5)^2 over 0..5 = 0.01 * 10 * 10.417 = 1.04 N mm, over the 0.5 floor.
        base = beam_field()

        def field(p: Point) -> tuple[float, ...]:
            sxx, syy, szz, sxy, syz, szx = base(p)
            return (sxx, syy, szz, sxy + 0.01 * (p[2] - DEPTH / 2), syz, szx)
        found = self.assess(field)
        self.assertEqual((found.status, found.reasons), ("unknown", ("torsion_on_section",)))
        self.assertRegex(found.message, r"section stresses.*torque 1\.0\d* N mm")

    def test_a_stress_side_torque_under_the_floor_does_not_abstain(self) -> None:
        # 0.0005 gives 0.0005 * 5 * 83.33 = 0.21 N mm, under the 0.5 N mm floor.
        self.assertEqual(self.assess(self.twisting(0.0005)).status, "linearised")

    def test_a_centred_load_of_3e153_with_doubled_bending_abstains_and_never_passes_on_a_nan_residual(self) -> None:
        # The squared moment norms of a 3e153 N load overflow a naive norm to inf, and inf / inf is nan, which
        # max() drops when it comes second. Doubled bending near the root (x < 10) is a 100% moment miss there, over
        # the 5% limit; the load section at x = 25 is exact, so only the root section's residual can refuse.
        load = 3e153
        tip = nodes_at(self.coordinates, 0, LENGTH)
        centre = next(n for n in tip if self.coordinates[n][1:] == (WIDTH / 2, DEPTH / 2))
        self.loads = [{n: (0.0, 0.0, -load if n == centre else 0.0) for n in tip}]
        exact, doubled = beam_field(load), beam_field(load, bending=2.0)
        found = self.assess(lambda p: doubled(p) if p[0] < 10.0 else exact(p))
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("cross_check_failed",), None))
        # Root section: lines -1.5e155 + 7.5e154 applied = 7.5e154 over the scale 7.5e154, whole; a naive norm gives nan.
        self.assertRegex(found.message, r"fixed face.*moment residual 100\.0%")

    def test_a_torque_under_the_floor_does_not_abstain(self) -> None:
        # 0.005 mm of eccentricity is 0.25 N mm, under the 0.5 N mm floor.
        found = self.assess(loads=self.eccentric_tip_load(0.005))
        self.assertEqual((found.status, found.reasons), ("linearised", ()))


class ZoneDepth(unittest.TestCase):
    def test_the_zone_is_the_larger_of_one_local_thickness_and_three_coarse_mesh_sizes(self) -> None:
        for thickness, h_coarse, depth in ((5.0, 1.0, 5.0), (5.0, 4.5, 13.5), (2.0, 1.0, 3.0), (3.0, 1.0, 3.0)):
            with self.subTest(thickness=thickness, h_coarse=h_coarse):
                self.assertAlmostEqual(ns.zone_depth(thickness, h_coarse), depth, places=12)


class LoadBlocks(unittest.TestCase):
    def test_each_cload_block_is_one_face_with_its_forces_summed_per_node_and_zero_entries_kept(self) -> None:
        inp = ("*NSET,NSET=FixedFaces\n1,\n** FaceForce0\n*CLOAD\n** node loads on shape: Part:Face2\n"
               "5,3,-0\n6,3,-2.5\n6,1,1.5\n** FaceForce1\n*CLOAD\n7,2,4.0\n")
        self.assertEqual(study.load_blocks(inp), [{5: (0.0, 0.0, 0.0), 6: (1.5, 0.0, -2.5)}, {7: (0.0, 4.0, 0.0)}])

    def test_a_repeated_degree_of_freedom_in_one_block_is_refused(self) -> None:
        with self.assertRaises(study.BoundaryNodesError):
            study.load_blocks("*CLOAD\n5,3,1.0\n5,3,2.0\n")


class RealCantilever(unittest.TestCase):
    """The fast-bias cantilever at 4.5 mm: 100 x 10 x 5 mm, clamped at x = 0, 50 N in -z at x = 100.

    The zone is max(5, 3 * 4.5) = 13.5 mm. At x = 13.5 the moment is 50 * 86.5 = 4325 N mm, so Mc/I = 4325 * 2.5 /
    104.1667 = 103.8 MPa. Near the load, at x = 86.5, M = 675 and Mc/I = 16.2 MPa. The solve's nodal stresses are
    smoothed, so the allowed distance is 3.5% of the root figure."""

    def assess(self) -> ns.NearSupport:
        with gzip.open(FIXTURES / "cantilever_r1_4.5mm.frd.gz", "rt") as handle:
            result = fs.read_frd(handle.read())
        elements = study.element_connectivity((FIXTURES / "cantilever_r1_4.5mm.elements.inp").read_text(encoding="utf-8"))
        faces = (FIXTURES / "cantilever_r1_4.5mm.faces.inp").read_text(encoding="utf-8")
        fixed, _ = study.boundary_nodes(faces)
        return ns.assess(result, elements, fixed=fixed, loads=study.load_blocks(faces), h_coarse=4.5, h_mesh=4.5)

    def test_the_provisional_five_percent_refuses_this_smoothed_mesh_on_its_force_residual(self) -> None:
        # Measured: the root section's force residual is 5.2% and the load section's 6.1%, over the 5% limit.
        found = self.assess()
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("cross_check_failed",), None))
        self.assertRegex(found.message, r"force residual 5\.\d%")

    def test_the_smoothed_mesh_also_trips_the_torsion_floor_once_the_residual_limit_is_widened(self) -> None:
        # Measured: the integrated section torque of the smoothed ccx stresses is 1.06 N mm at the root section and
        # 0.52 N mm at the load section, 0.21% and 0.10% of F x L = 500 N mm, over the 0.1% floor (0.5 N mm).
        with patch.object(ns, "TOLERANCE", 0.10):
            found = self.assess()
        self.assertEqual((found.status, found.reasons, found.sigma_mpa), ("unknown", ("torsion_on_section",), None))
        self.assertRegex(found.message, r"section stresses.*torque 1\.0\d* N mm")

    def test_with_the_limit_and_the_floor_widened_the_sections_give_mc_over_i(self) -> None:
        with patch.object(ns, "TOLERANCE", 0.10), patch.object(ns, "TORSION_FLOOR", 0.005):
            found = self.assess()
        self.assertEqual((found.status, found.reasons), ("linearised", ()))
        by_face = {s.face: s for s in found.sections}
        self.assertAlmostEqual(by_face["fixed"].section_mm, 13.5, places=6)
        self.assertAlmostEqual(by_face["load"].section_mm, 86.5, places=6)
        self.assertAlmostEqual(by_face["fixed"].sigma_mpa, 103.8, delta=3.6)
        self.assertAlmostEqual(by_face["load"].sigma_mpa, 16.2, delta=1.0)
        for section in found.sections:
            self.assertLess(section.moment_residual, 0.01)


stress_mode_tests = _sibling("test_fea_stress_mode")
stress_tests = _sibling("test_fea_stress")
conditions_tests = _sibling("test_fea_conditions")
STRENGTH = stress_mode_tests.STRENGTH


def beam_plan(field: Callable[[Point], tuple[float, ...]], fixed_planes: tuple[float, ...], load_plane: float,
              load: float, elements_only: Mapping[int, study.Element] | None = None,
              cells_x: int = 30) -> list[dict[str, Any]]:
    """Two stand-in solves that both return the beam bar's field: the coarse and the fine mesh are the one mesh, so
    the study settles on its own, and `load` newtons act in -z over the nodes at x = `load_plane`."""
    nodes, elements = bar(cells_x)
    frd = stress_tests.frd_text(nodes, {n: (0.0, 0.0, 0.01) for n in nodes}, {n: field(p) for n, p in nodes.items()})
    fixed = sorted(n for plane in fixed_planes for n in nodes_at(nodes, 0, plane))
    carried = sorted(nodes_at(nodes, 0, load_plane))
    inp = ("*NSET,NSET=FixedFaces\n" + "".join(f"{n},\n" for n in fixed) + "** FaceForce0\n*CLOAD\n"
           + "".join(f"{n},3,{-load / len(carried)!r}\n" for n in carried)
           + "*ELEMENT, TYPE=C3D10, ELSET=Evolumes\n"
           + "".join(f"{i}, " + ", ".join(str(n) for n in e.nodes) + "\n"
                     for i, e in (elements_only or elements).items()))
    return [{"frd": frd, "inp": inp, "displacement": [0.0, 0.2]}, {"frd": frd, "inp": inp, "displacement": [0.0, 0.2]}]


class ThroughTheStudy(stress_mode_tests.StressCase):
    """A stress case on the bar, through fea_static. Yield is 250 MPa and REQ-001 asks for a factor of 2.

    The study's own kept-region peak is the surface stress at the first node outside the 3 mm cutoff, the mid-edge
    node at x = 3.5: 50 * 26.5 * 2.5 / I = 31.8 MPa at 50 N, a factor of 7.86, and 133.56 MPa at 210 N, 1.8718."""

    def solve(self, plan: list[dict[str, Any]], docs: dict[str, Any] | None = None,
              material: dict[str, Any] | None = None, artifacts: dict[str, bytes] | None = None) -> dict[str, Any]:
        """`artifacts` are source files (relative to the record) that the version's record snapshot also holds."""
        self.plan = plan
        self.build(docs or conditions_tests.documents(profiles=[self.ductile_alloy()]))
        for rel, data in (artifacts or {}).items():
            target = self.hw / "versions" / "v1" / "record" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if artifacts:
            self.seal("v1")
        if material and "effective_isotropic" in material:
            conditions_tests.write_test_decision(self.hw, "DR-003", title="DR-003: effective isotropic model")
        case = self.case(material or {"conditions": conditions_tests.SERVICE}, mode="stress", mesh_size=1.0,
                         acceptance={"strength": "REQ-001", "stiffness": "REQ-002"})
        status, report = self.call(case)
        self.assertEqual(status, 0, report)
        found = report["stress_study"]
        self.assertEqual(found["outcome"], "settled_away_from_support", found["message"])
        return report

    @staticmethod
    def ductile_alloy(elongation: float | None = 0.14, gauge: str | None = "5.65sqrtS0", *, orientation: str | None = None,
                      base: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
        """The synthetic wrought alloy with an elongation_at_break of `elongation` (a ratio) on `gauge`, or with no
        elongation entry at all when `elongation` is None. The default sits exactly on the EN 13445-2 4.1.4 limit.
        `extra` goes to the property fixture (conditioning, temperature, basis)."""
        tests = conditions_tests
        profile = base or tests.alloy()
        if elongation is not None:
            extra = {"temperature": tests.fx.quantity(lower=10, upper=40, units="deg_C"), **extra}
            entry = tests.prop("elongation_at_break", elongation, "dimensionless", **extra,
                               **({"orientation": tests.fx.known(orientation)} if orientation else {}))
            if gauge is not None:
                entry["conditions"]["gauge"] = gauge
            profile["properties"].append(entry)
        return profile

    def fresh(self) -> None:
        """Forget the published bundle and the recorded jobs, so the next solve of a changed profile reruns."""
        for published in ("analysis", "checks"):
            shutil.rmtree(self.hw / published / "v1", ignore_errors=True)
        self.jobs.clear()

    def row(self, report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        row = next(r for r in report["engineering"]["outcomes"] if r["obligation"] == STRENGTH)
        finding = next((f for f in report["engineering"]["findings"] if f["obligation"] == STRENGTH), None)
        return row, finding

    def test_a_cantilever_root_linearised_inside_the_cross_check_passes_strength(self) -> None:
        report = self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD))
        near = report["stress_study"]["near_support"]
        self.assertEqual((near["outcome"], near["reasons"]), ("linearised", []))
        self.assertEqual(self.row(report)[0]["outcome"], "pass")
        found = report["stress_study"]
        self.assertEqual((found["strength_eligible"], found["sigma_mpa"]), (False, None))  # the study itself is unchanged

    def test_a_linearised_stress_over_the_criterion_fails_strength_at_the_hand_value(self) -> None:
        report = self.solve(beam_plan(beam_field(210.0), (0.0,), LENGTH, 210.0))
        row, finding = self.row(report)
        self.assertEqual(row["outcome"], "fail")
        assert finding is not None
        self.assertAlmostEqual(finding["measured"]["value"], 250.0 / 133.56, places=3)

    def test_a_record_gap_turns_a_linearised_strength_fail_into_unknown(self) -> None:
        # The same 210 N case fails strength at 1.8718 against 2 (test above). A record that fails its schema is a gap
        # (#262): it leaves the verdict unknown on the near-support path as on every other.
        docs = conditions_tests.documents(profiles=[self.ductile_alloy()])
        docs["requirements.yaml"]["bogus"] = 1
        report = self.solve(beam_plan(beam_field(210.0), (0.0,), LENGTH, 210.0), docs)
        self.assertEqual(report["stress_study"]["near_support"]["outcome"], "linearised")
        row, finding = self.row(report)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("hw/requirements.yaml: Additional properties", row["uncertainty"])
        self.assertEqual([f["code"] for f in report["engineering"]["findings"] if f["outcome"] == "fail"], [])

    def test_a_fixed_fixed_beam_abstains_and_never_fails(self) -> None:
        report = self.solve(beam_plan(beam_field(210.0), (0.0, LENGTH), 15.0, 210.0, cells_x=60))
        near = report["stress_study"]["near_support"]
        self.assertEqual((near["outcome"], near["reasons"]), ("unknown", ["statically_indeterminate"]))
        row, _ = self.row(report)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("statically_indeterminate", row["uncertainty"])

    def test_a_failed_cross_check_abstains_even_when_the_figure_is_over_the_criterion(self) -> None:
        report = self.solve(beam_plan(beam_field(210.0, bending=1.2), (0.0,), LENGTH, 210.0))
        near = report["stress_study"]["near_support"]
        self.assertEqual((near["outcome"], near["reasons"]), ("unknown", ["cross_check_failed"]))
        self.assertEqual(self.row(report)[0]["outcome"], "unknown")

    def test_a_linearisation_refusal_abstains_with_its_reason(self) -> None:
        # No element between x = 4 and 6: the root SCL runs through a void.
        coordinates, elements = bar()
        kept = {i: e for i, e in elements.items() if not 4.0 < sum(coordinates[n][0] for n in e.nodes[:4]) / 4 < 6.0}
        report = self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD, kept))
        self.assertEqual(report["stress_study"]["near_support"]["reasons"], ["scl_outside_mesh"])
        self.assertEqual(self.row(report)[0]["outcome"], "unknown")

    def test_ductility_needs_the_en_13445_elongation_on_the_5_65_gauge(self) -> None:
        # EN 13445-2:2014 4.1.4: at least 14% (0.14 as a ratio) on 5.65 * sqrt(S0). Every other case is not shown
        # ductile, so the linearised 133.56 MPa (factor 1.8718 against 2) stays unknown instead of failing.
        cases = {
            "exactly 0.14 on the EN gauge": (0.14, "5.65sqrtS0", "pass", None),
            "0.139 on the EN gauge": (0.139, "5.65sqrtS0", "unknown", "0.139"),
            "a good value on the A50mm gauge": (0.30, "A50mm", "unknown", "A50mm"),
            "a good value on the 5d gauge": (0.30, "5d", "unknown", "5d"),
            "a good value with no gauge": (0.30, None, "unknown", "stated on no gauge"),
            "no elongation entry": (None, None, "unknown", "records no known elongation_at_break"),
        }
        for name, (value, gauge, outcome, why) in cases.items():
            with self.subTest(name):
                self.fresh()
                load = LOAD if outcome == "pass" else 210.0
                field = beam_field() if outcome == "pass" else beam_field(210.0)
                report = self.solve(beam_plan(field, (0.0,), LENGTH, load),
                                    conditions_tests.documents(profiles=[self.ductile_alloy(value, gauge)]))
                self.assertEqual(report["stress_study"]["near_support"]["outcome"], "linearised")
                row, _ = self.row(report)
                self.assertEqual(row["outcome"], outcome, row)
                self.assertEqual(report["material"]["ductility"]["shown"], outcome == "pass")
                if why:
                    self.assertIn("not shown ductile and isotropic", row["uncertainty"])
                    self.assertIn(why, row["uncertainty"])

    def test_a_percent_elongation_is_compared_as_a_ratio(self) -> None:
        profile = self.ductile_alloy(None)
        tested = conditions_tests.fx.quantity(lower=10, upper=40, units="deg_C")
        entry = conditions_tests.prop("elongation_at_break", 14, "percent", temperature=tested)
        entry["conditions"]["gauge"] = "5.65sqrtS0"
        profile["properties"].append(entry)
        report = self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD), conditions_tests.documents(profiles=[profile]))
        self.assertEqual(self.row(report)[0]["outcome"], "pass")

    def unknown_with(self, profile: dict[str, Any], reason: str, material: dict[str, Any] | None = None) -> None:
        """The linearisation of this case gives 133.56 MPa, so only the ductility gate can hold it at unknown."""
        self.fresh()
        report = self.solve(beam_plan(beam_field(210.0), (0.0,), LENGTH, 210.0),
                            conditions_tests.documents(profiles=[profile]), material)
        self.assertEqual(report["stress_study"]["near_support"]["outcome"], "linearised")
        row, _ = self.row(report)
        self.assertEqual(row["outcome"], "unknown", row)
        self.assertFalse(report["material"]["ductility"]["shown"])
        self.assertIn(reason, report["material"]["ductility"]["reason"])
        self.assertIn(reason, row["uncertainty"])

    def test_disagreeing_elongations_on_the_en_gauge_give_unknown(self) -> None:
        # 0.20 and 0.30 both match the conditions: the resolver refuses differing values, so no minimum qualifies.
        profile = self.ductile_alloy(0.30, base=self.ductile_alloy(0.20))
        self.unknown_with(profile, "match with different values")

    def test_an_elongation_that_is_not_service_evidence_does_not_show_ductility(self) -> None:
        for basis in ("user_declared", "estimate"):
            with self.subTest(basis):
                self.unknown_with(self.ductile_alloy(0.30, basis=basis), f"is a {basis} value, not service evidence")

    def test_an_elongation_citing_a_missing_source_artifact_does_not_show_ductility(self) -> None:
        profile = self.ductile_alloy(0.30)
        fx = conditions_tests.fx
        profile["properties"][-1]["value"]["sources"] = [
            fx.source("datasheet", "TST sheet", artifact="manufacturing/sources/missing.pdf", sha256=fx.sha256(b"x"),
                      conditions="TST")]
        self.unknown_with(profile, "manufacturing/sources/missing.pdf is not in the version's record snapshot")

    def test_an_elongation_source_artifact_must_match_its_recorded_digest(self) -> None:
        # The artifact is in the snapshot in both cases. Only its bytes differ from the recorded sha256.
        fx, rel = conditions_tests.fx, "manufacturing/sources/elongation.pdf"
        for name, held, ductile in (("bytes match", b"recorded bytes", True), ("bytes differ", b"other bytes", False)):
            with self.subTest(name):
                profile = self.ductile_alloy(0.30)
                profile["properties"][-1]["value"]["sources"] = [
                    fx.source("datasheet", "TST sheet", artifact=rel, sha256=fx.sha256(b"recorded bytes"), conditions="TST")]
                self.fresh()
                load = LOAD if ductile else 210.0
                report = self.solve(beam_plan(beam_field() if ductile else beam_field(210.0), (0.0,), LENGTH, load),
                                    conditions_tests.documents(profiles=[profile]), artifacts={rel: held})
                self.assertEqual(report["material"]["ductility"]["shown"], ductile)
                row, _ = self.row(report)
                if ductile:
                    self.assertEqual(row["outcome"], "pass", row)
                else:
                    self.assertEqual(row["outcome"], "unknown", row)
                    reason = f"elongation_at_break source artifact {rel} does not match its recorded sha256"
                    self.assertIn(reason, report["material"]["ductility"]["reason"])
                    self.assertIn(reason, row["uncertainty"])

    def test_an_elongation_tested_under_other_conditions_is_not_used(self) -> None:
        tested = conditions_tests.fx.quantity(lower=50, upper=80, units="deg_C")
        cases = {
            "conditioning": (self.ductile_alloy(0.30, conditioning="conditioned"), "tested conditioned, dry requested"),
            "temperature": (self.ductile_alloy(0.30, temperature=tested), "tested at"),
        }
        for name, (profile, reason) in cases.items():
            with self.subTest(name):
                self.unknown_with(profile, reason)

    def test_an_elongation_at_another_orientation_is_not_used(self) -> None:
        # Every property has the XY orientation, so the material is isotropic and the case takes XY. The only elongation has Z.
        tests = conditions_tests
        tested = tests.fx.quantity(lower=10, upper=40, units="deg_C")
        xy = {"temperature": tested, "orientation": tests.fx.known("XY")}
        profile = tests.alloy(
            tests.prop("youngs_modulus", 70000, "MPa", **xy), tests.prop("poisson_ratio", 0.33, "dimensionless", **xy),
            tests.prop("density", 2700, "kg_m3", **xy), tests.prop("yield_strength", 250, "MPa", **xy))
        self.ductile_alloy(0.30, orientation="Z", base=profile)
        self.unknown_with(profile, "orientation Z, XY requested", {"conditions": {**tests.SERVICE, "orientation": "XY"}})

    def test_an_interval_elongation_counts_at_its_lower_bound(self) -> None:
        fx = conditions_tests.fx
        cases = {"0.10 to 0.30": (0.10, 0.30, False), "0.14 to 0.30": (0.14, 0.30, True)}
        for name, (lower, upper, ductile) in cases.items():
            with self.subTest(name):
                profile = self.ductile_alloy(0.20)
                profile["properties"][-1]["value"]["value"] = fx.quantity(lower=lower, upper=upper, units="dimensionless")
                if ductile:
                    self.fresh()
                    report = self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD),
                                        conditions_tests.documents(profiles=[profile]))
                    self.assertEqual(self.row(report)[0]["outcome"], "pass")
                else:
                    self.unknown_with(profile, "elongation_at_break 0.1 on the 5.65sqrtS0 gauge is below")

    def test_a_shipped_polymer_profile_shows_no_ductility(self) -> None:
        # No shipped polymer states an elongation gauge, so none can meet the EN 13445-2 threshold: PMMA and PC
        # sheet were eligible under the old form stand-in and are not now.
        assets = HERE.parents[1] / "cad-record" / "assets" / "manufacturing" / "material-profiles"
        metals = ("steel", "aluminium", "fastener")
        checked = []
        for path in sorted(assets.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            profiles, _ = conditions.intent().profile_document(data, "materials", path.name)
            for profile in profiles:
                if any(word in str(profile.family).lower() for word in metals):
                    continue
                checked.append(profile.id)
                elongations = [p for p in profile.properties if p.name == "elongation_at_break"]
                with self.subTest(profile.id):
                    self.assertIsNotNone(conditions.gauge_gap(elongations))
        self.assertIn("sheet_pc_makrolon_gp_clear_099", checked)
        self.assertIn("fdm_petg_polylite", checked)

    def test_an_effective_isotropic_material_stays_unknown_even_when_linearised(self) -> None:
        # The printed Z yield is 20 MPa against a 133.56 MPa stress: were the material eligible this would fail.
        fx, tests = conditions_tests.fx, conditions_tests
        part = tests.bracket("tst_polymer_fdm", [fx.operation("print", "fdm", fx.unknown("no capability in this fixture"))])
        model = {"decision": "DR-003", "justification": "TST: Z-direction values bound the layer-normal load path"}
        report = self.solve(beam_plan(beam_field(210.0), (0.0,), LENGTH, 210.0),
                            tests.documents(profiles=[tests.printed()], part=part),
                            {"conditions": {**tests.DRY_23C, "orientation": "Z"}, "effective_isotropic": model})
        self.assertEqual(report["material"]["isotropy"]["model"], "effective_isotropic")
        self.assertEqual(report["stress_study"]["near_support"]["outcome"], "linearised")
        row, _ = self.row(report)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("not shown ductile and isotropic", row["uncertainty"])

    def test_good_elongation_does_not_make_orientation_dependent_properties_eligible(self) -> None:
        # The Z elongation is 0.30 on the EN gauge, so the ductility evidence holds, but the properties differ by
        # orientation (Z yield 20 MPa against 133.56 MPa): the isotropy must hold the strength back on its own.
        tests = conditions_tests
        profile = self.ductile_alloy(0.30, "5.65sqrtS0", orientation="Z", base=tests.printed())
        profile["form"] = "rod"
        profile["process_state"] = {"process": tests.fx.unknown(), "conditioning": "dry"}
        model = {"decision": "DR-003", "justification": "TST: Z-direction values bound the layer-normal load path"}
        report = self.solve(beam_plan(beam_field(210.0), (0.0,), LENGTH, 210.0),
                            tests.documents(profiles=[profile], part=tests.bracket("tst_polymer_fdm")),
                            {"conditions": {**tests.DRY_23C, "orientation": "Z"}, "effective_isotropic": model})
        self.assertEqual(report["material"]["isotropy"]["model"], "effective_isotropic")
        self.assertTrue(report["material"]["ductility"]["shown"])
        row, _ = self.row(report)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("effective_isotropic", row["uncertainty"])

    def allowable_profile(self, *, allowable: bool = True, elongation: float | None = None) -> dict[str, Any]:
        """An alloy with a 250 MPa typical yield and, when asked, a 200 MPa allowable and a 5.65sqrtS0 elongation."""
        tests = conditions_tests
        tested = tests.fx.quantity(lower=10, upper=40, units="deg_C")
        profile = tests.alloy(
            tests.prop("youngs_modulus", 70000, "MPa", temperature=tested),
            tests.prop("poisson_ratio", 0.33, "dimensionless", temperature=tested),
            tests.prop("density", 2700, "kg_m3", temperature=tested),
            tests.prop("yield_strength", 250, "MPa", temperature=tested),
            *([tests.prop("yield_strength", 200, "MPa", basis="allowable", temperature=tested)] if allowable else []),
            typical_not_allowable=False)
        profile["form"] = "bulk"
        return self.ductile_alloy(elongation, base=profile)

    def production(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD),
                          conditions_tests.documents(profiles=[profile], service_class="production"),
                          {"conditions": conditions_tests.SERVICE})

    def test_a_sourced_yield_allowable_alone_does_not_show_ductility(self) -> None:
        # An allowable is a statistical strength value: it says nothing about elongation. 200 / 31.8 would pass
        # were the material eligible, so the unknown here is the ductility gate, not the factor.
        report = self.production(self.allowable_profile())
        rows = {row["input"]: row for row in report["material"]["properties"]}
        self.assertEqual(rows["yield"]["basis"], "allowable")
        self.assertEqual(report["stress_study"]["near_support"]["outcome"], "linearised")
        row, _ = self.row(report)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIn("records no known elongation_at_break", row["uncertainty"])

    def test_a_sourced_yield_allowable_with_the_elongation_evidence_is_eligible(self) -> None:
        report = self.production(self.allowable_profile(elongation=0.20))
        self.assertEqual({row["input"]: row for row in report["material"]["properties"]}["yield"]["basis"], "allowable")
        self.assertEqual(self.row(report)[0]["outcome"], "pass", self.row(report))

    def test_the_typical_yield_with_the_elongation_evidence_is_eligible_under_prototype_service(self) -> None:
        report = self.solve(beam_plan(beam_field(), (0.0,), LENGTH, LOAD),
                            conditions_tests.documents(profiles=[self.allowable_profile(allowable=False, elongation=0.20)]),
                            {"conditions": conditions_tests.SERVICE})
        self.assertNotEqual({row["input"]: row for row in report["material"]["properties"]}["yield"]["basis"], "allowable")
        self.assertEqual(self.row(report)[0]["outcome"], "pass", self.row(report))


if __name__ == "__main__":
    unittest.main()
