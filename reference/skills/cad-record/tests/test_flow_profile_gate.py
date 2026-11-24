#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""flow_profile_gate: the pure gate on product.yaml flow.profile (missing or unasked answers, unquoted words,
the schema's shape) and the flow.conflict rules between the profile and the rest of the record. The gate
reads no files: every case passes the parsed record and an approval callable."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL.parents[1] / "scripts"))
from modload import load_module  # noqa: E402 - the path to scripts/ is put on sys.path just above

gate_module = load_module("cad_record_flow_profile_gate", SKILL / "scripts" / "flow_profile_gate.py")
yaml_loader = load_module("cad_record_yaml_loader", SKILL / "scripts" / "yaml_loader.py")
fx = load_module("cad_record_mi_fixtures", HERE / "fixtures" / "manufacturing_intent.py")

PRODUCT_SCHEMA = json.loads((SKILL / "schemas" / "product.schema.json").read_text(encoding="utf-8"))
INTERFACES = "https://srobroek.com/cad/schemas/interfaces.schema.json"
# The project-start answers' fields, written out here apart from the module's own list.
QUESTION_FIELDS = (
    "human_approval", "fea", "stack_up", "critique", "storage_results_in_git", "processes/fdm/orientation",
    "processes/fdm/supports", "processes/fdm/overhang_deg", "processes/fdm/bridge_mm", "processes/fdm/min_wall_mm",
    "processes/fdm/min_feature_mm", "processes/fdm/warp", "processes/fdm/cosmetic_faces", "processes/fdm/print_in_place",
    "processes/fdm/pip_clearance_mm/xy", "processes/fdm/pip_clearance_mm/z")


def approved(_decision: str) -> None:
    return None


def refused(why: str) -> Any:
    return lambda _decision: why


def profile_errors(profile: Any) -> list[str]:
    validator = gate_module.schema_registry.ref_validator(gate_module.SCHEMAS, gate_module.PROFILE_REF)
    return [error.message for error in validator.iter_errors(profile)]


