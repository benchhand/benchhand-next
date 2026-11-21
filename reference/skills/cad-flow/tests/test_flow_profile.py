#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""cad-flow flow_profile.py: the project-start questions, the record of their answers in product.yaml
flow.profile with its accepted MADR decision, and the check that reports what a missing or unasked profile
blocks. The gate itself (cad-record flow_profile_gate.py) has its own tests."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "flow_profile.py"
SKILLS = HERE.parents[1]
sys.path.insert(0, str(SKILLS.parent / "scripts"))
from decision_fixture import write_test_decision  # noqa: E402 - the path to scripts/ is put on sys.path just above
from modload import load_module  # noqa: E402 - the path to scripts/ is put on sys.path just above

flow_profile = load_module("cad_flow_profile", SCRIPT)
gate = flow_profile.gate
yaml_loader = flow_profile.yaml_loader  # the repo's YAML reader: YAML 1.1, so a bare on, off, yes or no is a boolean
decision_records = flow_profile.decision_records
fx = load_module("cad_record_mi_fixtures", SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")

# The nine project-start questions, copied by hand.
QUESTIONS = [
    "Must any part carry a load where breaking or bending would matter? Should I simulate it?",
    "Which fits must not jam or rattle with real, imperfect parts: only the critical ones, all of them, or none?",
    "How much review before release: full, a quick re-check of retainers, mounts and walls, or none?",
    "Which printer, nozzle and filament? What is the bed size?",
    "Are supports allowed, or must parts print support-free? Do you know your overhang, bridge, thinnest-wall and "
    "smallest-feature limits, or should I wait for a test print?",
    "Will you pick the print orientation, or should I propose options? Which faces must stay clean?",
    "Would you like hinges or joints printed already assembled where that fits?",
    "Should every stage gate wait for your approval, or only intent, variant, freeze and release?",
    "Should generated results (STEP, GLB, renders) be committed to git?",
]

OPTIONS = ("human-approval", "fea", "stack-up", "critique", "results-in-git", "orientation", "supports", "overhang-deg",
           "bridge-mm", "min-wall-mm", "min-feature-mm", "warp", "cosmetic-faces", "print-in-place", "pip-clearance-xy",
           "pip-clearance-z")
QUESTION_FIELDS = (
    "human_approval", "fea", "stack_up", "critique", "storage_results_in_git", "processes/fdm/orientation",
    "processes/fdm/supports", "processes/fdm/overhang_deg", "processes/fdm/bridge_mm", "processes/fdm/min_wall_mm",
    "processes/fdm/min_feature_mm", "processes/fdm/warp", "processes/fdm/cosmetic_faces", "processes/fdm/print_in_place",
    "processes/fdm/pip_clearance_mm/xy", "processes/fdm/pip_clearance_mm/z")

PRODUCT = """\
record_version: 2
id: tst-product
# a comment the profile record keeps
rigor: pro
flow:
  stage: intent
  recheck_from: intent
units: mm
"""


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=120)


class Questions(unittest.TestCase):
    def test_questions_prints_the_nine_project_start_questions_verbatim_and_states_the_motion_sweep(self) -> None:
        result = run("questions")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        numbered = [line for line in lines if line[:2] in {f"{n}." for n in range(1, 10)}]
        self.assertEqual(numbered, [f"{n}. {text}" for n, text in enumerate(QUESTIONS, start=1)])
        self.assertTrue(any("motion sweep" in line and "not asked" in line for line in lines), result.stdout)

    def test_questions_lists_the_default_of_every_decision(self) -> None:
        lines = run("questions").stdout.splitlines()
        for line in ("  human_approval: \"all\"", "  fea: {\"enabled\": true, \"mode\": \"accurate\"}",
                     "  processes.fdm.print_in_place: false", "  processes.fdm.pip_clearance_mm.z: \"calibrated\"",
                     "  storage_results_in_git: false"):
            self.assertIn(line, lines)

    def test_the_record_options_cover_exactly_the_questions_fields(self) -> None:
        self.assertEqual(tuple(field for _option, field, _parse, _metavar in flow_profile.OPTIONS), QUESTION_FIELDS)
        self.assertEqual(tuple(option.removeprefix("--") for option, *_rest in flow_profile.OPTIONS), OPTIONS)


