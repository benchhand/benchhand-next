# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A project with a sealed version and a published stop-reaction bundle, for the tests of FEA reaction loads (#153).

It needs no fea_reaction.py: the bundle is written through cad-record's check_packet and layout, and the case runs
through fea_static.main. test_fea_reaction.py (stubbed solve) and test_fea_static.py (FreeCAD and a $CCX recorder) share it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SKILLS = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))

import fea_static  # noqa: E402
import stop_reaction  # noqa: E402


def load_by_path(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LAYOUT = load_by_path("cad_record_layout", SKILLS / "cad-record" / "scripts" / "layout.py")
CHECK_PACKET = load_by_path("cad_record_check_packet", SKILLS / "cad-record" / "scripts" / "check_packet.py")
INTENT = load_by_path("cad_record_manufacturing_intent", SKILLS / "cad-record" / "scripts" / "manufacturing_intent.py")

# A versioned case takes its material from the part's profile in the version's record snapshot (record version 2).
CASE_TAIL = """part: TST-0101
material: {conditions: {conditioning: dry, temperature: {value: 23, units: deg_C}}}
fixed_faces: {plane: {axis: y, value: 50, tolerance: 0.000001}}
loads:
  - selector: {plane: {axis: y, value: 150, tolerance: 0.000001}}
    force: [0, 0, -50]
    reaction: IF-006
mesh_size: 5
"""
INTERFACE = "IF-006"
SUBJECT = "stop-reaction"  # the bundle stop_reaction.py publishes: hw/checks/<V>/stop-reaction/
EVIDENCE = "stop-reaction.json"


def current_code() -> dict[str, str]:
    """The code table stop_reaction.py puts in its recipe: the closure of the script and its VERDICT_DATA (#140)."""
    return dict(stop_reaction.code_shas.closure(Path(stop_reaction.__file__), stop_reaction.VERDICT_DATA))


def end(status: str, design: float | None) -> dict[str, Any]:
    return {"touching": True, "reaction": {"status": status, "design_reaction_n": design}}


def packet(outcome: str) -> dict[str, Any]:
    """A schema-valid stop-reaction packet for IF-006 with one outcome."""
    obligation = f"engineering.stop_reaction@{INTERFACE}"
    row: dict[str, Any] = {"obligation": obligation, "outcome": outcome, "level": "simulation_supported",
                           "method": "rigid statics of the modelled stop contact", "coverage": "one pivot at its limits"}
    if outcome == "unknown":
        row["uncertainty"] = "the reaction is not established"
    return {"schema_version": 1, "record_version": 2, "producer": "cad-analysis stop_reaction.py",
            "scope": [{"interface": INTERFACE}],
            "expected": [{"id": obligation, "family": "engineering.stop_reaction", "subject": {"interface": INTERFACE},
                          "level": "simulation_supported", "stage": "layout", "basis": "test"}],
            "outcomes": [row], "findings": [], "dependencies": {}, "complete": True,
            "result": "pass" if outcome == "not_applicable" else outcome}


def bare_end(touching: bool = True) -> dict[str, Any]:
    """A limit of the pivot with no calculated reaction: stop_reaction.py reports one for a stop whose force is unknown."""
    return {"touching": touching}


def entry(outcome: str = "pass", ends: dict[str, Any] | None = None, reason: str | None = None,
          recorded_contact_load_n: float | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"outcome": outcome, "ends": ends or {}}
    if reason:
        data["reason"] = reason
    if recorded_contact_load_n is not None:
        data["recorded_contact_load_n"] = recorded_contact_load_n
    return data


class Scenario:
    """A project with the sealed version v1, a case that names IF-006 for its 50 N load and, optionally, a stop-reaction bundle."""

    def __init__(self, test: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        self.test = test
        self.solves = 0
        self.project = Path(temporary.name) / "project"
        self.hw = self.project / "hw"
        self.case_dir = self.hw / "analysis" / "cases" / "cantilever"
        self.case_dir.mkdir(parents=True)
        (self.case_dir / "beam.step").write_bytes(b"STEP geometry")
        self.case = self.case_dir / "case.yaml"
        self.case.write_text("step: beam.step\n" + CASE_TAIL, encoding="utf-8")
        self.version = self.hw / "versions" / "v1"
        record = self.version / "record"
        record.mkdir(parents=True)
        import test_fea_conditions as sourced  # the record version 2 fixture of the sourced-material tests

        documents = sourced.documents()
        sourced.fx.write_record(self.hw, documents)
        for name in documents:
            if not name.startswith("_") and (self.hw / name).is_file():
                (record / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.hw / name, record / name)
        self.seal()

    def name_limit(self, limit: str) -> None:
        """Make the case's load name the joint limit it reacts against."""
        self.case.write_text(self.case.read_text(encoding="utf-8").replace("    reaction: IF-006\n", f"    reaction: IF-006\n    limit: {limit}\n"),
                             encoding="utf-8")

    def seal(self) -> None:
        files = {path.relative_to(self.version).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in self.version.rglob("*") if path.is_file() and path.name != "manifest.json"}
        (self.version / "manifest.json").write_text(json.dumps({"label": "v1", "files": files}), encoding="utf-8")

    def publish(self, interfaces: dict[str, Any], outcome: str = "pass", replace: bool = False,
                code: dict[str, str] | None | str = "current") -> Path:
        """Seal a stop-reaction bundle. Its recipe records `code`, the current code table unless another is given
        (None records none), the way stop_reaction.py records it."""
        detail = {"interfaces": interfaces, "limits": []}
        recipe: dict[str, Any] = {"detail": hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()}
        if code is not None:
            recipe["code"] = current_code() if code == "current" else code
        output, _ = CHECK_PACKET.emit(LAYOUT, self.hw, "v1", SUBJECT, "cad-analysis stop_reaction.py", packet(outcome),
                                      detail, EVIDENCE, recipe, out=None, replace=replace,
                                      record_version=INTENT.RECORD_VERSION)
        return Path(output["bundle"])

    def call(self, replace: bool = False, solve: bool = True) -> tuple[int, dict[str, Any]]:
        """fea_static.main on the case with a stub for the solver: it passes, or it fails the test when `solve` is False."""
        argv = [str(self.case), "--hw", str(self.hw), "--version", "v1"] + (["--replace"] if replace else [])
        tools = {"freecad": {"path": "/opt/freecad/freecadcmd", "version": "1.1.4"},
                 "gmsh": {"path": "/opt/freecad/gmsh", "version": "4.15.0"},
                 "calculix": {"path": "/opt/freecad/ccx", "version": "2.23"}}
        refusal = AssertionError("the case was refused before the solve, yet a solve started")
        probe = {"return_value": tools} if solve else {"side_effect": AssertionError("the solvers were probed")}
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", **probe), \
             patch("fea_static.run_job", side_effect=self.passing_job if solve else refusal), patch("sys.stdout", output):
            status = fea_static.main(argv)
        return status, json.loads(output.getvalue())

    def passing_job(self, case_path: Path, case: dict, **kwargs: Any) -> tuple[dict, int]:
        self.solves += 1
        run_dir = Path(kwargs["scratch_root"]) / "jobs" / "fea_static" / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "solver.dat").write_text("solver output\n", encoding="utf-8")
        result = {"status": "pass", "run_directory": str(run_dir), "retained_files": ["solver.dat"],
                  "solver_versions": kwargs["solver_versions"]}
        kwargs["result_path"].write_text(json.dumps(result), encoding="utf-8")
        return result, 0

    def refused(self, code: str) -> dict[str, Any]:
        status, report = self.call(solve=False)
        self.test.assertEqual((status, report["error"]["code"]), (2, code), report)
        return report
