#!/usr/bin/env python3
"""The 3MF writer and reader (cadmodel.threemf): package layout, deterministic bytes, structure checks and
the mesh measures. The tests that need trimesh, lxml, lib3mf or OCP run in uv scripts (fixtures/threemf_probe.py,
fixtures/threemf_occ_probe.py).

Run: python3 -m unittest discover -s cad/skills/cad-model/tests -p test_threemf.py -v
"""

from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent / "scripts"))
from cadmodel import manufacture, store, threemf  # noqa: E402
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module  # noqa: E402

# A 10 mm cube: 8 vertices, 12 triangles wound outward. Its volume is 10^3 and its area 6 x 10^2.
CUBE_VERTICES = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0),
                 (0.0, 0.0, 10.0), (10.0, 0.0, 10.0), (10.0, 10.0, 10.0), (0.0, 10.0, 10.0)]
CUBE_TRIANGLES = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
                  (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
ORDER = ["[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"]


def cube(material: str | None = "PETG", color: str | None = None) -> bytes:
    return threemf.dumps(CUBE_VERTICES, CUBE_TRIANGLES, name="TST-0001", material=material, color=color)


def entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def repack(data: bytes, **replace: bytes) -> bytes:
    """`data` with the bytes of the named entries swapped, in the same order."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            target.writestr(info, replace.get(info.filename, source.read(info.filename)))
    return out.getvalue()


class PackageTests(unittest.TestCase):
    def test_entries_are_in_the_fixed_order_stored_and_dated_1980(self) -> None:
        with zipfile.ZipFile(io.BytesIO(cube())) as archive:
            infos = archive.infolist()
        self.assertEqual([info.filename for info in infos], ORDER)
        for info in infos:
            with self.subTest(entry=info.filename):
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual((info.create_system, info.external_attr), (3, 0o644 << 16))

    def test_two_writes_of_the_same_mesh_are_byte_identical(self) -> None:
        self.assertEqual(cube(), cube())

    def test_a_different_material_changes_the_bytes_and_none_writes_no_metadata(self) -> None:
        self.assertNotEqual(cube("PETG"), cube("PLA"))
        model = entries(cube(None))["3D/3dmodel.model"].decode("utf-8")
        self.assertNotIn("metadata", model)

    def test_the_model_is_core_millimetres_with_one_object_in_the_build_and_no_extension(self) -> None:
        model = entries(cube())["3D/3dmodel.model"].decode("utf-8")
        self.assertIn('unit="millimeter"', model)
        self.assertIn('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"', model)
        self.assertEqual(model.count("<object "), 1)
        self.assertEqual(model.count("<item "), 1)
        for absent in ("production", "UUID", "requiredextensions", "slice", "toolpath", "displaycolor", "basematerials",
                       "pid="):
            self.assertNotIn(absent, model)

    def test_a_float_is_written_with_six_decimals_and_no_negative_zero(self) -> None:
        data = threemf.dumps([(-0.0, 1 / 3, -2.5e-9), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)], name="P")
        model = entries(data)["3D/3dmodel.model"].decode("utf-8")
        self.assertIn('<vertex x="0.000000" y="0.333333" z="0.000000"/>', model)

    def test_a_name_and_material_with_markup_are_escaped(self) -> None:
        data = threemf.dumps(CUBE_VERTICES, CUBE_TRIANGLES, name='A&"<B>', material="PLA <1> & \"2\"")
        read = threemf.read(data).objects[0]
        self.assertEqual((read.name, read.metadata), ('A&"<B>', {"cadagent:material": 'PLA <1> & "2"'}))


class ColourTests(unittest.TestCase):
    def test_a_colour_writes_a_basematerials_entry_the_object_points_at(self) -> None:
        model = entries(cube("PETG", "#1a2B3c"))["3D/3dmodel.model"].decode("utf-8")
        self.assertIn('<basematerials id="1"><base name="PETG" displaycolor="#1A2B3CFF"/></basematerials>', model)
        self.assertIn('<object id="2" name="TST-0001" type="model" pid="1" pindex="0">', model)
        self.assertIn('<item objectid="2"/>', model)
        self.assertIn('<metadata name="cadagent:material">PETG</metadata>', model)
        self.assertIn('xmlns:cadagent="https://github.com/benchhand/benchhand/ns/3mf/2026"', model)

    def test_the_colour_is_read_back_as_rrggbbaa_and_a_colourless_part_reads_none(self) -> None:
        (coloured,) = threemf.read(cube("PETG", "#1a2B3c")).objects
        (plain,) = threemf.read(cube("PETG")).objects
        self.assertEqual((coloured.color, coloured.id, coloured.metadata), ("#1A2B3CFF", 2, {"cadagent:material": "PETG"}))
        self.assertIsNone(plain.color)

    def test_a_colour_without_a_material_names_the_base_after_the_part(self) -> None:
        model = entries(cube(None, "#000000"))["3D/3dmodel.model"].decode("utf-8")
        self.assertIn('<base name="TST-0001" displaycolor="#000000FF"/>', model)
        self.assertNotIn("metadata", model)

    def test_a_different_colour_changes_the_bytes_and_two_writes_are_identical(self) -> None:
        self.assertEqual(cube("PETG", "#FF0000"), cube("PETG", "#FF0000"))
        self.assertEqual(len({cube("PETG"), cube("PETG", "#336699"), cube("PETG", "#336698")}), 3)
        self.assertNotEqual(cube("PETG", "#FF0000"), cube("PETG", "#00FF00"))

    def test_a_colour_that_is_not_rrggbb_is_refused(self) -> None:
        for bad in ("red", "FF0000", "#FF00", "#FF000000", "#GG0000", ""):
            with self.subTest(color=bad), self.assertRaises(threemf.ThreeMFError):
                cube("PETG", bad)

    def test_a_pid_that_resolves_to_no_basematerials_entry_is_refused(self) -> None:
        package = cube("PETG", "#FF0000")
        model = entries(package)["3D/3dmodel.model"]
        for label, good, bad in (("pid", b'pid="1"', b'pid="9"'), ("pindex", b'pindex="0"', b'pindex="3"')):
            with self.subTest(label), self.assertRaises(threemf.ThreeMFError):
                threemf.read(repack(package, **{"3D/3dmodel.model": model.replace(good, bad)}))


def plan(color: str | None = None, material: str = "PETG") -> manufacture.Plan:
    """A plan with the fields `facts` reads. `color` is the part's PartIntent.color."""
    policy = types.SimpleNamespace(relationship="same", state="installed", reason=None, decision=None,
                                   volume_rel_tolerance=0.0, volume_abs_tolerance_mm3=0.0, linear_deflection_mm=0.1,
                                   angular_deflection_rad=0.1, volume_tolerance_mm3=lambda volume: 0.0,
                                   outputs=("part.step", "part.stl", "part.3mf", "manufacturing.json"))
    part = types.SimpleNamespace(intent=types.SimpleNamespace(color=color))
    record = {"rev": "A", "title": "T", "material": material, "process": "fdm", "finish": None}
    return manufacture.Plan("TST-0001", record, policy, part, {}, None, {})


def entry_of(chosen: manufacture.Plan) -> dict[str, object]:
    native = {"kernel_volume_mm3": 1.0, "kernel_solids": 1, "kernel_valid": True, "kernel_errors": []}
    return manufacture.facts(chosen, "P", {"kernel_volume_mm3": 1.0}, native, "p")


def recipe_hash(material: str = "PETG", color: str | None = None) -> str:
    return store.key(manufacture.outputs_recipe(entry_of(plan(color=color, material=material)), None, None, "process"))


class RecipeTests(unittest.TestCase):
    def test_a_colour_or_material_change_stales_the_3mf_artifact_of_that_part_and_a_finish_change_does_not(self) -> None:
        impact = load_module("cad_record_impact", HERE.parents[1] / "cad-record" / "scripts" / "impact.py")
        artifact = types.SimpleNamespace(id="export.3mf@TST-0001", family="export.3mf", subject={"PN": "TST-0001"})
        key = artifact.id
        for domain, stale in (("appearance", True), ("material", True), ("geometry", True), ("finish", False)):
            with self.subTest(domain):
                changed = {"TST-0001": (domain,), "TST-0002": ("appearance", "material")}
                self.assertEqual(impact.stale_obligations([artifact], changed), {key: (domain,)} if stale else {})

    def test_changing_the_colour_changes_the_recipe_hash(self) -> None:
        self.assertNotEqual(recipe_hash(color="#FF0000"), recipe_hash(color="#00FF00"))
        self.assertNotEqual(recipe_hash(color="#FF0000"), recipe_hash(color=None))

    def test_changing_the_material_changes_the_recipe_hash(self) -> None:
        self.assertNotEqual(recipe_hash(material="PETG"), recipe_hash(material="PLA"))

    def test_the_same_colour_and_material_keep_the_recipe_hash(self) -> None:
        self.assertEqual(recipe_hash(color="#FF0000"), recipe_hash(color="#FF0000"))


class ReadTests(unittest.TestCase):
    def test_the_mesh_the_writer_wrote_is_read_back(self) -> None:
        model = threemf.read(cube())
        (obj,) = model.objects
        self.assertEqual((model.unit, obj.id, obj.name, obj.metadata), ("millimeter", 1, "TST-0001",
                                                                       {"cadagent:material": "PETG"}))
        self.assertEqual(obj.vertices, CUBE_VERTICES)
        self.assertEqual(obj.triangles, CUBE_TRIANGLES)
        self.assertEqual([(item.objectid, item.transform) for item in model.build], [(1, None)])

    def test_a_package_that_breaks_the_structure_is_refused(self) -> None:
        good = entries(cube())
        model = good["3D/3dmodel.model"].decode("utf-8")
        cases = {
            "build item names a missing object": repack(cube(), **{"3D/3dmodel.model": model.replace(
                '<item objectid="1"', '<item objectid="7"').encode()}),
            "triangle index past the vertices": repack(cube(), **{"3D/3dmodel.model": model.replace(
                'v2="2" v3="1"', 'v2="2" v3="99"', 1).encode()}),
            "unit is inch": repack(cube(), **{"3D/3dmodel.model": model.replace("millimeter", "inch").encode()}),
            "duplicate object id": repack(cube(), **{"3D/3dmodel.model": model.replace(
                "</resources>", model[model.index("<object "):model.index("</resources>")] + "</resources>").encode()}),
            "object id zero": repack(cube(), **{"3D/3dmodel.model": model.replace(
                '<object id="1"', '<object id="0"').replace('objectid="1"', 'objectid="0"').encode()}),
            "object id past the resource range": repack(cube(), **{"3D/3dmodel.model": model.replace(
                '<object id="1"', '<object id="2147483648"').replace('objectid="1"', 'objectid="2147483648"').encode()}),
            "required extension": repack(cube(), **{"3D/3dmodel.model": model.replace(
                "<model ", '<model requiredextensions="cadagent" ', 1).encode()}),
            "model is not XML": repack(cube(), **{"3D/3dmodel.model": b"not xml"}),
            "content types lack the model": repack(cube(), **{"[Content_Types].xml": b'<Types xmlns="http://schemas.'
                b'openxmlformats.org/package/2006/content-types"/>'}),
            "relationships lack the model": repack(cube(), **{"_rels/.rels": b'<Relationships xmlns="http://schemas.'
                b'openxmlformats.org/package/2006/relationships"/>'}),
            "extra entry": _with_extra(cube()),
            "not a zip": b"PK nothing",
        }
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(threemf.ThreeMFError):
                threemf.read(data)


def _with_extra(data: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("extra.txt", b"x")
    return out.getvalue()


class MeasureTests(unittest.TestCase):
    def measure(self, triangles: Sequence[Sequence[int]], vertices=CUBE_VERTICES) -> dict:
        return threemf.measure(vertices, triangles)

    def test_the_cube_is_closed_wound_outward_and_measured(self) -> None:
        report = self.measure(CUBE_TRIANGLES)
        self.assertEqual((report["watertight"], report["winding_consistent"]), (True, True))
        self.assertAlmostEqual(report["volume_mm3"], 1000.0)
        self.assertAlmostEqual(report["area_mm2"], 600.0)
        self.assertEqual(report["bbox_mm"], {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]})

    def test_a_missing_triangle_is_a_crack(self) -> None:
        report = self.measure(CUBE_TRIANGLES[:-1])
        self.assertEqual(report["watertight"], False)

    def test_one_reversed_triangle_breaks_the_winding(self) -> None:
        flipped = [*CUBE_TRIANGLES[:-1], CUBE_TRIANGLES[-1][::-1]]
        report = self.measure(flipped)
        self.assertEqual((report["watertight"], report["winding_consistent"]), (True, False))

    def test_a_mesh_wound_inward_has_negative_volume(self) -> None:
        report = self.measure([triangle[::-1] for triangle in CUBE_TRIANGLES])
        self.assertEqual((report["watertight"], report["winding_consistent"]), (True, True))
        self.assertAlmostEqual(report["volume_mm3"], -1000.0)

    def test_a_vertex_duplicated_in_place_leaves_the_mesh_open(self) -> None:
        vertices = [*CUBE_VERTICES, CUBE_VERTICES[0]]
        triangles = [(8, 2, 1), *CUBE_TRIANGLES[1:]]  # the first triangle uses a copy of vertex 0
        self.assertEqual(self.measure(triangles, vertices)["watertight"], False)


@unittest.skipUnless(shutil.which("uv"), "uv is required for the OCP environment")
class TessellationTests(unittest.TestCase):
    """The mesh of a STEP read-back, written as 3MF and judged by manufacture's check (fixtures/threemf_occ_probe.py)."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / "threemf_occ_probe.py"), tmp],
                                  capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr[-3000:]
        cls.report = json.loads(proc.stdout)

    def test_a_drilled_plate_with_reversed_hole_faces_is_closed_outward_and_at_its_analytic_volume(self) -> None:
        plate = self.report["TST-0001"]
        self.assertEqual(plate["good"]["status"], "pass", plate["good"])
        analytic = 40 * 30 * 8 - math.pi * 2.5 ** 2 * 8  # 9442.92 mm3. The 0.1 rad hole polygon adds about 0.26
        self.assertAlmostEqual(plate["threemf_volume_mm3"], analytic, delta=0.5)

    def test_a_ball_with_collapsed_pole_triangles_is_closed_outward_and_at_its_analytic_volume(self) -> None:
        ball = self.report["TST-0002"]
        self.assertEqual(ball["good"]["status"], "pass", ball["good"])
        self.assertAlmostEqual(ball["threemf_volume_mm3"], 4 / 3 * math.pi * 5 ** 3, delta=5.0)

    def test_the_3mf_holds_the_triangles_the_stl_holds(self) -> None:
        for pn, report in self.report.items():
            with self.subTest(pn=pn):
                self.assertAlmostEqual(report["threemf_volume_mm3"], report["stl_volume_mm3"],
                                       delta=1e-4 * report["stl_volume_mm3"])

    def test_a_declared_colour_the_3mf_carries_passes_the_check_for_both_shapes(self) -> None:
        for pn, report in self.report.items():
            with self.subTest(pn=pn):
                self.assertEqual((report["good_colour"]["status"], report["good_colour"]["failed"]), ("pass", []),
                                 report["good_colour"])

    def test_each_fault_fails_the_check_by_the_condition_it_breaks(self) -> None:
        expected = {"cracked": ["watertight"], "inward": ["outward", "volume_within_deflection"],
                    "scaled": ["volume_within_deflection", "box_within_deflection"],
                    "other_material": ["material_named"], "no_material": ["material_named"],
                    "colour_declared_not_written": ["color_matches"],
                    "colour_written_not_declared": ["color_matches"], "other_colour": ["color_matches"],
                    "transformed": ["no_transform"], "two_items": ["one_object"], "two_objects": ["one_object"]}
        for pn, report in self.report.items():
            for fault, failed in expected.items():
                with self.subTest(pn=pn, fault=fault):
                    self.assertEqual((report["faults"][fault]["status"], report["faults"][fault]["failed"]),
                                     ("fail", failed))


@unittest.skipUnless(shutil.which("uv"), "uv is required for the trimesh, lxml and lib3mf environment")
class ReadBackTests(unittest.TestCase):
    """A written package as trimesh, the 3MF Consortium schemas and lib3mf read it."""

    @classmethod
    def package(cls) -> bytes:
        return cube()

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        target = Path(cls.tmp.name) / "part.3mf"
        target.write_bytes(cls.package())
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(FIXTURES / "threemf_probe.py"), str(target)],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr[-3000:]
        cls.report = json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_trimesh_reads_one_closed_millimetre_object_at_the_identity(self) -> None:
        trimesh = self.report["trimesh"]
        self.assertEqual(trimesh["units"], "millimeter")
        self.assertEqual(trimesh["geometries"], 1)
        self.assertEqual(trimesh["transform"], [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        self.assertTrue(trimesh["watertight"])
        self.assertAlmostEqual(trimesh["volume_mm3"], 1000.0)

    def test_every_xml_part_validates_against_the_3mf_consortium_schemas(self) -> None:
        self.assertEqual(self.report["schema"], {"[Content_Types].xml": [], "_rels/.rels": [], "3D/3dmodel.model": []})

    def test_lib3mf_reads_it_in_strict_mode_where_a_wheel_exists(self) -> None:
        lib3mf = self.report["lib3mf"]
        if lib3mf.get("skipped"):
            self.skipTest(lib3mf["skipped"])
        self.assertEqual(lib3mf, {"warnings": 0, "meshes": 1, "vertices": 8, "triangles": 12})


@unittest.skipUnless(shutil.which("uv"), "uv is required for the trimesh, lxml and lib3mf environment")
class ColouredReadBackTests(ReadBackTests):
    """The same readers on a package with a basematerials group: the schemas and strict lib3mf accept it."""

    @classmethod
    def package(cls) -> bytes:
        return cube("PETG", "#1A2B3C")


if __name__ == "__main__":
    unittest.main()
