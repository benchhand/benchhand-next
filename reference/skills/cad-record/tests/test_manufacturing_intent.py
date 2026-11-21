#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""manufacturing_intent.py: record versions, units, the normalized record and its problems, and the
policy every skill reads it through (use-case readiness, part routes, condition-qualified material
properties, calibrated capability limits and required checks)."""

from __future__ import annotations

import copy
import json
import math
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SKILL = HERE.parent


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from decision_fixture import decision_path, write_test_decision  # noqa: E402
from modload import load_module as load  # noqa: E402


fx = load("cad_record_mi_fixtures", HERE / "fixtures" / "manufacturing_intent.py")
mi = fx.intent_module()


def temp_hw(test: unittest.TestCase) -> Path:
    temporary = tempfile.TemporaryDirectory(prefix="cad-intent-test-")
    test.addCleanup(temporary.cleanup)
    return Path(temporary.name) / "project" / "hw"


def purchase_criteria() -> dict[str, Any]:
    return {"identity": fx.known("TST pin 6x20"), "specification": fx.known("TST hardened steel pin"),
            "ratings": fx.known("TST shear rating"), "supplier_evidence": [fx.source("supplier")]}


def proposing_selection(pn: str = "TST-0901") -> dict[str, Any]:
    """An assessed selection whose one candidate keeps TST-0001 printed, buys TST-0002 (made to drawing in the
    record) as a catalogue item with its purchase criteria, and proposes a new catalogue pin `pn`."""
    bought = {"kind": "purchased", "capability": fx.not_applicable("a purchase has no capability"), "purchase": purchase_criteria()}
    return {"status": "assessed", "assessment": {"input_sha256": "a" * 64, "method": "TST", "date": "2026-01-01"},
            "candidates": [{
                "id": "pinned", "title": "Printed bracket with a bought shaft and pin", "architecture": "printed bracket, bought shaft, new pin",
                "parts": [{"PN": "TST-0001", "material_profile": "tst_polymer_printed", "route": [{"kind": "fdm", "capability": "tst_printer"}]},
                          {"PN": "TST-0002", "material_profile": fx.not_applicable("catalogue item"), "route": [copy.deepcopy(bought)]},
                          {"PN": pn, "material_profile": fx.not_applicable("catalogue item"), "route": [copy.deepcopy(bought)],
                           "proposed": {"title": "TST pin", "sourcing": "catalogue", "reason": "the pin carries the bracket pivot",
                                        "functions": [{"function": "rotating", "requirements": ["REQ-001"]}]}}],
                "evaluations": [], "pros": ["TST pro"], "cons": ["TST con"], "tradeoffs": ["TST tradeoff"]}]}


class Versions(unittest.TestCase):
    def test_only_version_2_is_current_and_any_other_is_refused(self) -> None:
        self.assertEqual(mi.record_version({"record_version": 2}), 2)
        for product in ({}, {"record_version": 1}, {"record_version": 3}, {"record_version": True},
                        {"record_version": "2"}, {"record_version": None}):
            with self.subTest(product=product), self.assertRaises(mi.UnsupportedRecordVersion):
                mi.record_version(product)

    def test_version_problem_refuses_any_unknown_version_and_blocks(self) -> None:
        for product in ({"id": "x"}, {"record_version": 1}, {"record_version": 7}):
            with self.subTest(product=product):
                problem = mi.version_problem(product)
                self.assertEqual((problem.code, problem.severity, problem.path, problem.pointer),
                                 ("record.version_unsupported", "error", "hw/product.yaml", "record_version"))
        self.assertIsNone(mi.version_problem({"record_version": 2}))
        self.assertEqual(mi.version_problem(None).code, "record.version_unsupported", "no product.yaml names no version")
        self.assertLessEqual({"record.version_unsupported", "record.incomplete"}, set(mi.CODES))
        self.assertNotIn("record.migration_required", mi.CODES)


class Quantities(unittest.TestCase):
    def test_conversion_stays_within_a_dimension(self) -> None:
        self.assertAlmostEqual(mi.convert(1500, "mm", "m"), 1.5)
        self.assertAlmostEqual(mi.convert(23, "deg_C", "K"), 296.15)
        self.assertAlmostEqual(mi.convert(180, "deg", "rad"), math.pi)
        self.assertAlmostEqual(mi.convert(1.24, "g_cm3", "kg_m3"), 1240)
        self.assertAlmostEqual(mi.convert(50, "percent", "dimensionless"), 0.5)
        with self.assertRaisesRegex(mi.IntentError, "cannot convert"):
            mi.convert(1, "MPa", "kg_m3")
        with self.assertRaisesRegex(mi.IntentError, "unknown unit"):
            mi.convert(1, "inch", "mm")

    def test_quantities_refuse_non_finite_boolean_and_reversed_values(self) -> None:
        for data in ({"value": float("nan"), "units": "mm"}, {"value": float("inf"), "units": "mm"}, {"value": True, "units": "mm"},
                     {"lower": 2, "upper": 1, "units": "mm"}, {"value": 1, "units": "furlong"}, {"units": "mm"},
                     {"value": 10**400, "units": "mm"}):
            with self.subTest(data=data), self.assertRaises(mi.IntentError):
                mi.quantity(data)
        tested = mi.quantity({"lower": 20, "upper": 80, "units": "deg_C"})
        self.assertTrue(tested.contains(mi.quantity({"value": 60, "units": "deg_C"})))
        self.assertTrue(tested.contains(mi.quantity({"value": 300, "units": "K"})))
        self.assertFalse(tested.contains(mi.quantity({"lower": 60, "upper": 90, "units": "deg_C"})))
        self.assertFalse(tested.contains(mi.quantity({"value": 60, "units": "mm"})))


class Normalization(unittest.TestCase):
    def test_the_tst_record_normalizes_without_problems(self) -> None:
        hw = fx.write_record(temp_hw(self), fx.tst_record())
        record, problems = mi.check_record(hw)
        self.assertEqual([p.finding() for p in problems], [])
        self.assertEqual(record.version, 2)
        self.assertEqual({pn: p.sourcing for pn, p in record.parts.items()},
                         {"TST-0001": "make", "TST-0002": "made_to_drawing", "TST-0003": "catalogue", "TST-0004": "make"})
        bracket = record.parts["TST-0001"]
        self.assertEqual([op.id for op in bracket.intent.route], ["print", "ream"])
        self.assertEqual(bracket.intent.material_profile, "tst_polymer_printed")
        self.assertEqual(bracket.material, "TST polymer", "the legacy declaration stays a string")
        load_fact = record.use_case.loads[0].magnitude
        self.assertEqual((load_fact.status, load_fact.value), ("known", mi.Quantity("N", value=11.0)))
        self.assertTrue(record.use_case.service_class.unknown)
        self.assertEqual(record.use_case.service_class.question, "Q-001")
        self.assertEqual(dict(mi.source_artifacts(record)), {"manufacturing/sources/tst-sheet.pdf": fx.sha256(b"%PDF-1.4 TST fixture datasheet\n")})
        self.assertEqual(record.materials["tst_metal_rod"].properties[0].value.basis, "allowable")
        self.assertTrue(record.capabilities["tst_printer"].parameters["nozzle_diameter"].known)
        self.assertEqual(len(record.assembly_operations), 1)

    def test_a_material_property_exposes_its_elongation_gauge_or_none(self) -> None:
        documents = fx.tst_record()
        gauged = fx.material_property("elongation_at_break", 0.25, "dimensionless", temperature=fx.quantity(20, "deg_C"))
        gauged["conditions"]["gauge"] = "5.65sqrtS0"
        bare = fx.material_property("elongation_at_break", 0.25, "dimensionless")
        rod = next(p for p in documents["manufacturing/materials.yaml"]["profiles"] if p["id"] == "tst_metal_rod")
        rod["properties"] += [gauged, bare]
        record, problems = mi.check_record(fx.write_record(temp_hw(self), documents))
        self.assertEqual([p.finding() for p in problems], [])
        found = [p for p in record.materials["tst_metal_rod"].properties if p.name == "elongation_at_break"]
        self.assertEqual([p.gauge for p in found], ["5.65sqrtS0", None])

    def test_a_record_of_an_unsupported_version_reads_as_unknowns_and_one_problem(self) -> None:
        for version in (1, 3):
            hw = fx.write_record(temp_hw(self), fx.tst_record())
            product = hw / "product.yaml"
            product.write_text(product.read_text(encoding="utf-8").replace("record_version: 2", f"record_version: {version}"),
                               encoding="utf-8")
            record = mi.load_record(hw)
            with self.subTest(version=version):
                self.assertEqual(record.version, 0)
                self.assertEqual([p.code for p in record.problems], ["record.version_unsupported"])
                self.assertTrue(record.use_case.unknown)
                self.assertTrue(record.assembly_operations.unknown)
                self.assertEqual((dict(record.capabilities), dict(record.materials)), ({}, {}))

    def test_a_candidate_proposes_a_new_part_that_is_never_a_record(self) -> None:
        documents = fx.tst_record()
        documents["manufacturing/selection.yaml"] = proposing_selection()
        record, problems = mi.check_record(fx.write_record(temp_hw(self), documents))
        self.assertEqual([p.finding() for p in problems], [])
        self.assertEqual(set(record.selection.proposed), {"pinned"})
        self.assertEqual(set(record.selection.proposed["pinned"]), {"TST-0901"}, "declared parts are not proposals")
        proposal = record.selection.proposed["pinned"]["TST-0901"]
        self.assertEqual((proposal.pn, proposal.candidate, proposal.title, proposal.sourcing, proposal.transparency),
                         ("TST-0901", "pinned", "TST pin", "catalogue", None))
        self.assertEqual([(f.function, f.requirements) for f in proposal.functions], [("rotating", ("REQ-001",))])
        self.assertNotIn("TST-0901", record.parts)
        self.assertEqual([o.id for o in mi.required_checks(record) if o.subject.get("PN") == "TST-0901"], [], "a proposal has no obligations")
        step = record.selection.candidates["pinned"]["parts"][1]["route"][0]
        self.assertEqual((step["kind"], step["purchase"]["identity"]["value"]), ("purchased", "TST pin 6x20"),
                         "a purchased alternative to a made part carries its purchase criteria")

    def test_each_contradiction_is_reported_with_its_code(self) -> None:
        def part(d: dict[str, Any], pn: str = "TST-0001") -> dict[str, Any]:
            return d[f"parts/{pn}/part.yaml"]

        def route(d: dict[str, Any], pn: str = "TST-0001") -> list[dict[str, Any]]:
            return part(d, pn)["intent"]["route"]

        def material(d: dict[str, Any], index: int) -> dict[str, Any]:
            return d["manufacturing/materials.yaml"]["profiles"][index]

        def capability(d: dict[str, Any], index: int) -> dict[str, Any]:
            return d["manufacturing/capabilities.yaml"]["profiles"][index]

        def drawing_operations(d: dict[str, Any]) -> None:
            d["assembly.yaml"]["drawing"] = {"number": "TST", "rev": "X1", "title": "TST", "views": [], "items": [],
                                             "operations": copy.deepcopy(d["assembly.yaml"]["operations"])}

        def set_direction(d: dict[str, Any], direction: list[float]) -> None:
            d["product.yaml"]["use_case"]["loads"][0]["direction"] = direction

        def propose(d: dict[str, Any], pn: str = "TST-0901") -> None:
            d["manufacturing/selection.yaml"] = proposing_selection(pn)

        def candidate_parts(d: dict[str, Any]) -> list[dict[str, Any]]:
            propose(d)
            return d["manufacturing/selection.yaml"]["candidates"][0]["parts"]

        cases: dict[str, tuple[Callable[[dict[str, Any]], Any], str]] = {
            "unanswered question id": (lambda d: part(d)["intent"].update(functions=fx.unknown("x", "Q-099")), "intent.reference"),
            "undeclared requirement": (lambda d: part(d)["intent"]["service"].update(requirements=["REQ-009"]), "intent.reference"),
            "undeclared load": (lambda d: part(d)["intent"]["service"].update(loads=["wind"]), "intent.reference"),
            "undeclared material profile": (lambda d: part(d)["intent"].update(material_profile="unobtainium"), "intent.reference"),
            "undeclared capability": (lambda d: route(d)[0].update(capability="ghost_printer"), "intent.reference"),
            "undeclared inspection": (lambda d: part(d)["intent"]["critical_surfaces"][0].update(inspection="nothing"), "intent.reference"),
            "missing decision record": (lambda d: route(d)[0]["orientation"].update(decision="DR-009"), "intent.reference"),
            "missing stack case": (lambda d: d["interfaces.yaml"]["interfaces"][0]["functional"].update(
                variation={"stack_case": "stk-9", "contributors": ["manufacture"], "method": "worst_case"}), "intent.reference"),
            "duplicate question": (lambda d: d["requirements.yaml"]["open_questions"].append(fx.question("Q-001")), "intent.duplicate"),
            "duplicate operation": (lambda d: route(d).append(fx.operation("print", "finishing")), "intent.duplicate"),
            "force given in mm": (lambda d: d["product.yaml"]["use_case"]["loads"][0].update(magnitude=fx.known(fx.quantity(11, "mm"))), "intent.units"),
            "temperature given in MPa": (lambda d: d["product.yaml"]["use_case"]["environment"].update(
                temperature=fx.known(fx.quantity(40, "MPa"))), "intent.units"),
            "direction of norm 1 + 2e-6": (lambda d: set_direction(d, [1 + 2e-6, 0, 0]), "load.direction_not_unit"),
            "zero direction": (lambda d: set_direction(d, [0, 0, 0]), "load.direction_not_unit"),
            "direction of norm 2": (lambda d: set_direction(d, [0, 0, -2]), "load.direction_not_unit"),
            "not a number": (lambda d: d["product.yaml"]["use_case"]["loads"][0].update(magnitude=fx.known(fx.quantity(float("nan"), "N"))),
                             "intent.number"),
            "reversed interval": (lambda d: d["product.yaml"]["use_case"]["environment"].update(
                temperature=fx.known(fx.quantity(lower=60, upper=-20, units="deg_C"))), "intent.number"),
            "not a unit quaternion": (lambda d: route(d)[0]["orientation"]["rotation"].update(quaternion=[1, 1, 0, 0]), "intent.number"),
            "dependency on no operation": (lambda d: route(d)[1].update(depends_on=["mill"]), "intent.route"),
            "cyclic route": (lambda d: (route(d)[0].update(depends_on=["ream"]), route(d)[1].update(depends_on=["print"])), "intent.route"),
            "catalogue buy that is machined": (lambda d: route(d, "TST-0003").append(fx.operation("drill", "drilling")), "intent.route"),
            "catalogue buy without its purchase": (lambda d: part(d, "TST-0003")["intent"].update(route=[fx.operation("check", "inspection")]),
                                                   "intent.route"),
            "made part bought as an operation": (lambda d: route(d).insert(0, fx.operation("buy", "purchased")), "intent.route"),
            "two operation authorities": (drawing_operations, "intent.dual_authority"),
            "allowable in a typical profile": (lambda d: material(d, 2)["properties"].append(
                fx.material_property("yield_strength", 1, "MPa", basis="allowable")), "intent.allowable"),
            "allowable in family guidance": (lambda d: material(d, 0)["properties"].append(
                fx.material_property("yield_strength", 1, "MPa", basis="allowable", orientation=fx.known("XY"))), "intent.allowable"),
            "printed property without orientation": (lambda d: material(d, 0)["properties"].append(fx.material_property("youngs_modulus", 1, "MPa")),
                                                     "intent.profile"),
            "unknown property name": (lambda d: material(d, 1)["properties"].append(fx.material_property("strength_from_density", 1, "MPa")),
                                      "intent.profile"),
            "property of the wrong dimension": (lambda d: material(d, 1)["properties"].append(fx.material_property("density", 1, "MPa")),
                                                "intent.units"),
            "accuracy as a parameter": (lambda d: capability(d, 0)["parameters"].update(hole_accuracy=fx.known(fx.quantity(0.1))), "intent.profile"),
            "text parameter as a quantity": (lambda d: capability(d, 0)["parameters"].update(enclosure=fx.known(fx.quantity(1))), "intent.units"),
            "template used as a capability": (lambda d: capability(d, 0).update(template=True, guidance=["x"], calibrations=[]), "intent.profile"),
            "laser profile on a print": (lambda d: route(d)[0].update(capability="tst_laser"), "intent.profile"),
            "calibration from an estimate": (lambda d: capability(d, 0)["calibrations"][0].update(source=fx.source("estimate")), "intent.profile"),
            "calibration from a guideline": (lambda d: capability(d, 0)["calibrations"][0].update(
                source=fx.source("guideline", "fdm.generic", revision="1", sha256="a" * 64)), "intent.profile"),
            "unknown route kind": (lambda d: route(d).append(fx.operation("sinter", "sintering")), "intent.coverage"),
            "part without intent": (lambda d: part(d).pop("intent"), "record.incomplete"),
            "interface without functional": (lambda d: d["interfaces.yaml"]["interfaces"][0].pop("functional"), "record.incomplete"),
            "assembly without operations": (lambda d: d["assembly.yaml"].pop("operations"), "record.incomplete"),
            "requirements without questions": (lambda d: d["requirements.yaml"].pop("open_questions"), "record.incomplete"),
            "no selection record": (lambda d: d.pop("manufacturing/selection.yaml"), "record.incomplete"),
            "source bytes changed": (lambda d: d["_sources"].update({"manufacturing/sources/tst-sheet.pdf": b"edited"}), "intent.source_artifact"),
            "source missing": (lambda d: d["_sources"].clear(), "intent.source_artifact"),
            "proposed part that is already declared": (lambda d: propose(d, "TST-0003"), "intent.duplicate"),
            "candidate part listed twice": (lambda d: (lambda parts: parts.append(copy.deepcopy(parts[0])))(candidate_parts(d)), "intent.duplicate"),
            "candidate part neither declared nor proposed": (lambda d: candidate_parts(d)[2].pop("proposed"), "intent.reference"),
            "unanswered question in a candidate purchase": (lambda d: candidate_parts(d)[1]["route"][0]["purchase"].update(
                ratings=fx.unknown("x", "Q-099")), "intent.reference"),
            "undeclared requirement of a proposed part": (lambda d: candidate_parts(d)[2]["proposed"]["functions"][0].update(
                requirements=["REQ-009"]), "intent.reference"),
            "undeclared policy decision": (lambda d: d["requirements.yaml"]["requirements"][0].setdefault("acceptance", []).append(
                fx.criterion("load", ">=", 1, "N", source=fx.source("policy", decision="DR-009"))), "intent.reference"),
            "edge distance criterion in degrees": (lambda d: d["assembly.yaml"]["operations"][0].update(edge_distance={
                "criterion": fx.criterion("edge_distance", ">=", 3, "deg"), "distance": fx.known(fx.quantity(4))}), "intent.units"),
            "edge distance given as an angle": (lambda d: d["assembly.yaml"]["operations"][0].update(edge_distance={
                "criterion": fx.criterion("edge_distance", ">=", 3, "mm"), "distance": fx.known(fx.quantity(4, "deg"))}), "intent.units"),
            "angular compliance in mm": (lambda d: d["interfaces.yaml"]["interfaces"][0]["functional"].update(play={
                "compliance": {"angular": fx.known(fx.quantity(0.1))}}), "intent.units"),
        }
        for label, (edit, code) in cases.items():
            with self.subTest(label):
                documents = fx.tst_record()
                edit(documents)
                hw = fx.write_record(temp_hw(self), documents)
                record = mi.load_record(hw)
                codes = [p.code for p in record.problems]
                self.assertIn(code, codes, [p.message for p in record.problems])
                severity = {p.code: p.severity for p in record.problems}[code]
                self.assertEqual(severity, "warning" if code == "intent.coverage" else "error")

    def test_a_decision_the_layout_cannot_resolve_is_a_reference_problem_not_a_crash(self) -> None:
        for label, ident, extra in (("two files with one id", "DR-009", "DR-009-second.md"),
                                    ("an id that is not DR-###", "DR-9", None)):
            with self.subTest(label):
                documents = fx.tst_record()
                documents["parts/TST-0001/part.yaml"]["intent"]["route"][0]["orientation"].update(decision=ident)
                hw = fx.write_record(temp_hw(self), documents)
                if extra is not None:
                    write_test_decision(hw, "DR-009")
                    shutil.copyfile(decision_path(hw, "DR-009"), hw / "decisions" / extra)
                record = mi.load_record(hw)
                messages = [p.message for p in record.problems if p.code == "intent.reference"]
                self.assertTrue(any(ident in message for message in messages), messages)

    def test_a_load_direction_within_the_unit_tolerance_is_accepted(self) -> None:
        for direction in ([0, 0, -1], [0.6, 0.0, -0.8], [1 + 5e-7, 0, 0]):
            with self.subTest(direction):
                documents = fx.tst_record()
                documents["product.yaml"]["use_case"]["loads"][0]["direction"] = direction
                record = mi.load_record(fx.write_record(temp_hw(self), documents))
                self.assertEqual([p.finding() for p in record.problems], [])

    def test_a_load_that_names_an_application_is_hashable_and_keeps_it(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["application"] = {"PN": "TST-0001"}
        record = mi.load_record(fx.write_record(temp_hw(self), documents))
        load = record.use_case.loads[0]
        self.assertEqual(dict(load.application), {"PN": "TST-0001"})
        self.assertEqual(hash(load), hash(load))

    def test_a_load_keeps_an_omitted_application_apart_from_an_invalid_one(self) -> None:
        """Omitted is None. A present application that is empty or not a mapping reads as an empty subject, never None,
        so a reader cannot take invalid input for the assembly frame."""
        for application, expected in ((None, None), ({}, {}), ("bracket", {}), ([], {}), ({"PN": "TST-0001"}, {"PN": "TST-0001"})):
            with self.subTest(application=application):
                documents = fx.tst_record()
                if application is not None:
                    documents["product.yaml"]["use_case"]["loads"][0]["application"] = application
                loaded = mi.load_record(fx.write_record(temp_hw(self), documents)).use_case.loads[0].application
                self.assertEqual(None if loaded is None else dict(loaded), expected)

    def test_a_non_unit_load_direction_names_its_load(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["direction"] = [0, 0, 0]
        record = mi.load_record(fx.write_record(temp_hw(self), documents))
        [problem] = [p for p in record.problems if p.code == "load.direction_not_unit"]
        self.assertIn("head_load", problem.message)
        self.assertEqual(problem.pointer, "use_case/loads/0/direction")

    def test_a_load_direction_beyond_float_range_is_reported_not_raised(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["direction"] = [10 ** 400, 0, 0]
        record = mi.normalize_record(documents)
        self.assertIn("load.direction_not_unit", [p.code for p in record.problems])
        self.assertIsNone(record.use_case.loads[0].direction)

    def test_a_non_finite_load_direction_is_reported_and_carried_as_none(self) -> None:
        for direction in ([float("nan"), 0, 0], [float("inf"), 0, 0], [10 ** 400, float("nan"), 0], [10 ** 400, float("inf"), 0]):
            with self.subTest(direction):
                documents = fx.tst_record()
                documents["product.yaml"]["use_case"]["loads"][0]["direction"] = direction
                record = mi.normalize_record(documents)
                codes = [p.code for p in record.problems]
                self.assertEqual(codes.count("intent.number"), 1, codes)
                self.assertNotIn("load.direction_not_unit", codes)
                self.assertIsNone(record.use_case.loads[0].direction)

    def test_a_parsed_load_carries_its_direction_as_floats(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["direction"] = [0, 0.6, -0.8]
        record = mi.normalize_record(documents)
        self.assertEqual(record.use_case.loads[0].direction, (0.0, 0.6, -0.8))

    def test_a_malformed_load_direction_is_a_schema_problem_only(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["direction"] = [0, -1]
        record, problems = mi.check_record(fx.write_record(temp_hw(self), documents))
        codes = [p.code for p in problems]
        self.assertIn("intent.schema", codes)
        self.assertNotIn("load.direction_not_unit", codes)

    def test_normalization_needs_no_files(self) -> None:
        documents = fx.tst_record()
        documents.pop("_decisions")
        documents.pop("_sources")
        record = mi.normalize_record(documents)
        self.assertEqual([p.finding() for p in record.problems], [], "without hw, decision and artifact files are not checked")


class LoadByPathWithoutOptionalDependencies(unittest.TestCase):
    def test_the_module_loads_and_normalizes_with_pyyaml_jsonschema_and_referencing_missing(self) -> None:
        documents = fx.tst_record()
        code = ("import importlib.util, pickle, sys\n"
                "class Block:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name.split('.')[0] in ('yaml', 'jsonschema', 'referencing'):\n"
                "            raise ModuleNotFoundError(name)\n"
                "sys.meta_path.insert(0, Block())\n"
                "spec = importlib.util.spec_from_file_location('cad_record_manufacturing_intent', sys.argv[1])\n"
                "sys.modules['cad_record_manufacturing_intent'] = module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "record = module.normalize_record(pickle.load(sys.stdin.buffer))\n"
                "print('ok', len(record.parts), [n for n in ('yaml', 'jsonschema', 'referencing') if n in sys.modules])\n")
        done = subprocess.run([sys.executable, "-c", code, str(SKILL / "scripts" / "manufacturing_intent.py")],
                              input=pickle.dumps(documents), capture_output=True, check=False)
        parts = len(mi.normalize_record(documents).parts)
        self.assertGreater(parts, 0, "the fixture must hold parts, or the count below proves nothing")
        self.assertEqual(done.stdout.decode().strip(), f"ok {parts} []", done.stderr.decode())


class UseCaseReadiness(unittest.TestCase):
    def confirmed(self) -> Any:
        """The TST record with its use case confirmed by DR-001: every question resolved and every use-case fact
        answered (here not applicable), as a resolved question requires."""
        def answered(value: Any) -> Any:
            if isinstance(value, dict):
                return fx.not_applicable("TST answer, DR-001") if value.get("status") == "unknown" else \
                    {key: answered(item) for key, item in value.items()}
            return [answered(item) for item in value] if isinstance(value, list) else value

        documents = fx.tst_record()
        use = documents["product.yaml"]["use_case"] = answered(documents["product.yaml"]["use_case"])
        use.update(status="confirmed", decision="DR-001", service_class=fx.known("functional_demo"))
        for item in documents["requirements.yaml"]["open_questions"]:
            item.update(status="resolved", resolution={"answer": "TST answer", "decision": "DR-001"})
        return documents

    def test_a_draft_use_case_supports_only_conditional_recommendations(self) -> None:
        assessment = mi.assess_use_case(mi.normalize_record(fx.tst_record()))
        self.assertFalse(assessment.final_ready)
        self.assertIn("the use case is not confirmed by a decision", assessment.blocking)
        self.assertIn("the service class is unknown", assessment.blocking)
        self.assertIn("Q-001", assessment.open_questions)
        self.assertIn("environment.temperature", assessment.unknown)

    def test_a_confirmed_use_case_with_answered_questions_is_ready(self) -> None:
        assessment = mi.assess_use_case(mi.normalize_record(self.confirmed()))
        self.assertEqual((assessment.final_ready, assessment.blocking, assessment.service_class), (True, (), "functional_demo"))

    def test_untracked_unknowns_and_safety_policy_block(self) -> None:
        documents = self.confirmed()
        documents["product.yaml"]["use_case"]["environment"]["uv"] = fx.unknown("never asked")
        assessment = mi.assess_use_case(mi.normalize_record(documents))
        self.assertFalse(assessment.final_ready)
        self.assertIn("use_case.environment.uv is unknown and no open question tracks it", assessment.blocking)
        documents = self.confirmed()
        documents["product.yaml"]["use_case"]["service_class"] = fx.known("safety_critical")
        assessment = mi.assess_use_case(mi.normalize_record(documents))
        self.assertIn("a safety-critical use case needs use_case.consequences.standards", assessment.blocking)
        documents = self.confirmed()
        documents["requirements.yaml"]["open_questions"].append(fx.question("Q-050", material=True))
        self.assertEqual(mi.assess_use_case(mi.normalize_record(documents)).open_questions, ("Q-050",))
        self.assertFalse(mi.assess_use_case(mi.load_record(fx.LAMP)).final_ready)

    def test_a_resolved_question_does_not_track_an_unknown(self) -> None:
        documents = self.confirmed()
        question = mi.normalize_record(fx.tst_record()).use_case.facts["environment.uv"].question
        documents["product.yaml"]["use_case"]["environment"]["uv"] = fx.unknown("never measured", question)
        contradiction = (f"use_case.environment.uv is unknown but its question {question} is resolved; "
                         "record the answer in the fact or reopen the question")
        assessment = mi.assess_use_case(mi.normalize_record(documents))
        self.assertFalse(assessment.final_ready)
        self.assertEqual(assessment.blocking, (contradiction,))
        entry = next(q for q in documents["requirements.yaml"]["open_questions"] if q["id"] == question)
        entry.update(status="open")
        entry.pop("resolution")
        assessment = mi.assess_use_case(mi.normalize_record(documents))
        self.assertNotIn(contradiction, assessment.blocking, "an open question tracks the unknown")
        self.assertFalse(any("environment.uv" in reason for reason in assessment.blocking))


class Routes(unittest.TestCase):
    def test_route_order_and_predecessors(self) -> None:
        documents = fx.tst_record()
        route = documents["parts/TST-0001/part.yaml"]["intent"]["route"]
        route.append(fx.operation("coat", "coating", depends_on=["print"]))
        record = mi.normalize_record(documents)
        planned = mi.part_route(record, "TST-0001")
        self.assertEqual([op.id for op in planned.operations], ["print", "ream", "coat"])
        self.assertEqual(dict(planned.predecessors), {"print": (), "ream": ("print",), "coat": ("print",)})
        self.assertEqual((planned.sourcing, planned.components, planned.unsupported, planned.unknown), ("make", ("main",), (), None))
        with self.assertRaisesRegex(mi.IntentError, "no part"):
            mi.part_route(record, "TST-0999")

    def test_unknown_and_unsupported_routes_stay_visible(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["route"] = fx.unknown("not planned", "Q-001")
        documents["parts/TST-0002/part.yaml"]["intent"]["route"].append(fx.operation("sinter", "sintering"))
        record = mi.normalize_record(documents)
        self.assertEqual((mi.part_route(record, "TST-0001").operations, mi.part_route(record, "TST-0001").unknown.reason), ((), "not planned"))
        self.assertEqual(mi.part_route(record, "TST-0002").unsupported, ("sinter",))
        documents = fx.tst_record()
        route = documents["parts/TST-0001/part.yaml"]["intent"]["route"]
        route[0]["depends_on"], route[1]["depends_on"] = ["ream"], ["print"]
        with self.assertRaisesRegex(mi.IntentError, "cycle"):
            mi.part_route(mi.normalize_record(documents), "TST-0001")


class PartColor(unittest.TestCase):
    def test_intent_carries_the_declared_color_or_none(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["color"] = "#FF8000"
        record = mi.normalize_record(documents)
        self.assertEqual(record.parts["TST-0001"].intent.color, "#FF8000")
        self.assertIsNone(record.parts["TST-0002"].intent.color)

    def test_an_invalid_color_is_a_named_problem_and_reads_as_none(self) -> None:
        for label, bad in (("three digits", "#abc"), ("integer", 16744448), ("trailing newline", "#FF8000\n"),
                           ("colour name", "orange"), ("lists", ["#FF8000"]), ("null", None)):
            with self.subTest(label):
                documents = fx.tst_record()
                documents["parts/TST-0001/part.yaml"]["intent"]["color"] = bad
                record = mi.normalize_record(documents)
                found = [p for p in record.problems if p.code == "intent.color_invalid"]
                self.assertEqual([(p.path, p.pointer, p.severity) for p in found],
                                 [("hw/parts/TST-0001/part.yaml", "intent/color", "error")])
                self.assertIn(repr(bad), found[0].message)
                self.assertIn("quote", found[0].message, "the message names the unquoted # YAML comment as the likely cause")
                self.assertIsNone(record.parts["TST-0001"].intent.color)

    def test_a_valid_color_raises_no_problem_in_either_case(self) -> None:
        for good in ("#FF8000", "#ff8000"):
            with self.subTest(good):
                documents = fx.tst_record()
                documents["parts/TST-0001/part.yaml"]["intent"]["color"] = good
                record = mi.normalize_record(documents)
                self.assertEqual([p for p in record.problems if p.code == "intent.color_invalid"], [])
                self.assertEqual(record.parts["TST-0001"].intent.color, good)


class MaterialProperties(unittest.TestCase):
    def setUp(self) -> None:
        self.materials = mi.normalize_record(fx.tst_record()).materials

    def test_an_allowable_resolves_only_under_its_conditions(self) -> None:
        rod = self.materials["tst_metal_rod"]
        room = mi.Quantity("deg_C", value=23.0)
        found = mi.resolve_property(rod, "yield_strength", temperature=room, conditioning="dry", allowable=True)
        self.assertEqual((found.status, found.value, found.basis), ("resolved", mi.Quantity("MPa", value=111.0), "allowable"))
        self.assertEqual(found.conditions["conditioning"], "dry")
        hot = mi.resolve_property(rod, "yield_strength", temperature=mi.Quantity("deg_C", value=60.0))
        self.assertEqual((hot.status, hot.value, hot.basis), ("resolved", mi.Quantity("MPa", value=99.0), "estimate"),
                         "a room-temperature value never answers 60 deg_C; the 20..80 value does")
        self.assertEqual(mi.resolve_property(rod, "yield_strength", temperature=mi.Quantity("deg_C", value=60.0), allowable=True).status,
                         "refused", "typical or estimated values are never relabelled allowable")
        hotter = mi.resolve_property(rod, "yield_strength", temperature=mi.Quantity("deg_C", value=120.0))
        self.assertEqual(hotter.status, "refused")
        self.assertTrue(any("120 deg_C requested" in reason for reason in hotter.reasons), hotter.reasons)
        self.assertEqual(mi.resolve_property(rod, "yield_strength", conditioning="conditioned").status, "refused")
        self.assertEqual(mi.resolve_property(rod, "yield_strength", form="printed").status, "refused")

    def test_family_guidance_orientation_and_density_never_stand_in(self) -> None:
        printed = self.materials["tst_polymer_printed"]
        self.assertEqual(mi.resolve_property(printed, "density", orientation="XY").status, "resolved")
        self.assertEqual(mi.resolve_property(printed, "density", orientation="ZX").status, "refused")
        self.assertEqual(mi.resolve_property(printed, "yield_strength").status, "unknown", "density is not strength")
        self.assertEqual(mi.resolve_property(printed, "density", allowable=True).status, "refused")
        with self.assertRaises(mi.IntentError):
            mi.resolve_property(printed, "strength_from_density")

    def test_two_matching_values_that_differ_are_ambiguous(self) -> None:
        documents = fx.tst_record()
        documents["manufacturing/materials.yaml"]["profiles"][1]["properties"].append(
            fx.material_property("yield_strength", 105, "MPa", basis="allowable"))
        rod = mi.normalize_record(documents).materials["tst_metal_rod"]
        self.assertEqual(mi.resolve_property(rod, "yield_strength", allowable=True).status, "refused")


class Capabilities(unittest.TestCase):
    def test_only_a_scoped_calibration_answers_achievable_accuracy(self) -> None:
        documents = fx.tst_record()
        documents["manufacturing/capabilities.yaml"]["profiles"][0]["calibrations"].append(
            {**fx.calibration("old", "min_wall", "tst_polymer_printed", fx.quantity(lower=0.8, upper=1.0)), "valid_until": "2026-02-01"})
        printer = mi.normalize_record(documents).capabilities["tst_printer"]
        found = mi.capability_limit(printer, "hole_diameter_deviation", material="tst_polymer_printed", orientation="XY")
        self.assertEqual((found.status, found.calibration.limits), ("calibrated", mi.Quantity("mm", lower=-0.2, upper=0.0)))
        self.assertEqual(mi.capability_limit(printer, "hole_diameter_deviation", material="tst_metal_rod").status, "refused")
        self.assertEqual(mi.capability_limit(printer, "hole_diameter_deviation", material="tst_polymer_printed", orientation="ZX").status,
                         "refused")
        self.assertEqual(mi.capability_limit(printer, "nozzle_diameter", material="tst_polymer_printed").status, "unknown",
                         "a nominal parameter is never a calibration")
        self.assertEqual(mi.capability_limit(printer, "min_wall", material="tst_polymer_printed", on=date(2026, 3, 1)).status, "refused")
        documents["manufacturing/capabilities.yaml"]["profiles"][0]["template"] = True
        template = mi.normalize_record(documents).capabilities["tst_printer"]
        self.assertEqual(mi.capability_limit(template, "hole_diameter_deviation", material="tst_polymer_printed").status, "refused")


# The obligations of fx.tst_record(), a record with no loaded structural interface, as origin/main a7d007e3 enumerates them
# without engineering.stop_reaction. 88be42e5 added assembly.order@product to the 54 of 43ad4409, making 55. Issue #174
# added cad.glb_step_agreement for each of the three made parts, making 58.
TST_RECORD_OBLIGATIONS = (
    'assembly.access@op:fit_bearing',
    'assembly.joint@op:fit_bearing',
    'assembly.order@op:fit_bearing',
    'assembly.order@product',
    'cad.glb_step_agreement@TST-0001',
    'cad.glb_step_agreement@TST-0002',
    'cad.glb_step_agreement@TST-0004',
    'cad.readback@TST-0001',
    'cad.readback@TST-0002',
    'cad.readback@TST-0004',
    'contact.wear@TST-0002',
    'engineering.anisotropy@TST-0001',
    'engineering.creep@TST-0001',
    'engineering.stiffness@TST-0001',
    'engineering.strength@TST-0001',
    'export.3mf@TST-0001',
    'feature.fit@TST-0001#pivot_bore',
    'feature.inspection@TST-0001#pivot_bore',
    'intent.critical_surfaces@TST-0002',
    'intent.use_case@product',
    'interface.acceptance.physically_validated@IF-001#running_clearance',
    'interface.fit@IF-001',
    'interface.stack@IF-001',
    'motion.play@IF-001',
    'motion.play@TST-0002',
    'optical.route@TST-0004',
    'optical.transmission@TST-0004',
    'process.cnc.access@TST-0002/turn',
    'process.cnc.features@TST-0002/turn',
    'process.cnc.precision@TST-0002/turn',
    'process.cnc.setup@TST-0002/turn',
    'process.cnc.stock@TST-0002/turn',
    'process.fdm.geometry@TST-0001/print',
    'process.fdm.orientation@TST-0001/print',
    'process.fdm.support@TST-0001/print',
    'process.fdm.thermal_distortion@TST-0001/print',
    'process.fdm.trial@TST-0001/print',
    'process.laser.features@TST-0004/cut',
    'process.laser.fit_coupon@TST-0004/cut',
    'process.laser.kerf@TST-0004/cut',
    'process.laser.material@TST-0004/cut',
    'process.laser.nesting@TST-0004/cut',
    'process.laser.thermal@TST-0004/cut',
    'process.reaming.access@TST-0001/ream',
    'process.reaming.allowance@TST-0001/ream',
    'purchase.availability@TST-0003/buy',
    'purchase.dimensions@TST-0003/buy',
    'purchase.identity@TST-0003/buy',
    'purchase.mounting@TST-0003/buy',
    'purchase.rating@TST-0003/buy',
    'requirement.simulation_supported@REQ-001',
    'route.consistency@TST-0001',
    'route.consistency@TST-0002',
    'route.consistency@TST-0004',
    'route.operation_plan@TST-0001/print',
    'route.operation_plan@TST-0001/ream',
    'route.operation_plan@TST-0002/turn',
    'route.operation_plan@TST-0004/cut',
)



class RequiredChecks(unittest.TestCase):
    def obligations(self, documents: dict[str, Any]) -> dict[str, Any]:
        return {o.id: o for o in mi.required_checks(mi.normalize_record(documents))}

    def test_every_obligation_validates_and_is_enumerated_once(self) -> None:
        checks = mi.required_checks(mi.normalize_record(fx.tst_record()))
        schema = fx.ref_validator("https://srobroek.com/cad/schemas/manufacturing.schema.json#/$defs/obligation")
        self.assertEqual([o.id for o in checks], sorted({o.id for o in checks}))
        for obligation in checks:
            with self.subTest(obligation.id):
                self.assertEqual([e.message for e in schema.iter_errors(obligation.as_dict())], [])

    def test_route_function_interface_and_requirement_obligations(self) -> None:
        found = self.obligations(fx.tst_record())
        for ident in ("process.fdm.orientation@TST-0001/print", "process.fdm.support@TST-0001/print", "process.fdm.trial@TST-0001/print",
                      "process.reaming.allowance@TST-0001/ream", "route.operation_plan@TST-0001/ream", "cad.readback@TST-0001",
                      "engineering.strength@TST-0001", "engineering.creep@TST-0001", "engineering.anisotropy@TST-0001",
                      "feature.fit@TST-0001#pivot_bore", "process.cnc.access@TST-0002/turn", "contact.wear@TST-0002",
                      "process.laser.material@TST-0004/cut", "optical.route@TST-0004", "interface.stack@IF-001",
                      "interface.acceptance.physically_validated@IF-001#running_clearance", "assembly.access@op:fit_bearing",
                      "requirement.simulation_supported@REQ-001", "intent.use_case@product", "intent.critical_surfaces@TST-0002"):
            self.assertIn(ident, found)
        self.assertEqual((found["process.fdm.trial@TST-0001/print"].level, found["process.fdm.trial@TST-0001/print"].stage),
                         ("physically_validated", "release"))
        self.assertEqual(found["engineering.creep@TST-0001"].level, "physically_validated", "static analysis cannot pass creep")

    def test_an_fdm_part_is_owed_one_export_3mf_obligation_and_other_processes_none(self) -> None:
        found = self.obligations(fx.tst_record())
        owed = found["export.3mf@TST-0001"]
        self.assertEqual((owed.family, dict(owed.subject), owed.level), ("export.3mf", {"PN": "TST-0001"}, "cad_valid"))
        self.assertEqual(sorted(i for i in found if i.startswith("export.3mf")), ["export.3mf@TST-0001"])

    def test_each_made_part_is_owed_one_glb_step_agreement_obligation_and_a_bought_part_none(self) -> None:
        """cad-model check judges each occurrence's GLB node against the STEP; the release sees it per made part.
        The bearing TST-0003 is bought: a catalogue item gets purchase checks only."""
        found = self.obligations(fx.tst_record())
        owed = sorted(i for i in found if i.startswith("cad.glb_step_agreement"))
        self.assertEqual(owed, ["cad.glb_step_agreement@TST-0001", "cad.glb_step_agreement@TST-0002",
                                "cad.glb_step_agreement@TST-0004"])
        first = found["cad.glb_step_agreement@TST-0001"]
        self.assertEqual((first.family, dict(first.subject), first.level, first.stage),
                         ("cad.glb_step_agreement", {"PN": "TST-0001"}, "cad_valid", "layout"))

    def test_each_declared_heat_set_is_owed_a_declared_dimensions_obligation_whatever_its_interface_criticality(self) -> None:
        """IF-002's criticality is unknown, so it owes no fit or stack checks, but its two heat-set declarations each owe
        the check that the host has a bore of the declared size. The obligation is named after the entry's place."""
        documents = fx.tst_record()
        entry = {"pair": ["TST-0001", "TST-0004"], "hole_d": 4.0, "insert": "M3 x 5.7", "source": "https://example.com/insert"}
        documents["interfaces.yaml"]["interfaces"].append(
            fx.interface("IF-002", "TST-0001", "TST-0004", limits={"heat_set": [entry, {**entry, "hole_d": 5.6}]}))
        found = self.obligations(documents)
        owed = sorted(i for i in found if i.startswith("cad.declared_dimensions"))
        self.assertEqual(owed, ["cad.declared_dimensions@IF-002#heat_set_1", "cad.declared_dimensions@IF-002#heat_set_2"])
        second = found["cad.declared_dimensions@IF-002#heat_set_2"]
        self.assertEqual((second.family, dict(second.subject), second.level, second.stage),
                         ("cad.declared_dimensions", {"interface": "IF-002", "feature": "heat_set_2"}, "cad_valid", "layout"))
        schema = fx.ref_validator("https://srobroek.com/cad/schemas/manufacturing.schema.json#/$defs/obligation")
        self.assertEqual([e.message for ident in owed for e in schema.iter_errors(found[ident].as_dict())], [])
        self.assertEqual([i for i in found if i.startswith(("interface.", "intent.interface")) and "IF-002" in i],
                         ["intent.interface@IF-002"], "IF-002 owes nothing else: its criticality is unknown")

    def test_purchased_items_get_purchase_checks_only(self) -> None:
        found = self.obligations(fx.tst_record())
        bearing = sorted(i for i in found if "TST-0003" in i)
        self.assertEqual(bearing, ["purchase.availability@TST-0003/buy", "purchase.dimensions@TST-0003/buy", "purchase.identity@TST-0003/buy",
                                   "purchase.mounting@TST-0003/buy", "purchase.rating@TST-0003/buy"])
        self.assertFalse(any(i.startswith("process.") for i in found if "TST-0002" in i and "cnc" not in i),
                         "a made-to-drawing buy gets its actual route's checks, never FDM ones")

    def lamp_with_unknown_fdm_routes(self) -> Path:
        """A copy of the lamp-arm record whose fdm parts carry the legacy unknown route."""
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        hw = scratch / "hw"
        shutil.copytree(fx.LAMP, hw)
        for pn, question in (("LMP-0001", "Q-012"), ("LMP-0004", "Q-015")):
            path = hw / "parts" / pn / "part.yaml"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            start = next(i for i, line in enumerate(lines) if line.startswith("  route:"))
            legacy = f"  route: {{status: unknown, reason: not recorded before record version 2, question: {question}}}\n"
            path.write_text("".join(lines[:start]) + legacy, encoding="utf-8")
        return hw

    def test_unknowns_and_unsupported_kinds_are_explicit_gaps(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0002/part.yaml"]["intent"]["route"] = [fx.operation("sinter", "sintering")]
        documents["parts/TST-0004/part.yaml"]["intent"].update(route=fx.unknown("not planned"), functions=fx.unknown("not asked"))
        documents["product.yaml"]["use_case"]["loads"] = fx.unknown("not measured")
        found = self.obligations(documents)
        self.assertEqual(sorted(i for i in found if i.startswith("process.") and "TST-0002" in i), ["process.sintering.coverage@TST-0002/sinter"])
        self.assertIn("intent.route@TST-0004", found)
        self.assertIn("intent.functions@TST-0004", found)
        self.assertIn("optical.route@TST-0004", found, "transparency still demands an optical route")
        self.assertIn("engineering.load_cases@TST-0001", found)
        self.assertNotIn("engineering.creep@TST-0001", found)
        legacy = {o.id for o in mi.required_checks(mi.load_record(self.lamp_with_unknown_fdm_routes()))}
        self.assertIn("intent.route@LMP-0001", legacy)
        self.assertIn("intent.use_case@product", legacy)
        self.assertFalse(any(i.startswith("process.fdm") for i in legacy), "a legacy fdm label dispatches no process checks")

    def test_every_component_gets_its_own_obligations(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["components"] = [{"id": "left", "witness": [0, 0, 1]},
                                                                          {"id": "right", "witness": [50, 0, 1]}]
        found = self.obligations(documents)
        for component in ("left", "right"):
            self.assertIn(f"process.fdm.support@TST-0001.{component}/print", found)
            self.assertIn(f"cad.readback@TST-0001.{component}", found)
        self.assertNotIn("process.fdm.support@TST-0001/print", found)

    def test_joining_operations_get_joint_evidence_and_moving_interfaces_get_play(self) -> None:
        """assembly.joint for every joining operation, never a closure or service step; motion.play for a
        critical rotating or sliding interface before it declares any play, and for any declared play."""
        documents = fx.tst_record()
        documents["assembly.yaml"]["operations"] += [
            {"id": "fasten_plate", "kind": "fasten", "part": "TST-0004", "into": "TST-0001", "direction": [0, 0, -1],
             "acceptance": {"kind": "torqued", "features": ["head"]}},
            {"id": "close_cover", "kind": "close", "part": "TST-0004", "into": "TST-0001", "closes": ["TST-0003"]},
            {"id": "check_fit", "kind": "inspect", "part": "TST-0003", "acceptance": {"kind": "inspected", "features": ["bore"]}}]
        found = self.obligations(documents)
        self.assertEqual(sorted(i for i in found if i.startswith("assembly.joint")),
                         ["assembly.joint@op:fasten_plate", "assembly.joint@op:fit_bearing"])
        joint = found["assembly.joint@op:fit_bearing"]
        self.assertEqual((joint.level, joint.stage, dict(joint.subject)), ("process_planned", "detail", {"assembly_operation": "fit_bearing"}))
        self.assertIn("edge distance", joint.basis)
        self.assertIn("motion.play@IF-001", found, "a critical rotating interface needs its play checked though it declares none")
        functional = documents["interfaces.yaml"]["interfaces"][0]["functional"]
        functional["functions"] = [{"function": "locating"}]
        self.assertNotIn("motion.play@IF-001", self.obligations(documents))
        functional["play"] = {"radial": fx.known(fx.quantity(0.02))}
        self.assertIn("motion.play@IF-001", self.obligations(documents), "declared play is checked whatever the function")

    def test_a_record_without_a_loaded_structural_interface_owes_exactly_the_earlier_obligations(self) -> None:
        self.assertEqual(sorted(self.obligations(fx.tst_record())), list(TST_RECORD_OBLIGATIONS))

    def test_a_loaded_structural_interface_adds_exactly_its_stop_reaction(self) -> None:
        def with_interface(functions: list[dict[str, str]]) -> set[str]:
            documents = fx.tst_record()
            documents["interfaces.yaml"]["interfaces"].append(fx.interface("IF-011", "TST-0001", "TST-0002", "other", {
                "critical": fx.known(True), "functions": functions, "loads": ["head_load"]}))
            return set(self.obligations(documents))
        # Any critical interface owes its fit and stack checks, written out here so an error in the generator shows.
        generic = set(TST_RECORD_OBLIGATIONS) | {"interface.fit@IF-011", "interface.stack@IF-011"}
        self.assertEqual(with_interface([{"function": "locating"}]), generic)
        self.assertEqual(with_interface([{"function": "structural"}]), generic | {"engineering.stop_reaction@IF-011"})

    def test_a_critical_structural_interface_that_carries_a_load_needs_its_stop_reaction(self) -> None:
        """engineering.stop_reaction for a critical structural interface with use-case loads or a known contact
        load, at layout. A non-critical, non-structural or unloaded interface needs none."""
        documents = fx.tst_record()
        interfaces = documents["interfaces.yaml"]["interfaces"]
        structural = [{"function": "structural"}]
        for ident, critical, functions, extra in (
                ("IF-011", True, structural, {"loads": ["head_load"]}),
                ("IF-012", True, structural, {"contact": {"materials": ["tst_polymer_printed", "tst_metal_rod"],
                                                          "load": fx.known(fx.quantity(240, "N"))}}),
                ("IF-013", True, structural, {}),
                ("IF-014", True, [{"function": "locating"}], {"loads": ["head_load"]}),
                ("IF-015", False, structural, {"loads": ["head_load"]})):
            interfaces.append(fx.interface(ident, "TST-0001", "TST-0002", "other", {
                "critical": fx.known(critical), "functions": functions, **extra}))
        found = self.obligations(documents)
        self.assertEqual(sorted(i for i in found if i.startswith("engineering.stop_reaction")),
                         ["engineering.stop_reaction@IF-011", "engineering.stop_reaction@IF-012"])
        obligation = found["engineering.stop_reaction@IF-011"]
        self.assertEqual((obligation.level, obligation.stage, dict(obligation.subject)),
                         ("simulation_supported", "layout", {"interface": "IF-011"}))


class ProfileDocuments(unittest.TestCase):
    def test_standalone_profiles_are_checked_without_a_project(self) -> None:
        documents = fx.tst_record()
        materials = copy.deepcopy(documents["manufacturing/materials.yaml"])
        profiles, problems = mi.profile_document(materials, "materials", "library.yaml")
        self.assertEqual(([p.id for p in profiles], [p.finding() for p in problems]),
                         (["tst_polymer_printed", "tst_metal_rod", "tst_clear_sheet"], []))
        materials["profiles"][2]["properties"].append(fx.material_property("yield_strength", 1, "MPa", basis="allowable"))
        materials["profiles"].append(copy.deepcopy(materials["profiles"][0]))
        _profiles, problems = mi.profile_document(materials, "materials", "library.yaml")
        self.assertEqual(sorted(p.code for p in problems), ["intent.allowable", "intent.duplicate"])
        with self.assertRaises(mi.IntentError):
            mi.profile_document(materials, "selection", "x.yaml")

    def test_a_fu_fy_ratio_reads_alike_as_a_number_or_as_percent(self) -> None:
        materials = copy.deepcopy(fx.tst_record()["manufacturing/materials.yaml"])
        materials["profiles"][1]["properties"] += [fx.material_property("fu_fy_ratio", 1.1, "dimensionless"),
                                                   fx.material_property("fu_fy_ratio", 110, "percent")]
        profiles, problems = mi.profile_document(materials, "materials", "library.yaml")
        self.assertEqual([p.finding() for p in problems], [])
        ratios = [p.value.value.to("dimensionless").value for p in profiles[1].properties if p.name == "fu_fy_ratio"]
        self.assertEqual(len(ratios), 2)
        self.assertAlmostEqual(ratios[0], 1.1)
        self.assertAlmostEqual(ratios[1], 1.1)


class SubjectOccurrences(unittest.TestCase):
    """A subject's `occurrence` must be an occurrence of its PN; an omitted one needs a single occurrence."""

    def problems(self, subject: dict[str, Any]) -> list[Any]:
        documents = fx.with_subject_occurrences(fx.tst_record(), subject)
        return mi.check_record(fx.write_record(temp_hw(self), documents))[1]

    def test_an_occurrence_of_another_part_is_a_reference_problem(self) -> None:
        [problem] = self.problems({"PN": "TST-0001", "occurrence": "@left"})
        self.assertEqual((problem.code, problem.path, problem.pointer),
                         ("intent.reference", "hw/requirements.yaml", "requirements/0/subjects/0"))
        self.assertIn("@left is an occurrence of TST-0003, not TST-0001", problem.message)

    def test_an_unknown_occurrence_is_a_reference_problem(self) -> None:
        [problem] = self.problems({"PN": "TST-0003", "occurrence": "@ghost"})
        self.assertEqual((problem.code, problem.pointer), ("intent.reference", "requirements/0/subjects/0"))
        self.assertIn("@ghost names no occurrence", problem.message)

    def test_the_part_own_occurrence_is_clean(self) -> None:
        self.assertEqual(self.problems({"PN": "TST-0003", "occurrence": "@right"}), [])

    def test_an_omitted_occurrence_of_a_single_occurrence_part_is_clean(self) -> None:
        self.assertEqual(self.problems({"PN": "TST-0001"}), [])


class CombinatorPointers(unittest.TestCase):
    """A oneOf/anyOf error is reported where its best branch fails, not at the branch point."""

    def load_problems(self, application: Any) -> list[Any]:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["application"] = application
        return mi.schema_problems(documents)

    def test_a_bad_load_application_points_at_application_and_names_the_keyword(self) -> None:
        problems = self.load_problems({"bogus": 1})
        self.assertEqual([(p.pointer, p.message) for p in problems],
                         [("use_case/loads/0/application",
                           "use_case/loads/0/application: Additional properties are not allowed ('bogus' was unexpected)")])

    def test_a_bad_value_inside_application_points_at_that_key(self) -> None:
        problems = self.load_problems({"PN": "bad pn!"})
        self.assertEqual([p.pointer for p in problems], ["use_case/loads/0/application/PN"])
        self.assertIn("does not match", problems[0].message)
        self.assertNotIn("head_load", problems[0].message, "the whole load is not quoted")

    def test_a_bad_fact_value_is_reported_inside_the_fact(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["service_class"] = fx.known("nonsense")
        problems = mi.schema_problems(documents)
        self.assertEqual(len(problems), 1, problems)
        self.assertEqual(problems[0].pointer, "use_case/service_class/value")
        self.assertNotIn("is not valid under any of the given schemas", problems[0].message)

    def test_check_documents_filters_on_the_document_of_the_deeper_pointer(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["application"] = {"bogus": 1}

        def pointers(paths: set[str]) -> list[str]:
            return [p.pointer for p in mi.check_documents(documents, paths) if p.code == "intent.schema"]

        self.assertEqual(pointers({"hw/product.yaml"}), ["use_case/loads/0/application"])
        self.assertEqual(pointers({"hw/requirements.yaml"}), [])

    def test_an_unknown_fact_without_a_reason_is_reported_as_missing_its_reason(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["loads"][0]["magnitude"] = {"status": "unknown"}
        problems = mi.schema_problems(documents)
        self.assertEqual([(p.pointer, p.message) for p in problems],
                         [("use_case/loads/0/magnitude", "use_case/loads/0/magnitude: 'reason' is a required property")])

    def test_an_object_branch_with_only_nested_errors_is_preferred_to_an_unknown_fact(self) -> None:
        cases = (("product.yaml", "use_case", "evidence_policy",
                  {"obligations": [{"requirement": "REQ-001", "level": "simulated"}], "decision": "DR-001"},
                  "use_case/evidence_policy/obligations/0/level", "is not one of"),
                 ("parts/TST-0001/part.yaml", "intent", "service", {"life": {"status": "unknown"}},
                  "intent/service/life", "'reason' is a required property"))
        for document, section, field, value, pointer, message in cases:
            with self.subTest(pointer=pointer):
                documents = fx.tst_record()
                documents[document][section][field] = value
                problems = mi.schema_problems(documents)
                self.assertEqual([p.pointer for p in problems], [pointer])
                self.assertIn(message, problems[0].message)

    def test_a_branch_local_value_enum_does_not_choose_the_status_branch(self) -> None:
        documents = fx.tst_record()
        fact = fx.known("nonsense")
        del fact["status"]
        documents["product.yaml"]["use_case"]["service_class"] = fact
        problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["use_case/service_class"])
        self.assertIn("is not valid under any of the given schemas", problems[0].message)

    def test_an_unknown_orientation_does_not_report_an_invalid_rotation(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["route"][0]["orientation"] = {
            "status": "unknown", "rotation": {"quaternion": [1, "bad", 0, 0]}}
        problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["intent/route/0/orientation"])
        self.assertIn("Additional properties", problems[0].message)
        self.assertNotIn("is not valid under any of the given schemas", problems[0].message)

    def test_an_orientation_with_a_bogus_status_keeps_the_parent_error(self) -> None:
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["route"][0]["orientation"] = {
            "status": "bogus", "rotation": {"quaternion": [1, "bad", 0, 0]}}
        problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["intent/route/0/orientation"])
        self.assertIn("is not valid under any of the given schemas", problems[0].message)

    def test_a_matching_orientation_status_reports_its_invalid_rotation(self) -> None:
        for status in ("proposed", "approved"):
            with self.subTest(status=status):
                documents = fx.tst_record()
                documents["parts/TST-0001/part.yaml"]["intent"]["route"][0]["orientation"] = {
                    "status": status, "rotation": {"quaternion": [1, "bad", 0, 0]}, "decision": "DR-001"}
                problems = mi.schema_problems(documents)
                self.assertEqual([p.pointer for p in problems], ["intent/route/0/orientation/rotation/quaternion/1"])
                self.assertIn("is not of type 'number'", problems[0].message)

    def test_a_known_quantity_wrapped_in_allof_reports_its_invalid_value(self) -> None:
        documents = fx.tst_record()
        documents["product.yaml"]["use_case"]["environment"]["temperature"] = fx.known({"value": "hot", "units": "deg_C"})
        problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["use_case/environment/temperature/value/value"])
        self.assertIn("is not of type 'number'", problems[0].message)

    def test_a_quantity_selected_by_type_reports_its_invalid_unit(self) -> None:
        documents = fx.tst_record()
        documents["requirements.yaml"]["assumptions"] = [{
            "id": "ASM-001", "text": "TST force", "origin": "TST fixture", "reason": "TST estimate",
            "owner": "TST owner", "validation": "TST measurement", "status": "open",
            "bounds": {"value": 5, "units": "bogus"}}]
        problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["assumptions/0/bounds/units"])
        self.assertIn("'bogus' is not one of", problems[0].message)

    def test_a_bogus_fact_status_keeps_the_parent_after_type_selection(self) -> None:
        for field in ("functions", "route"):
            with self.subTest(field=field):
                documents = fx.tst_record()
                documents["parts/TST-0001/part.yaml"]["intent"][field] = {"status": "bogus", "reason": "TST reason"}
                problems = mi.schema_problems(documents)
                self.assertEqual([p.pointer for p in problems], [f"intent/{field}"])
                self.assertIn("is not valid under any of the given schemas", problems[0].message)

    def test_discriminator_collection_stops_at_a_recursive_alternative(self) -> None:
        schemas = temp_hw(self).parent / "schemas"
        shutil.copytree(mi.SCHEMAS, schemas)
        path = schemas / "part.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["$defs"]["orientation"]["allOf"] = [{"$ref": "#/$defs/orientation_guard"}]
        schema["$defs"]["orientation_guard"] = {"anyOf": [{"type": "object"}, {"$ref": "#/$defs/orientation_guard"}]}
        path.write_text(json.dumps(schema), encoding="utf-8")
        documents = fx.tst_record()
        documents["parts/TST-0001/part.yaml"]["intent"]["route"][0]["orientation"]["rotation"]["quaternion"][1] = "bad"
        with patch.object(mi, "SCHEMAS", schemas):
            problems = mi.schema_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["intent/route/0/orientation/rotation/quaternion/1"])
        self.assertIn("is not of type 'number'", problems[0].message)

    def test_a_fact_without_a_matching_status_stays_at_the_fact(self) -> None:
        for fact in ({"status": "bogus"}, {}):
            with self.subTest(fact=fact):
                documents = fx.tst_record()
                documents["product.yaml"]["use_case"]["loads"][0]["magnitude"] = fact
                problems = mi.schema_problems(documents)
                self.assertEqual([p.pointer for p in problems], ["use_case/loads/0/magnitude"])
                self.assertIn("is not valid under any of the given schemas", problems[0].message)

    def test_no_combinator_problem_has_an_empty_message(self) -> None:
        for application in ({"bogus": 1}, {"PN": ""}, {"interface": None}, {"product": False}):
            with self.subTest(application=application):
                documents = fx.tst_record()
                documents["product.yaml"]["use_case"]["loads"][0]["application"] = application
                documents["assembly.yaml"]["operations"] = [{"id": {"not": "a name"}}]
                problems = mi.schema_problems(documents)
                self.assertEqual(len(problems), 2, problems)
                for problem in problems:
                    self.assertTrue(problem.message.removeprefix(problem.pointer + ": ").strip(), problem)

    def test_the_tst_record_has_no_schema_problems(self) -> None:
        self.assertEqual(mi.schema_problems(fx.tst_record()), [])