class SchemaContract(unittest.TestCase):
    """The product.schema.json values other packages build on."""

    def test_the_question_fields_are_the_sixteen_answers_in_question_order(self) -> None:
        self.assertEqual(gate_module.QUESTION_FIELDS, QUESTION_FIELDS)

    def test_every_question_field_and_motion_has_a_schema_default_that_the_module_applies(self) -> None:
        defs = PRODUCT_SCHEMA["$defs"]
        profile, fdm, fea = defs["profile"]["properties"], defs["fdm_profile"]["properties"], defs["fea"]["properties"]
        expected = {
            "human_approval": profile["human_approval"]["default"], "stack_up": profile["stack_up"]["default"],
            "critique": profile["critique"]["default"], "motion": profile["motion"]["default"],
            "storage_results_in_git": profile["storage_results_in_git"]["default"],
            "fea": {"enabled": fea["enabled"]["default"], "mode": fea["mode"]["default"]},
            **{f"processes/fdm/{key}": fdm[key]["default"] for key in (
                "orientation", "supports", "overhang_deg", "bridge_mm", "min_wall_mm", "min_feature_mm", "warp",
                "cosmetic_faces", "print_in_place")},
            **{f"processes/fdm/pip_clearance_mm/{axis}": fdm["pip_clearance_mm"]["properties"][axis]["default"]
               for axis in ("xy", "z")}}
        self.assertEqual(gate_module.DEFAULTS, expected)
        self.assertEqual(set(gate_module.DEFAULTS), {*QUESTION_FIELDS, "motion"})

    def test_the_fea_shape_agreed_with_package_a(self) -> None:
        accepted = ({"enabled": False}, {"enabled": True, "mode": "accurate"}, {"enabled": True, "mode": "fast"},
                    {"enabled": True, "mode": "fast", "fast_band_pct": 50})
        rejected = ({"enabled": True}, {"enabled": False, "mode": "fast"}, {"enabled": False, "fast_band_pct": 5},
                    {"enabled": True, "mode": "accurate", "fast_band_pct": 5},
                    {"enabled": True, "mode": "fast", "fast_band_pct": 0},
                    {"enabled": True, "mode": "fast", "fast_band_pct": -1},
                    {"enabled": True, "mode": "fast", "fast_band_pct": 50.5},
                    {"enabled": True, "mode": "fast", "solver": "ccx"}, "off", True, "not_asked")
        for fea in accepted:
            with self.subTest(accepted=fea):
                self.assertEqual(profile_errors(fx.flow_profile(fea=fea)), [])
        for fea in rejected:
            with self.subTest(rejected=fea):
                self.assertNotEqual(profile_errors(fx.flow_profile(fea=fea)), [])

    def test_a_fea_setting_needs_a_boolean_enabled_and_is_otherwise_not_assessed(self) -> None:
        for fea, expected in (("off", (None, None)), ({"enabled": False}, (False, None)),
                              ({"enabled": True, "mode": "fast"}, (True, "fast"))):
            with self.subTest(fea=fea):
                self.assertEqual(gate_module.fea_setting(fx.flow_profile(fea=fea)), expected)

    def test_the_asked_state_takes_only_the_two_provenances(self) -> None:
        for provenance, ok in (("user", True), ("asked-accepted-default", True), ("not_asked", False), ("default", False)):
            with self.subTest(provenance):
                self.assertEqual(profile_errors(fx.flow_profile(asked={"stack_up": provenance})) == [], ok)

    def test_fdm_is_the_iso_52900_material_extrusion_category(self) -> None:
        processes = PRODUCT_SCHEMA["$defs"]["profile"]["properties"]["processes"]["properties"]
        self.assertEqual(gate_module.ISO_52900_CATEGORY["fdm"], "mex")
        self.assertEqual(set(gate_module.ISO_52900_CATEGORY), set(processes), "every profile process has a category")
        self.assertLessEqual(set(gate_module.ISO_52900_CATEGORY.values()),
                             set(PRODUCT_SCHEMA["$defs"]["iso_52900_category"]["enum"]))

    def test_the_print_in_place_block_of_an_interface_names_joints_faces_and_how_they_break_free(self) -> None:
        face = {"PN": "TST-0001", "feature": "knuckle"}
        other = {"PN": "TST-0002", "feature": "pin"}
        joint = {"joint": "hinge", "print_pose": {"J-001": 0}, "gap_features": [[face, other]],
                 "break_free": {"method": "flex by hand", "force_n": 5}}
        validator = gate_module.schema_registry.ref_validator(
            gate_module.SCHEMAS, f"{INTERFACES}#/$defs/functional/properties/print_in_place")
        self.assertEqual(list(validator.iter_errors([joint])), [])
        for name, bad in (("unknown joint", {**joint, "joint": "gear"}), ("no gap", {**joint, "gap_features": []}),
                          ("one face", {**joint, "gap_features": [[face]]}),
                          ("bad joint id", {**joint, "print_pose": {"hinge": 0}}),
                          ("no method", {**joint, "break_free": {"force_n": 5}}),
                          ("zero force", {**joint, "break_free": {"method": "pry", "force_n": 0}})):
            with self.subTest(name):
                self.assertNotEqual(list(validator.iter_errors([bad])), [])

    def test_a_requirement_verification_names_the_step_that_verifies_it(self) -> None:
        validator = gate_module.schema_registry.document_validator(gate_module.SCHEMAS, "requirements.schema.json")
        record = fx.tst_record()["requirements.yaml"]
        self.assertEqual(list(validator.iter_errors(record)), [])
        for step, ok in (("fea", True), ("physical", True), ("welding", False)):
            with self.subTest(step):
                edited = copy.deepcopy(record)
                edited["requirements"][0]["verification"]["step"] = step
                self.assertEqual(list(validator.iter_errors(edited)) == [], ok)


