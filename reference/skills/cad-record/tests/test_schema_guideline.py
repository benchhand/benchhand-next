#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The manufacturing guideline schema (benchhand-lch): the file, the guideline source kind, the capability
profile pin and the material-profile scope facts. Every case names the rule it proves."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

SKILL = Path(__file__).resolve().parents[1]
SCHEMAS = SKILL / "schemas"
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

fx = load("cad_record_mi_fixtures", Path(__file__).resolve().parent / "fixtures" / "manufacturing_intent.py")
registry = fx.schema_registry_module()
GUIDELINE = "manufacturing-guideline.schema.json"
SHA = "a" * 64


def errors(name: str, document: Any) -> list[str]:
    validator = registry.document_validator(SCHEMAS, name)
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(document)]


def datasheet() -> dict[str, Any]:
    return fx.source("datasheet", "TST guide", locator="table 2")


def limit(**edit: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(0.8),
                            "citations": [datasheet()]}
    data.update(edit)
    return data


def guideline(**edit: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"schema_version": 1, "id": "fdm.generic", "revision": 1, "title": "TST", "scope": {"process": "fdm"},
                            "limits": [limit()]}
    data.update(edit)
    return data


class GuidelineFile(unittest.TestCase):
    def assert_cases(self, cases: dict[str, tuple[dict[str, Any], bool]]) -> None:
        for label, (document, valid) in cases.items():
            with self.subTest(label):
                self.assertEqual(not errors(GUIDELINE, document), valid, errors(GUIDELINE, document))

    def test_a_minimal_file_validates_and_unknown_keys_are_refused(self) -> None:
        self.assert_cases({
            "minimal": (guideline(), True),
            "extends and abstract": (guideline(extends=["fdm.generic"], abstract=True), True),
            "a $schema key": ({**guideline(), "$schema": "x"}, False),
            "an x- key": ({**guideline(), "x-note": 1}, False),
            "a stored layer": ({**guideline(), "layer": "generic"}, False),
            "a machine scope": (guideline(scope={"process": "fdm", "machine": ["h2d"]}), False),
            "a limit confidence": (guideline(limits=[limit(confidence="multi")]), False),
            "a limit_grade": (guideline(limits=[limit(limit_grade="guideline")]), False),
            "missing limits": ({k: v for k, v in guideline().items() if k != "limits"}, False),
        })

    def test_ids_are_dotted_semantic_segments(self) -> None:
        self.assert_cases({
            "nozzle": (guideline(id="fdm.nozzle.d0_4"), True),
            "material": (guideline(id="fdm.material.tpu_95a"), True),
            "segment starting with a digit": (guideline(id="fdm.nozzle.0_4"), False),
            "capital": (guideline(id="FDM.generic"), False),
            "a dash": (guideline(id="fdm.pa-cf"), False),
            "a parent that is not an id": (guideline(extends=["fdm..x"]), False),
        })

    def test_the_operator_is_the_criterion_enum_and_shapes_the_value(self) -> None:
        self.assert_cases({
            ">= with a value": (guideline(limits=[limit(operator=">=")]), True),
            "> with a value": (guideline(limits=[limit(operator=">")]), True),
            "< with a value": (guideline(limits=[limit(operator="<")]), True),
            "< with an interval": (guideline(limits=[limit(operator="<", quantity=fx.quantity(lower=0.8, upper=1.2))]), False),
            "<= with a value": (guideline(limits=[limit(operator="<=")]), True),
            "between with an interval": (guideline(limits=[limit(operator="between", quantity=fx.quantity(lower=0.8, upper=1.2))]), True),
            "between with a single value": (guideline(limits=[limit(operator="between")]), False),
            ">= with an interval": (guideline(limits=[limit(quantity=fx.quantity(lower=0.8, upper=1.2))]), False),
            "the old min operator": (guideline(limits=[limit(operator="min")]), False),
            "a quantity without units": (guideline(limits=[limit(quantity={"value": 0.8})]), False),
            "no value at all": (guideline(limits=[{k: v for k, v in limit().items() if k != "quantity"}]), False),
        })

    def test_a_relative_floor_is_bounded_by_its_characteristic_like_a_quantity(self) -> None:
        base = {k: v for k, v in limit().items() if k != "quantity"}
        relative = {"relative_to": "nozzle_diameter", "factor": 2}
        cases: dict[str, tuple[dict[str, Any], bool]] = {}
        for characteristic, good, bad in (("nozzle_diameter", 0.4, 50), ("hole_diameter_deviation", 0.1, 5),
                                          ("dimensional_deviation", 0.1, 5), ("profile_deviation", 0.1, 5)):
            for label, floor, valid in (("good", good, True), ("out of bound", bad, False)):
                limit_ = {**base, "characteristic": characteristic, "relative": {**relative, "floor": fx.quantity(floor)}}
                cases[f"{characteristic} {label} floor"] = (guideline(limits=[limit_]), valid)
        self.assert_cases(cases)

    def test_a_categorical_characteristic_takes_only_categorical_operators_and_values_of_its_kind(self) -> None:
        enclosure = {"characteristic": "enclosure", "operator": "equals", "value": True, "citations": [datasheet()]}
        nozzle = {"characteristic": "nozzle_material", "operator": "one_of", "value": ["hardened_steel"], "citations": [datasheet()]}
        numeric = {"operator": "equals", "value": True, "citations": [datasheet()]}
        self.assert_cases({
            "enclosure equals": (guideline(limits=[enclosure]), True),
            "enclosure equals false": (guideline(limits=[{**enclosure, "value": False}]), True),
            "enclosure one_of booleans": (guideline(limits=[{**enclosure, "operator": "one_of", "value": [True]}]), True),
            "enclosure one_of a string": (guideline(limits=[{**enclosure, "operator": "one_of", "value": ["true"]}]), False),
            "enclosure equals a string": (guideline(limits=[{**enclosure, "value": "true"}]), False),
            "enclosure in mm": (guideline(limits=[limit(characteristic="enclosure", quantity=fx.quantity(5))]), False),
            "enclosure >=": (guideline(limits=[limit(characteristic="enclosure", operator=">=")]), False),
            "enclosure between": (guideline(limits=[limit(characteristic="enclosure", operator="between",
                                                          quantity=fx.quantity(lower=1, upper=2))]), False),
            "enclosure beside a quantity": (guideline(limits=[{**enclosure, "quantity": fx.quantity(1)}]), False),
            "nozzle_material one_of": (guideline(limits=[nozzle]), True),
            "nozzle_material equals": (guideline(limits=[{**nozzle, "operator": "equals", "value": "hardened_steel"}]), True),
            "nozzle_material in capitals": (guideline(limits=[{**nozzle, "value": ["Hardened_Steel"]}]), False),
            "nozzle_material equals in capitals": (guideline(limits=[{**nozzle, "operator": "equals", "value": "Hardened_Steel"}]), False),
            "nozzle_material as a boolean": (guideline(limits=[{**nozzle, "operator": "equals", "value": True}]), False),
            "nozzle_material <=": (guideline(limits=[limit(characteristic="nozzle_material", operator="<=")]), False),
            "equals with a list": (guideline(limits=[{**enclosure, "value": ["x"]}]), False),
            "one_of with a string": (guideline(limits=[{**nozzle, "value": "hardened_steel"}]), False),
            "min_wall equals": (guideline(limits=[{**numeric, "characteristic": "min_wall"}]), False),
            "bridge_span one_of": (guideline(limits=[{**numeric, "characteristic": "bridge_span", "operator": "one_of", "value": ["a"]}]), False),
        })

    def test_a_relative_limit_names_its_base_factor_and_floor(self) -> None:
        relative = {"relative_to": "line_width", "factor": 3, "floor": fx.quantity(0.8)}
        base = {k: v for k, v in limit().items() if k != "quantity"}
        self.assert_cases({
            "line width": (guideline(limits=[{**base, "relative": relative}]), True),
            "nozzle diameter": (guideline(limits=[{**base, "relative": {**relative, "relative_to": "nozzle_diameter"}}]), True),
            "no floor": (guideline(limits=[{**base, "relative": {k: v for k, v in relative.items() if k != "floor"}}]), False),
            "zero factor": (guideline(limits=[{**base, "relative": {**relative, "factor": 0}}]), False),
            "another base": (guideline(limits=[{**base, "relative": {**relative, "relative_to": "layer_height"}}]), False),
            "relative and quantity": (guideline(limits=[{**base, "relative": relative, "quantity": fx.quantity(1)}]), False),
            "a floor below the min_wall bound": (guideline(limits=[{**base, "relative": {**relative, "floor": fx.quantity(0.01)}}]), False),
        })

    def test_a_quantity_is_bounded_by_its_characteristic(self) -> None:
        self.assert_cases({
            "layer height is a capability parameter, not a limit": (guideline(limits=[limit(characteristic="layer_height")]), False),
            "min_feature in range": (guideline(limits=[limit(characteristic="min_feature", quantity=fx.quantity(2.0))]), True),
            "min_hole in range": (guideline(limits=[limit(characteristic="min_hole", quantity=fx.quantity(2.0))]), True),
            "min_feature below its bound": (guideline(limits=[limit(characteristic="min_feature", quantity=fx.quantity(0.05))]), False),
            "min_hole in the wrong dimension": (guideline(limits=[limit(characteristic="min_hole", quantity=fx.quantity(2.0, "deg"))]), False),
            "a characteristic the capability schema does not bound": (guideline(limits=[limit(characteristic="min_gap")]), False),
            "overhang in range": (guideline(limits=[limit(characteristic="overhang_angle", operator="<=", quantity=fx.quantity(45, "deg"))]), True),
            "overhang past 90 deg": (guideline(limits=[limit(characteristic="overhang_angle", operator="<=", quantity=fx.quantity(120, "deg"))]), False),
            "wall below 0.1 mm": (guideline(limits=[limit(quantity=fx.quantity(0.05))]), False),
            "bridge past the build volume": (guideline(limits=[limit(characteristic="bridge_span", operator="<=", quantity=fx.quantity(900))]), False),
            "nozzle past 3 mm": (guideline(limits=[limit(characteristic="nozzle_diameter", quantity=fx.quantity(5))]), False),
        })

    def test_scope_selectors_are_declarative_and_the_nozzle_is_a_bounded_interval(self) -> None:
        nozzle = fx.quantity(lower=0.4, upper=0.4)
        self.assert_cases({
            "material scope": (guideline(scope={"process": "fdm", "material_family": ["pa"], "filler": ["cf"], "shore": ["95a"]}), True),
            "nozzle interval and material": (guideline(scope={"process": "fdm", "nozzle_diameter": nozzle, "nozzle_material": ["brass"]}), True),
            "a nozzle past 3 mm": (guideline(scope={"process": "fdm", "nozzle_diameter": fx.quantity(lower=4, upper=5)}), False),
            "a nozzle with one value": (guideline(scope={"process": "fdm", "nozzle_diameter": fx.quantity(0.4)}), False),
            "an expression": (guideline(scope={"process": "fdm", "when": "nozzle > 0.4"}), False),
            "no process": (guideline(scope={"filler": ["cf"]}), False),
        })

    def test_a_relaxing_limit_needs_a_reason_and_a_citation_and_a_dispute_is_a_flag(self) -> None:
        relaxes = {"reason": "TST vendor profile", "citation": datasheet()}
        self.assert_cases({
            "relaxes": (guideline(limits=[limit(relaxes=relaxes)]), True),
            "relaxes without a citation": (guideline(limits=[limit(relaxes={"reason": "x"})]), False),
            "disputed": (guideline(limits=[limit(disputed=True)]), True),
            "disputed as text": (guideline(limits=[limit(disputed="yes")]), False),
            "applies_to": (guideline(limits=[limit(applies_to={"orientation": "z_up", "feature": "wall"})]), True),
            "no citation": (guideline(limits=[limit(citations=[])]), False),
        })


