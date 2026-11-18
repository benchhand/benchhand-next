#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Realistic part fixtures for the static FEA: seven parts, each with a material profile, supports, a service load
and a direction vector, built with the kernel cad-model uses and solved by fea_static.

Every fixture is a versioned case in one record version 2 project. The solve needs FreeCAD 1.1.4 and `uv`
(it builds the STEP through cadquery); without them the specification tests still run. Benchmark and test data
only: the sizes, loads and material numbers are typical of the part type, with synthetic datasheet sources.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import yaml

SKILLS = Path(__file__).resolve().parents[2]
SCRIPTS = SKILLS / "cad-analysis" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SKILLS / "cad-drawings" / "scripts"))
sys.path.insert(0, str(SKILLS / "cad-record" / "scripts"))

import fea_static  # noqa: E402
import freecad_runtime  # noqa: E402

_spec = importlib.util.spec_from_file_location("cad_record_mi_fixtures",
                                               SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
assert _spec and _spec.loader
fx = sys.modules.get(_spec.name)
if fx is None:
    fx = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = fx
    _spec.loader.exec_module(fx)

FREECADCMD = freecad_runtime.find_freecadcmd()
FREECAD_PRESENT = FREECADCMD is not None and FREECADCMD.is_file() and os.access(FREECADCMD, os.X_OK)
UV = shutil.which("uv")
TOOLS = {"freecad": {"path": "/opt/freecad/freecadcmd", "version": "1.1.4"}}
CONDITIONS = {"conditioning": "dry", "temperature": {"value": 23, "units": "deg_C"}}

DATASHEET = fx.source("datasheet", "TST datasheet typical values")


def prop(name: str, value: float, units: str, **extra: Any) -> dict[str, Any]:
    data = fx.material_property(name, value, units, basis="supplier_typical", **extra)
    data["value"]["sources"] = [DATASHEET]
    return data


def profile(ident: str, form: str, process: str | None, *, E: float, nu: float, density: float, yield_mpa: float) -> dict[str, Any]:
    tested = fx.quantity(lower=10, upper=40, units="deg_C")
    data = fx.material_profile(ident, form=form, properties=[
        prop("youngs_modulus", E, "MPa", temperature=tested), prop("poisson_ratio", nu, "dimensionless", temperature=tested),
        prop("density", density, "kg_m3", temperature=tested), prop("yield_strength", yield_mpa, "MPa", temperature=tested)])
    if process is not None:
        data["process_state"] = {"process": process, "conditioning": "dry"}
    return data


# Typical room-temperature values of the grade. The sources are synthetic fixtures and no real citations.
PROFILES = {
    "steel_s355": profile("steel_s355", "wrought", None, E=210000, nu=0.30, density=7850, yield_mpa=355),
    "al_6061_t6": profile("al_6061_t6", "sheet", None, E=68900, nu=0.33, density=2700, yield_mpa=276),
    "abs_moulded": profile("abs_moulded", "moulded", "moulding", E=2300, nu=0.35, density=1050, yield_mpa=40),
    "pa6_moulded": profile("pa6_moulded", "moulded", "moulding", E=3000, nu=0.39, density=1140, yield_mpa=70),
}

Faces = list[dict[str, Any]]
Selector = dict[str, Any]


def plane(axis: str, value: float) -> Callable[[Faces], Selector]:
    return lambda faces: {"plane": {"axis": axis, "value": value, "tolerance": 1e-6}}


def cylinders(radius: float, **where: Any) -> Callable[[Faces], Selector]:
    """The cylindrical faces of this radius (to 0.01 mm), optionally limited to a center-of-mass box."""
    def pick(faces: Faces) -> Selector:
        chosen = [f["index"] for f in faces if f["kind"] == "Cylinder" and abs(f["radius"] - radius) < 0.01
                  and all(lo <= f["centre"]["xyz".index(axis)] <= hi for axis, (lo, hi) in where.items())]
        if not chosen:
            raise LookupError(f"no cylinder of radius {radius} {where}")
        return {"indices": chosen}
    return pick


def flank(radius_range: tuple[float, float], angle_range: tuple[float, float]) -> Callable[[Faces], Selector]:
    """A planar face whose center lies in a radius and angle window around the Z axis (a gear tooth flank)."""
    def pick(faces: Faces) -> Selector:
        chosen = []
        for f in faces:
            x, y, _ = f["centre"]
            radius, angle = math.hypot(x, y), math.atan2(y, x)
            if f["kind"] == "Plane" and radius_range[0] <= radius <= radius_range[1] and angle_range[0] <= angle <= angle_range[1]:
                chosen.append(f["index"])
        if len(chosen) != 1:
            raise LookupError(f"expected one flank in {radius_range} {angle_range}, found {chosen}")
        return {"indices": chosen}
    return pick


@dataclass(frozen=True)
class Fixture:
    name: str                                  # the fea_parts.py part name
    pn: str
    title: str
    material: str
    route: str                                 # the part's route kind
    fixed: Callable[[Faces], Selector]
    load: Callable[[Faces], Selector]
    force_n: float                             # service load magnitude
    direction: tuple[float, float, float]      # its unit vector, in the part's frame
    mesh_size: float
    aspect: float                              # bbox longest / shortest side
    note: str = ""
    load_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "load_id", f"{self.name}_load")