class CheckDocuments(unittest.TestCase):
    """check_documents: schema and record problems of the documents named by `paths` (hw/-prefixed) only."""

    def codes(self, paths: set[str]) -> list[tuple[str, str]]:
        # requirements.yaml holds a schema problem (priority) and a record problem (wrong-owner occurrence);
        # assembly.yaml holds a schema problem (title) only.
        documents = fx.with_subject_occurrences(fx.tst_record(), {"PN": "TST-0001", "occurrence": "@left"})
        documents["requirements.yaml"]["requirements"][0]["priority"] = "urgent"
        documents["assembly.yaml"]["subassemblies"][0]["title"] = 7
        return sorted((p.code, p.path) for p in mi.check_documents(documents, paths))

    def test_a_path_includes_its_schema_and_record_problems(self) -> None:
        self.assertEqual(self.codes({"hw/requirements.yaml"}),
                         [("intent.reference", "hw/requirements.yaml"), ("intent.schema", "hw/requirements.yaml")])

    def test_another_path_excludes_them(self) -> None:
        self.assertEqual(self.codes({"hw/assembly.yaml"}), [("intent.schema", "hw/assembly.yaml")])

    def test_no_paths_report_nothing(self) -> None:
        self.assertEqual(self.codes(set()), [])

    def test_two_paths_report_the_union(self) -> None:
        self.assertEqual(self.codes({"hw/requirements.yaml", "hw/assembly.yaml"}),
                         [("intent.reference", "hw/requirements.yaml"), ("intent.schema", "hw/assembly.yaml"),
                          ("intent.schema", "hw/requirements.yaml")])


