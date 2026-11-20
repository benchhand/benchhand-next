# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["numpy==2.5.5", "hypothesis==6.170.15"]
# ///

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Properties of `cadmodel.agreement._Surface`, the triangle lookup of the agreement check, on meshes built here.

The lookup must answer each point exactly as a search of every triangle does: a triangle counts when its box,
grown by the reach, holds the point and the point lies within the reach of it. test_agreement.py runs each test
here in its own process. Usage: uv run --script surface_index_probe.py [SurfaceIndex.test_name ...]
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from hypothesis import given, strategies as st

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
sys.path.insert(0, str(HERE.parents[4] / "scripts"))
from cadmodel import agreement  # noqa: E402
import property_profile  # noqa: E402,F401  (registers and loads the profile)

LATTICE = st.integers(-400, 400).map(lambda k: k / 8)  # mm, exact in binary, so points land on cell borders
POINT = st.tuples(LATTICE, LATTICE, LATTICE)
REACH = st.sampled_from([0.125, 0.155, 0.25, 0.5, 2.0])
NEAR_REACH = st.sampled_from([0.0, 0.5, 0.999999, 1.0, 1.000001, 1.5])  # offsets in reaches from a triangle


@st.composite
def triangle(draw: st.DrawFn) -> np.ndarray:
    """Corners (3, 3): a small triangle, a long thin sliver, or three free corners."""
    a = np.array(draw(POINT))
    kind = draw(st.sampled_from(["small", "sliver", "free"]))
    small = st.tuples(*[st.integers(-16, 16).map(lambda k: k / 8)] * 3)
    if kind == "small":
        b, c = a + np.array(draw(small)), a + np.array(draw(small))
    elif kind == "sliver":
        b = np.array(draw(POINT))
        tiny = np.array(draw(st.tuples(*[st.integers(-2, 2).map(lambda k: k / 64)] * 3)))
        c = a + (b - a) * draw(st.integers(0, 8)) / 8 + tiny
    else:
        b, c = np.array(draw(POINT)), np.array(draw(POINT))
    return np.stack([a, b, c])


@st.composite
def case(draw: st.DrawFn) -> tuple[np.ndarray, float, np.ndarray]:
    """(corners (M, 3, 3), reach, points (K, 3)) for one lookup."""
    corners = np.stack(draw(st.lists(triangle(), min_size=1, max_size=40)))
    reach = draw(REACH)
    points = [np.array(p) for p in draw(st.lists(POINT, max_size=40))]
    for _ in range(draw(st.integers(0, 30))):  # points at a set fraction of the reach from a triangle
        corner = corners[draw(st.integers(0, len(corners) - 1))]
        weights = np.array(draw(st.tuples(*[st.integers(0, 4)] * 3)), dtype=float) + 1e-3
        direction = np.array(draw(st.tuples(*[st.integers(-3, 3)] * 3)), dtype=float) + (1e-3, 0.0, 0.0)
        offset = direction / np.linalg.norm(direction) * reach * draw(NEAR_REACH)
        points.append(weights @ corner / weights.sum() + offset)
    return corners, reach, np.array(points).reshape(-1, 3)


def mesh_of(corners: np.ndarray) -> agreement.Mesh:
    return agreement.Mesh(corners.reshape(-1, 3), np.arange(3 * len(corners)).reshape(-1, 3))


def brute_force(corners: np.ndarray, reach: float, points: np.ndarray) -> np.ndarray:
    """Per point: whether a triangle within reach of it exists, from every point and triangle pair."""
    pairs_p = np.repeat(points, len(corners), axis=0)
    pairs_t = np.tile(np.arange(len(corners)), len(points))
    low, high = corners.min(axis=1) - reach, corners.max(axis=1) + reach
    boxed = np.all((pairs_p >= low[pairs_t]) & (pairs_p <= high[pairs_t]), axis=1)
    picked = corners[pairs_t]
    squared = agreement._triangle_sq(pairs_p, picked[:, 0], picked[:, 1], picked[:, 2])
    return (boxed & (squared <= reach * reach)).reshape(len(points), len(corners)).any(axis=1)