FIXTURE_SET = [
    Fixture("l_bracket", "TST-0401", "Sheet-metal L-bracket", "al_6061_t6", "sheet_forming", plane("z", 0), plane("x", 2),
            100.0, (1, 0, 0), 1.0, 1.5, "bolted down on its base, pulled sideways on the flange"),
    Fixture("moulded_housing", "TST-0402", "Ribbed moulded housing", "abs_moulded", "moulding", plane("z", 28), plane("z", 2.5),
            200.0, (0, 0, -1), 3.0, 80 / 30, "screwed down on the four boss tops, 0.05 MPa inside pressure on the floor"),
    Fixture("pillow_block", "TST-0403", "Machined pillow block", "steel_s355", "cnc", plane("z", 0), cylinders(12.5),
            25000.0, (0, 0, 1), 5.0, 100 / 40, "bolted down, 25 kN uplift on the bearing bore"),
    Fixture("pipe_flange", "TST-0404", "Pipe flange with bolt circle", "steel_s355", "cnc", cylinders(9.0), plane("z", 40),
            28000.0, (0, 0, 1), 8.0, 150 / 40, "held at its eight bolt holes, 8 MPa end load on the neck"),
    Fixture("keyed_shaft", "TST-0405", "Shaft with keyway and shoulders", "steel_s355", "cnc", plane("x", 140), plane("y", 4),
            3000.0, (0, 1, 0), 5.0, 140 / 40, "clamped at the 35 mm end, key force on the keyway flank"),
    Fixture("sprocket", "TST-0406", "Sixteen-tooth sprocket", "pa6_moulded", "moulding", cylinders(10.0),
            flank((35.0, 40.0), (-0.21 - 0.12, -0.21 + 0.12)), 300.0, (0, 1, 0), 2.0, 80 / 8,
            "held at the bore, 300 N on one tooth flank"),
    Fixture("truss_member", "TST-0407", "Warren-truss frame member", "al_6061_t6", "cnc", plane("x", 0), plane("x", 320),
            1500.0, (0, 0, -1), 6.0, 320 / 16, "clamped at one end, loaded at the other"),
]
BY_NAME = {f.name: f for f in FIXTURE_SET}

# Timeouts in seconds, with clear headroom over the solves seen on dev (the slowest build, face listing and solve
# took under a minute each): a loaded host must not turn a slow step into a failure.
BUILD_TIMEOUT_S, FACES_TIMEOUT_S, SOLVE_TIMEOUT_S = 1800, 900, 1800
SPECIFICATION_TIMEOUT_S = 300   # the specification tests in a child process: seconds when nothing stalls