class Gate(unittest.TestCase):
    """The check cad_model.py run, validate.py and the stage advance share (the later PR wires them)."""

    def setUp(self) -> None:
        self.record = fx.tst_record()
        self.product = self.record["product.yaml"]
        self.parts = {rel.split("/")[1]: doc for rel, doc in self.record.items() if rel.startswith("parts/")}

    def with_profile(self, profile: Any, stage: str = "specify") -> dict[str, Any]:
        product = copy.deepcopy(self.product)
        product["flow"].update(stage=stage, recheck_from=stage)
        if profile is None:
            product["flow"].pop("profile", None)
        else:
            product["flow"]["profile"] = profile
        return product

    def check(self, recorded: str, profile: Any, approval: Any = approved, **kwargs: Any) -> list[tuple[str, str]]:
        """The gate's findings for a product recorded at stage `recorded`."""
        _stage, found = gate_module.gate(self.with_profile(profile, recorded), self.parts, approval, **kwargs)
        return [(item.code, item.path) for item in found]

    def test_a_complete_profile_with_an_approving_decision_passes_at_every_stage(self) -> None:
        for stage in gate_module.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(self.check(stage, fx.flow_profile()), [])

    def test_a_missing_profile_blocks_from_specify_on(self) -> None:
        for stage, expected in (("ground", []), ("intent", []), ("specify", [("flow.profile", "flow/profile")]),
                                ("layout", [("flow.profile", "flow/profile")])):
            with self.subTest(stage=stage):
                self.assertEqual(self.check(stage, None), expected)

    def test_a_build_checks_at_layout_at_the_earliest(self) -> None:
        self.assertEqual(self.check("intent", None, build=True), [("flow.profile", "flow/profile")])
        self.assertEqual(self.check("intent", None), [])

    def test_the_stage_argument_overrides_the_recorded_stage(self) -> None:
        self.assertEqual(self.check("intent", None, stage="parts"), [("flow.profile", "flow/profile")])

    def test_a_profile_citing_no_decision_blocks(self) -> None:
        profile = fx.flow_profile()
        del profile["decision"]
        self.assertEqual(self.check("specify", profile), [("flow.profile", "flow/profile/decision")])

    def test_a_cited_decision_that_does_not_approve_blocks_with_the_approvals_reason(self) -> None:
        _stage, found = gate_module.gate(self.with_profile(fx.flow_profile("DR-009")), self.parts,
                                         refused("has status proposed, not the user's approval"))
        self.assertEqual([(item.path, item.message) for item in found], [(
            "flow/profile/decision", "flow.profile cites DR-009, which has status proposed, not the user's approval")])

    def test_the_approval_is_asked_about_the_cited_decision_only(self) -> None:
        asked: list[str] = []
        self.check("specify", fx.flow_profile("DR-042"), approval=lambda decision: asked.append(decision))
        self.assertEqual(asked, ["DR-042"])

    def test_a_profile_with_no_asked_state_blocks_on_every_start_question_from_specify_on(self) -> None:
        profile = fx.flow_profile()
        del profile["asked"]
        for stage, expected in (("intent", []), ("specify", [f"flow/profile/asked/{field}" for field in QUESTION_FIELDS])):
            with self.subTest(stage=stage):
                self.assertEqual([path for _code, path in self.check(stage, profile)], expected)

    def test_one_question_with_no_asked_state_blocks_by_itself(self) -> None:
        profile = fx.flow_profile()
        del profile["asked"]["fea"]
        self.assertEqual(self.check("parts", profile), [("flow.profile", "flow/profile/asked/fea")])

    def test_an_unknown_provenance_is_a_schema_finding(self) -> None:
        profile = fx.flow_profile(asked={**fx.flow_profile()["asked"], "critique": "not_asked"})
        self.assertIn("flow/profile/asked/critique", [path for _code, path in self.check("parts", profile)])

    def test_asked_keys_of_mixed_types_with_bad_provenance_are_findings_not_a_crash(self) -> None:
        """YAML reads `1: bogus` as an integer key beside the string keys; the findings still sort and report."""
        profile = fx.flow_profile(asked={**fx.flow_profile()["asked"], 1: "bogus", "fea": "bogus"})
        paths = [path for _code, path in self.check("parts", profile)]
        self.assertIn("flow/profile/asked/1", paths)
        self.assertIn("flow/profile/asked/fea", paths)

    def test_a_default_marked_accepted_must_equal_the_default(self) -> None:
        profile = fx.flow_profile(stack_up="off")
        profile["asked"]["stack_up"] = "asked-accepted-default"
        self.assertEqual(self.check("parts", profile), [("flow.profile", "flow/profile/asked/stack_up")])
        _stage, found = gate_module.gate(self.with_profile(profile), self.parts, approved)
        self.assertIn("auto", found[0].message)
        profile = fx.flow_profile(stack_up="auto")
        profile["asked"]["stack_up"] = "asked-accepted-default"
        self.assertEqual(self.check("parts", profile), [])

    def test_the_fdm_questions_apply_only_to_a_product_that_plans_fdm(self) -> None:
        profile = fx.flow_profile()
        del profile["asked"]["processes/fdm/orientation"]
        fdm_part, cnc_part = self.parts["TST-0001"], self.parts["TST-0002"]
        for name, parts, processes, expected in (
                ("an fdm part", {"TST-0001": fdm_part}, None, 1), ("no fdm part", {"TST-0002": cnc_part}, None, 0),
                ("fdm planned at intent", {}, ["fdm"], 1), ("no parts", {}, None, 0),
                ("an fdm route operation", {"TST-0009": {"process": "cnc", "intent": {"route": [{"kind": "fdm"}]}}}, None, 1)):
            with self.subTest(name):
                self.parts = parts
                product = self.with_profile(profile, "parts")
                if processes:
                    product["manufacturing"] = {"processes": processes}
                _stage, found = gate_module.gate(product, parts, approved)
                self.assertEqual(len(found), expected)

    def test_the_pip_clearance_questions_apply_only_while_print_in_place_is_offered(self) -> None:
        for offer, expected in ((True, [("flow.profile", "flow/profile/asked/processes/fdm/pip_clearance_mm/z")]), (False, [])):
            with self.subTest(print_in_place=offer):
                profile = fx.flow_profile(fdm={"print_in_place": offer})
                del profile["asked"]["processes/fdm/pip_clearance_mm/z"]
                self.assertEqual(self.check("detail", profile), expected)


