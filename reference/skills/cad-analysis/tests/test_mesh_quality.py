#!/usr/bin/env python3
"""C3D10 element validity and quality, and the high-order fallback decision, without FreeCAD."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mesh_quality import jacobian_determinants, mesh_quality, needs_fallback, read_c3d10, scaled_jacobian  # noqa: E402

CORNERS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))


def tetrahedron(edge_1_2_node_x: float = 0.5) -> list[tuple[float, float, float]]:
    """The unit right tetrahedron in ccx's C3D10 node order. Its edge 1-2 node sits at x = `edge_1_2_node_x`."""
    middles = [tuple((CORNERS[a][k] + CORNERS[b][k]) / 2 for k in range(3)) for a, b in EDGES]
    middles[0] = (edge_1_2_node_x, 0.0, 0.0)
    return [*CORNERS, *middles]  # type: ignore[list-item]


class ElementJacobians(unittest.TestCase):
    # A shift of the edge 1-2 node by d along x adds d * dN5 to the x row of the identity Jacobian, where
    # dN5 = 4 * (L1 * dL2 + L2 * dL1): det J = 1 + 4d at corner 1, 1 - 4d at corner 2 and 1 at corners 3 and 4.

    def test_a_straight_sided_tetrahedron_has_a_constant_jacobian(self) -> None:
        for value in jacobian_determinants(tetrahedron()):
            self.assertAlmostEqual(value, 1.0, places=12)
        self.assertAlmostEqual(scaled_jacobian(tetrahedron()), 1.0, places=12)

    def test_a_shifted_edge_node_distorts_the_jacobian_toward_one_corner(self) -> None:
        corners = jacobian_determinants(tetrahedron(0.7))[:4]
        for value, expected in zip(corners, (1.8, 0.2, 1.0, 1.0)):
            self.assertAlmostEqual(value, expected, places=12)
        self.assertAlmostEqual(scaled_jacobian(tetrahedron(0.7)), 0.2 / 1.8, places=12)

    def test_an_edge_node_past_three_quarters_of_its_edge_inverts_the_element(self) -> None:
        self.assertAlmostEqual(jacobian_determinants(tetrahedron(0.9))[1], -0.6, places=12)
        self.assertLess(scaled_jacobian(tetrahedron(0.9)), 0)

    def test_a_wholly_inverted_element_reports_minus_one_whatever_its_size(self) -> None:
        # A reflection through x = 0 inverts the element: every sampled determinant is -1 (unit), or -8 when
        # the element is twice as large. The measure is dimensionless, so both report -1.
        mirrored = [(-x, y, z) for x, y, z in tetrahedron()]
        doubled = [(2.0 * x, 2.0 * y, 2.0 * z) for x, y, z in mirrored]
        for nodes, determinant in ((mirrored, -1.0), (doubled, -8.0)):
            with self.subTest(determinant=determinant):
                for value in jacobian_determinants(nodes):
                    self.assertAlmostEqual(value, determinant, places=12)
                self.assertAlmostEqual(scaled_jacobian(nodes), -1.0, places=12)


class MeshFile(unittest.TestCase):
    def test_reads_the_c3d10_elements_of_an_input_file_and_counts_the_invalid_ones(self) -> None:
        good, bad = tetrahedron(), tetrahedron(0.9)
        lines = ["** written by FreeCAD", "*Node, NSET=Nall"]
        lines += [f"{n}, {x}, {y}, {z}" for n, (x, y, z) in enumerate(good + bad[4:5], 1)]
        lines += ["*Element, TYPE=C3D10, ELSET=Evolumes", "1, 1, 2, 3, 4, 5, 6, 7,", "8, 9, 10",
                  "2, 1, 2, 3, 4, 11, 6, 7, 8, 9, 10", "*Element, TYPE=S6, ELSET=Efaces", "3, 1, 2, 3, 5, 6, 7"]
        nodes, elements = read_c3d10("\n".join(lines) + "\n")
        self.assertEqual(len(nodes), 11)
        self.assertEqual(elements, [(1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10), (2, 1, 2, 3, 4, 11, 6, 7, 8, 9, 10)])
        quality = mesh_quality(nodes, elements)
        self.assertEqual((quality["elements"], quality["invalid_elements"]), (2, 1))
        self.assertLess(quality["min_scaled_jacobian"], 0)


class FallbackDecision(unittest.TestCase):
    def test_only_an_invalid_or_empty_mesh_below_the_fallback_level_is_remeshed(self) -> None:
        # (quality, level, fallback level) -> remesh at the fallback level?
        cases = [
            ({"elements": 10, "invalid_elements": 0, "min_scaled_jacobian": 0.35}, 3, 2, False),
            ({"elements": 10, "invalid_elements": 0, "min_scaled_jacobian": 0.05}, 3, 2, False),
            ({"elements": 10, "invalid_elements": 59, "min_scaled_jacobian": -0.95}, 3, 2, True),
            ({"elements": 0, "invalid_elements": 0, "min_scaled_jacobian": None}, 0, 2, True),
            # The fallback level is terminal: the job keeps LMP-0002's level-2 mesh (min scaled Jacobian 0.0762),
            # and refuses an invalid one as mesh_invalid instead of remeshing it.
            ({"elements": 12937, "invalid_elements": 0, "min_scaled_jacobian": 0.0762}, 2, 2, False),
            ({"elements": 10, "invalid_elements": 1, "min_scaled_jacobian": -0.2}, 2, 2, False),
        ]
        for quality, level, fallback, expected in cases:
            with self.subTest(quality=quality, level=level):
                self.assertIs(needs_fallback(quality, level, fallback), expected)


if __name__ == "__main__":
    unittest.main()