@dataclass(frozen=True)
class Expected:
    """Broad bounds on the peak von Mises stress and peak displacement, from a hand calculation made
    from the geometry and the load alone, never from a solver result. The stress band runs from 0.3 to 8 times the
    nominal: the peak sits at a fully fixed support or a hole, where the solver sees a singularity or a stress
    concentration the hand number leaves out. The displacement band is 0.3 to 3 times the nominal unless stated."""
    sigma_mpa: float
    delta_mm: float
    basis: str
    delta_band: tuple[float, float] | None = None   # absolute (low, high) when the hand model is one-sided

    def sigma_range(self) -> tuple[float, float]:
        return 0.3 * self.sigma_mpa, 8 * self.sigma_mpa

    def delta_range(self) -> tuple[float, float]:
        return self.delta_band or (0.3 * self.delta_mm, 3 * self.delta_mm)


EXPECTED = {
    "l_bracket": Expected(
        75.0, 0.435, "the 2 mm flange as a 40 mm cantilever, 40 wide, under 100 N spread over its face: "
        "sigma = (w L^2 / 2) (t / 2) / I with w = 2.5 N/mm, I = 26.7 mm^4; delta = w L^4 / (8 E I)"),
    "moulded_housing": Expected(
        12.0, 0.28, "the 75 x 55 x 2.5 mm floor as a clamped plate under 0.05 MPa, ribs ignored (Roark, a/b = 1.36): "
        "delta = 0.022 p b^4 / (E t^3), sigma = 0.5 p b^2 / t^2"),
    "pillow_block": Expected(
        25.0, 0.0021, "the 25 kN uplift through the two 12.5 x 40 mm side walls of the body at the bore: "
        "sigma = F / (2 x 12.5 x 40); delta = sigma (18 mm from base top to bore) / E, the lower end, because the "
        "model leaves out the bore's ovalising and the 5.5 mm strip above it", delta_band=(0.3 * 0.0021, 10 * 0.0021)),
    "pipe_flange": Expected(
        15.0, 0.00084, "the 8 MPa neck stress (28 kN over the 3506 mm^2 neck annulus) lengthens its 22 mm by "
        "sigma L / E; the disc between the neck and the bolt circle (10 mm span, 18 mm thick, 81 N/mm of shear) "
        "bends at sigma = 6 M / t^2 with M = 810 N mm/mm"),
    "keyed_shaft": Expected(
        85.5, 0.0987, "a cantilever from the clamped end (x = 140) to the key at x = 20 across the 35, 40 and 30 mm "
        "sections: sigma = 32 M / (pi d^3) at the 35 mm root with M = 3000 x 120; delta = integral of "
        "F (x - 20)^2 / (E I(x))"),
    "sprocket": Expected(
        14.0, 0.0122, "one tooth as a cantilever (6 mm high, 8 x 8 mm at the root) under 300 N at mid-flank: "
        "sigma = 6 F h / (b w^2); delta is bracketed by that tooth on a rigid root (low) and the whole 30 mm "
        "sector from the bore as a cantilever (high, 1.5 mm), since the real rim is continuous",
        delta_band=(0.0122, 1.5)),
    "truss_member": Expected(
        22.0, 0.36, "a 320 mm cantilever of two 16 x 16 mm chords 84 mm apart (I = 914,000 mm^4) under 1500 N "
        "plus the four diagonals' axial shortening: chord stress = M / (84 A) with M = 1500 x 320; "
        "delta = F L^3 / (3 E I) + shear of the diagonals"),
}


def documents() -> dict[str, Any]:
    """The record version 2 documents of the project: seven parts, four sourced profiles, one load each."""
    loads = [{"id": f.load_id, "kind": "static", "magnitude": fx.known(fx.quantity(f.force_n, "N")),
              "direction": list(f.direction), "requirements": ["REQ-001"]} for f in FIXTURE_SET]
    use = fx.use_case("draft", service_class=fx.known("working_prototype"), loads=loads)
    use["environment"]["temperature"] = fx.known(fx.quantity(lower=15, upper=30, units="deg_C"))
    requirements = fx.requirements([fx.requirement("REQ-001", "Carry the service load",
                                                   acceptance=[fx.criterion("yield_safety_factor", ">=", 1.0, "dimensionless")])])
    parts = [fx.part(f.pn, f.title, process="cnc" if f.route == "cnc" else f.route, material=f.material, part_intent=fx.intent(
        functions=[{"function": "structural", "requirements": ["REQ-001"]}], material_profile=f.material,
        service={"requirements": ["REQ-001"], "loads": [f.load_id]},
        critical_surfaces=fx.not_applicable("no critical surface in this fixture"),
        route=[fx.operation("make", f.route, fx.unknown("no capability in this fixture"))])) for f in FIXTURE_SET]
    return fx.record(product_data=fx.product(use, stage="analysis"), requirements_data=requirements, parts=parts,
                     materials=[copy.deepcopy(p) for p in PROFILES.values()], decisions=("DR-001",))