class BareYaml(unittest.TestCase):
    """YAML 1.1 reads a bare on, off, yes or no as a boolean (the repo's yaml_loader). A two-state field is a
    boolean, so the bare word is its value; a field with more states is a string, and a bare word blocks
    with flow.profile_unquoted, never read as an answer."""

    BOOLEAN = (("enabled", "on", "fea/enabled", True), ("enabled", "off", "fea/enabled", False),
               ("cosmetic_faces", "on", "processes/fdm/cosmetic_faces", True),
               ("cosmetic_faces", "off", "processes/fdm/cosmetic_faces", False),
               ("print_in_place", "yes", "processes/fdm/print_in_place", True),
               ("print_in_place", "no", "processes/fdm/print_in_place", False),
               ("storage_results_in_git", "yes", "storage_results_in_git", True),
               ("storage_results_in_git", "no", "storage_results_in_git", False))
    STRING = (("stack_up", "on", "stack_up"), ("stack_up", "off", "stack_up"), ("critique", "off", "critique"),
              ("supports", "off", "processes/fdm/supports"), ("overhang_deg", "off", "processes/fdm/overhang_deg"),
              ("bridge_mm", "off", "processes/fdm/bridge_mm"), ("min_wall_mm", "off", "processes/fdm/min_wall_mm"),
              ("min_feature_mm", "off", "processes/fdm/min_feature_mm"), ("warp", "off", "processes/fdm/warp"))

    def parsed(self, key: str, word: str) -> Any:
        """product.yaml at release with `key: <word>` written bare, read by the repo's loader."""
        product = fx.product(stage="release")
        product["flow"]["profile"] = fx.flow_profile()
        if key == "enabled":
            product["flow"]["profile"]["fea"] = {"enabled": True, "mode": "accurate"} if word == "on" else {"enabled": False}
        text = yaml.safe_dump(product, sort_keys=False)
        lines = [line for line in text.splitlines() if line.lstrip().startswith(f"{key}:") and not line.endswith(": user")]
        self.assertEqual(len(lines), 1, key)
        indent = lines[0][:len(lines[0]) - len(lines[0].lstrip())]
        return yaml_loader.safe_load(text.replace(lines[0], f"{indent}{key}: {word}"))

    def test_a_bare_word_is_the_value_of_a_two_state_field(self) -> None:
        for key, word, path, value in self.BOOLEAN:
            with self.subTest(f"{key}: {word}"):
                product = self.parsed(key, word)
                self.assertEqual(gate_module.value_at(product["flow"]["profile"], path), value)
                self.assertEqual(gate_module.gate(product, {}, approved)[1], [])

    def test_a_bare_on_or_off_in_a_field_with_more_states_blocks_and_asks_for_quotes(self) -> None:
        for key, word, path in self.STRING:
            with self.subTest(f"{key}: {word}"):
                _stage, found = gate_module.gate(self.parsed(key, word), {}, approved)
                self.assertEqual([(item.code, item.path) for item in found], [("flow.profile_unquoted", f"flow/profile/{path}")])
                self.assertIn(f'write "{word}" in quotes', found[0].message)