class PlausibilityWarnings(unittest.TestCase):
    """plausibility_problems: a warning for a value inside its hard bound and outside its x-plausible band."""

    def documents(self, *, calibrations: list[dict[str, Any]] | None = None, parameters: dict[str, Any] | None = None,
                  **extra: Any) -> dict[str, Any]:
        profile = fx.capability_profile("tst_printer", "fdm", calibrations=calibrations, parameters=parameters, **extra)
        return {"manufacturing/capabilities.yaml": {"profiles": [profile]}}

    def hole(self, value: float, units: str = "mm") -> dict[str, Any]:
        return self.documents(calibrations=[fx.calibration("hole", "min_hole", "tst_polymer_printed", fx.quantity(value, units))])

    def test_a_min_hole_beyond_its_band_warns_with_the_band_and_the_value(self) -> None:
        documents = self.hole(15)
        self.assertEqual(mi.schema_problems(documents), [])
        (problem,) = mi.plausibility_problems(documents)
        self.assertEqual((problem.code, problem.severity, problem.path), ("plausibility.limits", "warning", "hw/manufacturing/capabilities.yaml"))
        self.assertEqual(problem.pointer, "profiles/0/calibrations/0/result/limits/value")
        self.assertIn("value 15 mm", problem.message)
        self.assertIn("0.5 to 10 mm", problem.message)

    def test_a_min_hole_inside_its_band_or_on_its_edge_does_not_warn(self) -> None:
        for value in (2, 0.5, 10):
            with self.subTest(value=value):
                self.assertEqual(mi.plausibility_problems(self.hole(value)), [])

    def test_a_min_hole_below_its_band_warns(self) -> None:
        (problem,) = mi.plausibility_problems(self.hole(0.2))
        self.assertIn("value 0.2 mm", problem.message)

    def test_a_min_hole_beyond_its_hard_bound_is_an_error_and_has_no_warning(self) -> None:
        documents = self.hole(26)
        self.assertTrue(mi.schema_problems(documents))
        self.assertEqual(mi.plausibility_problems(documents), [])

    def test_a_value_is_read_in_the_units_of_the_band(self) -> None:
        cases = [(15000, "um", True), (10000, "um", False), (0.015, "m", True), (0.002, "m", False)]  # 15 mm, 10 mm (the edge), 15 mm, 2 mm
        for value, units, warns in cases:
            with self.subTest(value=value, units=units):
                problems = mi.plausibility_problems(self.hole(value, units))
                self.assertEqual(len(problems), 1 if warns else 0)

    def test_another_characteristic_takes_its_own_band(self) -> None:
        def wall(value: float) -> dict[str, Any]:
            return self.documents(calibrations=[fx.calibration("wall", "min_wall", "tst_polymer_printed", fx.quantity(value))])

        self.assertEqual(mi.plausibility_problems(wall(5))[0].message.count("0.4 to 3 mm"), 1)  # 5 mm is inside min_hole's band, not min_wall's
        self.assertEqual(mi.plausibility_problems(wall(1)), [])
        self.assertEqual(mi.plausibility_problems(self.hole(5)), [])

    def test_a_fact_parameter_takes_the_band_of_its_definition(self) -> None:
        documents = self.documents(parameters={"nozzle_diameter": fx.known(fx.quantity(2))})
        self.assertEqual(mi.schema_problems(documents), [])
        (problem,) = mi.plausibility_problems(documents)
        self.assertEqual(problem.code, "plausibility.nozzle_diameter")
        self.assertIn("0.2 to 1.2 mm", problem.message)

    def test_both_ends_of_an_interval_are_checked(self) -> None:
        documents = self.documents(calibrations=[fx.calibration("hole", "min_hole", "tst_polymer_printed", fx.quantity(lower=1, upper=15))])
        (problem,) = mi.plausibility_problems(documents)
        self.assertIn("upper 15 mm", problem.message)

    def test_an_interval_end_inside_its_hard_bound_still_warns_when_its_sibling_breaks_the_bound(self) -> None:
        documents = self.documents(calibrations=[fx.calibration("hole", "min_hole", "tst_polymer_printed", fx.quantity(lower=0.2, upper=26))])
        self.assertTrue(mi.schema_problems(documents))  # upper 26 mm is past the 25 mm hard bound
        (problem,) = mi.plausibility_problems(documents)  # lower 0.2 mm is inside it and below the 0.5 mm band
        self.assertEqual(problem.pointer, "profiles/0/calibrations/0/result/limits/lower")
        self.assertIn("lower 0.2 mm", problem.message)

    def layer(self, layer: Any, nozzle: Any = None, **extra: Any) -> dict[str, Any]:
        parameters = {"layer_height": layer, **({"nozzle_diameter": nozzle} if nozzle is not None else {})}
        return self.documents(parameters=parameters, **extra)

    def test_a_layer_height_beyond_its_nozzle_band_warns_with_the_limit(self) -> None:
        documents = self.layer(fx.known(fx.quantity(0.9)), fx.known(fx.quantity(0.4)))  # the band is 0.8 of the nozzle: 0.32 mm
        self.assertEqual(mi.schema_problems(documents), [])
        (problem,) = mi.plausibility_problems(documents)
        self.assertEqual((problem.code, problem.severity, problem.path), ("plausibility.layer_height", "warning", "hw/manufacturing/capabilities.yaml"))
        self.assertEqual(problem.pointer, "profiles/0/parameters/layer_height/value/value")
        for text in ("value 0.9 mm", "at most 0.8 of nozzle_diameter 0.4 mm"):
            self.assertIn(text, problem.message)

    def test_a_layer_height_at_or_below_its_nozzle_band_does_not_warn(self) -> None:
        for layer in (0.32, 0.2, 0.05):  # 0.32 is the edge: 0.8 of 0.4
            with self.subTest(layer=layer):
                self.assertEqual(mi.plausibility_problems(self.layer(fx.known(fx.quantity(layer)), fx.known(fx.quantity(0.4)))), [])

    def test_a_layer_height_and_its_nozzle_are_compared_in_one_unit(self) -> None:
        cases = [(300, "um", 0.4, "mm", False), (500, "um", 0.4, "mm", True), (0.0003, "m", 0.4, "mm", False), (0.2, "mm", 400, "um", False)]
        for layer, layer_units, nozzle, nozzle_units, warns in cases:
            with self.subTest(layer=layer, layer_units=layer_units):
                documents = self.layer(fx.known(fx.quantity(layer, layer_units)), fx.known(fx.quantity(nozzle, nozzle_units)))
                self.assertEqual(len(mi.plausibility_problems(documents)), 1 if warns else 0)

    def test_a_layer_height_without_a_known_nozzle_or_value_has_no_relative_warning(self) -> None:
        unknown = fx.unknown()
        for label, documents in (("no nozzle", self.layer(fx.known(fx.quantity(0.9)))),
                                 ("unknown nozzle", self.layer(fx.known(fx.quantity(0.9)), unknown)),
                                 ("unknown layer", self.layer(unknown, fx.known(fx.quantity(0.4))))):
            with self.subTest(label):
                self.assertEqual(mi.plausibility_problems(documents), [])

    def test_each_end_of_a_layer_interval_is_checked_against_the_largest_nozzle(self) -> None:
        documents = self.layer(fx.known(fx.quantity(lower=0.1, upper=0.5)), fx.known(fx.quantity(lower=0.35, upper=0.45)))  # limit 0.36 mm
        (problem,) = mi.plausibility_problems(documents)
        self.assertEqual(problem.pointer, "profiles/0/parameters/layer_height/value/upper")
        self.assertIn("upper 0.5 mm", problem.message)

    def test_a_layer_height_beyond_its_hard_bound_has_no_relative_warning(self) -> None:
        documents = self.layer(fx.known(fx.quantity(4)), fx.known(fx.quantity(0.4)))
        self.assertTrue(mi.schema_problems(documents))
        self.assertEqual(mi.plausibility_problems(documents), [])

    def test_an_integer_too_large_for_a_float_is_left_to_its_hard_bound_and_does_not_crash(self) -> None:
        huge = 10**400
        cases = {  # label: (documents, pointers that warn: the huge member never, a representable sibling still)
            "plain number": ({"product.yaml": fx.product(general_tolerance=huge)}, []),
            "quantity": (self.hole(huge, "um"), []),
            "array element": (self.part_with_edges([huge, 1]), ["drawing/edges/external/1"]),
            "relative layer height": (self.layer(fx.known(fx.quantity(huge)), fx.known(fx.quantity(0.4))), []),
            "relative nozzle": (self.layer(fx.known(fx.quantity(0.9)), fx.known(fx.quantity(huge))), []),
        }
        for label, (documents, pointers) in cases.items():
            with self.subTest(label):
                self.assertEqual([p.pointer for p in mi.plausibility_problems(documents)], pointers)

    def test_a_tool_checks_its_own_layer_height_against_its_own_nozzle(self) -> None:
        tool = {"id": "wide", "description": "A wide hotend", "parameters": {
            "nozzle_diameter": fx.known(fx.quantity(0.4)), "layer_height": fx.known(fx.quantity(0.9))}}
        documents = self.layer(fx.known(fx.quantity(0.2)), fx.known(fx.quantity(0.4)), tools=[tool])
        self.assertEqual(mi.schema_problems(documents), [])
        (problem,) = mi.plausibility_problems(documents)
        self.assertEqual(problem.pointer, "profiles/0/tools/0/parameters/layer_height/value/value")

    def test_a_plain_number_takes_its_band(self) -> None:
        def tolerance(value: Any) -> list[Any]:
            return mi.plausibility_problems({"product.yaml": fx.product(general_tolerance=value)})

        (problem,) = tolerance(1)  # a linear general tolerance in mm: band 0.01 to 0.5, hard bound 5
        self.assertEqual((problem.code, problem.pointer), ("plausibility.general_tolerance", "general_tolerance"))
        self.assertIn("0.01 to 0.5", problem.message)
        for value in (0.1, "ISO 2768-m", 6):  # inside the band, a standard's name, past the hard bound
            with self.subTest(value=value):
                self.assertEqual(tolerance(value), [])

    def part_with_edges(self, external: list[float]) -> dict[str, Any]:
        part = fx.part("TST-0001")
        part["drawing"] = {"type": "vendor_specification", "edges": {"external": external, "internal": [0, 0]}}
        return {"parts/TST-0001/part.yaml": part}

    def test_each_array_element_warns_at_its_own_index(self) -> None:
        documents = self.part_with_edges([1, 1])  # ISO 13715 edge limits, band -0.5 to 0.5, hard bound -5 to 5
        self.assertEqual(mi.schema_problems(documents), [])
        problems = mi.plausibility_problems(documents)
        self.assertEqual([p.pointer for p in problems], ["drawing/edges/external/0", "drawing/edges/external/1"])
        self.assertEqual({p.code for p in problems}, {"plausibility.external"})

    def test_an_array_element_inside_its_hard_bound_warns_when_another_breaks_it(self) -> None:
        documents = self.part_with_edges([1, 9])
        self.assertTrue(mi.schema_problems(documents))
        self.assertEqual([p.pointer for p in mi.plausibility_problems(documents)], ["drawing/edges/external/0"])

    def test_a_deviation_inside_its_hard_bound_warns_when_its_sibling_breaks_it_under_a_oneof(self) -> None:
        part = fx.part("TST-0001")
        part["drawing"] = {"type": "detail", "dimensions": [
            {"id": "d1", "operation": "distance", "features": ["a", "b"], "tolerance": {"deviation_mm": [2, 11]}}]}
        documents = {"parts/TST-0001/part.yaml": part}
        self.assertTrue([p for p in mi.schema_problems(documents) if "tolerance" in p.pointer])  # 11 is past the 10 mm hard bound
        pointers = [p.pointer for p in mi.plausibility_problems(documents)]
        self.assertEqual(pointers, ["drawing/dimensions/0/tolerance/deviation_mm/0"])  # 2 is past the band's 1 mm only

    def test_a_list_where_a_plain_number_is_expected_has_no_member_warning(self) -> None:
        """general_tolerance [1] is refused by every alternative of its oneOf; the numeric branch's band must not warn at its member."""
        documents = {"product.yaml": fx.product(general_tolerance=[1])}
        self.assertTrue([p for p in mi.schema_problems(documents) if p.pointer.startswith("general_tolerance")])
        self.assertEqual(mi.plausibility_problems(documents), [])

    def test_a_unit_that_is_not_a_string_is_a_schema_problem_and_no_crash(self) -> None:
        documents = fx.record(capabilities=[fx.capability_profile(
            "tst_printer", "fdm", calibrations=[fx.calibration("hole", "min_hole", "tst_polymer_printed", {"value": 15, "units": ["mm"]})])])
        self.assertEqual(mi.plausibility_problems(documents), [])
        with tempfile.TemporaryDirectory(prefix="cad-plausibility-") as scratch:
            _record, problems = mi.check_record(fx.write_record(Path(scratch) / "hw", documents))
        self.assertTrue([p for p in problems if p.code == "intent.schema" and "units" in p.message])
        self.assertEqual([p for p in problems if p.code.startswith("plausibility.")], [])

    def test_check_documents_and_check_record_carry_the_warning_without_an_error(self) -> None:
        documents = fx.record(capabilities=[fx.capability_profile(
            "tst_printer", "fdm", calibrations=[fx.calibration("hole", "min_hole", "tst_polymer_printed", fx.quantity(15))])])
        found = [p for p in mi.check_documents(documents, {"hw/manufacturing/capabilities.yaml"}) if p.code.startswith("plausibility.")]
        self.assertEqual([(p.code, p.severity) for p in found], [("plausibility.limits", "warning")])
        with tempfile.TemporaryDirectory(prefix="cad-plausibility-") as scratch:
            hw = fx.write_record(Path(scratch) / "hw", documents)
            _record, problems = mi.check_record(hw)
        self.assertEqual([p.code for p in problems if p.code.startswith("plausibility.")], ["plausibility.limits"])
        self.assertEqual([p for p in problems if p.severity == "error" and p.code == "intent.schema"], [])