def lay_out(hw: Path, version: str = "v1") -> None:
    """Write the record below `hw` and snapshot it into versions/<version>, as the FEA tests lay out a version."""
    fx.write_record(hw, documents())
    folder = hw / "versions" / version
    record = folder / "record"
    for rel in documents():
        if not rel.startswith("_") and (hw / rel).is_file():
            (record / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hw / rel, record / rel)
    files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}
    (folder / "manifest.json").write_text(json.dumps({"label": version, "files": files}), encoding="utf-8")


def case_yaml(fixture: Fixture, faces: Faces) -> dict[str, Any]:
    """The case: the profile's conditions, the supports, and the service load as a force vector on its faces."""
    force = [round(fixture.force_n * c, 9) for c in fixture.direction]
    return {"step": f"{fixture.name}.step", "part": fixture.pn, "material": {"conditions": dict(CONDITIONS)},
            "acceptance": {"strength": "REQ-001"}, "fixed_faces": fixture.fixed(faces),
            "loads": [{"selector": fixture.load(faces), "force": force, "load": fixture.load_id}],
            "mesh_size": fixture.mesh_size, "timeout_seconds": SOLVE_TIMEOUT_S}


def fea_parts_table(source: str | None = None) -> tuple[dict[str, str], set[str]]:
    """fea_parts.py's PARTS table (part name to builder function name) and the functions it defines, read from its
    source (`source` replaces the file). Importing it would need cadquery, which only the gated solves install."""
    tree = ast.parse((FIXTURES / "fea_parts.py").read_text(encoding="utf-8") if source is None else source)
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    tables = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and [getattr(target, "id", None) for target in node.targets] == ["PARTS"]]
    if len(tables) != 1 or not isinstance(tables[0], ast.Dict):
        raise AssertionError("fea_parts.py needs exactly one `PARTS = {...}` table")
    parts: dict[str, str] = {}
    for key, value in zip(tables[0].keys, tables[0].values):
        # A `**other` entry has no key. It, a computed key and a computed builder all hide names from this reader.
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Name)):
            entry = ast.unparse(value) if key is None else f"{ast.unparse(key)}: {ast.unparse(value)}"
            raise AssertionError(f"PARTS must be a literal dict of name: builder, not `{'**' if key is None else ''}{entry}`")
        parts[key.value] = value.id
    return parts, functions