class Conflicts(unittest.TestCase):
    """What validate.py reports as flow.conflict, one rule per test."""

    def setUp(self) -> None:
        self.documents = fx.tst_record()

    def conflicts(self, fea_cases: tuple[str, ...] = (), **profile: Any) -> list[tuple[str, bool]]:
        product = self.documents["product.yaml"]
        product["flow"]["profile"] = fx.flow_profile(**profile)
        parts = {rel.split("/")[1]: doc for rel, doc in self.documents.items() if rel.startswith("parts/")}
        found = gate_module.conflicts(product, self.documents["requirements.yaml"], self.documents["interfaces.yaml"],
                                      parts, fea_cases)
        return [(item.rule, item.refuse) for item in found]

    def pip_joint(self, **interface: Any) -> None:
        joint = {"joint": "hinge", "print_pose": {"J-001": 0}, "break_free": {"method": "flex by hand"},
                 "gap_features": [[{"PN": "TST-0001", "feature": "knuckle"}, {"PN": "TST-0002", "feature": "pin"}]]}
        self.documents["interfaces.yaml"]["interfaces"][0]["functional"]["print_in_place"] = [joint]
        self.documents["interfaces.yaml"]["interfaces"][0].update(interface)

    def test_the_fixture_profile_conflicts_with_nothing_in_the_fixture_record(self) -> None:
        self.assertEqual(self.conflicts(), [])

    def test_a_product_without_a_profile_conflicts_with_nothing(self) -> None:
        self.assertEqual(gate_module.conflicts({}, {}, {}, {}, ()), [])

    def test_fea_off_conflicts_with_a_strength_requirement_or_an_authored_fea_case(self) -> None:
        self.assertEqual(self.conflicts(fea={"enabled": False}, critique="light", fea_cases=("bracket_load",)),
                         [("fea_off", False)])
        self.documents["requirements.yaml"]["requirements"][0]["verification"]["step"] = "fea"
        self.assertEqual(self.conflicts(fea={"enabled": False}, critique="light"), [("fea_off", False)])

    def test_stack_up_off_conflicts_with_a_critical_interface(self) -> None:
        self.assertEqual(self.conflicts(stack_up="off"), [("stack_up_off", False)])

    def test_fea_on_conflicts_with_a_light_or_no_critique(self) -> None:
        for critique in ("light", "off"):
            with self.subTest(critique=critique):
                self.assertEqual(self.conflicts(critique=critique), [("fea_without_critique", False)])

    def test_support_free_printing_conflicts_with_a_part_that_plans_supports(self) -> None:
        self.assertEqual(self.conflicts(fdm={"supports": "free"}), [("supports_free", False)])

    def test_a_print_in_place_joint_conflicts_with_declining_print_in_place_or_an_unchecked_overhang(self) -> None:
        self.pip_joint()
        for fdm in ({"print_in_place": False}, {"overhang_deg": "off"}):
            with self.subTest(**fdm):
                self.assertEqual(self.conflicts(fdm=fdm), [("pip_not_offered", False)])

    def test_a_print_in_place_joint_conflicts_with_a_required_play_tighter_than_the_clearance(self) -> None:
        self.pip_joint(pair=["TST-0001", "TST-0002"], min_clearance_mm=0.2, type="clearance")
        self.assertEqual(self.conflicts(fdm={"pip_clearance_mm": {"xy": 0.2, "z": "calibrated"}}), [])
        self.assertEqual(self.conflicts(fdm={"pip_clearance_mm": {"xy": 0.2, "z": 0.3}}), [("pip_play_too_tight", False)])

    def test_safety_critical_service_or_regulated_rigor_refuses_every_off_and_light(self) -> None:
        profile = {"fea": {"enabled": False}, "critique": "light", "stack_up": "auto", "fdm": {"warp": "off"}}
        expected = [("fea_off", False), ("safety_off", True), ("safety_off", True), ("safety_off", True)]
        self.documents["product.yaml"]["use_case"]["service_class"] = fx.known("safety_critical")
        self.assertEqual(self.conflicts(fea_cases=("bracket_load",), **profile), expected)
        self.documents["product.yaml"]["use_case"]["service_class"] = fx.known("production")
        self.documents["product.yaml"]["rigor"] = "regulated"
        self.assertEqual(self.conflicts(fea_cases=("bracket_load",), **profile), expected)

    def test_a_list_the_record_holds_as_something_else_counts_as_empty_and_never_crashes(self) -> None:
        profile = fx.flow_profile(stack_up="off", fea={"enabled": False})
        product = {**self.documents["product.yaml"], "flow": {"stage": "parts", "recheck_from": "parts", "profile": profile}}
        for name, requirements, interfaces in (("scalars", {"requirements": 7}, {"interfaces": 7}),
                                               ("strings", {"requirements": "x"}, {"interfaces": "x"}),
                                               ("not mappings", [], []), ("items", {"requirements": [3]}, {"interfaces": [3]})):
            with self.subTest(name):
                self.assertEqual(gate_module.conflicts(product, requirements, interfaces, {}, ()), [])


if __name__ == "__main__":
    unittest.main()