class StrictBoundTests(unittest.TestCase):
    """`<` and `>` beside `<=` and `>=`: which of two one-sided bounds is tighter, and when a worst case breaks one."""

    def test_an_upper_bound_tightens_by_value_and_then_by_strictness(self) -> None:
        cases = [  # (old, new, expected), worked out by hand: a smaller limit is tighter; at one limit `<` beats `<=`
            (("<=", 5), ("<=", 4), True), (("<=", 5), ("<=", 5), True), (("<=", 5), ("<=", 6), False),
            (("<=", 5), ("<", 5), True), (("<=", 5), ("<", 4), True), (("<=", 5), ("<", 6), False),
            (("<", 5), ("<=", 5), False), (("<", 5), ("<=", 4.999), True), (("<", 5), ("<=", 6), False),
            (("<", 5), ("<", 5), True), (("<", 5), ("<", 4), True), (("<", 5), ("<", 6), False),
        ]
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertIs(mi.tightens(old, new), expected)

    def test_a_lower_bound_tightens_by_value_and_then_by_strictness(self) -> None:
        cases = [  # a larger limit is tighter; at one limit `>` beats `>=`
            ((">=", 5), (">=", 6), True), ((">=", 5), (">=", 5), True), ((">=", 5), (">=", 4), False),
            ((">=", 5), (">", 5), True), ((">=", 5), (">", 6), True), ((">=", 5), (">", 4), False),
            ((">", 5), (">=", 5), False), ((">", 5), (">=", 5.001), True), ((">", 5), (">=", 4), False),
            ((">", 5), (">", 5), True), ((">", 5), (">", 6), True), ((">", 5), (">", 4), False),
        ]
        for old, new, expected in cases:
            with self.subTest(old=old, new=new):
                self.assertIs(mi.tightens(old, new), expected)

    def test_bounds_on_opposite_sides_or_not_one_sided_cannot_be_compared(self) -> None:
        for old, new in ((("<=", 5), (">=", 3)), ((">", 3), ("<", 5)), (("<", 5), (">", 5)),
                         (("between", [1, 2]), ("<=", 5)), (("<=", 5), ("equals", 5)), (("~", 1), ("<=", 5))):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                mi.tightens(old, new)

    def test_a_worst_case_at_the_limit_breaks_a_strict_upper_bound_only(self) -> None:
        cases = [  # (operator, limit, worst, tolerance, expected)
            ("<=", 5, 5, 0.0, False), ("<", 5, 5, 0.0, True),
            ("<=", 5, 4.999, 0.0, False), ("<", 5, 4.999, 0.0, False),
            ("<=", 5, 5.001, 0.0, True), ("<", 5, 5.001, 0.0, True),
            ("<=", 5, 5 + 1e-10, 1e-9, False), ("<", 5, 5 - 1e-10, 1e-9, True),
        ]
        for operator, limit, worst, tolerance, expected in cases:
            with self.subTest(operator=operator, worst=worst):
                self.assertIs(mi.exceeds_upper_bound(worst, operator, limit, tolerance), expected)

    def test_only_an_upper_bound_operator_can_be_exceeded(self) -> None:
        for operator in (">=", ">", "between", "equals"):
            with self.subTest(operator=operator), self.assertRaises(ValueError):
                mi.exceeds_upper_bound(1, operator, 5)


if __name__ == "__main__":
    unittest.main()