class GuidelineSource(unittest.TestCase):
    def source_errors(self, source: dict[str, Any]) -> list[str]:
        check = registry.ref_validator(SCHEMAS, "https://srobroek.com/cad/schemas/manufacturing.schema.json#/$defs/source")
        return [e.message for e in check.iter_errors(source)]

    def test_a_guideline_source_needs_a_revision_and_a_digest_and_no_artifact(self) -> None:
        good = {"kind": "guideline", "reference": "fdm.generic", "revision": "1", "sha256": SHA}
        self.assertEqual(self.source_errors(good), [])
        for label, source in {"no revision": {k: v for k, v in good.items() if k != "revision"},
                              "no digest": {k: v for k, v in good.items() if k != "sha256"}}.items():
            with self.subTest(label):
                self.assertTrue(self.source_errors(source))

    def test_a_digest_still_needs_an_artifact_for_every_other_kind(self) -> None:
        self.assertTrue(self.source_errors({"kind": "datasheet", "reference": "x", "url": "https://example.invalid/d",
                                            "accessed": "2026-01-01", "sha256": SHA}))

    def test_a_source_may_state_where_in_it_the_value_sits(self) -> None:
        self.assertEqual(self.source_errors(fx.source("datasheet", "x", locator="section 4")), [])
        self.assertTrue(self.source_errors(fx.source("datasheet", "x", locator="")))


