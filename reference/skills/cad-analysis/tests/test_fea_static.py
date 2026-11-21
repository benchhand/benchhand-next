# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

#!/usr/bin/env python3
"""Focused FEA selection, input, missing-FreeCAD, and solver integration checks."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from os import environ as process_env
from pathlib import Path

import importlib.util
from unittest.mock import patch
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/fea_static.py"
OCCURRENCE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "build_occurrence_step.py"
POSE_PATH = Path(__file__).resolve().parents[2] / "cad-motion" / "scripts" / "pose.py"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cad-drawings" / "scripts"))
import freecad_runtime
FREECADCMD = freecad_runtime.find_freecadcmd()
FREECAD_PRESENT = FREECADCMD is not None and FREECADCMD.is_file() and os.access(FREECADCMD, os.X_OK)
sys.path.insert(0, str(SCRIPT.parent))

import fea_static
from fea_static import CaseError, apply_required_safety_factor, error, load_case, result_exit_code, run_directory
from ccx_failure import ccx_failure
import ccx_failure as failure_checks
from fea_part_selection import MultipleSolids, SceneObject, select_occurrence, select_part_solid, select_solid_index
OCCURRENCE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "build_occurrence_step.py"
CONTAINER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "build_container_steps.py"
LAYOUT_PATH = SCRIPT.parents[2] / "cad-record" / "scripts" / "layout.py"
LAYOUT_SPEC = importlib.util.spec_from_file_location("cad_record_layout", LAYOUT_PATH)
assert LAYOUT_SPEC and LAYOUT_SPEC.loader
LAYOUT = sys.modules.get("cad_record_layout")
if LAYOUT is None:
    LAYOUT = importlib.util.module_from_spec(LAYOUT_SPEC)
    sys.modules["cad_record_layout"] = LAYOUT
    LAYOUT_SPEC.loader.exec_module(LAYOUT)


def load_reaction_project():
    """fixtures/reaction_project.py: sealed versions with a real stop-reaction bundle."""
    name = "cad_analysis_reaction_project"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / "fixtures" / "reaction_project.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


CASE_TAIL = """material: {name: Aluminium 6061, E: 69000, nu: 0.33, density: 2700, yield: 276}
fixed_faces: {plane: {axis: y, value: 50, tolerance: 0.000001}}
loads:
  - selector: {plane: {axis: y, value: 150, tolerance: 0.000001}}
    force: [0, 0, -50]
mesh_size: 5
"""

# The 100 x 10 x 5 mm cantilever of StaticFEAContracts.make_cantilever_step, fixed at x=0 and loaded at x=100.
CANTILEVER_TAIL = """material: {E: 69000, nu: 0.33, density: 2700, yield: 276}
fixed_faces: {plane: {axis: x, value: 0, tolerance: 0.000001}}
loads: [{selector: {plane: {axis: x, value: 100, tolerance: 0.000001}}, force: [0, 0, -50]}]
mesh_size: 5
"""


CANTILEVER_VERSIONED_TAIL = """part: TST-0101
material: {conditions: {conditioning: dry, temperature: {value: 23, units: deg_C}}}
fixed_faces: {plane: {axis: x, value: 0, tolerance: 0.000001}}
loads: [{selector: {plane: {axis: x, value: 100, tolerance: 0.000001}}, force: [0, 0, -50]}]
mesh_size: 5
"""


def hanging_freecad(root: Path, child_pid: Path, startup_seconds: float = 0) -> Path:
    """A FreeCAD stand-in that sleeps `startup_seconds`, runs the real job script, starts a solver-like child,
    writes its pid to `child_pid`, and hangs in the job's STEP import."""
    freecad = root / "freecadcmd"
    freecad.write_text(f"""#!{sys.executable}
import runpy, subprocess, sys, time
from unittest import mock
time.sleep({startup_seconds!r})
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open({str(child_pid)!r}, "w").write(str(child.pid))
for name in ("Part", "Import", "ObjectsFem", "femmesh", "femmesh.gmshtools", "femtools", "femtools.ccxtools"):
    sys.modules[name] = mock.MagicMock()
app = mock.MagicMock()
app.newDocument.side_effect = lambda name: time.sleep(120)
sys.modules["FreeCAD"] = app
runpy.run_path(sys.argv[1], run_name="__main__")
""", encoding="utf-8")
    freecad.chmod(0o755)
    return freecad


def failing_freecad(root: Path) -> Path:
    """A FreeCAD stand-in that runs the real job script and fails in its STEP import."""
    freecad = root / "freecadcmd"
    freecad.write_text(f"""#!{sys.executable}
import runpy, sys
from unittest import mock
for name in ("Part", "Import", "ObjectsFem", "femmesh", "femmesh.gmshtools", "femtools", "femtools.ccxtools"):
    sys.modules[name] = mock.MagicMock()
app = mock.MagicMock()
app.newDocument.side_effect = RuntimeError("import exploded")
sys.modules["FreeCAD"] = app
runpy.run_path(sys.argv[1], run_name="__main__")
""", encoding="utf-8")
    freecad.chmod(0o755)
    return freecad


def job_of(script: str) -> dict:
    """The job data a generated fea_job.py carries."""
    import ast
    import re

    match = re.search(r"^JOB=json[.]loads\((.*)\)$", script, flags=re.M)
    assert match is not None
    return json.loads(ast.literal_eval(match.group(1)))


def timeout_clock_after_phase():
    """Patch for `fea_static.lifecycle.run`: the job's timeout clock starts once the job has written its phase
    file, so a slow start-up cannot spend the budget. The wait is bounded at 120 s, then the clock starts anyway."""
    real_run = fea_static.lifecycle.run
    real_communicate = fea_static.lifecycle.Supervised.communicate

    def run(argv, *, cwd, **kwargs):
        def communicate(process, input=None, timeout=None):
            wait_until(lambda: any(Path(cwd).glob("fea_static_*_phase.json")), timeout=120)
            return real_communicate(process, input, timeout=timeout)

        with patch.object(fea_static.lifecycle.Supervised, "communicate", communicate):
            return real_run(argv, cwd=cwd, **kwargs)

    return patch("fea_static.lifecycle.run", run)


def hanging_case(step: Path, timeout_seconds: float) -> dict:
    return {"_step": str(step), "material": {"E": 1, "nu": 0.3, "density": 1, "yield": 1},
            "fixed_faces": {"indices": [1]}, "loads": [], "mesh_size": 1, "timeout_seconds": timeout_seconds}


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def pid_runs(pid: int) -> bool:
    """Whether process `pid` runs; a zombie waiting to be reaped has ended."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def group_runs(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_pose():
    """cad-motion's pose module: the writer of `<PN> <title> [@id]` component names."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cad_motion_pose", POSE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["cad_motion_pose"] = module
    spec.loader.exec_module(module)
    return module


class SolidSelectionContracts(unittest.TestCase):
    def test_single_solid_does_not_require_part(self) -> None:
        self.assertEqual(select_solid_index([["LMP-0002 Lower link"]], None), 0)

    def test_multi_solid_selects_part_by_product_or_label_prefix(self) -> None:
        self.assertEqual(select_solid_index([["LMP-0001 Base"], ["LMP-0002 Lower link"]], "LMP-0002"), 1)

    def test_unknown_part_lists_available_product_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "LMP-0001, LMP-0002"):
            select_solid_index([["LMP-0001 Base"], ["LMP-0002 Lower link"]], "LMP-0003")

    def test_ambiguous_part_lists_available_product_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "matches 2 STEP solids.*LMP-0002"):
            select_solid_index([["LMP-0002 Lower link"], ["LMP-0002 Lower link copy"]], "LMP-0002")

    def test_repeated_part_points_to_the_occurrence_selector(self) -> None:
        with self.assertRaisesRegex(ValueError, 'matches 2 STEP solids; a part placed more than once is selected by '
                                                'occurrence: "@id"'):
            select_solid_index([["TST-0301 Beam"], ["TST-0301 Beam001"]], "TST-0301")


class PartCandidateContracts(unittest.TestCase):
    """The imported document as FreeCAD's Import.insert builds it, described without FreeCAD: cad-model's part
    STEP of LMP-0008 imports as the App::Part "LMP-0008 Bushing" around one unnamed Part::Feature "SOLID"."""

    LMP_0008 = [SceneObject(("SOLID", "Part__Feature"), True, (100.0,), (1,)),
                SceneObject(("LMP-0008 Bushing", "LMP_0008_Bushing"), False, (100.0,))]

    def test_the_container_is_not_a_candidate_and_names_its_unnamed_child(self) -> None:
        self.assertEqual(select_part_solid(self.LMP_0008, "LMP-0008", None), (0, 0))
        self.assertEqual(select_part_solid(self.LMP_0008, None, None), (0, 0))

    def test_solid_index_counts_the_solids_of_the_leaves_only(self) -> None:
        objects = [SceneObject(("TST-0401 Plate", "Plate"), True, (6400.0,), (3,)),
                   SceneObject(("SOLID", "Beam"), True, (5000.0,), (2, 3)),
                   SceneObject(("TST-0402 Beam", "TST_0402_Beam"), False, (5000.0,), (3,)),
                   SceneObject(("top", "top"), False, (6400.0, 5000.0))]
        self.assertEqual(select_part_solid(objects, None, 2), (1, 0))
        with self.assertRaisesRegex(ValueError, "solid_index 3 is out of range for 2 STEP solids"):
            select_part_solid(objects, None, 3)

    def test_a_part_of_several_solids_is_refused_with_their_volumes(self) -> None:
        # A part STEP of two disjoint solids: FreeCAD names each child after the part.
        objects = [SceneObject(("TST-0403 Pair", "Part__Feature"), True, (1000.0,), (2,)),
                   SceneObject(("TST-0403 Pair001", "Part__Feature001"), True, (2000.0,), (2,)),
                   SceneObject(("TST-0403 Pair002", "TST_0403_Pair"), False, (1000.0, 2000.0))]
        for part in ("TST-0403", None):
            with self.subTest(part=part), self.assertRaises(MultipleSolids) as raised:
                select_part_solid(objects, part, None)
            self.assertEqual(raised.exception.details, {"count": 2, "volumes_mm3": [1000.0, 2000.0],
                                                        "solid_indices": [1, 2]})
            self.assertRegex(str(raised.exception), "solid_index.*occurrence.*one solid")

    def test_a_part_placed_twice_still_points_to_the_occurrence_selector(self) -> None:
        objects = [SceneObject(("TST-0301 Beam", "Part__Feature"), True, (5000.0,), (2,)),
                   SceneObject(("TST-0301 Beam001", "Part__Feature001"), True, (5000.0,), (2,)),
                   SceneObject(("beam-pair", "beam_pair"), False, (5000.0, 5000.0))]
        with self.assertRaisesRegex(ValueError, 'matches 2 STEP solids; a part placed more than once'):
            select_part_solid(objects, "TST-0301", None)


