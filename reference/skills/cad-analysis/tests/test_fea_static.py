
#!/usr/bin/env python3
"""Focused FEA selection, input, missing-FreeCAD, and solver integration checks."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
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


def hanging_freecad(root: Path, child_pid: Path) -> Path:
    """A FreeCAD stand-in that runs the real job script, starts a solver-like child, writes its pid to
    `child_pid`, and hangs in the job's STEP import."""
    freecad = root / "freecadcmd"
    freecad.write_text(f"""#!{sys.executable}
import runpy, subprocess, sys, time
from unittest import mock
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

    def make_cantilever_step(self, root: Path) -> Path:
        step = root / "cantilever.step"
        job = root / "make_cantilever.py"
        job.write_text(
            f'''import FreeCAD as App, Part, Import
doc=App.newDocument("CantileverFixture")
beam=doc.addObject("Part::Feature", "Beam")
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
        import math
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

    def test_case_timeout_names_the_phase_its_knob_and_stops_the_jobs_children(self) -> None:
        from fea_static import run_job
        with tempfile.TemporaryDirectory(prefix="cad-fea-timeout-") as directory:
            root = Path(directory)
            step = root / "part.step"
            step.touch()
            child_pid = root / "child.pid"
            freecad = hanging_freecad(root, child_pid)
            case = hanging_case(step, timeout_seconds=5)
            with patch("fea_static.find_freecad", return_value=freecad):
                result, status = run_job(root / "case.yaml", case,
                                         solver_versions={"calculix": {"path": "/unused/ccx", "version": "2.23"}})
            self.assertEqual(status, 2)
            self.assertEqual(result["error"]["code"], "freecad_timeout")
            self.assertEqual(result["error"]["details"], {"phase": "import"})
            self.assertIn("timeout_seconds of 5 while importing the STEP; raise timeout_seconds in the case YAML",
                          result["error"]["message"])
            pid = int(child_pid.read_text(encoding="utf-8"))
            self.assertTrue(wait_until(lambda: not pid_runs(pid)), "a child of the timed-out FreeCAD job is still running")

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
            parent_code = (f"import sys\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
                           f"sys.path.insert(0, {str(SCRIPT.parent)!r})\nimport fea_static\n"
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
            [group] = json.loads(record.read_text(encoding="utf-8"))["groups"]
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
        self.case.write_text("step: beam.step\n" + CASE_TAIL, encoding="utf-8")
        version = self.hw / "versions" / "v1"
        record = version / "record"
        record.mkdir(parents=True)
        for name in ("product.yaml", "interfaces.yaml", "assembly.yaml"):
            (record / name).write_text("{}\n", encoding="utf-8")
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
        step = StaticFEAContracts.make_cantilever_step(self, Path(self.temporary.name))
        shutil.copyfile(step, self.case_dir / "cantilever.step")
        self.case.write_text(f"step: cantilever.step\n{CANTILEVER_TAIL}", encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key not in ("CCX", "GMSH")}
        run = subprocess.run([sys.executable, str(SCRIPT), "hw/analysis/cases/cantilever/case.yaml",
                              "--hw", "hw", "--version", "v1"], cwd=self.project, capture_output=True, text=True,
                             timeout=600, env={**env, "FREECADCMD": str(wrapper), "PATH": "/usr/bin:/bin"})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        report = json.loads(run.stdout)
        self.assertLess(abs(report["max_von_mises_mpa"] / 120.0 - 1), 0.05)
        self.assertLess(abs(report["max_displacement_mm"] / 2.31884 - 1), 0.05)
        for tool in ("gmsh", "calculix"):  # the wrapper's directory and PATH hold neither tool
            with self.subTest(tool=tool):
                path = Path(report["solver_versions"][tool]["path"])
                self.assertTrue(path.is_absolute())
                self.assertNotEqual(path.parent, wrapper.parent)
        manifest = json.loads((self.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["recipe"]["solver_versions"]), {"freecad", "gmsh", "calculix"})

    @unittest.skipUnless(FREECAD_PRESENT, "FreeCAD 1.1.4 freecadcmd is not installed (shared lookup)")
    def test_relative_hw_publishes_a_solved_bundle(self) -> None:
        step = StaticFEAContracts.make_cantilever_step(self, Path(self.temporary.name))
        shutil.copyfile(step, self.case_dir / "cantilever.step")
        self.case.write_text(f"step: cantilever.step\n{CANTILEVER_TAIL}", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT), "hw/analysis/cases/cantilever/case.yaml",
                              "--hw", "hw", "--version", "v1"],
                             cwd=self.project, capture_output=True, text=True, timeout=600)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "pass")
        self.assertTrue((self.hw / "analysis" / "v1" / "cantilever" / "results.json").is_file())


if __name__ == "__main__":
    unittest.main()