class Record(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-flow-profile-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "hw"
        self.hw.mkdir()
        self.product = self.hw / "product.yaml"
        self.product.write_text(PRODUCT, encoding="utf-8")

    def record(self, decision: str = "DR-001", *answers: str) -> subprocess.CompletedProcess[str]:
        """The user answers the options in `answers` (option, value pairs) and accepts the default of every other."""
        given = {answers[i].removeprefix("--") for i in range(0, len(answers), 2)}
        accepted = [name for name in OPTIONS if name not in given]
        return run("record", "--hw", str(self.hw), "--decision", decision, *answers, "--accept-default", *accepted)

    def profile(self) -> Any:
        return yaml_loader.safe_load(self.product.read_text(encoding="utf-8"))["flow"]["profile"]

    def test_record_writes_the_answers_the_defaults_accepted_and_who_gave_each(self) -> None:
        result = self.record("DR-001", "--human-approval", "key", "--fea", "fast:5", "--stack-up", "off", "--critique", "light",
                             "--results-in-git", "no", "--supports", "free", "--overhang-deg", "50", "--warp", "off",
                             "--cosmetic-faces", "on", "--print-in-place", "offer", "--pip-clearance-xy", "0.3")
        self.assertEqual(result.returncode, 0, result.stderr)
        c = "calibrated"
        accepted = ("orientation", "bridge_mm", "min_wall_mm", "min_feature_mm", "pip_clearance_mm/z")
        self.assertEqual(self.profile(), {
            "decision": "DR-001", "human_approval": "key", "fea": {"enabled": True, "mode": "fast", "fast_band_pct": 5},
            "stack_up": "off", "critique": "light", "motion": "auto", "storage_results_in_git": False,
            "processes": {"fdm": {"orientation": "user", "supports": "free", "overhang_deg": 50, "bridge_mm": c, "min_wall_mm": c,
                                  "min_feature_mm": c, "warp": "off", "cosmetic_faces": True, "print_in_place": True,
                                  "pip_clearance_mm": {"xy": 0.3, "z": c}}},
            "asked": {field: ("asked-accepted-default" if field.removeprefix("processes/fdm/") in accepted else "user")
                      for field in QUESTION_FIELDS}})
        data = yaml_loader.safe_load(self.product.read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in data.items() if k != "flow"},
                         {"record_version": 2, "id": "tst-product", "rigor": "pro", "units": "mm"})
        self.assertEqual((data["flow"]["stage"], data["flow"]["recheck_from"]), ("intent", "intent"))
        self.assertIn("# a comment the profile record keeps\n", self.product.read_text(encoding="utf-8"))

    def test_accepting_every_default_records_the_conservative_defaults(self) -> None:
        self.assertEqual(run("record", "--hw", str(self.hw), "--decision", "DR-001", "--accept-default", *OPTIONS).returncode, 0)
        profile = self.profile()
        self.assertEqual({k: v for k, v in profile.items() if k != "asked"}, {
            "decision": "DR-001", "human_approval": "all", "fea": {"enabled": True, "mode": "accurate"}, "stack_up": "auto",
            "critique": "full", "motion": "auto", "storage_results_in_git": False,
            "processes": {"fdm": {"orientation": "user", "supports": "allowed", "overhang_deg": "calibrated",
                                  "bridge_mm": "calibrated", "min_wall_mm": "calibrated", "min_feature_mm": "calibrated",
                                  "warp": "calibrated", "cosmetic_faces": False, "print_in_place": False,
                                  "pip_clearance_mm": {"xy": "calibrated", "z": "calibrated"}}}})
        self.assertEqual(set(profile["asked"].values()), {"asked-accepted-default"})

    def test_record_refuses_a_question_neither_answered_nor_accepted_and_writes_nothing(self) -> None:
        result = run("record", "--hw", str(self.hw), "--decision", "DR-001", "--fea", "off", "--accept-default",
                     *[name for name in OPTIONS if name not in ("fea", "stack-up", "warp")])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--stack-up", result.stderr)
        self.assertIn("--warp", result.stderr)
        self.assertNotIn("--critique", result.stderr)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)
        self.assertFalse((self.hw / "decisions").exists())

    def test_record_refuses_an_option_both_answered_and_accepted(self) -> None:
        result = run("record", "--hw", str(self.hw), "--decision", "DR-001", "--fea", "off", "--accept-default", *OPTIONS)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fea", result.stderr)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)

    def test_record_quotes_every_string_it_writes(self) -> None:
        self.assertEqual(self.record("DR-001", "--stack-up", "off", "--warp", "off", "--fea", "off").returncode, 0)
        text = self.product.read_text(encoding="utf-8")
        for line in ('    stack_up: "off"\n', '        warp: "off"\n', '      enabled: false\n', '    critique: "full"\n'):
            self.assertIn(line, text)

    def test_the_fea_answer_records_off_accurate_or_fast_with_an_optional_band(self) -> None:
        for decision, answer, fea in (("DR-001", "off", {"enabled": False}),
                                      ("DR-002", "accurate", {"enabled": True, "mode": "accurate"}),
                                      ("DR-003", "fast", {"enabled": True, "mode": "fast"}),
                                      ("DR-004", "fast:2.5", {"enabled": True, "mode": "fast", "fast_band_pct": 2.5}),
                                      ("DR-005", "fast:50", {"enabled": True, "mode": "fast", "fast_band_pct": 50})):
            with self.subTest(answer):
                self.product.write_text(PRODUCT, encoding="utf-8")
                self.assertEqual(self.record(decision, "--fea", answer).returncode, 0)
                self.assertEqual(self.profile()["fea"], fea)
        for index, answer in enumerate(("on", "accurate:5", "fast:0", "fast:-1", "fast:50.5", "fast:x")):
            with self.subTest(answer):
                self.assertEqual(self.record(f"DR-09{index}", "--fea", answer).returncode, 2)

    def test_record_writes_an_accepted_madr_decision(self) -> None:
        self.assertEqual(self.record("DR-004", "--fea", "accurate").returncode, 0)
        decisions = self.hw / "decisions"
        found = decision_records.find_decision(decisions, "DR-004")
        self.assertEqual((found.id, found.title, found.status), ("DR-004", "Flow profile", "accepted"))
        self.assertIn("| fea.mode | accurate | user |", found.more_information)
        self.assertIn("| processes.fdm.orientation | user | asked-accepted-default |", found.more_information)
        self.assertIn("| motion | auto | stated |", found.more_information)
        index = (decisions / "index.md").read_text(encoding="utf-8")
        self.assertIn("| [DR-004](DR-004-flow-profile.md) | Flow profile | accepted |", index)

    def test_the_recorded_decision_approves_the_profile_that_cites_it(self) -> None:
        self.assertEqual(self.record("DR-004", "--fea", "accurate").returncode, 0)
        validate = flow_profile.load_validate()
        self.assertIsNone(validate.approval_problem(self.hw, "DR-004"))

    def test_record_refuses_a_decision_that_exists_and_changes_nothing(self) -> None:
        earlier = write_test_decision(self.hw, "DR-001", title="An earlier decision")
        before = earlier.read_text(encoding="utf-8")
        result = self.record("DR-001", "--fea", "accurate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("DR-001", result.stderr)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)
        self.assertEqual(earlier.read_text(encoding="utf-8"), before)
        self.assertEqual([path.name for path in (self.hw / "decisions").glob("DR-*.md")], [earlier.name])

    def test_record_refuses_a_malformed_decision_id(self) -> None:
        result = self.record("DR-1", "--fea", "accurate")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)

    def test_a_second_record_replaces_the_profile_under_its_new_decision(self) -> None:
        self.assertEqual(self.record("DR-001", "--fea", "off").returncode, 0)
        self.assertEqual(self.record("DR-002", "--fea", "accurate").returncode, 0)
        self.assertEqual((self.profile()["decision"], self.profile()["fea"]), ("DR-002", {"enabled": True, "mode": "accurate"}))
        self.assertEqual(self.product.read_text(encoding="utf-8").count("profile:"), 1)
        self.assertEqual([r.id for r in decision_records.read_decisions(self.hw / "decisions")], ["DR-001", "DR-002"])

    def read_only(self, directory: Path) -> None:
        """Make `directory` unwritable for this test; the cleanup restores it so the temp tree can be removed."""
        if os.geteuid() == 0:
            self.skipTest("root writes through a read-only directory")
        directory.chmod(0o555)
        self.addCleanup(directory.chmod, 0o755)

    def test_a_product_that_cannot_be_written_leaves_no_decision_and_a_message_not_a_traceback(self) -> None:
        (self.hw / "decisions").mkdir()
        self.read_only(self.hw)
        result = self.record("DR-001", "--fea", "accurate")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("cannot write", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)
        self.assertEqual(sorted(path.name for path in (self.hw / "decisions").iterdir()), [])

    def test_a_decision_that_cannot_be_written_restores_the_product(self) -> None:
        decisions = self.hw / "decisions"
        decisions.mkdir()
        self.read_only(decisions)
        result = self.record("DR-001", "--fea", "accurate")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.product.read_text(encoding="utf-8"), PRODUCT)
        self.assertEqual(sorted(path.name for path in decisions.iterdir()), [])
        decisions.chmod(0o755)
        self.assertEqual(self.record("DR-001", "--fea", "accurate").returncode, 0, "the retry is not refused")

    def test_an_index_that_cannot_be_updated_removes_the_new_record_and_restores_the_product(self) -> None:
        """decisions/ is writable, so the record is created; the index write then fails because index.md is a directory."""
        earlier = write_test_decision(self.hw, "DR-001", title="An earlier decision")
        before = earlier.read_text(encoding="utf-8")
        index = self.hw / "decisions" / "index.md"
        index.unlink()
        index.mkdir()
        marker = index / "marker"
        marker.write_text("prior state\n", encoding="utf-8")
        result = self.record("DR-002", "--fea", "accurate")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("cannot write the decision record", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.product.read_bytes(), PRODUCT.encode("utf-8"))
        self.assertEqual([path.name for path in (self.hw / "decisions").glob("DR-*.md")], [earlier.name])
        self.assertEqual(earlier.read_text(encoding="utf-8"), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "prior state\n")
        marker.unlink()
        index.rmdir()
        self.assertEqual(self.record("DR-002", "--fea", "accurate").returncode, 0, "the retry is not refused")
        listing = (self.hw / "decisions" / "index.md").read_text(encoding="utf-8")
        self.assertIn("[DR-001]", listing)
        self.assertIn("[DR-002]", listing)

    def test_record_refuses_a_flow_it_cannot_edit_as_text(self) -> None:
        text = PRODUCT.replace("flow:\n  stage: intent\n  recheck_from: intent\n", "flow: {stage: intent, recheck_from: intent}\n")
        self.product.write_text(text, encoding="utf-8")
        result = self.record("DR-001", "--fea", "accurate")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.product.read_text(encoding="utf-8"), text)
        self.assertFalse((self.hw / "decisions").exists())


