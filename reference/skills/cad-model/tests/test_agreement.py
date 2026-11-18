#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""cadmodel.agreement: whether a GLB mesh depicts the STEP shape it is placed for, from the probe in
fixtures/agreement_probe.py (it builds the shapes and the GLB with OCP; this file judges the verdicts).

Run: python3 -m unittest discover -s skills/cad-model/tests -p test_agreement.py -v
Needs `uv`; the probe's environment holds only OCP and pyyaml.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "fixtures" / "agreement_probe.py"


class AgreementTests(unittest.TestCase):
    probe: dict

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run(["uv", "run", "--quiet", "--script", str(PROBE), folder],
                                  capture_output=True, text=True, check=False)  # cold OCP imports take minutes
        assert proc.returncode == 0, proc.stderr[-2000:]
        lines = proc.stdout.splitlines()  # the STEP writer logs to stdout around the JSON line
        cls.probe = json.loads(next(line for line in lines if line.startswith('{"cases"')))

    def status(self, name: str) -> str:
        return self.probe["cases"][name]["status"]

    def test_a_mesh_of_the_same_shape_agrees(self) -> None:
        self.assertEqual(self.status("same_shape"), "pass", self.probe["cases"]["same_shape"])

    def test_a_cylinder_of_the_blocks_volume_does_not_agree(self) -> None:
        self.assertEqual(self.status("equal_volume_cylinder"), "fail")

    def test_a_mesh_three_millimetres_off_does_not_agree(self) -> None:
        self.assertEqual(self.status("shifted_3_mm"), "fail")

    def test_the_smallest_flagged_displacement_is_the_reach_at_the_probes_deflection(self) -> None:
        """The floor is twice the sum of the GLB deflection (0.04 mm) and the reference's half of it (0.02 mm),
        plus 0.005 mm: 0.125 mm. A flat block, where the tessellation adds no chord error, shows it exactly."""
        self.assertAlmostEqual(self.probe["cases"]["flat_shifted_just_above_floor"]["tolerance_mm"], 0.125, places=9)
        self.assertEqual(self.status("flat_shifted_just_above_floor"), "fail")  # 0.13 mm
        self.assertEqual(self.status("flat_shifted_just_below_floor"), "pass")  # 0.12 mm

    def test_the_floor_at_a_large_assemblys_deflection_is_three_times_it_plus_the_epsilon(self) -> None:
        """The exporter writes the GLB of a large assembly at its cap, 0.05 mm: floor = 3 x 0.05 + 0.005 = 0.155 mm.
        A coarser GLB widens the floor in step, so a change to REACH_MARGIN, REFERENCE_FACTOR or EPS_MM shows here
        as a moved number."""
        self.assertAlmostEqual(self.probe["cases"]["flat_shifted_above_large_floor"]["tolerance_mm"], 0.155, places=9)
        self.assertEqual(self.status("flat_shifted_above_large_floor"), "fail")  # 0.16 mm
        self.assertEqual(self.status("flat_shifted_below_large_floor"), "pass")  # 0.15 mm

    def test_the_exporter_caps_a_large_assemblys_deflection_at_the_floors_0_05_mm(self) -> None:
        """The cap decides the floor above: lamp-arm's 0.0005 x diagonal would be 0.2 mm or more, and the exporter
        records 0.05 mm in the manifest, which the check reads. A small part stays at its own 0.0005 x diagonal."""
        self.assertEqual(self.probe["exporter_deflection_mm"]["large"], 0.05)
        self.assertAlmostEqual(self.probe["exporter_deflection_mm"]["small"], 0.03, places=9)  # 60 mm diagonal

    def test_the_reference_of_a_torus_fillet_stays_within_its_budget(self) -> None:
        """The floor relies on the STEP reference lying within REFERENCE_FACTOR x the GLB deflection (0.025 mm) of the
        B-rep. BRepMesh holds that on a torus only with the control-surface deflection on for all surfaces. Without
        it the reference stayed 3.1 x the budget away on a R 44.85, r 1.2 fillet (3.15 x on LMP-0004's face 28).
        With the flag, OCCT holds 0.81 to 1.21 x the budget on lamp-arm's tori, so the test allows 1.25 x."""
        torus = self.probe["reference_torus"]
        self.assertAlmostEqual(torus["budget_mm"], 0.025, places=9)
        self.assertLessEqual(torus["worst_mm"], 1.25 * torus["budget_mm"], torus)

    def test_the_exported_glb_of_a_torus_fillet_stays_within_its_deflection_of_the_face(self) -> None:
        """The exporter records a linear deflection and the floor trusts it: the GLB must lie that close to the
        B-rep. Without the control-surface deflection on for all surfaces the exported torus fillet strayed about 3 x
        farther. The test reads the torus face's own triangulation and measures every triangle center, seam edges
        included, against that face (the solid would read 0 inside). The GLB must hold all of those triangles. The
        test allows 1.25 x, like the reference test."""
        torus = self.probe["glb_torus"]
        self.assertGreater(torus["triangles"], 100)  # the fillet has triangles to measure
        self.assertEqual(torus["matched"], 1.0, torus)  # the exported GLB holds every one of them
        self.assertLessEqual(torus["worst_mm"], 1.25 * torus["linear_mm"], torus)

    def test_parts_whose_reference_honours_its_deflection_still_agree(self) -> None:
        """A small fillet disc and the R44.85 mm fillet ring (the shape of lamp-arm's LMP-0004 face 28): their reference
        meshes lie within the reach's 0.05 mm share, so the verdict stands."""
        reference = self.probe["reference"]
        for name in ("disc", "ring"):
            self.assertEqual(reference[name]["verdict"].get("status"), "pass", reference[name])
            self.assertLess(reference[name]["deviation"]["error_mm"], reference["budget_mm"], reference[name])

    def test_the_abstain_threshold_is_the_reaches_share_of_the_reference_not_its_requested_deflection(self) -> None:
        """A ball of R5 mm: its 0.25 rad reference sags more than the 0.025 mm requested for it, less than 0.05 mm.
        The reach's own 2x margin covers that, so the verdict stands."""
        reference = self.probe["reference"]
        self.assertAlmostEqual(reference["budget_mm"], 0.05, places=9)
        mid = reference["mid"]
        self.assertGreater(mid["deviation"]["error_mm"], reference["reference_share_mm"], mid)
        self.assertLess(mid["deviation"]["error_mm"], reference["budget_mm"], mid)
        self.assertEqual(mid["verdict"].get("status"), "pass", mid)

    def test_a_reference_mesh_beyond_its_budget_makes_the_verdict_unknown(self) -> None:
        """The fillet ring's reference lies 0.02 mm from the torus. Held to a 0.01 mm budget (the parameter, as no solid
        sags past the real 0.05 mm once the mesher holds its deflection) the verdict becomes unknown, never pass."""
        tight = self.probe["reference"]["tight"]
        self.assertGreater(tight["deviation"]["error_mm"], 0.01, tight)
        self.assertEqual(tight["verdict"].get("status"), "unknown", tight)
        self.assertNotIn("glb_to_step_mm", tight["verdict"])  # the code never compared the meshes

    def test_the_unknown_names_the_part_the_face_and_the_measured_error(self) -> None:
        tight = self.probe["reference"]["tight"]
        deviation, reason = tight["deviation"], tight["verdict"].get("reason", "")
        self.assertIn("PART", reason)
        self.assertIn(f"face {deviation['face']} ({deviation['surface']})", reason)
        self.assertIn(f"{deviation['error_mm']:.4f} mm", reason)
        self.assertIn("0.0100 mm", reason)  # the threshold it enforced

    def test_a_curved_extrusion_is_measured_and_a_reference_beyond_its_budget_makes_it_unknown(self) -> None:
        """A bent spline profile extruded 5 mm: its reference triangles lie off the surface of extrusion by more than a
        0.001 mm budget. The old code skipped surfaces of extrusion. The verdict names the face and its type."""
        curved = self.probe["reference"]["curved"]
        self.assertIsNotNone(curved["deviation"], curved)
        self.assertEqual(curved["deviation"]["surface"], "SurfaceOfExtrusion")
        self.assertGreater(curved["deviation"]["error_mm"], 0.001, curved)
        row = curved["tight_verdict"]
        self.assertEqual(row.get("status"), "unknown", row)
        self.assertIn(f"face {curved['deviation']['face']} (SurfaceOfExtrusion)", row.get("reason", ""))

    def test_a_flat_extrusion_is_not_measured_and_still_agrees(self) -> None:
        """The same extrusion of collinear points is a plane in all but name: skipped, so even a 0.001 mm budget
        leaves the verdict at pass."""
        flat = self.probe["reference"]["flat"]
        self.assertIsNone(flat["deviation"], flat)
        self.assertEqual(flat["tight_verdict"].get("status"), "pass", flat)

    def test_a_cylinder_is_not_measured_and_agrees(self) -> None:
        """With the mesher holding its deflection a cylinder's reference lies a chord sagitta off (0.011 mm at R10 mm and
        0.25 rad, within the 0.025 mm requested at every radius tried). Cylinders are the most common face, so the code skips them."""
        cylinder = self.probe["reference"]["cylinder"]
        self.assertIsNone(cylinder["deviation"], cylinder)
        self.assertEqual(cylinder["verdict"].get("status"), "pass", cylinder)

    def test_a_bspline_face_beyond_its_budget_is_unknown_with_the_few_triangles_sampled(self) -> None:
        """A bulging B-spline patch held to a 0.001 mm budget: the largest triangles sampled per face still find that the
        reference strays, and the verdict names the face and its type."""
        patch = self.probe["reference"]["bspline"]
        self.assertIsNotNone(patch["deviation"], patch)
        self.assertEqual(patch["deviation"]["surface"], "BSplineSurface")
        row = patch["tight_verdict"]
        self.assertEqual(row.get("status"), "unknown", row)
        self.assertIn(f"face {patch['deviation']['face']} (BSplineSurface)", row.get("reason", ""))

    def test_a_hole_eight_millimetres_off_does_not_agree(self) -> None:
        self.assertEqual(self.status("hole_moved_8_mm"), "fail")

    def test_a_mesh_lacking_the_steps_hole_does_not_agree(self) -> None:
        row = self.probe["cases"]["hole_missing_in_mesh"]
        self.assertEqual(row["status"], "fail")
        self.assertGreater(row["step_to_glb_mm"], row["tolerance_mm"])  # no mesh lies near the hole wall of the STEP

    def test_a_mesh_with_a_hole_the_step_lacks_does_not_agree(self) -> None:
        row = self.probe["cases"]["extra_hole_in_mesh"]
        self.assertEqual(row["status"], "fail")
        self.assertGreater(row["glb_to_step_mm"], row["tolerance_mm"])  # the hole wall of the mesh is off the STEP surface

    def test_a_hole_a_quarter_millimetre_too_wide_does_not_agree(self) -> None:
        self.assertEqual(self.status("hole_6_vs_6_5"), "fail")

    def test_a_mesh_a_thousand_times_too_large_does_not_agree(self) -> None:
        self.assertEqual(self.status("thousand_times_larger"), "fail")

    def test_an_empty_mesh_or_shape_is_unknown_not_a_pass(self) -> None:
        self.assertEqual((self.status("mesh_empty"), self.status("step_empty")), ("unknown", "unknown"))

    def test_what_the_data_cannot_judge_is_unknown_with_its_reason(self) -> None:
        rows = self.probe["abstentions"]["rows"]
        self.assertEqual(rows["no_node"]["status"], "unknown")
        self.assertIn("no mesh node", rows["no_node"]["reason"])
        self.assertEqual(rows["no_shape"]["status"], "unknown")
        self.assertIn("no shape for Y", rows["no_shape"]["reason"])
        self.assertEqual(rows["has_node"]["status"], "fail")  # the one-triangle GLB is not the block: judged, not skipped
        self.assertEqual(set(self.probe["abstentions"]["no_deflection"].values()), {"unknown"})

    def test_a_nested_glb_node_reads_in_millimetres_z_up_at_its_world_pose(self) -> None:
        glb = self.probe["glb"]
        self.assertEqual(glb["names"], ["inner"])  # only a node that holds a mesh reads as one
        # glTF meters, Y up -> CAD mm, Z up: (x, y, z) -> (1000 x, -1000 z, 1000 y). The child's local points
        # (0,0,0), (.001,0,0), (0,.001,0) turn +90 degrees about Y to (0,0,0), (0,0,-.001), (0,.001,0), then add
        # the parent's (.01, .02, .03): (10, -30, 20), (10, -29, 20), (10, -30, 21).
        want = [[10.0, -30.0, 20.0], [10.0, -29.0, 20.0], [10.0, -30.0, 21.0]]
        for got_point, want_point in zip(glb["points"], want):
            for got, expected in zip(got_point, want_point):
                self.assertAlmostEqual(got, expected, places=4)
        self.assertEqual(glb["triangles"], [[0, 1, 2]])


if __name__ == "__main__":
    unittest.main()
