#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""FEA material sourcing and evidence: properties come only from the analysed part's material profile under the
case's stated conditions, refusals happen before any solve, and a result is simulation-supported evidence at
most. The FreeCAD job is replaced by a stand-in that records the material card it was given."""

from __future__ import annotations

import copy
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

import yaml

SKILLS = Path(__file__).resolve().parents[2]
SCRIPTS = SKILLS / "cad-analysis" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fea_conditions  # noqa: E402
import fea_static  # noqa: E402

_spec = importlib.util.spec_from_file_location("cad_record_mi_fixtures",
                                               SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
assert _spec and _spec.loader
fx = sys.modules.get(_spec.name)
if fx is None:
    fx = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = fx
    _spec.loader.exec_module(fx)


def evidence_module() -> Any:
    """cad-record evidence.py, the reader of every producer's required-check packet."""
    name = "cad_record_evidence"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SKILLS / "cad-record" / "scripts" / "evidence.py")
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


PN = "TST-0101"
DATASHEET = fx.source("datasheet", "TST alloy datasheet")
TOOLS = {"freecad": {"path": "/opt/freecad/freecadcmd", "version": "1.1.4"},
         "gmsh": {"path": "/opt/freecad/gmsh", "version": "4.15.0"},
         "calculix": {"path": "/opt/freecad/ccx", "version": "2.23"}}
DRY_23C = {"conditioning": "dry", "temperature": {"value": 23, "units": "deg_C"}}
SERVICE = {"conditioning": "dry", "temperature": {"lower": 15, "upper": 30, "units": "deg_C"}}  # the use case's range


def prop(name: str, value: float, units: str, *, basis: str = "supplier_typical", **extra: Any) -> dict[str, Any]:
    """A profile property with a synthetic datasheet source (allowables keep the fixture's derivation)."""
    data = fx.material_property(name, value, units, basis=basis, **extra)
    if basis != "allowable":
        data["value"]["sources"] = [DATASHEET]
    return data