class Check(unittest.TestCase):
    """flow_profile.py check: the gate over a work tree, with the cited decision judged by cad-record's reader."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-flow-profile-check-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "hw"
        self.hw.mkdir()
        self.documents = fx.tst_record()

    def write(self, stage: str = "parts", profile: Any = None, *, process: str = "fdm") -> None:
        product = copy.deepcopy(self.documents["product.yaml"])
        product["flow"].update(stage=stage, recheck_from=stage)
        if profile is not None:
            product["flow"]["profile"] = profile
        (self.hw / "product.yaml").write_text(yaml.safe_dump(product, sort_keys=False), encoding="utf-8")
        part = copy.deepcopy(self.documents["parts/TST-0001/part.yaml"])
        part["process"] = process
        if process != "fdm":
            part["intent"]["route"] = []  # the fixture's route prints the part
        target = self.hw / "parts" / "TST-0001" / "part.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(part, sort_keys=False), encoding="utf-8")

    def check(self, *stage: str) -> tuple[int, dict[str, Any]]:
        result = run("check", "--hw", str(self.hw), *(("--stage", *stage) if stage else ()))
        return result.returncode, json.loads(result.stdout) if result.stdout else {"stderr": result.stderr}

    def test_a_complete_profile_with_an_accepted_decision_passes(self) -> None:
        self.write("release", fx.flow_profile("DR-007"))
        write_test_decision(self.hw, "DR-007", status="accepted")
        self.assertEqual(self.check(), (0, {"ok": True, "stage": "release", "problems": []}))

    def test_a_missing_profile_blocks_from_specify_on(self) -> None:
        for stage, code in (("intent", 0), ("specify", 1), ("layout", 1)):
            with self.subTest(stage=stage):
                self.write(stage)
                exit_code, report = self.check()
                self.assertEqual(exit_code, code, report)
                self.assertEqual([p["path"] for p in report["problems"]], ["flow/profile"] if code else [])

    def test_a_decision_that_is_missing_or_not_accepted_blocks_and_says_why(self) -> None:
        self.write("specify", fx.flow_profile("DR-009"))
        exit_code, report = self.check()
        self.assertEqual((exit_code, [p["path"] for p in report["problems"]]), (1, ["flow/profile/decision"]))
        self.assertIn("has no record", report["problems"][0]["message"])
        write_test_decision(self.hw, "DR-009", status="proposed")
        exit_code, report = self.check()
        self.assertEqual(exit_code, 1)
        self.assertIn("has status proposed", report["problems"][0]["message"])

    def test_a_profile_recorded_by_the_record_command_passes_its_own_check(self) -> None:
        (self.hw / "product.yaml").write_text(PRODUCT.replace("intent", "specify"), encoding="utf-8")
        recorded = run("record", "--hw", str(self.hw), "--decision", "DR-001", "--accept-default", *OPTIONS)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(self.check(), (0, {"ok": True, "stage": "specify", "problems": []}))

    def test_the_fdm_questions_follow_the_part_records_in_the_work_tree(self) -> None:
        profile = fx.flow_profile("DR-007")
        del profile["asked"]["processes/fdm/orientation"]
        write_test_decision(self.hw, "DR-007", status="accepted")
        for process, code in (("fdm", 1), ("cnc", 0)):
            with self.subTest(process=process):
                self.write("parts", profile, process=process)
                exit_code, report = self.check()
                self.assertEqual(exit_code, code, report)
                self.assertEqual([p["path"] for p in report["problems"]],
                                 ["flow/profile/asked/processes/fdm/orientation"] if code else [])

    def test_the_lamp_arm_example_records_a_profile_that_passes_the_check(self) -> None:
        result = run("check", "--hw", str(SKILLS.parent / "examples" / "lamp-arm" / "hw"))
        self.assertEqual((result.returncode, json.loads(result.stdout)["problems"]), (0, []), result.stdout)

    def test_check_exits_2_without_a_readable_record_or_with_an_unknown_stage(self) -> None:
        self.write("parts", fx.flow_profile())
        self.assertEqual(run("check", "--hw", str(self.hw), "--stage", "assembly").returncode, 2)
        (self.hw / "product.yaml").unlink()
        self.assertEqual(run("check", "--hw", str(self.hw)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