def square(size: float, steps: int) -> agreement.Mesh:
    """A size x size square in z = 0 centered on the origin, in steps x steps cells of two triangles."""
    ticks = np.linspace(-size / 2, size / 2, steps + 1)
    x, y = np.meshgrid(ticks, ticks, indexing="ij")
    points = np.stack([x.ravel(), y.ravel(), np.zeros(x.size)], axis=1)
    corner = (np.arange(steps)[:, None] * (steps + 1) + np.arange(steps)[None, :]).ravel()
    triangles = np.concatenate([np.stack([corner, corner + steps + 1, corner + steps + 2], axis=1),
                                np.stack([corner, corner + steps + 2, corner + 1], axis=1)])
    return agreement.Mesh(points, triangles)


def cylinder(radius: float, height: float, segments: int) -> agreement.Mesh:
    """The side wall of a cylinder standing on z = 0 at the origin: tall thin triangles."""
    angles = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    ring = np.stack([radius * np.cos(angles), radius * np.sin(angles), np.zeros(segments)], axis=1)
    points = np.concatenate([ring, ring + (0.0, 0.0, height)])
    here, there = np.arange(segments), (np.arange(segments) + 1) % segments
    triangles = np.concatenate([np.stack([here, there, there + segments], axis=1),
                                np.stack([here, there + segments, here + segments], axis=1)])
    return agreement.Mesh(points, triangles)


def joined(*meshes: agreement.Mesh) -> agreement.Mesh:
    offsets = np.cumsum([0] + [len(m.points) for m in meshes[:-1]])
    return agreement.Mesh(np.concatenate([m.points for m in meshes]),
                          np.concatenate([m.triangles + offset for m, offset in zip(meshes, offsets)]))