def alloy(*properties: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A synthetic wrought rod grade profile; with no properties, a complete typical set tested over 10..40 deg_C."""
    tested = fx.quantity(lower=10, upper=40, units="deg_C")
    return fx.material_profile("tst_alloy_rod", form="rod", properties=list(properties) or [
        prop("youngs_modulus", 70000, "MPa", temperature=tested), prop("poisson_ratio", 0.33, "dimensionless", temperature=tested),
        prop("density", 2700, "kg_m3", temperature=tested), prop("yield_strength", 250, "MPa", temperature=tested)], **extra)


def printed(**extra: Any) -> dict[str, Any]:
    """A synthetic printed grade profile with XY and Z values: orientation-dependent material."""
    properties = []
    for orientation, modulus, strength in (("XY", 2000, 40), ("Z", 1500, 20)):
        properties += [prop("youngs_modulus", modulus, "MPa", orientation=fx.known(orientation)),
                       prop("yield_strength", strength, "MPa", orientation=fx.known(orientation))]
    properties += [prop("poisson_ratio", 0.35, "dimensionless", orientation=fx.known("XY")),
                   prop("poisson_ratio", 0.35, "dimensionless", orientation=fx.known("Z")),
                   prop("density", 1200, "kg_m3", orientation=fx.known("XY")),
                   prop("density", 1200, "kg_m3", orientation=fx.known("Z"))]
    data = fx.material_profile("tst_polymer_fdm", form="printed", properties=properties, **extra)
    data["process_state"] = {"process": "fdm", "conditioning": "dry"}
    return data


def bracket(profile: Any = "tst_alloy_rod", route: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return fx.part(PN, "Bracket", process="cnc", material="TST alloy", part_intent=fx.intent(
        functions=[{"function": "structural", "requirements": ["REQ-001"]}], material_profile=profile,
        service={"requirements": ["REQ-001"], "loads": ["head_load"]},
        critical_surfaces=fx.not_applicable("no critical surface in this fixture"),
        route=route if route is not None else [fx.operation("turn", "cnc", fx.unknown("no capability in this fixture"))]))


def documents(*, profiles: list[dict[str, Any]] | None = None, part: dict[str, Any] | None = None,
              service_class: str = "working_prototype", direction: Any = (0, 0, -1)) -> dict[str, Any]:
    """`direction` is the unit vector of the force head_load stands for: the required [x, y, z] list of the load
    schema. Any other value is written as given, to test what the record and the reader refuse; None leaves it out."""
    load = {"id": "head_load", "kind": "static", "magnitude": fx.known(fx.quantity(50, "N")), "requirements": ["REQ-001"]}
    if direction is not None:
        load["direction"] = list(direction) if isinstance(direction, (tuple, list)) else direction
    use = fx.use_case("draft", service_class=fx.known(service_class), loads=[load])
    use["environment"]["temperature"] = fx.known(fx.quantity(lower=15, upper=30, units="deg_C"))
    requirements = fx.requirements([
        fx.requirement("REQ-001", "Carry the head load",
                       acceptance=[fx.criterion("yield_safety_factor", ">=", 2, "dimensionless")]),
        fx.requirement("REQ-002", "Stay stiff", acceptance=[fx.criterion("max_displacement", "<=", 0.5, "mm")])])
    return fx.record(product_data=fx.product(use, stage="analysis"), requirements_data=requirements,
                     parts=[part or bracket()], materials=profiles if profiles is not None else [alloy()],
                     decisions=("DR-001", "DR-002", "DR-003"))


class SourcedFEACase(unittest.TestCase):
    """A versioned case in a record version 2 project, solved by a stand-in FreeCAD job."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.hw = self.project / "hw"
        self.solved: list[dict[str, Any]] = []
        self.solution = {"safety_factor_yield": 3.0, "max_displacement_mm": 0.2, "max_von_mises_mpa": 83.3,
                         "node_count": 1200, "element_count": 600}

    def build(self, docs: dict[str, Any], version: str = "v1") -> None:
        fx.write_record(self.hw, docs)
        folder = self.hw / "versions" / version
        record = folder / "record"
        for rel in docs:
            if not rel.startswith("_") and (self.hw / rel).is_file():
                (record / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.hw / rel, record / rel)
        (folder / "manifest.json").unlink(missing_ok=True)   # a rebuild in one test hashes the record, never the old manifest
        files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in folder.rglob("*") if p.is_file()}
        (folder / "manifest.json").write_text(json.dumps({"label": version, "files": files}), encoding="utf-8")

    def case(self, material: dict[str, Any], **extra: Any) -> Path:
        folder = self.hw / "analysis" / "cases" / "bracket"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "bracket.step").write_bytes(b"ISO-10303-21; TST bracket\n")
        data = {"step": "bracket.step", "part": PN, "material": material,
                "fixed_faces": {"indices": [1]}, "loads": [{"selector": {"indices": [2]}, "force": [0, 0, -50],
                                                             "load": "head_load"}],
                "mesh_size": 2}
        data.update(extra)
        path = folder / "case.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def run_job(self, case_path: Path, case: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], int]:
        self.solved.append(copy.deepcopy(case["material"]))
        run_dir = Path(kwargs["scratch_root"]) / "jobs" / "fea_static" / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "solver.dat").write_text("solver output\n", encoding="utf-8")
        result = fea_static.apply_required_safety_factor(
            {"run_directory": str(run_dir), "retained_files": ["solver.dat"], "solver_versions": TOOLS, **self.solution},
            case.get("required_safety_factor"))
        kwargs["result_path"].write_text(json.dumps(result), encoding="utf-8")
        return result, fea_static.result_exit_code(result)

    def call(self, case_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.solver_versions", return_value=TOOLS), \
             patch("fea_static.run_job", side_effect=self.run_job), patch("sys.stdout", output):
            status = fea_static.main([str(case_path), "--hw", str(self.hw), "--version", "v1", *extra])
        return status, json.loads(output.getvalue())

    def refused(self, case_path: Path) -> list[str]:
        status, report = self.call(case_path)
        self.assertEqual(status, 2, report)
        self.assertEqual(report["error"]["code"], "analysis_refused", report)
        self.assertEqual(self.solved, [], "a refused case must never reach the solver")
        return [problem["code"] for problem in report["error"]["details"]["problems"]]

    def outcomes(self, report: dict[str, Any]) -> dict[str, str]:
        return {row["obligation"]: row["outcome"] for row in report["engineering"]["outcomes"]}

    def profile_sha(self) -> str:
        record, _ = fea_conditions.read_record(self.hw / "versions" / "v1" / "record")
        return fea_conditions._digest(fea_conditions.intent().thaw(record.materials["tst_alloy_rod"].raw))

    def study(self, case_path: Path, **override: Any) -> dict[str, Any]:
        """A mesh convergence study bound to the case's geometry, material, supports, loads and mesh."""
        case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        study = {
            "geometry_sha256": hashlib.sha256((case_path.parent / case["step"]).read_bytes()).hexdigest(),
            "material": {"profile": "tst_alloy_rod", "sha256": self.profile_sha()},
            "supports": case["fixed_faces"],
            "loads": [{"selector": load["selector"], "force": load["force"]} for load in case["loads"]],
            "mesh": {"size_mm": case["mesh_size"], "element_order": "second"},
            "criterion": {"relative_change_max": 0.05},
            "refinements": [{"size_mm": 4, "max_von_mises_mpa": 78.0, "max_displacement_mm": 0.190},
                            {"size_mm": 2, "max_von_mises_mpa": 82.5, "max_displacement_mm": 0.198},
                            {"size_mm": 1, "max_von_mises_mpa": 83.3, "max_displacement_mm": 0.199}],
        }
        study.update(override)
        return study

    def approve(self, study: dict[str, Any] | None, *, status: str | None = "Status: APPROVED", ref: str = "DR-002") -> None:
        """Write the convergence decision: a status line, then the study block."""
        text = (f"{status}\n\n" if status is not None else "") + f"# {ref}: mesh convergence study\n\n"
        if study is not None:
            text += "```mesh-convergence\n" + yaml.safe_dump(study, sort_keys=False) + "```\n"
        (self.hw / "decisions" / f"{ref}.md").write_text(text, encoding="utf-8")

    def convergent_case(self, **extra: Any) -> Path:
        """A case with a sourced criterion and an approved, bound convergence study."""
        path = self.case({"conditions": SERVICE}, acceptance={"strength": "REQ-001", "stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"}, **extra)
        self.approve(self.study(path))
        return path


class Refusals(SourcedFEACase):
    def test_a_density_only_profile_is_refused_before_the_solve(self) -> None:
        self.build(documents(profiles=[alloy(prop("density", 2700, "kg_m3"))]))
        codes = self.refused(self.case({"conditions": DRY_23C}))
        self.assertIn("material.density_only", codes)
        self.assertIn("material.property", codes)  # E, nu and yield are unknown, never derived from density

    def test_a_property_tested_under_another_condition_is_refused(self) -> None:
        self.build(documents())
        self.assertIn("material.condition", self.refused(self.case({"conditions": {**DRY_23C, "conditioning": "conditioned"}})))
        self.solved.clear()
        hot = {"conditioning": "dry", "temperature": {"value": 80, "units": "deg_C"}}
        self.assertIn("material.condition", self.refused(self.case({"conditions": hot})))

    def test_numbers_inherited_into_a_versioned_case_are_refused(self) -> None:
        self.build(documents())
        explicit = {"name": "Aluminium 6061", "E": 69000, "nu": 0.33, "density": 2700, "yield": 276}
        self.assertEqual(self.refused(self.case(explicit)), ["material.inherited"])

    def test_a_profile_copied_from_another_part_is_refused(self) -> None:
        self.build(documents(profiles=[alloy(), printed()]))
        codes = self.refused(self.case({"profile": "tst_polymer_fdm", "conditions": DRY_23C}))
        self.assertIn("material.inherited", codes)

    def test_a_material_name_without_a_profile_is_refused(self) -> None:
        self.build(documents(part=bracket(profile=fx.unknown("material not chosen yet"))))
        self.assertEqual(self.refused(self.case({"conditions": DRY_23C})), ["material.name_only"])

    def test_family_guidance_is_refused(self) -> None:
        self.build(documents(profiles=[alloy(level="family")]))
        self.assertIn("material.grade", self.refused(self.case({"conditions": DRY_23C})))

    def test_orientation_dependent_material_without_an_effective_model_is_refused(self) -> None:
        part = bracket("tst_polymer_fdm", [fx.operation("print", "fdm", fx.unknown("no capability in this fixture"))])
        self.build(documents(profiles=[printed()], part=part))
        self.assertIn("material.condition", self.refused(self.case({"conditions": DRY_23C})))  # orientation unstated
        self.solved.clear()
        self.assertEqual(self.refused(self.case({"conditions": {**DRY_23C, "orientation": "Z"}})), ["material.anisotropy"])

    def test_bulk_properties_never_stand_in_for_a_printed_part(self) -> None:
        part = bracket("tst_alloy_rod", [fx.operation("print", "fdm", fx.unknown("no capability in this fixture"))])
        self.build(documents(part=part))
        self.assertIn("material.form_process", self.refused(self.case({"conditions": DRY_23C})))

    def test_production_service_needs_a_yield_allowable(self) -> None:
        self.build(documents(service_class="production"))
        self.assertIn("material.allowable", self.refused(self.case({"conditions": DRY_23C})))

    def test_a_standalone_case_cannot_name_profile_conditions(self) -> None:
        self.build(documents())
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), patch("sys.stdout", output):
            status = fea_static.main([str(self.case({"conditions": DRY_23C}))])
        self.assertEqual(status, 2)
        self.assertIn("--hw and --version", json.loads(output.getvalue())["error"]["message"])