class OccurrenceSelectionContracts(unittest.TestCase):
    def test_selects_the_component_named_by_cad_motion_for_that_occurrence(self) -> None:
        pose = load_pose()
        beam = pose.Part("TST-0301", "TST-0301 Beam", None)
        labels = ["beam-pair", "TST-0301 Beam"] + [
            pose.component_name(beam, pose.assembly_data.Occurrence(oid, "TST-0301", pose.assembly_data.IDENTITY, True))
            for oid in ("beam-a", "beam-b")
        ]
        self.assertEqual(select_occurrence(labels, "@beam-b"), 3)
        self.assertEqual(select_occurrence(labels, "@beam-a"), 2)

    def test_unknown_occurrence_lists_the_available_occurrences(self) -> None:
        with self.assertRaisesRegex(ValueError, "'@beam-c' matches no STEP component.*@beam-a, @beam-b"):
            select_occurrence(["TST-0301 Beam [@beam-b]", "TST-0301 Beam [@beam-a]"], "@beam-c")

    def test_step_without_occurrence_names_says_so(self) -> None:
        with self.assertRaisesRegex(ValueError, r"no component name carries \[@id\]"):
            select_occurrence(["LMP-0002 Lower link", "=>[0:1:1:2]"], "@ring-base")

    def test_case_accepts_one_occurrence_reference_and_one_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assembly.step").touch()
            case = root / "case.yaml"
            for selection, accepted in (('occurrence: "@beam-b"', True), ("occurrence: beam-b", False),
                                        ("occurrence: TST-0301", False),
                                        ('occurrence: "@beam-b"\npart: TST-0301', False),
                                        ('occurrence: "@beam-b"\nsolid_index: 1', False)):
                case.write_text(f"step: assembly.step\n{selection}\n{CASE_TAIL}", encoding="utf-8")
                with self.subTest(selection=selection):
                    if accepted:
                        self.assertEqual(load_case(case)["occurrence"], "@beam-b")
                    else:
                        with self.assertRaises(CaseError):
                            load_case(case)


class SweepEvidenceContracts(unittest.TestCase):
    """A case may name the worst.step.json a cad-motion sweep wrote beside its worst STEP: the case STEP must be
    the one it hashes and the case pose its recorded pose. Nothing is posed again."""

    POSE = {"J-001": 240.0, "J-013": -0.0, "J-043": 3.0}

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.step = self.root / "worst.step"
        self.step.write_bytes(b"ISO-10303-21; worst pose\n")
        import hashlib
        (self.root / "worst.step.json").write_text(json.dumps({
            "criterion": "maximum_interference", "pose": self.POSE, "independent_pose": {"J-001": 240.0},
            "step": {"path": str(self.step), "sha256": hashlib.sha256(self.step.read_bytes()).hexdigest()},
            "occurrences": {"piston-3": {"PN": "VSX-0201"}, "valve-3": {"PN": "VSX-0401"}}}), encoding="utf-8")

    def case(self, extra: str) -> dict:
        path = self.root / "case.yaml"
        path.write_text(f"step: worst.step\nevidence: worst.step.json\n{extra}\n{CASE_TAIL}", encoding="utf-8")
        return load_case(path)

    def test_the_recorded_pose_is_taken_when_the_case_has_none(self) -> None:
        case = self.case('occurrence: "@piston-3"')
        self.assertEqual(case["pose"], self.POSE)
        self.assertEqual(case["_evidence"]["criterion"], "maximum_interference")
        self.assertEqual(case["_evidence"]["path"], str((self.root / "worst.step.json").resolve()))

    def test_a_pose_copied_from_the_sweep_output_matches(self) -> None:
        self.assertEqual(self.case("pose: {J-001: 240.0, J-013: 0.0000004, J-043: 3.0}")["pose"]["J-013"], 4e-7)

    def test_a_different_pose_is_refused(self) -> None:
        with self.assertRaisesRegex(CaseError, "pose is not the pose .*worst.step.json records"):
            self.case("pose: {J-001: 245.0, J-013: 0.0, J-043: 3.0}")
        with self.assertRaisesRegex(CaseError, "pose is not the pose"):
            self.case("pose: {J-001: 240.0}")  # the independent setting alone is not the posed geometry's pose

    def test_a_changed_step_is_refused(self) -> None:
        self.step.write_bytes(b"ISO-10303-21; another pose\n")
        with self.assertRaisesRegex(CaseError, "is not the STEP .*worst.step.json records"):
            self.case("")

    def test_an_occurrence_outside_the_evidence_lists_the_recorded_ones(self) -> None:
        with self.assertRaisesRegex(CaseError, "occurrence @valve-9 is not in .*available: @piston-3, @valve-3"):
            self.case('occurrence: "@valve-9"')

    def test_a_file_without_a_step_hash_is_not_evidence(self) -> None:
        (self.root / "worst.step.json").write_text(json.dumps({"pose": self.POSE}), encoding="utf-8")
        with self.assertRaisesRegex(CaseError, "is not cad-motion sweep evidence"):
            self.case("")


@unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
@unittest.skipUnless(shutil.which("uv"), "uv is required to write the occurrence STEP through OCP")
class OccurrenceAnalysis(unittest.TestCase):
    """One beam definition placed twice (fixtures/build_occurrence_step.py): `@beam-b` is turned and moved, so
    its end faces lie on y = 50 and y = 150, where neither the definition nor `@beam-a` has a face."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="cad-fea-occurrence-")
        cls.root = Path(cls.tmp.name)
        cls.step = cls.root / "beams.step"
        built = subprocess.run(["uv", "run", "--quiet", "--script", str(OCCURRENCE_FIXTURE), str(cls.step)],
                               capture_output=True, text=True, check=False, timeout=900)
        if built.returncode != 0:
            raise RuntimeError(f"occurrence fixture build failed: {built.stderr[-2000:]}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def analyse(self, name: str, selection: str) -> tuple[int, dict]:
        case = self.root / name / "case.yaml"
        case.parent.mkdir()
        case.write_text(f"step: {self.step}\n{selection}\n{CASE_TAIL}", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT), str(case)], capture_output=True, text=True, timeout=900)
        return run.returncode, json.loads(run.stdout)

    def test_explicit_occurrence_is_analysed_once_at_its_placement(self) -> None:
        status, report = self.analyse("beam-b", 'occurrence: "@beam-b"')
        self.assertEqual(status, 0, report)
        self.assertEqual(report["occurrence"], "@beam-b")
        # The cantilever of test_cantilever_matches_beam_theory_within_five_percent: 120 MPa, 2.31884 mm.
        self.assertLess(abs(report["max_von_mises_mpa"] / 120.0 - 1), 0.05)
        self.assertLess(abs(report["max_displacement_mm"] / 2.31884 - 1), 0.05)

    def test_repeated_part_number_is_ambiguous(self) -> None:
        status, report = self.analyse("by-part", "part: TST-0301")
        self.assertEqual(status, 2, report)
        self.assertRegex(report["error"]["message"], 'matches 2 STEP solids; .*occurrence: "@id"')

    def test_unknown_occurrence_lists_the_placed_ones(self) -> None:
        status, report = self.analyse("beam-c", 'occurrence: "@beam-c"')
        self.assertEqual(status, 2, report)
        self.assertIn("Available occurrences: @beam-a, @beam-b", report["error"]["message"])


@unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
class ContainerAnalysis(unittest.TestCase):
    """STEPs FreeCAD writes (fixtures/build_container_steps.py). In two-roots.step the cantilever is the unnamed child
    of the App::Part "TST-0402 Beam", whose placement puts its end faces on y = 50 and y = 150: the form of cad-model's
    LMP-0008 part STEP. multi-solid.step is the part "TST-0403 Pair" of two solids, 1000 and 2000 mm^3."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="cad-fea-container-")
        cls.root = Path(cls.tmp.name)
        built = subprocess.run([str(FREECADCMD), str(CONTAINER_FIXTURE)], capture_output=True, text=True, timeout=300,
                               env={**os.environ, "CAD_FIXTURE_OUT": str(cls.root)}, check=False)
        if not all((cls.root / name).is_file() for name in ("two-roots.step", "multi-solid.step")):
            raise RuntimeError(f"container fixture build failed: {built.stdout[-2000:]} {built.stderr[-2000:]}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def analyse(self, name: str, step: str, selection: str) -> tuple[int, dict]:
        case = self.root / name / "case.yaml"
        case.parent.mkdir()
        case.write_text(f"step: {self.root / step}\n{selection}\n{CASE_TAIL}", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT), str(case)], capture_output=True, text=True, timeout=900)
        return run.returncode, json.loads(run.stdout)

    def test_a_part_inside_a_container_is_analysed_at_its_placement(self) -> None:
        status, report = self.analyse("beam", "two-roots.step", "part: TST-0402")
        self.assertEqual(status, 0, report)
        # The cantilever of test_cantilever_matches_beam_theory_within_five_percent: 120 MPa, 2.31884 mm.
        self.assertLess(abs(report["max_von_mises_mpa"] / 120.0 - 1), 0.05)
        self.assertLess(abs(report["max_displacement_mm"] / 2.31884 - 1), 0.05)

    def test_a_part_of_several_solids_is_refused_with_their_volumes(self) -> None:
        status, report = self.analyse("pair", "multi-solid.step", "part: TST-0403")
        self.assertEqual(status, 2, report)
        self.assertEqual(report["error"]["code"], "part_multiple_solids", report)
        details = report["error"]["details"]
        self.assertEqual((details["count"], details["solid_indices"]), (2, [1, 2]))
        for volume, expected in zip(details["volumes_mm3"], (1000.0, 2000.0)):
            self.assertAlmostEqual(volume, expected, places=6)