class Specification(unittest.TestCase):
    """What every fixture promises, without FreeCAD or cadquery."""

    def test_each_fixture_has_a_unit_direction_and_a_positive_load(self) -> None:
        for fixture in FIXTURE_SET:
            with self.subTest(fixture=fixture.name):
                self.assertAlmostEqual(math.sqrt(sum(c * c for c in fixture.direction)), 1.0, places=9)
                self.assertGreater(fixture.force_n, 0)
                self.assertGreater(fixture.mesh_size, 0)

    def test_every_fixture_has_hand_calculation_bounds_that_hold_its_nominal(self) -> None:
        self.assertEqual(sorted(EXPECTED), sorted(BY_NAME))
        for name, expected in EXPECTED.items():
            with self.subTest(fixture=name):
                low, high = expected.delta_range()
                self.assertTrue(0 < low <= expected.delta_mm <= high, (low, expected.delta_mm, high))
                low, high = expected.sigma_range()
                self.assertTrue(0 < low < expected.sigma_mpa < high, (low, expected.sigma_mpa, high))
                self.assertTrue(expected.basis)

    def test_names_and_part_numbers_are_unique_and_the_parts_exist(self) -> None:
        self.assertEqual(len({f.pn for f in FIXTURE_SET}), len(FIXTURE_SET))
        parts, functions = fea_parts_table()
        self.assertEqual(sorted(BY_NAME), sorted(parts))
        for name, builder in parts.items():
            with self.subTest(part=name):
                self.assertIn(builder, functions)

    def test_a_parts_table_that_is_not_a_literal_name_to_builder_dict_is_refused(self) -> None:
        for entry in ("**OTHER", "NAME: l_bracket", "'l_bracket': BUILDERS['l_bracket']", "'l_bracket': lambda: None"):
            with self.subTest(entry=entry), self.assertRaisesRegex(AssertionError, "PARTS must be a literal dict"):
                fea_parts_table(f"def l_bracket(): pass\nPARTS = {{'keyed_shaft': l_bracket, {entry}}}\n")

    def test_each_part_uses_a_profile_its_route_can_have(self) -> None:
        for fixture in FIXTURE_SET:
            with self.subTest(fixture=fixture.name):
                self.assertIn(fixture.material, PROFILES)
                moulded = PROFILES[fixture.material]["form"] == "moulded"
                self.assertEqual(moulded, fixture.route == "moulding")

    def test_the_record_names_every_load_with_its_direction_and_magnitude(self) -> None:
        loads = {load["id"]: load for load in documents()["product.yaml"]["use_case"]["loads"]}
        for fixture in FIXTURE_SET:
            self.assertEqual(loads[fixture.load_id]["direction"], list(fixture.direction))
            self.assertEqual(loads[fixture.load_id]["magnitude"]["value"]["value"], fixture.force_n)

    def test_the_case_force_is_the_service_load_along_its_direction(self) -> None:
        faces = [{"index": 1, "kind": "Cylinder", "radius": 9.0, "centre": [0, 0, 0]}]
        for fixture in FIXTURE_SET:
            with self.subTest(fixture=fixture.name):
                if fixture.name in ("pillow_block", "pipe_flange", "sprocket"):
                    continue   # these select cylinders or flanks by index, resolved against the real faces
                case = case_yaml(fixture, faces)
                force = case["loads"][0]["force"]
                self.assertAlmostEqual(math.sqrt(sum(c * c for c in force)), fixture.force_n, places=6)
                self.assertEqual([c / fixture.force_n for c in force], list(fixture.direction))

    def test_the_project_record_is_valid(self) -> None:
        """The record passes the production checks: the schemas of every document and the manufacturing-intent
        checks, not only a parse into the record reader."""
        import fea_conditions
        import validate

        with tempfile.TemporaryDirectory() as tmp:
            hw = Path(tmp) / "hw"
            lay_out(hw)
            self.assertEqual(validate.blocking(validate.validate_project(hw)), [])
            record, _ = fea_conditions.read_record(hw / "versions" / "v1" / "record")
            self.assertEqual(sorted(record.parts), sorted(f.pn for f in FIXTURE_SET))
            self.assertEqual(sorted(record.materials), sorted(PROFILES))