class QualifiedProfile(SourcedFEACase):
    def test_the_solver_gets_the_profile_values_and_the_result_is_simulation_evidence_only(self) -> None:
        self.build(documents())
        status, report = self.call(self.case({"conditions": DRY_23C}))
        self.assertEqual(status, 0, report)
        self.assertEqual(self.solved, [{"name": "tst_alloy_rod (TST fixture)", "E": 70000.0, "nu": 0.33,
                                        "density": 2700.0, "yield": 250.0}])
        self.assertEqual(report["evidence"]["level"], "simulation_supported")
        self.assertFalse(report["evidence"]["physical_validation"])
        self.assertFalse(report["evidence"]["exploratory"])
        self.assertEqual(report["material"]["source"], "profile")
        rows = {row["input"]: row for row in report["material"]["properties"]}
        self.assertEqual((rows["E"]["basis"], rows["E"]["sources"][0]["kind"]), ("supplier_typical", "datasheet"))
        self.assertEqual(report["mesh"]["convergence"]["status"], "not_demonstrated")
        binding = report["binding"]
        self.assertEqual((binding["PN"], binding["part_revision"], binding["route"]), (PN, "X1", ["cnc"]))
        self.assertEqual(binding["material_profile"]["id"], "tst_alloy_rod")
        manifest = json.loads((self.hw / "analysis" / "v1" / "bracket" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["conditions"]["binding"], binding)
        # No criterion is named and no convergence is shown: an expected check stays unknown, never pass.
        self.assertEqual(set(self.outcomes(report).values()), {"unknown"})
        self.assertEqual(report["engineering"]["result"], "unknown")
        self.validate_packet(report["engineering"])

    def test_a_criterion_service_loads_and_convergence_make_strength_and_stiffness_pass(self) -> None:
        self.build(documents())
        status, report = self.call(self.convergent_case())
        self.assertEqual(status, 0, report)
        self.assertEqual(report["required_safety_factor"], 2.0)  # from REQ-001, not a bare case number
        self.assertTrue(report["evidence"]["service_evidence"], report["evidence"]["gaps"])
        self.assertEqual(self.outcomes(report), {f"engineering.stiffness@{PN}": "pass", f"engineering.strength@{PN}": "pass"})
        self.assertEqual({row["level"] for row in report["engineering"]["outcomes"]}, {"simulation_supported"})
        self.assertEqual(report["engineering"]["dependencies"]["decision_dr_002"],
                         hashlib.sha256((self.hw / "decisions" / "DR-002.md").read_bytes()).hexdigest())
        self.validate_packet(report["engineering"])

    def test_the_engineering_packet_is_sealed_where_evidence_reads_producer_packets(self) -> None:
        """The record version 2 packet is published beside its analysis bundle as hw/checks/<V>/fea-<case>/,
        bound to the version and citing the analysis bundle; cad-record evidence.py collects it (its one
        reader of producer packets) and a rerun of the same case reuses both bundles."""
        self.build(documents())
        path = self.convergent_case()
        status, report = self.call(path)
        self.assertEqual((status, report["check_bundle"]), (0, "hw/checks/v1/fea-bracket"), report)
        bundle = self.hw / "checks" / "v1" / "fea-bracket"
        self.assertEqual(json.loads((bundle / "result.json").read_text(encoding="utf-8")), report["engineering"])
        analysis = json.loads((bundle / "evidence" / "analysis.json").read_text(encoding="utf-8"))["analysis"]
        self.assertEqual(analysis, {"bundle": "hw/analysis/v1/bracket", "manifest_sha256": hashlib.sha256(
            (self.hw / "analysis" / "v1" / "bracket" / "manifest.json").read_bytes()).hexdigest()})
        manifest_sha = hashlib.sha256((self.hw / "versions" / "v1" / "manifest.json").read_bytes()).hexdigest()
        packets, findings = evidence_module().collect_packets(self.hw, "v1", manifest_sha)
        self.assertEqual((findings, [p.bundle for p in packets]), ([], ["hw/checks/v1/fea-bracket"]))
        status, again = self.call(path)
        self.assertEqual((status, again["reused"], again["check_bundle"]), (0, True, "hw/checks/v1/fea-bracket"))
        self.assertEqual(self.solved[1:], [], "a reused case is not solved again")

    def test_a_missed_criterion_fails_with_a_critical_finding(self) -> None:
        self.build(documents())
        self.solution["safety_factor_yield"] = 1.5
        status, report = self.call(self.case({"conditions": DRY_23C}, acceptance={"strength": "REQ-001"}))
        self.assertEqual(status, 1)
        self.assertEqual(self.outcomes(report)[f"engineering.strength@{PN}"], "fail")
        finding = next(f for f in report["engineering"]["findings"] if f["code"] == "fea.strength.margin")
        self.assertEqual((finding["severity"], finding["measured"]), ("critical", {"value": 1.5, "units": "dimensionless"}))
        self.validate_packet(report["engineering"])

    def test_an_undercovered_service_load_keeps_strength_unknown(self) -> None:
        self.build(documents())
        path = self.case({"conditions": SERVICE}, acceptance={"strength": "REQ-001"}, mesh_convergence={"decision": "DR-002"},
                         loads=[{"selector": {"indices": [2]}, "force": [0, 0, -20], "load": "head_load"}])
        self.approve(self.study(path))
        status, report = self.call(path)
        self.assertEqual(status, 0)
        self.assertEqual(self.outcomes(report)[f"engineering.strength@{PN}"], "unknown")
        self.assertIn("reaches 50 N", report["engineering"]["outcomes"][1]["uncertainty"])

    def test_an_effective_isotropic_decision_needs_status_approved(self) -> None:
        """The same rule as for a convergence decision: a provisional or void decision is not evidence."""
        part = bracket("tst_polymer_fdm", [fx.operation("print", "fdm", fx.unknown("no capability in this fixture"))])
        self.build(documents(profiles=[printed()], part=part))
        model = {"decision": "DR-003", "justification": "TST: Z-direction values bound the layer-normal load path"}
        path = self.case({"conditions": {**DRY_23C, "orientation": "Z"}, "effective_isotropic": model})
        for status in (None, "Status: PROVISIONAL", "Status: VOID", "Status: DRAFT", "Status: approved", "Status: APPROVED "):
            with self.subTest(status=status):
                self.solved.clear()
                text = (f"{status}\n\n" if status is not None else "") + "# DR-003: effective isotropic model\n"
                (self.hw / "decisions" / "DR-003.md").write_text(text, encoding="utf-8")
                self.assertEqual(self.refused(path), ["material.anisotropy"])

    def test_an_approved_effective_isotropic_model_analyses_printed_material_at_its_orientation(self) -> None:
        part = bracket("tst_polymer_fdm", [fx.operation("print", "fdm", fx.unknown("no capability in this fixture"))])
        self.build(documents(profiles=[printed()], part=part))
        (self.hw / "decisions" / "DR-003.md").write_text("Status: APPROVED\n\n# DR-003: effective isotropic model\n", encoding="utf-8")
        model = {"decision": "DR-003", "justification": "TST: Z-direction values bound the layer-normal load path"}
        status, report = self.call(self.case({"conditions": {**DRY_23C, "orientation": "Z"}, "effective_isotropic": model}))
        self.assertEqual(status, 0, report)
        self.assertEqual((self.solved[0]["E"], self.solved[0]["yield"]), (1500.0, 20.0))
        self.assertEqual(report["material"]["isotropy"]["model"], "effective_isotropic")
        self.assertIn(f"engineering.anisotropy@{PN}", self.outcomes(report))
        self.validate_packet(report["engineering"])

    def test_production_service_resolves_the_yield_allowable(self) -> None:
        profile = alloy(prop("youngs_modulus", 70000, "MPa"), prop("poisson_ratio", 0.33, "dimensionless"),
                        prop("density", 2700, "kg_m3"), prop("yield_strength", 250, "MPa"),
                        prop("yield_strength", 200, "MPa", basis="allowable"), typical_not_allowable=False)
        self.build(documents(profiles=[profile], service_class="production"))
        status, report = self.call(self.case({"conditions": DRY_23C}))
        self.assertEqual(status, 0, report)
        self.assertEqual(self.solved[0]["yield"], 200.0)
        rows = {row["input"]: row for row in report["material"]["properties"]}
        self.assertEqual(rows["yield"]["basis"], "allowable")

    def test_a_changed_decision_invalidates_the_published_bundle(self) -> None:
        self.build(documents())
        path = self.case({"conditions": DRY_23C}, mesh_convergence={"decision": "DR-002"})
        self.assertEqual(self.call(path)[0], 0)
        (self.hw / "decisions" / "DR-002.md").write_text("# DR-002\n\nRevised mesh study.\n", encoding="utf-8")
        status, report = self.call(path)
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])

    def validate_packet(self, packet: dict[str, Any]) -> None:
        validator = fx.schema_registry_module().document_validator(
            SKILLS / "cad-record" / "schemas", "manufacturing-check-result.schema.json")
        errors = [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(packet)]
        self.assertEqual(errors, [])