class ProfilePins(unittest.TestCase):
    def test_a_profile_pin_is_an_exclusive_list_of_id_at_revision(self) -> None:
        for label, pin, valid in (("one", ["fdm.generic@1"], True), ("two", ["fdm.generic@1", "fdm.material.pa@3"], True),
                                  ("empty", [], False), ("duplicate", ["fdm.generic@1", "fdm.generic@1"], False),
                                  ("no revision", ["fdm.generic"], False), ("revision zero", ["fdm.generic@0"], False)):
            with self.subTest(label):
                document = {"profiles": [fx.capability_profile("printer", "fdm", guidelines=pin)]}
                found = errors("manufacturing-capabilities.schema.json", document)
                self.assertEqual(not found, valid, found)

    def test_a_material_profile_states_family_filler_and_shore_as_facts(self) -> None:
        for field in ("material_family", "filler", "shore"):
            with self.subTest(field):
                document = {"profiles": [fx.material_profile("pa", **{field: fx.known("pa")})]}
                self.assertEqual(errors("manufacturing-materials.schema.json", document), [])
                document = {"profiles": [fx.material_profile("pa", **{field: "pa"})]}
                self.assertTrue(errors("manufacturing-materials.schema.json", document))

    def test_a_scope_fact_value_is_lowercase_like_the_scope_names(self) -> None:
        for value, valid in (("pla", True), ("tpu", True), ("95a", True), ("PLA", False), ("Pa Cf", False)):
            with self.subTest(value):
                document = {"profiles": [fx.material_profile("pa", material_family=fx.known(value))]}
                self.assertEqual(not errors("manufacturing-materials.schema.json", document), valid)


if __name__ == "__main__":
    unittest.main()