class StaticFEAContracts(unittest.TestCase):
    def generated_job(self, case: dict) -> tuple[dict, str, Path]:
        """Start `case` with lifecycle.run stubbed: its keyword arguments, the job script and the run directory."""
        root = Path(tempfile.mkdtemp(prefix="cad-fea-job-"))
        self.addCleanup(shutil.rmtree, root, True)
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.lifecycle.run", side_effect=subprocess.TimeoutExpired("freecadcmd", 1)) as run:
            result, _ = fea_static.run_job(root / "case.yaml", {"_step": str(root / "beam.step"), **case},
                                           scratch_root=root)
        run_dir = Path(result["run_directory"])
        return run.call_args.kwargs, (run_dir / "fea_job.py").read_text(encoding="utf-8"), run_dir

    CASE = {"material": {"E": 1, "nu": 0.3, "density": 1, "yield": 1}, "fixed_faces": {"indices": [1]},
            "loads": [], "mesh_size": 1}

    def test_an_explicit_null_timeout_takes_the_default(self) -> None:
        kwargs, _, _ = self.generated_job({**self.CASE, "timeout_seconds": None})
        self.assertEqual(kwargs["timeout"], fea_static.DEFAULT_TIMEOUT_SECONDS)

    def test_the_job_runs_with_its_own_freecad_profile_outside_the_evidence(self) -> None:
        kwargs, _, run_dir = self.generated_job(self.CASE)
        env = kwargs["env"]
        self.assertEqual(env["QT_QPA_PLATFORM"], "offscreen")
        for key in ("HOME", "FREECAD_USER_HOME", "FREECAD_USER_DATA", "XDG_CONFIG_HOME"):
            with self.subTest(key=key):
                self.assertNotEqual(env[key], os.environ.get(key))
                self.assertNotIn(run_dir, Path(env[key]).parents)

    def test_the_job_pins_every_ccx_thread_count_to_one(self) -> None:
        _, script, _ = self.generated_job(self.CASE)
        self.assertEqual(job_of(script)["ccx_environment"], {"CCX_NPROC_EQUATION_SOLVER": "1",
                                                             "CCX_NPROC_STIFFNESS": "1", "CCX_NPROC_RESULTS": "1"})

    def test_a_job_stopped_while_it_writes_its_phase_leaves_no_partial_phase_file(self) -> None:
        # The parent reads the phase file after it kills a timed-out job, so the job must replace it whole.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freecad = root / "freecadcmd"
            freecad.write_text(f"""#!{sys.executable}
import json, runpy, sys
from unittest import mock
for name in ("FreeCAD", "Part", "Import", "ObjectsFem", "femmesh", "femmesh.gmshtools", "femtools", "femtools.ccxtools"):
    sys.modules[name] = mock.MagicMock()
def dump(obj, handle, **kwargs):
    handle.write('{{"pha')
    handle.flush()
    raise OSError("the job stopped mid-write")
json.dump = dump
runpy.run_path(sys.argv[1], run_name="__main__")
""", encoding="utf-8")
            freecad.chmod(0o755)
            case = {**self.CASE, "_step": str(root / "beam.step"), "timeout_seconds": 60}
            with patch("fea_static.find_freecad", return_value=freecad):
                fea_static.run_job(root / "case.yaml", case, scratch_root=root)
            phase_files = list((root / "jobs" / "fea_static").glob("*/fea_static_*_phase.json"))
            self.assertEqual(phase_files, [], [path.read_text(encoding="utf-8") for path in phase_files])

    def solve_cantilever(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="cad-fea-high-order-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            result, status = fea_static.run_job(case_path, load_case(case_path))
        self.assertEqual(status, 0, result)
        # 120 MPa and 2.31884 mm: test_cantilever_matches_beam_theory_within_five_percent
        self.assertLess(abs(result["max_von_mises_mpa"] / 120.0 - 1), 0.05)
        self.assertLess(abs(result["max_displacement_mm"] / 2.31884 - 1), 0.05)
        return result

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_valid_mesh_keeps_its_high_order_level_and_records_its_quality(self) -> None:
        quality = self.solve_cantilever()["mesh_quality"]
        self.assertEqual(quality["high_order_optimize"], fea_static.HIGH_ORDER["optimize"])
        self.assertNotIn("rejected", quality)
        self.assertGreater(quality["elements"], 0)
        self.assertEqual(quality["invalid_elements"], 0)
        self.assertGreater(quality["min_scaled_jacobian"], 0)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_fast_cantilever_reports_its_displacement_and_labelled_p95_from_the_full_mode_mesh(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-fast-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\nmode: fast\n{CANTILEVER_TAIL}", encoding="utf-8")
            result, status = fea_static.run_job(case_path, load_case(case_path))
            geo = (Path(result["run_directory"]) / "GmshInput.geo").read_text(encoding="utf-8")
        self.assertEqual(status, 0, result)
        self.assertLess(abs(result["max_displacement_mm"] / 2.31884 - 1), 0.05)  # beam theory, as the full solve
        indicator = result["mesh_stability_indicator"]
        self.assertIn("mesh-stability indicator", indicator["label"])
        self.assertIn("not a strength value", indicator["label"])
        self.assertIn("separate stress study", result["stress_study"])
        self.assertGreater(indicator["p95_von_mises_mpa"], 0)
        self.assertEqual(indicator["nodes"], result["node_count"])
        self.assertEqual({"max_von_mises_mpa", "safety_factor_yield", "required_safety_factor"} & set(result), set())
        # Fast mode withholds stress only: it meshes curved second-order elements at full mode's high-order level.
        self.assertEqual(result["mesh_quality"]["high_order_optimize"], fea_static.HIGH_ORDER["optimize"])
        self.assertRegex(geo, r"(?m)^Mesh[.]SecondOrderLinear = 0;")
        self.assertRegex(geo, r"(?m)^Mesh[.]HighOrderOptimize = %d;" % fea_static.HIGH_ORDER["optimize"])

    def solve_tube(self, root: Path, high_order: dict) -> tuple[dict, int]:
        """A thin brass tube (outer radius 3.985, bore 2.55, 8 long) at mesh_size 4, solved in `root`: with no
        high-order optimization, Gmsh curves its second-order nodes onto the bore and inverts two elements."""
        step = root / "tube.step"
        job = root / "make_tube.py"
        job.write_text(f'''import FreeCAD as App, Part, Import
doc=App.newDocument("Tube")
tube=doc.addObject("Part::Feature", "Tube")
tube.Shape=Part.makeCylinder(3.985, 8).cut(Part.makeCylinder(2.55, 8))
doc.recompute()
Import.export([tube], {str(step)!r})
App.closeDocument(doc.Name)
''', encoding="utf-8")
        built = subprocess.run([str(FREECADCMD), str(job)], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertTrue(step.is_file(), built.stdout + built.stderr)
        case_path = root / "case.yaml"
        case_path.write_text(f"""step: {step}
material: {{E: 97000, nu: 0.34, density: 8500, yield: 124}}
fixed_faces: {{plane: {{axis: z, value: 8, tolerance: 0.000001}}}}
loads: [{{selector: {{plane: {{axis: z, value: 0, tolerance: 0.000001}}}}, force: [0, 0, 500]}}]
mesh_size: 4
""", encoding="utf-8")
        with patch.dict(fea_static.HIGH_ORDER, high_order):
            return fea_static.run_job(case_path, load_case(case_path), scratch_root=root)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_mesh_with_invalid_elements_is_remeshed_at_the_fallback_level(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-tube-") as directory:
            result, status = self.solve_tube(Path(directory), {"optimize": 0, "fallback": 2})
        self.assertEqual(status, 0, result)
        quality = result["mesh_quality"]
        self.assertEqual((quality["high_order_optimize"], quality["invalid_elements"]), (2, 0))
        self.assertEqual(quality["rejected"]["high_order_optimize"], 0)
        self.assertGreater(quality["rejected"]["invalid_elements"], 0)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_an_invalid_mesh_at_the_terminal_level_is_refused_before_it_is_solved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-tube-") as directory:
            root = Path(directory)
            solves = root / "ccx-solves.log"
            ccx = root / "ccx"  # $CCX: identifies itself as CalculiX, and records every solve (-i) the job requests
            ccx.write_text(f"""#!{sys.executable}
import sys
print("CalculiX Version 2.23", flush=True)
if "-i" in [arg.strip() for arg in sys.argv[1:]]:
    open({str(solves)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")
    sys.exit(1)
""", encoding="utf-8")
            ccx.chmod(0o755)
            with patch.dict(os.environ, {"CCX": str(ccx)}):
                result, status = self.solve_tube(root, {"optimize": 0, "fallback": 0})
            self.assertEqual((status, result["error"]["code"]), (2, "mesh_invalid"), result)
            details = result["error"]["details"]
            self.assertEqual(details["high_order_optimize"], 0)
            self.assertGreater(details["invalid_elements"], 0)
            self.assertLess(details["min_scaled_jacobian"], 0)
            run_dir = Path(result["run_directory"])
            self.assertTrue(run_dir.is_dir())
            self.assertTrue((run_dir / "GmshInput.geo").is_file())  # the job meshed in this run directory
            self.assertFalse(solves.exists(), solves.read_text(encoding="utf-8") if solves.exists() else "")
            self.assertEqual(list(run_dir.glob("GmshMesh.frd")), [])

    def test_a_failed_job_keeps_its_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = {**self.CASE, "_step": str(root / "beam.step"), "timeout_seconds": 60}
            with patch("fea_static.find_freecad", return_value=failing_freecad(root)):
                result, status = fea_static.run_job(root / "case.yaml", case, scratch_root=root)
        self.assertEqual((status, result["error"]["code"]), (2, "analysis_failed"), result)
        self.assertIn("Traceback (most recent call last)", result["traceback"])
        self.assertIn("RuntimeError: import exploded", result["traceback"])

    def test_run_directory_is_nested_under_case_runs(self) -> None:
        case = Path(tempfile.gettempdir()) / "analysis" / "case.yaml"
        self.assertEqual(run_directory(case, "abc123"), case.parent.resolve() / "runs" / "abc123")

    def test_required_safety_factor_controls_completed_verdict(self) -> None:
        base = {"safety_factor_yield": 2.5}
        self.assertEqual(apply_required_safety_factor(base.copy(), 2)["status"], "pass")
        self.assertEqual(apply_required_safety_factor(base.copy(), 600)["status"], "fail")
        self.assertEqual(apply_required_safety_factor(base.copy(), None)["status"], "pass")

    def test_exit_codes_distinguish_failed_check_from_no_result(self) -> None:
        self.assertEqual(result_exit_code({"status": "pass"}), 0)
        self.assertEqual(result_exit_code({"status": "fail"}), 1)
        self.assertEqual(result_exit_code({"status": "error"}), 2)
        self.assertEqual(result_exit_code({}), 2)

    def test_empty_plane_selector_fails_case_validation_with_exit_two(self) -> None:
        from fea_static import CaseError, load_case
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "part.step").touch()
            case = root / "case.yaml"
            case.write_text(
                """step: part.step
material: {E: 69000, nu: 0.33, density: 2700, yield: 276}
fixed_faces: {plane: {}}
loads: [{selector: {indices: [1]}, force: [0, 0, 50]}]
mesh_size: 5
""", encoding="utf-8")
            with self.assertRaises(CaseError):
                load_case(case)

    def test_empty_plane_selection_is_a_no_result_input(self) -> None:
        from fea_static import CaseError, selected_face_indices

        class Bounds:
            XMin = XMax = 4.0

        class Face:
            BoundBox = Bounds()
        with self.assertRaisesRegex(CaseError, "matched no faces"):
            selected_face_indices(1, {"plane": {"axis": "x", "value": 0.0, "tolerance": 0.01}}, [Face()])
        self.assertEqual(result_exit_code(error("invalid plane selector")), 2)

    def test_multi_solid_accepts_one_based_selection_index(self) -> None:
        from fea_static import load_case, CaseError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "part.step").touch()
            case = root / "case.yaml"
            case.write_text(
                """step: part.step
solid_index: 2
material: {E: 69000, nu: 0.33, density: 2700, yield: 276}
fixed_faces: {indices: [1]}
loads: [{selector: {indices: [2]}, force: [0, 0, 50]}]
mesh_size: 5
""", encoding="utf-8")
            self.assertEqual(load_case(case)["solid_index"], 2)
            case.write_text(case.read_text(encoding="utf-8").replace("solid_index: 2", "solid_index: 0"), encoding="utf-8")
            with self.assertRaises(CaseError):
                load_case(case)

    def test_multi_solid_selection_uses_one_based_solid_index(self) -> None:
        names = [["LMP-0001 Base"], ["LMP-0001 Base"]]
        self.assertEqual(select_solid_index(names, None, 2), 1)
        with self.assertRaisesRegex(ValueError, "out of range"):
            select_solid_index(names, None, 3)

    def test_freecad_lookup_uses_home_path_and_case_insensitive_candidate_names(self) -> None:
        from freecad_lookup import find_freecad

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "bin" / "freecadcmd"
            command.parent.mkdir(parents=True)
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            with patch.dict("os.environ", {"HOME": str(root), "PATH": str(command.parent)}, clear=True):
                self.assertEqual(find_freecad(), command)
    def test_freecad_lookup_does_not_fallback_from_invalid_environment_override(self) -> None:
        from freecad_lookup import find_freecad

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            on_path = root / "freecadcmd"
            on_path.write_text("#!/bin/sh\n", encoding="utf-8")
            on_path.chmod(0o755)
            with patch.dict("os.environ", {"FREECADCMD": str(root / "missing"), "PATH": str(root)}, clear=True):
                self.assertEqual(find_freecad(), root / "missing")
            self.assertTrue(on_path.is_file())

    def test_missing_freecad_is_structured_exit_two(self) -> None:
        from unittest.mock import patch
        from fea_static import main
        with patch("fea_static.find_freecad", return_value=None):
            self.assertEqual(main(["unused.yaml"]), 2)

    def make_cantilever_step(self, root: Path, label: str = "Beam") -> Path:
        step = root / "cantilever.step"
        job = root / "make_cantilever.py"
        job.write_text(
            f'''import FreeCAD as App, Part, Import
doc=App.newDocument("CantileverFixture")
beam=doc.addObject("Part::Feature", "Beam")
beam.Label={label!r}
beam.Shape=Part.makeBox(100, 10, 5)
doc.recompute()
Import.export([beam], {str(step)!r})
App.closeDocument(doc.Name)
''', encoding="utf-8")
        generated = subprocess.run([str(FREECADCMD), str(job)], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertIn(generated.returncode, (0, 139), generated.stdout + generated.stderr)
        self.assertTrue(step.is_file() and step.stat().st_size > 0, generated.stdout + generated.stderr)
        return step

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_cantilever_matches_beam_theory_within_five_percent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-cantilever-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            case = root / "case.yaml"
            case.write_text(
                f"""step: {step}
pose: {{J-001: 17, J-002: -42}}
material: {{name: Aluminium 6061, E: 69000, nu: 0.33, density: 2700, yield: 276}}
fixed_faces: {{plane: {{axis: x, value: 0, tolerance: 0.000001}}}}
loads:
  - selector: {{plane: {{axis: x, value: 100, tolerance: 0.000001}}}}
    force: [0, 0, -50]
mesh_size: 5
""", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(case)], capture_output=True, text=True, timeout=600)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass", report)
            self.assertLess(abs(report["max_von_mises_mpa"] / 120.0 - 1), 0.05)
            self.assertLess(abs(report["max_displacement_mm"] / 2.31884 - 1), 0.05)
            self.assertGreater(report["node_count"], 0)
            self.assertGreater(report["element_count"], 0)
            self.assertTrue((root / "results.json").is_file())
            self.assertEqual(report["worst_case_pose"], {"step": str(step), "pose": {"J-001": 17, "J-002": -42}})

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_identical_case_repeats_mesh_and_stress_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-repeat-") as directory:
            root = Path(directory)
            step = root / "beam.step"
            job = root / "make_beam.py"
            job.write_text(
                f'''import FreeCAD as App, Part, Import
doc=App.newDocument("Beam")
beam=doc.addObject("Part::Feature", "Beam")
beam.Shape=Part.makeBox(100, 10, 5)
doc.recompute()
Import.export([beam], {str(step)!r})
App.closeDocument(doc.Name)
''', encoding="utf-8")
            generated = subprocess.run([str(FREECADCMD), str(job)], cwd=root, capture_output=True, text=True, timeout=120)
            self.assertIn(generated.returncode, (0, 139), generated.stdout + generated.stderr)
            case = root / "case.yaml"
            case.write_text(
                f"""step: {step}
material: {{name: Aluminum, E: 69000, nu: 0.33, density: 2700, yield: 276}}
fixed_faces: {{plane: {{axis: x, value: 0, tolerance: 0.000001}}}}
loads: [{{selector: {{plane: {{axis: x, value: 100, tolerance: 0.000001}}}}, force: [0, 0, -50]}}]
mesh_size: 5
""", encoding="utf-8")
            reports = []
            for _ in range(2):
                run = subprocess.run([sys.executable, str(SCRIPT), str(case)], capture_output=True, text=True, timeout=600)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                reports.append(json.loads(run.stdout))
            self.assertEqual(reports[0]["node_count"], reports[1]["node_count"])
            self.assertEqual(reports[0]["element_count"], reports[1]["element_count"])
            self.assertEqual(reports[0]["mesh_input_hashes"]["geometry_sha256"], reports[1]["mesh_input_hashes"]["geometry_sha256"])
            self.assertEqual(reports[0]["mesh_input_hashes"]["geo_sha256"], reports[1]["mesh_input_hashes"]["geo_sha256"])
            self.assertLessEqual(abs(reports[0]["safety_factor_yield"] / reports[1]["safety_factor_yield"] - 1), 0.0025)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_invalid_face_selector_is_structured_exit_two(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-case-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            case = root / "case.yaml"
            case.write_text(
                f"""step: {step}
material: {{E: 69000, nu: 0.33, density: 2700, yield: 276}}
fixed_faces: {{indices: [0]}}
loads: [{{selector: {{indices: [1]}}, force: [0, 0, 50]}}]
mesh_size: 5
""", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(case)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_case")

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_ccx_crash_inside_spooles_is_a_diagnosed_no_result(self) -> None:
        from fea_static import run_job
        with tempfile.TemporaryDirectory(prefix="cad-fea-ccx-crash-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            # A ccx that, like the phone-stand SPOOLES overflow, enters the factorisation and segfaults.
            ccx = root / "ccx"
            ccx.write_text(f"""#!{sys.executable}
import os, signal, sys
print("CalculiX Version 2.23", flush=True)
if len(sys.argv) > 1:
    open("spooles.out", "w").close()
    os.kill(os.getpid(), signal.SIGSEGV)
""", encoding="utf-8")
            ccx.chmod(0o755)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            with patch.dict(os.environ, {"CCX": str(ccx)}):  # the job's ccx override
                result, status = run_job(case_path, load_case(case_path))
            self.assertEqual(status, 2, result)
            self.assertEqual(result["error"]["code"], "solver_crashed", result)
            details = result["error"]["details"]
            self.assertEqual((details["signal"], details["stage"]), ("SIGSEGV", "spooles_factorisation"))
            self.assertGreater(details["node_count"], 0)
            self.assertEqual(details["degrees_of_freedom"], 3 * details["node_count"])
            self.assertIn("inside the SPOOLES equation solver", result["error"]["message"])

    def stand_in(self, root: Path, tool: str, body: str) -> Path:
        """A $CCX or $GMSH stand-in at root/<tool>: it runs `body`, then hands its arguments on to the real tool.
        It finds that tool when it runs, beside the executable of the FreeCAD process that started it (where the
        macOS app and an extracted or mounted AppImage keep ccx and gmsh), else on PATH. A path probed earlier could
        be inside an AppImage mount that ended with the probe."""
        path = root / tool
        script = root / f"{tool}.stand-in.py"
        # A shell front: it sets FreeCAD's PYTHONHOME, PYTHONPATH and LD_LIBRARY_PATH (a mounted AppImage sets its
        # own) aside, so they never steer this test's Python, and the real tool gets them back as FreeCAD set them.
        names = ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH")
        saved = "".join(f'CAD_HAD_{n}=${{{n}+1}} CAD_{n}=${{{n}-}}; export CAD_HAD_{n} CAD_{n}; unset {n}\n' for n in names)
        path.write_text(f'''#!/bin/sh
{saved}exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"
''', encoding="utf-8")
        script.write_text(f'''import os, shutil, subprocess, sys
def parent_and_executable(pid):
    if os.path.exists("/proc/%d/exe" % pid):
        with open("/proc/%d/stat" % pid, encoding="utf-8") as stat:
            parent = int(stat.read().rsplit(")", 1)[1].split()[1])
        return parent, os.path.realpath("/proc/%d/exe" % pid)
    found = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout.split(None, 1)
    return (int(found[0]), os.path.realpath(found[1].strip())) if len(found) == 2 else (0, "")
def real_tool(name):
    pid = os.getppid()
    while pid > 1:
        parent, executable = parent_and_executable(pid)
        beside = os.path.join(os.path.dirname(executable), name)
        if os.path.basename(executable).lower().startswith("freecad") and os.access(beside, os.X_OK):
            return beside
        pid = parent
    here = os.path.dirname(os.path.realpath(sys.argv[0]))
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if os.path.realpath(p) != here)
    return shutil.which(name, path=path) or sys.exit("%s: no %s beside a FreeCAD process or on PATH" % (sys.argv[0], name))
real = real_tool({tool!r})
with open({str(root / (tool + "-calls.log"))!r}, "a", encoding="utf-8") as log:
    log.write(" ".join([real, *sys.argv[1:]]) + "\\n")
{body}
for name in {names!r}:
    if os.environ.pop("CAD_HAD_" + name, ""):
        os.environ[name] = os.environ.get("CAD_" + name, "")
    os.environ.pop("CAD_" + name, None)
os.execv(real, [real, *sys.argv[1:]])
''', encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def solve_calls(root: Path) -> list[str]:
        """The ccx stand-in's solve calls: FreeCAD passes `-i <name>` to solve and `-v` to read the version."""
        calls = (root / "ccx-calls.log").read_text(encoding="utf-8").splitlines()
        return [line for line in calls if any(arg.strip() == "-i" for arg in line.split(" "))]

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_load_that_reaches_no_mesh_node_is_an_error_not_a_pass(self) -> None:
        """Issue #143: on a straight-sided second-order mesh, a load on a bore reaches no node of the ccx input.
        A $GMSH stand-in meshes that way. The run must refuse before ccx runs, instead of passing at stress 0."""
        with tempfile.TemporaryDirectory(prefix="cad-fea-unapplied-load-") as directory:
            root = Path(directory)
            step, bore = root / "block.step", root / "bore.json"
            job = root / "make_block.py"
            job.write_text(f'''import json, FreeCAD as App, Part, Import
doc=App.newDocument("BoredBlock")
block=doc.addObject("Part::Feature", "Block")
block.Shape=Part.makeBox(100, 40, 14, App.Vector(-50, -20, 0)).fuse(Part.makeBox(50, 40, 36, App.Vector(-25, -20, 14))).cut(
    Part.makeCylinder(12.5, 40, App.Vector(0, -20, 32), App.Vector(0, 1, 0))).removeSplitter()  # pillow_block, no bolt holes
doc.recompute()
Import.export([block], {str(step)!r})
App.closeDocument(doc.Name)
read=App.newDocument("Read"); Import.insert({str(step)!r}, read.Name)
faces=[o for o in read.Objects if o.isDerivedFrom("Part::Feature") and o.Shape.Solids][0].Shape.Faces
json.dump([i + 1 for i, f in enumerate(faces) if f.Surface.__class__.__name__ == "Cylinder"], open({str(bore)!r}, "w"))
''', encoding="utf-8")
            generated = subprocess.run([str(FREECADCMD), str(job)], cwd=root, capture_output=True, text=True, timeout=120)
            self.assertTrue(bore.is_file(), generated.stdout + generated.stderr)
            bore_faces = json.loads(bore.read_text(encoding="utf-8"))
            self.assertTrue(bore_faces)
            gmsh = self.stand_in(root, "gmsh", '''import re
for arg in sys.argv[1:]:
    if arg.endswith(".geo"):  # the bias campaign's straight-sided settings, set where the job's .geo sets them
        text = open(arg, encoding="utf-8").read()
        for key, value in (("SecondOrderLinear", 1), ("HighOrderOptimize", 0)):
            text, found = re.subn(r"(?m)^Mesh[.]%s[ \\t]*=[^;]*;" % key, "Mesh.%s = %d;" % (key, value), text)
            if not found:
                text = text.replace("Mesh  3;", "Mesh.%s = %d;\\nMesh  3;" % (key, value), 1)
        open(arg, "w", encoding="utf-8").write(text)''')
            ccx = self.stand_in(root, "ccx", "")  # records each call, so the test sees whether the job asked ccx to solve
            case_path = root / "case.yaml"
            case_path.write_text(f"""step: {step}
material: {{E: 210000, nu: 0.3, density: 7850, yield: 355}}
fixed_faces: {{plane: {{axis: z, value: 0, tolerance: 0.000001}}}}
loads: [{{selector: {{indices: {bore_faces}}}, force: [0, 0, 25000]}}]
mesh_size: 10
""", encoding="utf-8")
            with patch.dict(os.environ, {"GMSH": str(gmsh), "CCX": str(ccx)}):
                result, status = fea_static.run_job(case_path, load_case(case_path))
            self.assertEqual(status, 2, result)
            self.assertEqual(result["error"]["code"], "load_not_applied", result)
            self.assertEqual(result["error"]["details"]["loads"], [{"constraint": "FaceForce0", "force_n": 25000.0, "nodes": 0}])
            self.assertNotIn("max_von_mises_mpa", result)
            self.assertTrue((root / "ccx-calls.log").is_file(), "the job never ran the ccx stand-in, not even its version probe")
            self.assertEqual(self.solve_calls(root), [], "ccx was asked to solve an input whose load reaches no node")
            meshed = [line for line in (root / "gmsh-calls.log").read_text(encoding="utf-8").splitlines() if line.endswith(".geo")]
            self.assertEqual(len(meshed), 1, meshed)  # the stand-in meshed, so the empty load is the straight-sided one

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_zero_result_under_a_nonzero_load_is_an_error_not_a_pass(self) -> None:
        """A load that reaches the input but not ccx: a $CCX stand-in drops the *CLOAD node lines, then runs the
        real ccx. The cantilever then gives stress 0 and displacement 0, and the job must refuse that result."""
        with tempfile.TemporaryDirectory(prefix="cad-fea-zero-result-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            ccx = self.stand_in(root, "ccx", '''flag = next((i for i, arg in enumerate(sys.argv) if arg.strip() == "-i"), None)  # "-i " (ccxtools)
if flag is not None:
    path = sys.argv[flag + 1] + ".inp"
    kept, loads = [], False
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.upper().startswith("*CLOAD"):
            loads = True
        elif line.startswith("*") and not line.startswith("**"):
            loads = False
        elif loads and line[:1].isdigit():
            continue
        kept.append(line)
    open(path, "w", encoding="utf-8").write("\\n".join(kept) + "\\n")''')
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            with patch.dict(os.environ, {"CCX": str(ccx)}):
                result, status = fea_static.run_job(case_path, load_case(case_path))
            self.assertEqual(status, 2, result)
            self.assertEqual(result["error"]["code"], "zero_result", result)
            self.assertEqual(result["error"]["details"]["applied_force_n"], 50.0)
            self.assertEqual((result["error"]["details"]["max_von_mises_mpa"],
                              result["error"]["details"]["max_displacement_mm"]), (0.0, 0.0))
            self.assertEqual(len(self.solve_calls(root)), 1)  # ccx solved once: the refusal reads its result

    def reaction_run(self, root: Path, design_n: float, failing: bool = False) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run the 50 N cantilever case as a versioned case whose load names IF-006, whose sealed stop-reaction bundle
        holds a design reaction of `design_n` (a failing bundle, its recorded contact load understated, when `failing`).
        The $CCX stand-in records every call. The real FreeCAD does the rest."""
        reaction = load_reaction_project()
        scenario = reaction.Scenario(self)
        step = self.make_cantilever_step(root, "TST-0101 Beam")
        shutil.copyfile(step, scenario.case_dir / "beam.step")
        scenario.case.write_text("step: beam.step\n" + CANTILEVER_VERSIONED_TAIL.replace("force: [0, 0, -50]}",
                                                                                      "force: [0, 0, -50], reaction: IF-006}"), encoding="utf-8")
        if failing:
            scenario.publish({"IF-006": reaction.entry("fail", {"min": reaction.end("understated", design_n)},
                                                       recorded_contact_load_n=design_n / 2)}, outcome="fail")
        else:
            scenario.publish({"IF-006": reaction.entry(ends={"min": reaction.end("bounded", design_n)})})
        ccx = self.stand_in(root, "ccx", "pass")
        with patch.dict(os.environ, {"CCX": str(ccx)}):
            done = subprocess.run([sys.executable, str(SCRIPT), str(scenario.case), "--hw", str(scenario.hw), "--version", "v1"],
                                  capture_output=True, text=True, timeout=900)
        return done, scenario.hw

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_load_below_the_modelled_stop_reaction_is_refused_before_ccx_runs(self) -> None:
        """#153: the 50 N load names a stop whose design reaction is 60 N. fea_static refuses before it meshes, probes
        the solvers or starts ccx. The $CCX stand-in gets no call at all, not even for its version."""
        with tempfile.TemporaryDirectory(prefix="cad-fea-reaction-below-") as directory:
            root = Path(directory)
            done, hw = self.reaction_run(root, 60.0)
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertEqual(json.loads(done.stdout)["error"]["code"], "reaction_below_design")
            self.assertFalse((root / "ccx-calls.log").exists(), "ccx ran for a case refused before the solve")
            self.assertFalse((hw / "analysis" / "v1").exists())

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_load_at_the_modelled_stop_reaction_is_solved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-reaction-at-") as directory:
            root = Path(directory)
            done, hw = self.reaction_run(root, 50.0)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(json.loads(done.stdout)["status"], "pass")
            self.assertEqual(len(self.solve_calls(root)), 1, "ccx solved the case once")
            manifest = json.loads((hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["recipe"]["reactions"]["IF-006"]["design_reaction_n"], 50.0)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_load_that_meets_the_design_reaction_of_a_failing_bundle_is_solved(self) -> None:
        """The stop-reaction check failed (its recorded contact load is below the design reaction). The corrective FEA case
        runs all the same: the 50 N load meets the 40 N design reaction, and the recipe records that reaction."""
        with tempfile.TemporaryDirectory(prefix="cad-fea-reaction-fail-") as directory:
            root = Path(directory)
            done, hw = self.reaction_run(root, 40.0, failing=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(json.loads(done.stdout)["status"], "pass")
            self.assertEqual(len(self.solve_calls(root)), 1, "ccx solved the case once")
            manifest = json.loads((hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["recipe"]["reactions"]["IF-006"]["design_reaction_n"], 40.0)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_gmsh_tools_mesh_with_the_gmsh_the_job_resolved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-gmsh-override-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            calls = root / "gmsh-calls.log"
            gmsh = root / "override" / "gmsh"  # $GMSH: logs its arguments, then runs FreeCAD's Gmsh from PATH
            gmsh.parent.mkdir()
            gmsh.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexec gmsh "$@"\n', encoding="utf-8")
            gmsh.chmod(0o755)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            with patch.dict(os.environ, {"GMSH": str(gmsh)}):
                result, status = fea_static.run_job(case_path, load_case(case_path))
            self.assertEqual(status, 0, result)
            meshed = [line for line in calls.read_text(encoding="utf-8").splitlines() if line.endswith(".geo")]
        self.assertEqual(len(meshed), 1, meshed)

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_ccx_starts_with_one_thread_in_each_parallel_stage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-ccx-threads-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            seen = root / "ccx-environment.json"
            ccx = root / "ccx"  # a ccx that records the environment it solves in, then fails
            ccx.write_text(f"""#!{sys.executable}
import json, os, sys
print("CalculiX Version 2.23", flush=True)
if len(sys.argv) > 1:
    json.dump({{key: os.environ.get(key) for key in {sorted(fea_static.CCX_ENVIRONMENT)!r}}}, open({str(seen)!r}, "w"))
    sys.exit(1)
""", encoding="utf-8")
            ccx.chmod(0o755)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            with patch.dict(os.environ, {"CCX": str(ccx)}):
                result, status = fea_static.run_job(case_path, load_case(case_path))
            self.assertEqual(status, 2, result)
            self.assertEqual(json.loads(seen.read_text(encoding="utf-8")),
                             {"CCX_NPROC_EQUATION_SOLVER": "1", "CCX_NPROC_RESULTS": "1", "CCX_NPROC_STIFFNESS": "1"})

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_solver_whose_version_changed_since_the_probe_is_refused_before_meshing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-fea-solver-changed-") as directory:
            root = Path(directory)
            step = self.make_cantilever_step(root)
            case_path = root / "case.yaml"
            case_path.write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            result, status = fea_static.run_job(case_path, load_case(case_path),
                                                solver_versions={"calculix": {"path": "/elsewhere/ccx", "version": "0.1"}})
            self.assertEqual((status, result["error"]["code"]), (2, "solver_changed"), result)
            self.assertIn("not the recorded 0.1", result["error"]["message"])
            self.assertEqual(list(Path(result["run_directory"]).glob("GmshMesh*")), [])

    def assert_timeout_names_the_import_phase_and_stops_the_children(self, startup_seconds: float) -> None:
        from fea_static import run_job
        with tempfile.TemporaryDirectory(prefix="cad-fea-timeout-") as directory:
            root = Path(directory)
            step = root / "part.step"
            step.touch()
            child_pid = root / "child.pid"
            freecad = hanging_freecad(root, child_pid, startup_seconds)
            case = hanging_case(step, timeout_seconds=1)
            with patch("fea_static.find_freecad", return_value=freecad), timeout_clock_after_phase():
                result, status = run_job(root / "case.yaml", case,
                                         solver_versions={"calculix": {"path": "/unused/ccx", "version": "2.23"}})
            self.assertEqual(status, 2)
            self.assertEqual(result["error"]["code"], "freecad_timeout")
            self.assertEqual(result["error"]["details"], {"phase": "import"})
            self.assertIn("timeout_seconds of 1 while importing the STEP; raise timeout_seconds in the case YAML",
                          result["error"]["message"])
            pid = int(child_pid.read_text(encoding="utf-8"))
            self.assertTrue(wait_until(lambda: not pid_runs(pid)), "a child of the timed-out FreeCAD job is still running")

    def test_case_timeout_names_the_phase_its_knob_and_stops_the_jobs_children(self) -> None:
        self.assert_timeout_names_the_import_phase_and_stops_the_children(startup_seconds=0)

    def test_a_stand_in_that_starts_slower_than_the_old_5_s_budget_still_times_out_in_its_import_phase(self) -> None:
        self.assert_timeout_names_the_import_phase_and_stops_the_children(startup_seconds=6)

    def test_killing_the_fea_process_outright_stops_the_job_and_frees_its_run_record(self) -> None:
        lifecycle = fea_static.lifecycle
        with tempfile.TemporaryDirectory(prefix="cad-fea-killed-") as directory:
            root = Path(directory).resolve()
            hw = root / "hw"
            hw.mkdir()
            step = root / "part.step"
            step.touch()
            child_pid = root / "child.pid"
            freecad = hanging_freecad(root, child_pid)
            # The FEA process lists the job's group in its run record only after the job has started (Supervised
            # writes it after `ps` identifies the supervisor); a 2 s delay there holds that window open on any host.
            parent_code = (f"import sys, time\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
                           f"sys.path.insert(0, {str(SCRIPT.parent)!r})\nimport fea_static\n"
                           "register = fea_static.lifecycle.RunGuard._register\n"
                           "def late_register(guard, process):\n"
                           "    time.sleep(2)\n"
                           "    register(guard, process)\n"
                           "fea_static.lifecycle.RunGuard._register = late_register\n"
                           f"guard = fea_static.lifecycle.claim_run(Path({str(hw)!r}), 'fea')\n"
                           f"with patch('fea_static.find_freecad', return_value=Path({str(freecad)!r})):\n"
                           f"    fea_static.run_job(Path({str(root)!r}) / 'case.yaml', {hanging_case(step, 600)!r}, "
                           "guard=guard, solver_versions={'calculix': {'path': '/unused/ccx', 'version': '2.23'}})\n")
            parent = subprocess.Popen([sys.executable, "-c", parent_code], start_new_session=True,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(parent.wait)
            self.addCleanup(lambda: parent.poll() is None and os.killpg(parent.pid, signal.SIGKILL))
            self.assertTrue(wait_until(child_pid.is_file, 60), "the FreeCAD stand-in did not start its child")
            pid = int(child_pid.read_text(encoding="utf-8"))
            self.addCleanup(lambda: pid_runs(pid) and os.kill(pid, signal.SIGKILL))
            [record] = lifecycle.runs_dir(hw).glob("*.json")

            def groups() -> list:
                return json.loads(record.read_text(encoding="utf-8"))["groups"]

            self.assertTrue(wait_until(lambda: len(groups()) == 1, 60),
                            f"the run record never listed the FreeCAD job's process group: {record.read_text()}")
            [group] = groups()
            with self.assertRaises(lifecycle.RunRefused):  # one FEA run at a time
                lifecycle.claim_run(hw, "fea")
            os.killpg(parent.pid, signal.SIGKILL)  # the FEA process and its own group, with no chance to clean up
            parent.wait()
            self.assertTrue(wait_until(lambda: not pid_runs(pid)), "the FreeCAD job's child outlived the killed FEA run")
            self.assertTrue(wait_until(lambda: not group_runs(group["pgid"])), "the FreeCAD job's group outlived it")
            self.assertEqual(lifecycle.strays(hw), [])
            lifecycle.claim_run(hw, "fea").release()

    def test_two_fea_cases_run_at_once_and_the_same_case_twice_is_refused(self) -> None:
        lifecycle = fea_static.lifecycle
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            (project / "hw").mkdir()
            step = project / "beam.step"
            step.touch()
            cases = {}
            for name in ("bending", "torsion"):
                cases[name] = project / name / "case.yaml"
                cases[name].parent.mkdir()
                cases[name].write_text(f"step: {step}\n{CANTILEVER_TAIL}", encoding="utf-8")
            # a running FEA run of the bending case, recorded as fea_static.py records a scratch case
            holder = subprocess.Popen([sys.executable, "-c", f"import sys, time\nsys.path.insert(0, {str(SCRIPT.parent)!r})\n"
                                       f"import fea_static\nfea_static.lifecycle.claim_run({str(project / 'hw')!r}, 'fea', "
                                       f"scope={str(cases['bending'])!r})\nprint('claimed', flush=True)\ntime.sleep(600)\n"],
                                      stdout=subprocess.PIPE, text=True)
            self.addCleanup(lambda: (holder.kill(), holder.wait(), holder.stdout.close()))
            self.assertEqual(holder.stdout.readline().strip(), "claimed")

            def run(name: str) -> tuple:
                printed = __import__("io").StringIO()
                with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), patch("sys.stdout", printed), \
                     patch("fea_static.run_job", return_value=({"status": "pass", "run_directory": None}, 0)) as job:
                    status = fea_static.main([str(cases[name]), "--out", str(project / ".cad-work" / name / "result.json")])
                return status, json.loads(printed.getvalue()), job

            status, report, job = run("torsion")  # another case runs beside it, recorded while it runs
            self.assertEqual((status, report["status"], job.call_count), (0, "pass", 1), report)
            self.assertIsNotNone(job.call_args.kwargs["guard"])
            status, report, job = run("bending")  # the same case again is refused before it starts
            self.assertEqual((status, report["error"]["code"], job.call_count), (2, "run_refused", 0))
            self.assertIn(f"still runs as process {holder.pid}; stop it with `kill -TERM {holder.pid}`",
                          report["error"]["message"])
            self.assertEqual(len(list(lifecycle.runs_dir(project / "hw").glob("*.json"))), 1)

    def test_timeout_seconds_must_be_a_positive_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "part.step").touch()
            case = root / "case.yaml"
            for value in ("0", "-5", "true", "soon"):
                with self.subTest(value=value):
                    case.write_text(f"step: part.step\ntimeout_seconds: {value}\n{CASE_TAIL}", encoding="utf-8")
                    with self.assertRaisesRegex(CaseError, "timeout_seconds must be a positive finite number"):
                        load_case(case)
            case.write_text(f"step: part.step\ntimeout_seconds: 1800\n{CASE_TAIL}", encoding="utf-8")
            self.assertEqual(load_case(case)["timeout_seconds"], 1800)


class CcxFailureDiagnosis(unittest.TestCase):
    """What a failed ccx run reports; the phone-stand SPOOLES crash had 374,134 nodes."""

    def test_clean_exit_is_not_a_failure(self) -> None:
        self.assertIsNone(ccx_failure(0, "", spooles_started=True, node_count=10))

    def test_large_model_crash_in_spooles_names_the_front_overflow_and_the_remedy(self) -> None:
        # SIGSEGV, SIGBUS (the same overflow with a larger stack), and SIGSEGV through a shell wrapper.
        for returncode in (-signal.SIGSEGV, -signal.SIGBUS, 128 + signal.SIGSEGV):
            with self.subTest(returncode=returncode):
                failure = ccx_failure(returncode, "CalculiX Version 2.23\n", spooles_started=True, node_count=374_134)
                self.assertEqual(failure["code"], "solver_crashed")
                self.assertEqual(failure["details"]["degrees_of_freedom"], 1_122_402)
                self.assertIn("more than 46,340 fronts", failure["message"])
                self.assertIn("Increase mesh_size", failure["message"])

    def test_small_model_crash_in_spooles_is_not_blamed_on_the_overflow(self) -> None:
        failure = ccx_failure(-signal.SIGSEGV, "", spooles_started=True, node_count=2_000)
        self.assertEqual(failure["code"], "solver_crashed")
        self.assertIn("too few for SPOOLES's 46,340-front overflow", failure["message"])
        self.assertNotIn("Increase mesh_size", failure["message"])

    def test_crash_before_the_solver_is_not_blamed_on_spooles(self) -> None:
        failure = ccx_failure(-signal.SIGSEGV, "", spooles_started=False, node_count=374_134)
        self.assertEqual(failure["details"]["stage"], "before_equation_solver")
        self.assertIn("before reaching the SPOOLES equation solver", failure["message"])
        self.assertNotIn("46,340", failure["message"])

    def test_nonpositive_jacobian_lists_the_rejected_elements(self) -> None:
        stdout = "".join(f" *ERROR in e_c3d: nonpositive jacobian\n        determinant in element       {element}\n\n"
                         for element in (37786, 37786, 38821))
        failure = ccx_failure(201, " STEP            1\n\n" + stdout, spooles_started=False, node_count=75_147)
        self.assertEqual(failure["code"], "solver_failed")
        self.assertIn("2 element(s) have a nonpositive Jacobian (37786, 38821)", failure["message"])
        self.assertIn("reduce mesh_size", failure["message"])

    def test_other_ccx_errors_are_quoted(self) -> None:
        failure = ccx_failure(201, " *ERROR in calinput: no material was assigned\n        to element 7\n",
                              spooles_started=False, node_count=10)
        self.assertEqual(failure["message"],
                         "CalculiX ccx stopped with exit status 201: *ERROR in calinput: no material was assigned "
                         "to element 7")


# The load section FreeCAD 1.1.4 writes into the ccx input: each force constraint's name, then its *CLOAD node lines
# (node, degree of freedom, load). FaceForce1 is the pillow_block bore load of issue #143: its header is there,
# and no node line.
CLOAD_SECTION = """*NODE, NSET=Nall
1, 0, 0, 0
*STEP, INC=2000
*BOUNDARY
FemConstraintFixed,1
** constraints force node loads
** FaceForce0
*CLOAD
** node loads on shape: SelectedPart:Face2
4,1,1.25
4,3,-2.5
7,3,-2.5
9,3,0
** FaceForce1
*CLOAD
** node loads on shape: SelectedPart:Face11


** FaceForce2
*CLOAD
** node loads on shape: SelectedPart:Face5
3,2,0.5

*NODE FILE
U
*END STEP
"""


class LoadApplication(unittest.TestCase):
    """Loads that never reach the mesh, or a loaded run that never moves it (issue #143: a bore load that reached
    no node gave stress 0 and displacement 0, and the run passed)."""

    def test_each_force_constraint_counts_the_nodes_its_cload_lines_load(self) -> None:
        # FaceForce0 loads node 4 (two components) and node 7. Node 9's line has a load of 0, so it loads nothing.
        self.assertEqual(failure_checks.applied_loads(CLOAD_SECTION), {"FaceForce0": 2, "FaceForce1": 0, "FaceForce2": 1})

    def test_a_nonzero_load_that_reaches_no_node_is_refused_before_the_solve(self) -> None:
        failure = failure_checks.unapplied_load({"FaceForce0": 2, "FaceForce1": 0},
                                                [("FaceForce0", 50.0), ("FaceForce1", 25_000.0)])
        self.assertEqual(failure["code"], "load_not_applied")
        self.assertEqual(failure["details"]["loads"], [{"constraint": "FaceForce1", "force_n": 25_000.0, "nodes": 0}])
        self.assertIn("load 1 (25000 N) reaches no mesh node", failure["message"])

    def test_loads_that_reach_nodes_or_carry_no_force_are_not_refused(self) -> None:
        for applied, loads in (({"FaceForce0": 2}, [("FaceForce0", 50.0)]),
                               ({}, [("FaceForce0", 0.0)]),
                               ({"FaceForce0": 2, "FaceForce1": 1}, [("FaceForce0", 50.0), ("FaceForce1", 1e-3)])):
            with self.subTest(applied=applied, loads=loads):
                self.assertIsNone(failure_checks.unapplied_load(applied, loads))

    def test_a_zero_stress_or_displacement_under_a_nonzero_load_is_refused(self) -> None:
        for stress, displacement in ((0.0, 0.0), (0.0, 0.002), (41.0, 0.0)):
            with self.subTest(stress=stress, displacement=displacement):
                failure = failure_checks.zero_result(stress, displacement, [("FaceForce0", 25_000.0)])
                self.assertEqual(failure["code"], "zero_result")
                self.assertEqual(failure["details"], {"max_von_mises_mpa": stress, "max_displacement_mm": displacement,
                                                      "applied_force_n": 25_000.0})

    def test_a_moving_result_or_an_unloaded_case_is_not_refused(self) -> None:
        self.assertIsNone(failure_checks.zero_result(41.0, 0.0065, [("FaceForce0", 25_000.0)]))
        self.assertIsNone(failure_checks.zero_result(0.0, 0.0, [("FaceForce0", 0.0)]))


# A versioned case takes its material from the part's profile in the version's record snapshot (record version 2).
VERSIONED_TAIL = """part: TST-0101
material: {conditions: {conditioning: dry, temperature: {value: 23, units: deg_C}}}
fixed_faces: {plane: {axis: y, value: 50, tolerance: 0.000001}}
loads:
  - selector: {plane: {axis: y, value: 150, tolerance: 0.000001}}
    force: [0, 0, -50]
mesh_size: 5
"""


class VersionedPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.hw = self.project / "hw"
        self.case_dir = self.hw / "analysis" / "cases" / "cantilever"
        self.case_dir.mkdir(parents=True)
        self.step = self.case_dir / "beam.step"
        self.step.write_bytes(b"STEP geometry")
        self.case = self.case_dir / "case.yaml"
        self.case.write_text("step: beam.step\n" + VERSIONED_TAIL, encoding="utf-8")
        import test_fea_conditions as sourced  # the record version 2 fixture of the sourced-material tests

        documents = sourced.documents()
        sourced.fx.write_record(self.hw, documents)
        version = self.hw / "versions" / "v1"
        record = version / "record"
        for name in documents:
            if not name.startswith("_") and (self.hw / name).is_file():
                (record / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.hw / name, record / name)
        files = {path.relative_to(version).as_posix(): fea_static.hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in version.rglob("*") if path.is_file()}
        (version / "manifest.json").write_text(json.dumps({"label": "v1", "files": files}), encoding="utf-8")

    def call(self, replace: bool = False, tools_root: str = "/opt/freecad-a") -> tuple[int, dict]:
        argv = [str(self.case), "--hw", str(self.hw), "--version", "v1"]
        if replace:
            argv.append("--replace")
        tools = {"freecad": {"path": f"{tools_root}/freecadcmd", "version": "1.1.4"},
                 "gmsh": {"path": f"{tools_root}/gmsh", "version": "4.15.0"},
                 "calculix": {"path": f"{tools_root}/ccx", "version": "2.23"}}
        output = __import__("io").StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", return_value=tools), \
             patch("fea_static.run_job", side_effect=self.run_job), \
             patch("sys.stdout", output):
            status = fea_static.main(argv)
        return status, json.loads(output.getvalue())

    @staticmethod
    def run_job(case_path: Path, case: dict, **kwargs) -> tuple[dict, int]:
        output = kwargs["result_path"]
        run_dir = Path(kwargs["scratch_root"]) / "jobs" / "fea_static" / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "solver.dat").write_text("solver output\n", encoding="utf-8")
        result = {"status": "pass", "run_directory": str(run_dir), "retained_files": ["solver.dat"],
                  "solver_versions": kwargs["solver_versions"]}
        output.write_text(json.dumps(result), encoding="utf-8")
        return result, 0

    def test_rerun_reuses_bundle_without_running_solver(self) -> None:
        first_status, first = self.call()
        self.assertEqual(first_status, 0)
        bundle = self.hw / "analysis" / "v1" / "cantilever"
        before = {path.relative_to(bundle).as_posix(): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
        with patch("fea_static.run_job", side_effect=AssertionError("reused bundle should skip solver")):
            status, second = self.call()
        self.assertEqual(status, 0)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(before, {path.relative_to(bundle).as_posix(): path.read_bytes()
                                  for path in bundle.rglob("*") if path.is_file()})

    def test_same_solver_versions_at_another_install_path_reuse_the_bundle(self) -> None:
        self.assertEqual(self.call(tools_root="/opt/freecad-a")[0], 0)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["solver_versions"], {"freecad": "1.1.4", "gmsh": "4.15.0", "calculix": "2.23"})
        with patch("fea_static.run_job", side_effect=AssertionError("same tool versions should reuse")):
            status, report = self.call(tools_root="/home/other/squashfs-root/usr/bin")
        self.assertEqual((status, report["reused"]), (0, True))

    def test_changed_case_recipe_is_refused_then_replaced_immutably(self) -> None:
        self.call()
        bundle = self.hw / "analysis" / "v1" / "cantilever"
        original = {path.relative_to(bundle).as_posix(): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
        self.case.write_text(self.case.read_text(encoding="utf-8").replace("mesh_size: 5", "mesh_size: 6"), encoding="utf-8")
        status, report = self.call()
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])
        self.assertEqual(original, {path.relative_to(bundle).as_posix(): path.read_bytes()
                                    for path in bundle.rglob("*") if path.is_file()})
        status, report = self.call(replace=True)
        self.assertEqual(status, 0)
        replaced_path = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["replaces"]["moved_to"]
        replaced_bundle = self.project / replaced_path
        self.assertTrue(replaced_bundle.is_dir())
        self.assertEqual(original, {path.relative_to(replaced_bundle).as_posix(): path.read_bytes()
                                    for path in replaced_bundle.rglob("*") if path.is_file()})

    def test_standalone_output_override_outside_cad_work_is_refused(self) -> None:
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")):
            output = __import__("io").StringIO()
            self.case.write_text("step: beam.step\n" + CASE_TAIL, encoding="utf-8")  # a standalone case
            with patch("sys.stdout", output):
                status = fea_static.main([str(self.case), "--out", str(self.project / "results.json")])
        self.assertEqual(status, 2)
        self.assertIn("--out must be under", json.loads(output.getvalue())["error"]["message"])

    def test_solver_evidence_excludes_python_bytecode_and_cache_dirs(self) -> None:
        for path in ("result.frd", "nested/result.inp"):
            with self.subTest(path=path):
                self.assertTrue(fea_static._is_solver_evidence(path))
        for path in ("module.pyc", "__pycache__/module.cpython-313.pyc", "nested/__pycache__/module.pyc",
                     "fea_job.py", "fea_static_123.json"):
            with self.subTest(path=path):
                self.assertFalse(fea_static._is_solver_evidence(path))

    def test_generated_job_name_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            step = root / "beam.step"
            step.touch()
            case = {"_step": str(step), "material": {"E": 1, "nu": 0.3, "density": 1, "yield": 1},
                    "fixed_faces": {"indices": [1]}, "loads": [], "mesh_size": 1, "timeout_seconds": 0.01}
            with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
                 patch("fea_static.lifecycle.run",
                       side_effect=subprocess.TimeoutExpired("freecadcmd", 0.01)) as run:
                fea_static.run_job(root / "case.yaml", case, scratch_root=root,
                                   solver_versions={"calculix": {"path": "/fake/ccx", "version": "2.23"}})
            self.assertEqual(Path(run.call_args.args[0][1]).name, "fea_job.py")

    PROBED = {"freecad": {"path": "/tmp/.mount_x/usr/bin/freecadcmd", "version": "1.1.4"},
              "resource_dir": "/tmp/.mount_x/usr/share/",
              "gmsh": {"path": "/tmp/.mount_x/usr/bin/gmsh", "version": "4.15.0", "source": "FreeCAD's lookup"},
              "calculix": {"path": "/tmp/.mount_x/usr/bin/ccx", "version": "2.23", "source": "FreeCAD's lookup"}}

    def test_solver_versions_record_the_tools_freecad_resolves(self) -> None:
        freecad = Path(self.temporary.name) / "freecadcmd"
        with patch("fea_static.find_freecad", return_value=freecad), \
             patch.object(fea_static.SOLVERS, "probe", return_value=self.PROBED) as probe:
            versions = fea_static.solver_versions()
        probe.assert_called_once_with(freecad)
        self.assertEqual(versions, {"freecad": {"path": str(freecad.resolve()), "version": "1.1.4"},
                                    "gmsh": {"path": "/tmp/.mount_x/usr/bin/gmsh", "version": "4.15.0"},
                                    "calculix": {"path": "/tmp/.mount_x/usr/bin/ccx", "version": "2.23"}})

    def test_a_solver_freecad_cannot_resolve_is_solver_unavailable(self) -> None:
        probed = {**self.PROBED, "calculix": {"error": "ccx not found: $CCX is unset"}}
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch.object(fea_static.SOLVERS, "probe", return_value=probed):
            with self.assertRaisesRegex(fea_static.SolverUnavailable, r"ccx not found: \$CCX is unset"):
                fea_static.solver_versions()
        output = __import__("io").StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", side_effect=fea_static.SolverUnavailable("ccx not found")), \
             patch("fea_static.run_job", side_effect=AssertionError("no solver, no run")), patch("sys.stdout", output):
            status = fea_static.main([str(self.case), "--hw", str(self.hw), "--version", "v1"])
        self.assertEqual((status, json.loads(output.getvalue())["error"]["code"]), (2, "solver_unavailable"))

    def test_a_changed_mesh_quality_check_changes_the_recipe(self) -> None:
        # Only mesh_quality.py's bytes change: the bundle sealed with the old check is not reused.
        self.assertEqual(self.call()[0], 0)
        read_bytes = Path.read_bytes

        def changed(path: Path) -> bytes:
            data = read_bytes(path)
            return data + b"\n# changed\n" if path.name == "mesh_quality.py" else data

        with patch.object(Path, "read_bytes", changed):
            status, report = self.call()
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])

    def test_a_changed_record_schema_changes_the_recipe(self) -> None:
        """The record checks behind an UNKNOWN (cad-record's schema registry and its bundled schemas) can change a
        verdict, so a bundle sealed with the old bytes is not reused."""
        self.assertEqual(self.call()[0], 0)
        read_bytes = Path.read_bytes
        for name in ("schema_registry.py", "manufacturing.schema.json", "drawing.schema.json"):
            with self.subTest(name):
                def changed(path: Path, name: str = name) -> bytes:
                    data = read_bytes(path)
                    return data + b"\n" if path.name == name else data

                with patch.object(Path, "read_bytes", changed):
                    status, report = self.call()
                self.assertEqual(status, 2)
                self.assertIn("--replace", report["error"]["message"])

    def test_a_changed_frame_dependency_changes_the_recipe(self) -> None:
        """The rotation code behind a load direction's frame (cad-motion pose and its imports, cad-record's occurrence
        inventory) can change a verdict, so a bundle sealed with the old bytes is not reused."""
        self.assertEqual(self.call()[0], 0)
        read_bytes = Path.read_bytes
        for name in ("pose.py", "coupling.py", "layout.py", "assembly_data.py"):
            with self.subTest(name):
                def changed(path: Path, name: str = name) -> bytes:
                    data = read_bytes(path)
                    return data + b"\n# changed\n" if path.name == name else data

                with patch.object(Path, "read_bytes", changed):
                    status, report = self.call()
                self.assertEqual(status, 2)
                self.assertIn("--replace", report["error"]["message"])

    def test_a_changed_stress_study_module_changes_the_recipe(self) -> None:
        """The linearisation and the study code decide a stress verdict, so a bundle sealed with the old bytes of any
        of them is not reused. fea_near_support and fea_linearise were added to the seal with #209; the other two
        had no test."""
        self.assertEqual(self.call()[0], 0)
        read_bytes = Path.read_bytes
        for name in ("fea_near_support.py", "fea_linearise.py", "fea_stress.py", "fea_stress_study.py"):
            with self.subTest(name):
                def changed(path: Path, name: str = name) -> bytes:
                    data = read_bytes(path)
                    return data + b"\n# changed\n" if path.name == name else data

                with patch.object(Path, "read_bytes", changed):
                    status, report = self.call()
                self.assertEqual(status, 2)
                self.assertIn("--replace", report["error"]["message"])

    def test_a_cheaper_first_high_order_level_changes_the_recipe(self) -> None:
        self.assertEqual(self.call()[0], 0)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        settings = manifest["recipe"]["options"]["mesh_settings"]
        self.assertEqual(settings["high_order_optimize"], 2)
        self.assertNotIn("high_order_fallback", settings)
        with patch.dict(fea_static.HIGH_ORDER, {"optimize": 1}):
            status, report = self.call()
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])

    def call_with_metals_flag(self, value: str | None) -> tuple[int, dict]:
        with patch.dict(process_env):
            process_env.pop("CAD_FEA_METALS_NEAR_SUPPORT", None)
            if value is not None:
                process_env["CAD_FEA_METALS_NEAR_SUPPORT"] = value
            return self.call()

    def refused_after_flag_change(self, first: str | None, second: str | None) -> None:
        # The fixture's alloy is not on the flag's metal list, so the flag leaves this verdict alone. The recipe still
        # seals the flag's value, so the other setting refuses the bundle.
        self.assertEqual(self.call_with_metals_flag(first)[0], 0)
        with patch("fea_static.run_job", side_effect=AssertionError("the changed flag must not reuse")):
            status, report = self.call_with_metals_flag(second)
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])

    def test_turning_the_metals_near_support_flag_on_refuses_the_reuse_of_a_bundle(self) -> None:
        self.refused_after_flag_change(None, "1")

    def test_turning_the_metals_near_support_flag_off_refuses_the_reuse_of_a_bundle(self) -> None:
        self.refused_after_flag_change("1", None)

    def test_the_same_metals_near_support_flag_reuses_the_bundle(self) -> None:
        self.assertEqual(self.call_with_metals_flag("1")[0], 0)
        with patch("fea_static.run_job", side_effect=AssertionError("the same flag should reuse")):
            status, report = self.call_with_metals_flag("1")
        self.assertEqual((status, report["reused"]), (0, True))

    def test_the_recipe_seals_the_flag_value_the_verdict_used(self) -> None:
        # The job reads the flag once, at assessment. The environment changes after the assessment and before the
        # recipe exists (the snapshot hashes run between them), and the recipe still seals the value the verdict used.
        real = fea_static._snapshot_record_hashes

        def flip_then_hash(*args, **kwargs):
            process_env.pop("CAD_FEA_METALS_NEAR_SUPPORT", None)
            return real(*args, **kwargs)

        with patch.dict(process_env, {"CAD_FEA_METALS_NEAR_SUPPORT": "1"}), \
             patch("fea_static._snapshot_record_hashes", side_effect=flip_then_hash):
            self.assertEqual(self.call()[0], 0)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["conditions"]["flags"], {"CAD_FEA_METALS_NEAR_SUPPORT": "1"})

    def test_changed_ccx_thread_counts_change_the_recipe(self) -> None:
        self.assertEqual(self.call()[0], 0)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["options"]["mesh_settings"]["calculix_environment"],
                         {"CCX_NPROC_EQUATION_SOLVER": "1", "CCX_NPROC_STIFFNESS": "1", "CCX_NPROC_RESULTS": "1"})
        with patch.dict(fea_static.CCX_ENVIRONMENT, {"CCX_NPROC_STIFFNESS": "8"}):
            status, report = self.call()
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_a_wrapper_script_freecadcmd_runs_the_bundled_solvers(self) -> None:
        # An AppImage install: FREECADCMD is a wrapper outside the bundle and PATH has neither ccx nor gmsh.
        assert FREECADCMD is not None
        wrapper = Path(self.temporary.name) / "wrapper" / "freecadcmd"
        wrapper.parent.mkdir()
        wrapper.write_text(f'#!/bin/sh\nexec "{FREECADCMD.resolve()}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        step = StaticFEAContracts.make_cantilever_step(self, Path(self.temporary.name), "TST-0101 Beam")
        shutil.copyfile(step, self.case_dir / "cantilever.step")
        self.case.write_text(f"step: cantilever.step\n{CANTILEVER_VERSIONED_TAIL}", encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key not in ("CCX", "GMSH")}
        run = subprocess.run([sys.executable, str(SCRIPT), "hw/analysis/cases/cantilever/case.yaml",
                              "--hw", "hw", "--version", "v1"], cwd=self.project, capture_output=True, text=True,
                             timeout=600, env={**env, "FREECADCMD": str(wrapper), "PATH": "/usr/bin:/bin"})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        report = json.loads(run.stdout)
        self.assertLess(abs(report["max_von_mises_mpa"] / 120.0 - 1), 0.05)
        # delta = P L^3 / (3 E I) = 50 N * (100 mm)^3 / (3 * 70000 MPa * 10 * 5^3 / 12 mm^4) = 2.285714 mm; the profile gives E = 70000
        self.assertLess(abs(report["max_displacement_mm"] / 2.285714 - 1), 0.05)
        for tool in ("gmsh", "calculix"):  # the wrapper's directory and PATH hold neither tool
            with self.subTest(tool=tool):
                path = Path(report["solver_versions"][tool]["path"])
                self.assertTrue(path.is_absolute())
                self.assertNotEqual(path.parent, wrapper.parent)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["recipe"]["solver_versions"]), {"freecad", "gmsh", "calculix"})

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_relative_hw_publishes_a_solved_bundle(self) -> None:
        step = StaticFEAContracts.make_cantilever_step(self, Path(self.temporary.name), "TST-0101 Beam")
        shutil.copyfile(step, self.case_dir / "cantilever.step")
        self.case.write_text(f"step: cantilever.step\n{CANTILEVER_VERSIONED_TAIL}", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT), "hw/analysis/cases/cantilever/case.yaml",
                              "--hw", "hw", "--version", "v1"],
                             cwd=self.project, capture_output=True, text=True, timeout=600)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "pass")
        self.assertTrue((self.hw / "analysis" / "v1" / "cantilever" / "results.json").is_file())


if __name__ == "__main__":
    unittest.main()