class SurfaceIndex(unittest.TestCase):
    def test_a_triangle_spanning_billions_of_cells_leaves_a_mesh_agreeing_with_itself(self) -> None:
        """One triangle's grown box spans about 4e6 cells per axis, whose product overflows int64. It must still
        count as wide, and the mesh of it and three small triangles must agree with itself."""
        far = 4194303.0
        small = [(0, 0, 0), (0.75, 0, 0), (0, 0.75, 0)]
        corners = np.array(small * 3 + [(0, 0, 0), (far, far, 0), (far, 0, far)], dtype=float)
        mesh = agreement.Mesh(corners, np.arange(len(corners)).reshape(-1, 3))
        self.assertEqual(agreement.compare(mesh, mesh, 0.04)["status"], "pass")

    def measure_pairs(self, corners: np.ndarray, points: np.ndarray, reach: float) -> tuple[int, int, np.ndarray]:
        """(the largest array `within` builds, the pairs it measures, its answer). SEAM: `_Surface.within` takes
        the points directly (compare samples its own). A wrapper on numpy's `repeat`, `tile` and `arange`, which
        build the pair arrays, records the largest length they return; that length stands in for memory, which a
        test cannot measure stably. `_near` is wrapped to count the pairs measured."""
        surface = agreement._Surface(mesh_of(corners), reach)
        largest, measured = [0], [0]
        repeat, tile, arange, near = np.repeat, np.tile, np.arange, surface._near

        def sized(build: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
            def wrapper(*args: Any, **kwargs: Any) -> np.ndarray:
                made = build(*args, **kwargs)
                largest[0] = max(largest[0], len(made))
                return made
            return wrapper

        def counted(points: np.ndarray, point: np.ndarray, triangle: np.ndarray) -> np.ndarray:
            measured[0] += len(point)
            return near(points, point, triangle)

        surface._near = counted  # type: ignore[method-assign]
        with (mock.patch.object(np, "repeat", sized(repeat)), mock.patch.object(np, "tile", sized(tile)),
              mock.patch.object(np, "arange", sized(arange))):
            found = surface.within(points)
        return largest[0], measured[0], found

    def test_many_triangles_in_one_cell_are_measured_in_bounded_batches(self) -> None:
        """100,000 copies of one triangle share every cell, so 1,500 points in its cells pair with 1.5e8 triangles.
        No array of those pairs may exist at once: the largest stays at PAIR_BATCH."""
        corners = np.tile(np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype=float), (100_000, 1)).reshape(-1, 3, 3)
        points = np.tile([1.2, 1.2, 0.0], (1_500, 1))
        largest, measured, found = self.measure_pairs(corners, points, 0.155)
        self.assertFalse(found.any())  # (1.2, 1.2) is 0.28 mm from the triangle, beyond the reach
        self.assertEqual(measured, 1_500 * 100_000)
        self.assertLessEqual(largest, agreement.PAIR_BATCH)

    def test_many_wide_triangles_are_measured_in_bounded_batches(self) -> None:
        """A thousand small triangles fix a cell of about 1 mm, so 300 copies of a 100 mm triangle, each over
        thousands of cells, are wide. 300 points pair with all of them: 90,000 pairs, more than PAIR_BATCH."""
        small = np.tile(np.array([(0, 0, 0), (0.75, 0, 0), (0, 0.75, 0)], dtype=float), (1_000, 1))
        big = np.tile(np.array([(0, 0, 0), (100, 0, 0), (0, 100, 0)], dtype=float), (300, 1))
        corners = np.concatenate([small, big]).reshape(-1, 3, 3)
        points = np.tile([-50.0, -50.0, 0.0], (300, 1))  # far from every triangle
        largest, measured, found = self.measure_pairs(corners, points, 0.155)
        self.assertFalse(found.any())
        self.assertEqual(measured, 300 * 300)
        self.assertLessEqual(largest, agreement.PAIR_BATCH)

    def test_more_wide_triangles_than_a_batch_are_split_across_blocks(self) -> None:
        """With PAIR_BATCH patched to 8, 30 wide triangles (copies of a 100 mm triangle moved by whole millimetres,
        beside a thousand small ones that fix the cell) outnumber a batch. The answer must equal a search of every
        triangle, and no pair array may exceed 8."""
        small = np.tile(np.array([(0, 0, 0), (0.75, 0, 0), (0, 0.75, 0)], dtype=float), (1_000, 1))
        big = np.concatenate([np.array([(k, 0, 0), (k + 100, 0, 0), (k, 100, 0)], dtype=float) for k in range(30)])
        corners = np.concatenate([small, big]).reshape(-1, 3, 3)
        points = np.array([(-50, -50, 0), (50, 10, 0), (-0.1, 5, 0), (-0.2, 5, 0), (29.1, 5, 0), (60, 60, 0),
                           (60, 60, 0.1), (60, 60, 0.2), (130, 1, 0), (129.9, 1, 0), (10, 10, 3), (10, 1, 0)],
                          dtype=float)
        with mock.patch.object(agreement, "PAIR_BATCH", 8):
            largest, measured, found = self.measure_pairs(corners, points, 0.155)
        want = brute_force(corners, 0.155, points)
        self.assertTrue(want.any() and not want.all())  # the points tell found from not found
        np.testing.assert_array_equal(found, want)
        self.assertEqual(measured, len(points) * 30)
        self.assertLessEqual(largest, 8)

    @given(case())
    def test_the_lookup_answers_every_point_as_a_search_of_every_triangle(
            self, drawn: tuple[np.ndarray, float, np.ndarray]) -> None:
        """Points on the 1/8 mm lattice land on cell borders without the test reading the grid: for the reaches
        that are multiples of 1/8 mm the origin (a corner minus the reach) and the cell (twice the reach, or the
        median extent of the boxes) are multiples of 1/8 mm too. SEAM: `_Surface` is built directly because
        compare samples its own points; only its constructor and `within` are used."""
        corners, reach, points = drawn
        if not len(points):
            return
        surface = agreement._Surface(mesh_of(corners), reach)
        np.testing.assert_array_equal(surface.within(points), brute_force(corners, reach, points))

    def test_a_large_face_of_two_triangles_agrees_with_a_fine_mesh_of_it(self) -> None:
        """Most triangles are a small cylinder's thin walls, so the face's two triangles each cover thousands of
        lookup cells. Every sample of the fine face still finds them."""
        wall = cylinder(3.0, 3.0, 200)
        coarse, fine = joined(square(200.0, 1), wall), joined(square(200.0, 40), wall)
        self.assertEqual(agreement.compare(coarse, fine, 0.05)["status"], "pass")
        self.assertEqual(agreement.compare(fine, coarse, 0.05)["status"], "pass")

    def test_a_face_off_axis_moved_0_2_mm_along_its_normal_does_not_agree(self) -> None:
        """0.2 mm is beyond the 0.155 mm reach at 0.05 mm. The face is tilted off every axis, so the grown box of
        each of its triangles still holds the moved points: only the distance to the triangle finds them off."""
        rng = np.random.default_rng(20261120)
        rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        normal = rotation[:, 2]
        self.assertLess(float(np.abs(normal).max()), 0.9, normal)  # the seed gives an off-axis face
        face = square(40.0, 10)
        drawn = agreement.Mesh(face.points @ rotation.T, face.triangles)
        depicted = agreement.Mesh(drawn.points + 0.2 * normal, face.triangles)
        self.assertEqual(agreement.compare(drawn, depicted, 0.05)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