class SpecificationNeedsNoKernel(unittest.TestCase):
    """The specification tests run without the cadquery environment: a `uv` that never returns cannot stall them."""

    def test_the_specification_finishes_with_a_uv_that_hangs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "uv"
            stub.write_text("#!/bin/sh\nexec sleep 600\n", encoding="utf-8")
            stub.chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
            child = subprocess.Popen([sys.executable, "-B", "-m", "unittest", "test_fea_part_fixtures.Specification"],
                                     cwd=Path(__file__).resolve().parent, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                _, stderr = child.communicate(timeout=SPECIFICATION_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)   # the child and the stub it started
                child.communicate()
                self.fail(f"the specification tests did not finish in {SPECIFICATION_TIMEOUT_S} s")
        self.assertEqual(child.returncode, 0, stderr[-2000:])
        self.assertRegex(stderr, r"(?m)^OK$")


@unittest.skipUnless(FREECAD_PRESENT and UV, "the solves need FreeCAD 1.1.4 freecadcmd and uv (for cadquery)")
class Solves(unittest.TestCase):
    """Each fixture gets built, its faces get resolved in FreeCAD's numbering, and it solves once. A bundle follows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="cad-fea-parts-")
        cls.root = Path(cls.tmp.name)
        cls.hw = cls.root / "project" / "hw"
        lay_out(cls.hw)
        cls.summary: dict[str, dict[str, Any]] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        print("\nFEA part fixtures:", json.dumps(cls.summary, sort_keys=True), file=sys.stderr)
        cls.tmp.cleanup()

    def build(self, fixture: Fixture) -> tuple[Path, dict[str, Any], Faces]:
        folder = self.hw / "analysis" / "cases" / fixture.name
        folder.mkdir(parents=True, exist_ok=True)
        step = folder / f"{fixture.name}.step"
        built = subprocess.run([UV, "run", "--script", str(FIXTURES / "fea_parts.py"), fixture.name, str(step), fixture.pn],
                               capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
        self.assertEqual(built.returncode, 0, built.stderr[-1500:])
        info = json.loads(built.stdout.strip().splitlines()[-1])
        self.assertEqual(info["solids"], 1)
        faces_path = folder / "faces.json"
        listed = subprocess.run([str(FREECADCMD), str(FIXTURES / "list_faces.py")], capture_output=True, text=True, timeout=FACES_TIMEOUT_S,
                                env={**os.environ, "FEA_FACES_STEP": str(step), "FEA_FACES_OUT": str(faces_path)})
        self.assertTrue(faces_path.is_file(), listed.stderr[-1500:] + listed.stdout[-1500:])
        faces = json.loads(faces_path.read_text(encoding="utf-8"))
        faces_path.unlink()
        return folder, info, faces

    def solve(self, name: str) -> None:
        fixture = BY_NAME[name]
        folder, info, faces = self.build(fixture)
        box = info["bbox_mm"]
        sides = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
        aspect = max(sides) / min(sides)
        self.assertAlmostEqual(aspect, fixture.aspect, delta=0.05 * fixture.aspect)
        path = folder / "case.yaml"
        path.write_text(yaml.safe_dump(case_yaml(fixture, faces), sort_keys=False), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.stdout", output):
            status = fea_static.main([str(path), "--hw", str(self.hw), "--version", "v1"])
        report = json.loads(output.getvalue())
        self.assertIn(status, (0, 1), report)   # 1 is a missed margin. The bundle appears all the same
        bundle = self.hw / "analysis" / "v1" / fixture.name
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        results = json.loads((bundle / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("status"), report.get("status"), manifest)
        expected = EXPECTED[name]
        for label, value, (low, high) in (("stress", results["max_von_mises_mpa"], expected.sigma_range()),
                                          ("displacement", results["max_displacement_mm"], expected.delta_range())):
            self.assertTrue(math.isfinite(value) and low <= value <= high,
                            f"{name} {label} {value} is outside the hand-calculation band [{low:g}, {high:g}]: {expected.basis}")
        self.assertEqual(report["material"]["source"], "profile")
        self.assertEqual(report["binding"]["material_profile"]["id"], fixture.material)
        self.__class__.summary[name] = {"dof": 3 * results["node_count"], "nodes": results["node_count"],
                                        "elements": results["element_count"], "aspect": round(aspect, 2),
                                        "bbox_mm": sides, "max_von_mises_mpa": round(results["max_von_mises_mpa"], 2),
                                        "max_displacement_mm": round(results["max_displacement_mm"], 5),
                                        "safety_factor_yield": round(results["safety_factor_yield"], 3),
                                        "solve_s": round(results["solve_time_seconds"], 1), "mesh_size_mm": fixture.mesh_size}


def _solve_test(name: str) -> Callable[[Solves], None]:
    def test(self: Solves) -> None:
        self.solve(name)
    test.__doc__ = f"{BY_NAME[name].title}: {BY_NAME[name].note}."
    return test


for _fixture in FIXTURE_SET:
    setattr(Solves, f"test_{_fixture.name}_builds_and_publishes_a_bundle", _solve_test(_fixture.name))


if __name__ == "__main__":
    unittest.main()