class QualificationBypasses(SourcedFEACase):
    """A pass needs service loads shown covered as vectors and a convergence study that is approved, bound to this
    case and converged. Anything unproven is unknown, never pass, and never service evidence."""

    def verdicts(self, report: dict[str, Any]) -> tuple[str, str]:
        outcomes = self.outcomes(report)
        return outcomes[f"engineering.strength@{PN}"], outcomes[f"engineering.stiffness@{PN}"]

    def solve(self, path: Path) -> dict[str, Any]:
        """Solve the case, replacing the bundle of an earlier variant of it."""
        self.solved.clear()
        status, report = self.call(path, "--replace")
        self.assertEqual(status, 0, report)
        return report

    fresh = solve

    def assert_unproven(self, report: dict[str, Any], *, convergence: bool = False, loads: bool = False) -> None:
        self.assertEqual(self.verdicts(report), ("unknown", "unknown"), report["engineering"]["outcomes"])
        self.assertEqual(report["engineering"]["result"], "unknown")
        self.assertFalse(report["evidence"]["service_evidence"])
        if convergence:
            self.assertEqual(report["mesh"]["convergence"]["status"], "not_demonstrated")
            self.assertTrue(report["mesh"]["convergence"]["problems"])
            self.assertTrue(any("mesh convergence" in gap for gap in report["evidence"]["gaps"]), report["evidence"]["gaps"])
        if loads:
            self.assertTrue(any("head_load" in gap for gap in report["evidence"]["gaps"]), report["evidence"]["gaps"])

    # -- service loads are compared as vectors -----------------------------------------------------------------

    def loads_case(self, *loads: tuple[list[int], list[float]]) -> Path:
        entries = [{"selector": {"indices": faces}, "force": force, "load": "head_load"} for faces, force in loads]
        path = self.case({"conditions": SERVICE}, acceptance={"strength": "REQ-001", "stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"}, loads=entries)
        self.approve(self.study(path))
        return path

    def test_a_larger_load_along_the_direction_and_a_small_cross_component_still_pass(self) -> None:
        self.build(documents())
        self.assertEqual(self.verdicts(self.solve(self.loads_case(([2], [0, 0, -60])))), ("pass", "pass"))
        self.solved.clear()
        self.assertEqual(self.verdicts(self.solve(self.loads_case(([2], [0.2, 0, -50])))), ("pass", "pass"))  # 0.4% across

    def test_split_loads_that_add_up_to_the_service_vector_pass(self) -> None:
        self.build(documents())
        report = self.solve(self.loads_case(([2], [0, 0, -30]), ([3], [0, 0, -20])))
        self.assertEqual(self.verdicts(report), ("pass", "pass"))

    def test_a_force_in_the_wrong_direction_keeps_the_verdict_unknown(self) -> None:
        self.build(documents())
        for name, force in (("opposite", [0, 0, 50]), ("perpendicular", [50, 0, 0]), ("tilted 30 degrees", [25, 0, -43.3])):
            with self.subTest(force=name):
                self.solved.clear()
                self.assert_unproven(self.solve(self.loads_case(([2], force))), loads=True)

    def test_a_cross_force_beyond_the_tolerance_keeps_the_verdict_unknown_with_the_full_load_along(self) -> None:
        """50 N along the service direction meets the along minimum; 1 N across it is 2% of the load, past the 1%
        tolerance. Only the cross check can refuse this case."""
        self.build(documents())
        report = self.solve(self.loads_case(([2], [1.0, 0, -50])))
        self.assert_unproven(report, loads=True)
        self.assertTrue(any("across" in gap for gap in report["evidence"]["gaps"]), report["evidence"]["gaps"])
        self.assertFalse(any("along" in gap for gap in report["evidence"]["gaps"]), report["evidence"]["gaps"])

    def test_cancelling_forces_keep_the_verdict_unknown(self) -> None:
        """Two 50 N forces that cancel have a magnitude sum of 100 N and a vector sum of zero."""
        self.build(documents())
        report = self.solve(self.loads_case(([2], [0, 0, -50]), ([3], [0, 0, 50])))
        self.assert_unproven(report, loads=True)

    def assert_direction_never_passes(self, direction: Any) -> None:
        """A direction that is not a valid unit vector either stops the case at the record (nothing is solved) or
        leaves its loads unproven."""
        self.solved.clear()
        self.build(documents(direction=direction))
        status, report = self.call(self.loads_case(([2], [0, 0, -50])), "--replace")
        if status == 2:
            self.assertEqual(self.solved, [], "a refused case must never reach the solver")
            return
        self.assertEqual(status, 0, report)
        self.assert_unproven(report, loads=True)

    def test_a_service_direction_that_is_missing_or_not_a_vector_never_passes(self) -> None:
        for direction in (None, "downwards", "0 0", {}, 7):
            with self.subTest(direction=direction):
                self.assert_direction_never_passes(direction)

    def test_a_malformed_vector_direction_never_passes(self) -> None:
        for direction in ((0, 0), (0, 0, 0), (0, 0, "down"), (0, 0, -1, 0), (0, 0, -2), (0.6, 0, -0.6)):
            with self.subTest(direction=direction):
                self.assert_direction_never_passes(direction)

    def test_a_non_finite_service_direction_never_passes(self) -> None:
        """YAML carries .nan and .inf where JSON cannot, so the fixture goes through the same YAML path the CLI reads."""
        nan, inf = float("nan"), float("inf")
        for direction in ([nan, 0, 1], [0, nan, 0], [inf, 0, 0], [0, 0, inf], [-inf, 0, 0], [0, -inf, 0], [nan, nan, nan]):
            with self.subTest(direction=direction):
                self.assert_direction_never_passes(direction)
                written = (self.hw / "product.yaml").read_text(encoding="utf-8")
                self.assertTrue(".nan" in written or ".inf" in written)   # the bare list reached product.yaml

    def test_text_forms_of_a_service_direction_are_no_longer_read(self) -> None:
        """The free-text forms were parsed before direction became a required [x, y, z] list; there is no fallback."""
        for direction in ("0 0 -1", "[0, 0, -1]", "(0,0,-2)", "-Z", "-z", fx.known("0 0 -1"), fx.known("-Z")):
            with self.subTest(direction=direction):
                self.assert_direction_never_passes(direction)

    def test_a_direction_within_the_unit_tolerance_covers_a_load_of_exactly_its_magnitude(self) -> None:
        """The record accepts a norm within 1e-6 of 1; the reader must project on the direction, not on its length.
        50 N along -Z reached 49.999975 N along (0, 0, -0.9999995) and the load was wrongly left unproven."""
        for scale in (1 - 0.9e-6, 1 + 0.9e-6):
            for axis, force in (((0, 0, -1), [0, 0, -50]), ((0.6, 0, -0.8), [30, 0, -40])):
                direction = tuple(c * scale for c in axis)
                with self.subTest(direction=direction):
                    self.solved.clear()
                    self.build(documents(direction=direction))
                    report = self.solve(self.loads_case(([2], force)))
                    self.assertEqual(self.verdicts(report), ("pass", "pass"), report["evidence"]["gaps"])

    def test_a_direction_just_outside_the_unit_tolerance_is_still_refused(self) -> None:
        for scale in (1 - 1.1e-6, 1 + 1.1e-6):
            direction = (0, 0, -scale)
            with self.subTest(direction=direction):
                self.assert_direction_never_passes(direction)

    def test_a_unit_vector_direction_is_read_as_given(self) -> None:
        for direction in ((0, 0, -1), (0.0, 0.0, -1.0), (0, -1, 0), (0.6, 0, -0.8)):
            with self.subTest(direction=direction):
                self.solved.clear()
                self.build(documents(direction=direction))
                force = [50 * c for c in direction]
                report = self.solve(self.loads_case(([2], force)))
                self.assertEqual(self.verdicts(report), ("pass", "pass"), report["evidence"]["gaps"])

    # -- a convergence decision counts only as an approved, bound, converged study ---------------------------------

    def test_only_a_first_line_of_exactly_status_approved_counts(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        study = self.study(path)
        statuses = [None, "Status: PROVISIONAL", "Status: VOID", "Status: DRAFT", "Status: approved", "Status: APPROVED ",
                    "Status:APPROVED", "status: APPROVED", "Status: NOT APPROVED"]
        for status in statuses:
            with self.subTest(status=status):
                self.approve(study, status=status)
                self.assert_unproven(self.fresh(path), convergence=True)
        self.approve(study, status="# DR-002\n\nStatus: APPROVED")  # approved only on a later line
        self.assert_unproven(self.fresh(path), convergence=True)
        self.approve(study)
        self.assertEqual(self.verdicts(self.fresh(path)), ("pass", "pass"))

    def test_a_decision_without_a_study_or_with_an_empty_one_proves_nothing(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        for name, study in (("no study block", None), ("empty study", {}), ("empty refinements", self.study(path, refinements=[])),
                            ("no refinements key", {k: v for k, v in self.study(path).items() if k != "refinements"})):
            with self.subTest(study=name):
                self.approve(study)
                self.assert_unproven(self.fresh(path), convergence=True)

    def test_a_study_missing_part_of_its_binding_proves_nothing(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        for key in ("geometry_sha256", "material", "supports", "loads", "mesh", "criterion"):
            with self.subTest(missing=key):
                self.approve({k: v for k, v in self.study(path).items() if k != key})
                self.assert_unproven(self.fresh(path), convergence=True)

    def test_a_study_bound_to_something_else_proves_nothing(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        base = self.study(path)
        other = {
            "another geometry": {"geometry_sha256": "0" * 64},
            "another material profile": {"material": {"profile": "tst_alloy_rod", "sha256": "1" * 64}},
            "another profile id": {"material": {"profile": "tst_polymer_fdm", "sha256": base["material"]["sha256"]}},
            "other supports": {"supports": {"indices": [4]}},
            "supports on a plane": {"supports": {"plane": {"axis": "x", "value": 0, "tolerance": 1e-6}}},
            "another force direction": {"loads": [{"selector": {"indices": [2]}, "force": [0, 0, 50]}]},
            "another force magnitude": {"loads": [{"selector": {"indices": [2]}, "force": [0, 0, -50.1]}]},
            "another application region": {"loads": [{"selector": {"indices": [3]}, "force": [0, 0, -50]}]},
            "an extra load": {"loads": base["loads"] + [{"selector": {"indices": [3]}, "force": [0, 0, -1]}]},
            "another mesh size": {"mesh": {"size_mm": 3, "element_order": "second"}},
            "another element order": {"mesh": {"size_mm": 2, "element_order": "first"}},
        }
        for name, change in other.items():
            with self.subTest(study=name):
                self.approve({**base, **change})
                self.assert_unproven(self.fresh(path), convergence=True)

    def test_a_study_bound_within_the_stated_tolerance_still_counts(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        study = self.study(path, loads=[{"selector": {"indices": [2]}, "force": [0, 0, -50.00001]}])
        self.approve(study)
        self.assertEqual(self.verdicts(self.fresh(path)), ("pass", "pass"))

    def test_a_coarse_case_mesh_is_unproven_even_when_the_two_finest_meshes_agree(self) -> None:
        """Sizes 4, 2, 1 with the case at 4: the finest pair differs 0.4 percent, but the case's own mesh reads
        6.4 percent below the finest, past the 5 percent limit."""
        self.build(documents())
        path = self.convergent_case(mesh_size=4)
        rows = self.study(path)["refinements"]
        self.assertEqual([row["size_mm"] for row in rows], [4, 2, 1])
        self.approve(self.study(path, refinements=[{"size_mm": 4, "max_von_mises_mpa": 78.0, "max_displacement_mm": 0.199},
                                                   {"size_mm": 2, "max_von_mises_mpa": 83.0, "max_displacement_mm": 0.199},
                                                   {"size_mm": 1, "max_von_mises_mpa": 83.3, "max_displacement_mm": 0.199}]))
        report = self.solve(path)
        self.assert_unproven(report, convergence=True)
        self.assertTrue(any("on the case's mesh differs" in p for p in report["mesh"]["convergence"]["problems"]),
                        report["mesh"]["convergence"]["problems"])
        self.assertFalse(any("two finest" in p for p in report["mesh"]["convergence"]["problems"]))
        self.approve(self.study(path, refinements=rows))   # the same case mesh with a settled series is demonstrated
        self.approve(self.study(path, refinements=[{"size_mm": 4, "max_von_mises_mpa": 82.5, "max_displacement_mm": 0.198},
                                                   {"size_mm": 2, "max_von_mises_mpa": 83.0, "max_displacement_mm": 0.199},
                                                   {"size_mm": 1, "max_von_mises_mpa": 83.3, "max_displacement_mm": 0.199}]))
        self.assertEqual(self.verdicts(self.solve(path)), ("pass", "pass"))

    def test_plane_selectors_bind_by_value_not_by_spelling(self) -> None:
        """0 and 0.0, 1e-06 and 0.000001, 100 and 100.0 select the same plane."""
        self.build(documents())
        plane = {"plane": {"axis": "x", "value": 0, "tolerance": 0.000001}}
        load_plane = {"plane": {"axis": "x", "value": 100, "tolerance": 0.000001}}
        path = self.case({"conditions": SERVICE}, acceptance={"strength": "REQ-001", "stiffness": "REQ-002"},
                         mesh_convergence={"decision": "DR-002"}, fixed_faces=plane,
                         loads=[{"selector": load_plane, "force": [0, 0, -50], "load": "head_load"}])
        respelled = {"supports": {"plane": {"axis": "x", "value": 0.0, "tolerance": 1e-06}},
                     "loads": [{"selector": {"plane": {"axis": "x", "value": 100.0, "tolerance": 1e-06}}, "force": [0, 0, -50]}]}
        self.approve(self.study(path, **respelled))
        self.assertEqual(self.verdicts(self.solve(path)), ("pass", "pass"))
        for name, change in {"another support plane value": {"supports": {"plane": {"axis": "x", "value": 0.5, "tolerance": 1e-06}}},
                             "another load plane axis": {"loads": [{"selector": {"plane": {"axis": "y", "value": 100.0,
                                                                                           "tolerance": 1e-06}}, "force": [0, 0, -50]}]},
                             "another tolerance": {"supports": {"plane": {"axis": "x", "value": 0.0, "tolerance": 0.01}}}}.items():
            with self.subTest(change=name):
                self.approve(self.study(path, **{**respelled, **change}))
                self.assert_unproven(self.solve(path), convergence=True)

    def test_a_study_that_has_not_converged_proves_nothing(self) -> None:
        self.build(documents())
        path = self.convergent_case()
        rows = self.study(path)["refinements"]
        studies = {
            "two refinements": rows[1:],
            "last two differ by 20 percent": [rows[0], rows[1], {**rows[2], "max_von_mises_mpa": 100.0}],
            "displacement still moving": [rows[0], rows[1], {**rows[2], "max_displacement_mm": 0.3}],
            "case mesh not among the sizes": [{**row, "size_mm": row["size_mm"] * 1.5} for row in rows],
            "sizes not decreasing": [rows[1], rows[0], rows[2]],
            "a monitored quantity missing": [{k: v for k, v in rows[2].items() if k != "max_displacement_mm"}, rows[0], rows[1]],
            "a non-numeric value": [rows[0], rows[1], {**rows[2], "max_von_mises_mpa": "83.3"}],
            "a zero value": [rows[0], rows[1], {**rows[2], "max_von_mises_mpa": 0}],
        }
        for name, refinements in studies.items():
            with self.subTest(study=name):
                self.approve(self.study(path, refinements=refinements))
                self.assert_unproven(self.fresh(path), convergence=True)
        for name, criterion in (("no tolerance", {}), ("zero tolerance", {"relative_change_max": 0}),
                                ("a tolerance above 10 percent", {"relative_change_max": 0.9})):
            with self.subTest(criterion=name):
                self.approve(self.study(path, criterion=criterion))
                self.assert_unproven(self.fresh(path), convergence=True)

    # -- the service-evidence flag follows loads and convergence ------------------------------------------------

    def test_service_evidence_needs_covered_loads_and_a_demonstrated_study(self) -> None:
        self.build(documents())
        good = self.solve(self.loads_case(([2], [0, 0, -50])))
        self.assertTrue(good["evidence"]["service_evidence"], good["evidence"]["gaps"])
        self.assertEqual(good["evidence"]["gaps"], [])
        self.solved.clear()
        gap = self.solve(self.loads_case(([2], [0, 0, 50])))   # study agrees with the case; the load is the wrong way
        self.assertFalse(gap["evidence"]["service_evidence"])
        self.assertTrue(any("head_load" in text for text in gap["evidence"]["gaps"]))
        self.assertEqual(gap["mesh"]["convergence"]["status"], "demonstrated")
        self.solved.clear()
        path = self.loads_case(([2], [0, 0, -50]))
        self.approve(self.study(path), status="Status: PROVISIONAL")
        unproven = self.fresh(path)
        self.assertFalse(unproven["evidence"]["service_evidence"])
        self.assertTrue(any("mesh convergence" in text for text in unproven["evidence"]["gaps"]))


class LegacyExplicitValues(SourcedFEACase):
    EXPLICIT = {"E": 69000, "nu": 0.33, "density": 2700, "yield": 276}

    def test_a_version_of_an_unsupported_record_version_is_refused(self) -> None:
        docs = documents()
        docs["product.yaml"] = {key: value for key, value in docs["product.yaml"].items()
                                if key not in ("record_version", "use_case")}
        self.build(docs)
        status, report = self.call(self.case(dict(self.EXPLICIT)))
        self.assertNotEqual(status, 0, report)
        self.assertIn("record.version_unsupported", json.dumps(report))

    def test_a_standalone_case_keeps_its_numbers_labelled_unsourced(self) -> None:
        path = self.case(dict(self.EXPLICIT))
        output = io.StringIO()

        def run_job(case_path: Path, case: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], int]:
            result = {"status": "pass", **self.solution}
            fea_static.default_result_path(case_path).write_text(json.dumps(result), encoding="utf-8")
            return result, 0

        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.run_job", side_effect=run_job), patch("sys.stdout", output):
            status = fea_static.main([str(path)])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 0, report)
        self.assertEqual((report["material"]["source"], report["evidence"]["level"]), ("unsourced_explicit", None))
        written = json.loads(fea_static.default_result_path(path).read_text(encoding="utf-8"))
        self.assertEqual(written["evidence"], report["evidence"])


if __name__ == "__main__":
    unittest.main()
