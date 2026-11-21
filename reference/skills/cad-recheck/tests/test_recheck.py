#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Integration tests for the staged CAD recheck stamp and its `--verify` check.

The project is a small record version 2 record: a confirmed use case and one CNC part. A stamp needs the
evidence packet of the staged record (cad-record evidence.py); the tests build it from a synthetic
producer packet, so they need no CAD kernel. Regression matrix row 13 (stamp refuses stale or missing
expected checks) and the stamp boundary cases."""

from __future__ import annotations

import os
import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any


SKILL = Path(__file__).resolve().parents[1]
STAMP = SKILL / "scripts" / "stamp.py"
ACCEPTANCE = SKILL.parent / "cad-record" / "tests" / "fixtures" / "acceptance.py"


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402
from decision_fixture import add_flow_profile, decision_path, write_test_decision  # noqa: E402


stamp_module = load("cad_recheck_stamp", STAMP)
acceptance = load("cad_record_acceptance_fixtures", ACCEPTANCE)
evidence, fx = acceptance.evidence, acceptance.fx
DAY = date(2026, 11, 19)  # the fixed UTC day of the gate decisions and of the stamp timestamp below
STAMP_TIME = "2026-11-19T10:00:00Z"
LEGACY_PRODUCT = "id: test-project\nflow:\n  stage: {stage}\n  recheck_from: {threshold}\n"


class RecheckHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.global_config = Path(self.temporary.name) / "global.gitconfig"
        self.global_config.write_text("", encoding="utf-8")
        self.git("-c", "init.templateDir=", "init", "-q")
        empty_hooks = Path(self.temporary.name) / "no-hooks"
        empty_hooks.mkdir()
        self.git("config", "core.hooksPath", str(empty_hooks))  # no host or global hook runs in this repo
        self.git("config", "user.name", "CAD Recheck Test")
        self.git("config", "user.email", "cad-recheck@example.invalid")
        self.write_product("specify", "layout")
        self.add_part()
        self.git("add", "hw")
        self.git("commit", "-qm", "initial design")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = str(self.global_config)
        return env

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, text=True, capture_output=True, check=check, env=self.git_env()
        )

    def run_python(self, script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=self.git_env(),
        )

    def add_part(self, pn: str = "PRT-0001", title: str = "Fixture") -> Path:
        part = self.root / "hw" / "parts" / pn
        part.mkdir(parents=True, exist_ok=True)
        intent = fx.intent([{"function": "cosmetic"}], fx.not_applicable("TST"), [fx.operation("mill", "cnc", "tst_cnc")],
                           service=fx.not_applicable("TST"), critical_surfaces=fx.not_applicable("TST"))
        record = {"PN": pn, "rev": "X1", "title": title, "material": "Steel", "process": "cnc", "finish": "As machined",
                  "mass_target": None, "make_buy": "make", "intent": intent}
        (part / "part.yaml").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        return part

    def write_product(self, stage: str, threshold: str | None, *, legacy: bool = False) -> None:
        product = self.root / "hw" / "product.yaml"
        product.parent.mkdir(parents=True, exist_ok=True)
        if legacy:
            product.write_text(LEGACY_PRODUCT.format(stage=stage, threshold=threshold), encoding="utf-8")
            self.add_profile(stage)
            return
        flow = {"stage": stage, **({"recheck_from": threshold} if threshold else {})}
        data = {"record_version": 2, "id": "test-project", "flow": flow,
                "use_case": acceptance.confirmed_use_case("appearance_concept")}
        product.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        self.add_profile(stage)
        assembly = self.root / "hw" / "assembly.yaml"
        if not assembly.exists():
            assembly.write_text("operations: []\n", encoding="utf-8")

    def add_profile(self, stage: str, project: Path | None = None) -> None:
        """The project-start profile, due from SPECIFY on, in the product of `project` (default: the repository)."""
        order = stamp_module.validate.stages()
        if order.index(stage) >= order.index("specify"):
            add_flow_profile((project or self.root) / "hw")

    def test_the_staged_record_carries_the_digests_of_its_guideline_sets(self) -> None:
        (self.root / "hw" / "manufacturing" / "guidelines").mkdir(parents=True)
        profile = fx.capability_profile("tst_printer", "fdm")
        (self.root / "hw" / "manufacturing" / "capabilities.yaml").write_text(
            json.dumps({"profiles": [profile]}), encoding="utf-8")
        guideline = {"schema_version": 1, "id": "fdm.generic", "revision": 1, "title": "TST", "scope": {"process": "fdm"},
                     "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(0.8),
                                 "citations": [fx.source("datasheet", "TST guide")]}]}
        path = self.root / "hw" / "manufacturing" / "guidelines" / "generic.yaml"
        path.write_text(json.dumps(guideline), encoding="utf-8")
        self.git("add", "hw")
        staged = stamp_module.staged_record(self.root)
        digests = staged.record.guideline_digests.get("tst_printer", {}).get("", {})  # the record holds no material
        self.assertEqual(digests.get("fdm.generic@1"), hashlib.sha256(path.read_bytes()).hexdigest(), "the project set shadows the shipped one")
        self.assertIn("fdm.nozzle.d0_4@1", digests, "the shipped sets that apply to an FDM profile are listed too")

    def stage_product(self, stage: str, threshold: str = "layout") -> None:
        self.write_product(stage, threshold)
        self.git("add", "hw/product.yaml")

    def verify(self) -> subprocess.CompletedProcess[str]:
        return self.run_python(STAMP, "--verify", cwd=self.root)

    def evidence_packet(self, stage: str, *, outcome: str = "pass", project: Path | None = None) -> Path:
        """The evidence packet of the staged record at `stage`: every software check `outcome` in a
        synthetic producer packet of a built v1. `project` is the directory holding hw/ (default: the repository)."""
        staged = stamp_module.staged_record(project or self.root)
        producer = evidence.ProducerPacket("hw/checks/v1/tst", "0" * 64,
                                           acceptance.producer_packet(staged.record, outcome=outcome))
        packet = evidence.assess(staged.record, version="v1", manifest_sha256="0" * 64, packets=[producer],
                                 selection_sha256=staged.selection_sha256).packet(stage, staged.record_sha256)
        checks = self.root / ".checks.json"
        checks.write_text(json.dumps(packet), encoding="utf-8")
        return checks

    def stamp(self, *, passed: bool, stage: str, outcome: str = "pass") -> dict[str, object]:
        args = ["--stage", stage, "--checks", str(self.evidence_packet(stage, outcome=outcome))]
        if passed:
            args.append("--passed")
        result = self.run_python(STAMP, *args, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.git("add", "hw/.cad/recheck.json")
        return json.loads(result.stdout)

    def test_staged_release_requires_stamp_even_when_worktree_is_below_threshold(self) -> None:
        self.write_product("release", "layout")
        self.git("add", "hw/product.yaml")
        self.write_product("specify", "layout")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no staged hw/.cad/recheck.json", result.stderr)

    def test_staged_pre_threshold_does_not_require_stamp_even_when_worktree_is_at_threshold(self) -> None:
        self.write_product("specify", "layout")
        self.git("add", "hw/product.yaml")
        self.write_product("release", "layout")
        self.add_part(title="Staged edit")
        self.git("add", "hw/parts/PRT-0001/part.yaml")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_recheck_threshold_is_refused(self) -> None:
        product = self.root / "hw" / "product.yaml"
        product.write_text("id: test-project\nflow:\n  stage: release\n", encoding="utf-8")
        self.git("add", "hw/product.yaml")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or unknown flow.recheck_from", result.stderr)

    def test_unparsable_staged_product_is_refused(self) -> None:
        product = self.root / "hw" / "product.yaml"
        product.write_text("id: test-project\nflow: [\n", encoding="utf-8")
        self.git("add", "hw/product.yaml")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot parse staged hw/product.yaml", result.stderr)

    def gate_packet(self, stage: str, *, outcome: str = "pass") -> Path:
        """The evidence packet at `stage` of a producer that shows only the checks due at or before `stage`:
        later-stage checks stay unknown, as in a project that has just frozen that stage."""
        order = stamp_module.validate.stages()
        staged = stamp_module.staged_record(self.root)
        due = [o for o in evidence.mi.required_checks(staged.record) if order.index(o.stage) <= order.index(stage)]
        producer = evidence.ProducerPacket("hw/checks/v1/tst", "0" * 64,
                                           acceptance.producer_packet(staged.record, outcome=outcome, obligations=due))
        packet = evidence.assess(staged.record, version="v1", manifest_sha256="0" * 64, packets=[producer],
                                 selection_sha256=staged.selection_sha256).packet(stage, staged.record_sha256)
        checks = self.root / ".checks.json"
        checks.write_text(json.dumps(packet), encoding="utf-8")
        return checks

    def provisional_gate(self, flow_stage: str, recheck_from: str = "ground", *, decision: str | None = "proposed",
                         decided: date = DAY) -> None:
        """The state after a provisional gate: flow.stage advanced to `flow_stage`, with a decision of status
        `decision` (none when None) dated `decided` (the fixed DAY by default)."""
        self.stage_product(flow_stage, recheck_from)
        if decision is not None:
            write_test_decision(self.root / "hw", "DR-001", status=decision, date=decided,
                                context="Temporary until the full check: v1 passed fast checks 1-4.")
        self.git("add", "hw")

    def stamp_gate(self, stage: str, *, outcome: str = "pass", passed: bool = True,
                   timestamp: str | None = STAMP_TIME) -> subprocess.CompletedProcess[str]:
        """Stamp `stage` through the public writer, then fix the stamp's timestamp (dropped when None) so no test
        reads the clock. The timestamp sits outside the tree hash, so the staged stamp stays valid."""
        args = ["--stage", stage, "--checks", str(self.gate_packet(stage, outcome=outcome))]
        result = self.run_python(STAMP, *(args + (["--passed"] if passed else [])), cwd=self.root)
        if result.returncode == 0:
            self.set_stamp_time(timestamp)
        return result

    def set_stamp_time(self, timestamp: str | None) -> None:
        path = self.root / "hw" / ".cad" / "recheck.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("timestamp", None)
        if timestamp is not None:
            data["timestamp"] = timestamp
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.git("add", "hw/.cad/recheck.json")

    def refused_gate(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("layout → parts", result.stderr)

    def test_a_stamp_at_the_gate_just_passed_is_accepted_after_the_stage_advanced(self) -> None:
        self.provisional_gate("parts")
        result = self.stamp_gate("layout")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verify().returncode, 0)

    def test_an_advance_without_a_decision_record_is_refused(self) -> None:
        self.provisional_gate("parts", decision=None)
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("layout → parts", result.stderr)
        self.assertIn("hw/decisions", result.stderr)

    def test_an_accepted_decision_dated_on_the_stamp_day_passes_the_advance(self) -> None:
        self.provisional_gate("parts", decision="accepted")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        self.assertEqual(self.verify().returncode, 0)

    def test_a_decision_of_another_status_does_not_pass_the_advance(self) -> None:
        for status in ("rejected", "deprecated"):
            with self.subTest(status=status):
                self.provisional_gate("parts", decision=status)
                self.assertEqual(self.stamp_gate("layout").returncode, 0)
                result = self.verify()
                self.assertEqual(result.returncode, 2)
                self.assertIn("layout → parts", result.stderr)

    def test_a_superseded_decision_does_not_pass_the_advance(self) -> None:
        self.provisional_gate("parts", decision="proposed")
        write_test_decision(self.root / "hw", "DR-002", status="rejected", date=DAY)
        write_test_decision(self.root / "hw", "DR-001", status="proposed", date=DAY,
                            superseded_by=("DR-002",))
        self.git("add", "hw")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("layout → parts", result.stderr)

    def test_a_decision_dated_before_the_stamp_does_not_pass_the_advance(self) -> None:
        self.provisional_gate("parts", decided=date(2026, 11, 18))
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("layout → parts", result.stderr)

    def test_a_malformed_decision_record_is_a_refusal(self) -> None:
        self.provisional_gate("parts")
        decision_path(self.root / "hw", "DR-001").write_text("not a record\n", encoding="utf-8")
        self.git("add", "hw")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("DR-001-", result.stderr)

    def test_a_stamp_at_the_current_stage_needs_no_decision_record(self) -> None:
        self.provisional_gate("layout", decision=None)
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        self.assertEqual(self.verify().returncode, 0)

    def test_a_decision_dated_after_the_stamp_passes_the_advance(self) -> None:
        self.provisional_gate("parts", decided=date(2026, 11, 20))
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        self.assertEqual(self.verify().returncode, 0)

    def test_a_stamp_without_a_complete_aware_timestamp_is_refused(self) -> None:
        for what, stamp in (("missing", None), ("garbled", "not-a-time"), ("date only", "2026-11-19"),
                            ("naive", "2026-11-19T10:00:00")):
            with self.subTest(what):
                self.provisional_gate("parts")
                self.assertEqual(self.stamp_gate("layout", timestamp=stamp).returncode, 0)
                result = self.verify()
                self.refused_gate(result)
                self.assertIn("timestamp", result.stderr)

    def test_the_stamp_day_is_its_utc_day(self) -> None:
        late = "2026-11-19T23:30:00-02:00"  # 2026-11-20 01:30 UTC
        self.provisional_gate("parts", decided=DAY)
        self.assertEqual(self.stamp_gate("layout", timestamp=late).returncode, 0)
        self.refused_gate(self.verify())
        self.provisional_gate("parts", decided=date(2026, 11, 20))
        self.assertEqual(self.stamp_gate("layout", timestamp=late).returncode, 0)
        self.assertEqual(self.verify().returncode, 0)

    def test_a_decisions_folder_without_a_decision_record_is_refused(self) -> None:
        self.provisional_gate("parts", decision=None)
        folder = self.root / "hw" / "decisions"
        folder.mkdir(exist_ok=True)
        (folder / "notes.txt").write_text("not a decision record\n", encoding="utf-8")
        (folder / "DR-001.txt").write_text("not a decision record either\n", encoding="utf-8")
        self.git("add", "hw")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        self.refused_gate(self.verify())

    def commit_gate(self, decision: str) -> None:
        """HEAD: flow.stage past the layout stamp, with one decision of status `decision`."""
        self.provisional_gate("parts", decision=decision)
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        self.git("commit", "-qm", f"gate with a {decision} decision")

    def restage_decision(self, decision: str) -> None:
        """The index: the decision at status `decision`, stamped again."""
        write_test_decision(self.root / "hw", "DR-001", status=decision, date=DAY)
        self.git("add", "hw")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)

    def test_the_committed_check_reaches_the_gate_decision_of_head(self) -> None:
        self.commit_gate("rejected")
        self.refused_gate(self.run_python(STAMP, "--verify", "--committed", cwd=self.root))

    def test_the_committed_check_takes_the_head_decision_not_the_index(self) -> None:
        self.commit_gate("rejected")
        self.restage_decision("accepted")
        self.refused_gate(self.run_python(STAMP, "--verify", "--committed", cwd=self.root))
        self.assertEqual(self.verify().returncode, 0)

    def test_the_staged_check_takes_the_index_decision_not_head(self) -> None:
        self.commit_gate("accepted")
        self.restage_decision("rejected")
        self.refused_gate(self.verify())
        self.assertEqual(self.run_python(STAMP, "--verify", "--committed", cwd=self.root).returncode, 0)

    def test_a_decision_only_in_the_work_tree_never_counts(self) -> None:
        self.commit_gate("rejected")
        (self.root / "hw" / "extra.txt").write_text("a staged change\n", encoding="utf-8")
        self.git("add", "hw/extra.txt")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        write_test_decision(self.root / "hw", "DR-001", status="accepted", date=DAY)  # in the work tree, not staged
        self.refused_gate(self.verify())
        self.refused_gate(self.run_python(STAMP, "--verify", "--committed", cwd=self.root))

    def without_profile(self) -> None:
        """product.yaml without flow.profile, as an old commit holds it."""
        path = self.root / "hw" / "product.yaml"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["flow"].pop("profile")
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    def test_verify_reads_the_profile_decision_from_the_index(self) -> None:
        hw = self.root / "hw"
        write_test_decision(hw, "DR-007", status="proposed")
        self.git("add", "hw")
        write_test_decision(hw, "DR-007", status="accepted")  # the work tree approves; the index does not
        result = self.verify()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("flow/profile/decision", result.stderr)
        self.assertIn("has status proposed", result.stderr)

    def test_verify_judges_the_profile_by_the_parts_of_the_index(self) -> None:
        no_fdm = {"processes": {}, "asked": {"human_approval": "user", "fea": "user", "stack_up": "user",
                                             "critique": "user", "storage_results_in_git": "user"}}
        add_flow_profile(self.root / "hw", **no_fdm)
        self.git("add", "hw")
        self.git("commit", "-qm", "a profile that asks no FDM question")
        record = json.loads((self.root / "hw/parts/PRT-0001/part.yaml").read_text(encoding="utf-8"))
        self.add_part_record({**record, "process": "fdm"})
        self.git("add", "hw")
        self.add_part_record(record)  # the work tree part is not FDM; the staged one is
        result = self.verify()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("processes/fdm", result.stderr)
        self.git("add", "hw")  # now the index holds the non-FDM part too
        self.assertEqual(self.verify().returncode, 0)

    def add_part_record(self, record: dict[str, Any]) -> None:
        (self.root / "hw/parts/PRT-0001/part.yaml").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")

    def test_committed_verify_reads_the_profile_of_head_and_refuses_when_head_lacks_it(self) -> None:
        self.without_profile()
        self.git("add", "hw")
        self.git("commit", "-qm", "a product without the project-start profile")
        add_flow_profile(self.root / "hw")
        self.git("add", "hw")
        self.assertEqual(self.verify().returncode, 0, "the index holds a settled profile")
        result = self.run_python(STAMP, "--verify", "--committed", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("flow/profile: flow.profile is missing", result.stderr)

    def test_a_stamp_two_stages_behind_flow_stage_is_refused(self) -> None:
        self.provisional_gate("detail")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.run_python(STAMP, "--verify", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match staged hw/product.yaml flow.stage", result.stderr)

    def test_a_stamp_below_recheck_from_is_refused(self) -> None:
        self.write_product("specify", "parts")
        self.git("add", "hw")
        self.git("commit", "-qm", "raise the threshold before the stage is due")
        self.provisional_gate("parts", "parts")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)
        result = self.run_python(STAMP, "--verify", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("is below flow.recheck_from parts", result.stderr)

    def test_a_fresh_committed_stamp_below_recheck_from_is_refused_in_committed_mode(self) -> None:
        self.write_product("specify", "parts")
        self.git("add", "hw")
        self.git("commit", "-qm", "raise the threshold before the stage is due")
        self.provisional_gate("parts", "parts")
        self.assertEqual(self.stamp_gate("layout").returncode, 0)  # the writer does not enforce the threshold
        self.git("commit", "-qm", "stage, stamp and threshold together")  # tree and record hashes now match
        result = self.run_python(STAMP, "--verify", "--committed", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("is below flow.recheck_from parts", result.stderr)

    def test_a_raised_threshold_of_a_project_below_the_repository_root_is_refused(self) -> None:
        project = self.move_project("examples/proj")
        product = project / "hw" / "product.yaml"
        data = json.loads(product.read_text(encoding="utf-8"))
        data["flow"] = {"stage": "specify", "recheck_from": "parts"}  # still below the raised threshold
        product.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        self.git("add", "examples/proj")
        result = self.run_python(STAMP, "--verify", "--hw", "examples/proj/hw", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("later than HEAD's layout", result.stderr)

    def test_a_failing_layout_check_blocks_the_stamp_and_the_commit(self) -> None:
        self.provisional_gate("parts")
        refused = self.stamp_gate("layout", outcome="fail")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("--passed contradicts the evidence packet", refused.stderr)
        self.assertEqual(self.stamp_gate("layout", outcome="fail", passed=False).returncode, 0)
        result = self.run_python(STAMP, "--verify", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("the recheck stamp does not say passed: true", result.stderr)

    def test_at_or_after_threshold_refuses_missing_stamp(self) -> None:
        self.stage_product("layout")
        self.git("add", "hw/product.yaml")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no staged hw/.cad/recheck.json", result.stderr)

    def test_matching_passing_stamp_is_accepted(self) -> None:
        self.stage_product("detail")
        stamp = self.stamp(passed=True, stage="detail")
        self.assertTrue(stamp["passed"])
        self.assertEqual(stamp["tree_hash"], self.staged_hash())
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_untracked_stray_is_refused_even_below_recheck_threshold(self) -> None:
        stray = self.root / "hw" / "parts" / "PRT-0001" / ".cad-work" / "generated.step"
        stray.parent.mkdir()
        stray.write_bytes(b"hidden generated payload")
        self.stage_product("design_freeze", "layout")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CAD layout has", result.stderr)

    def test_frozen_pre_freeze_stage_refuses_a_stray_file(self) -> None:
        product_path = self.root / "hw" / "product.yaml"
        version = self.root / "hw" / "versions" / "v1"
        version.mkdir(parents=True)
        version_files = {
            "assembly.step": "step\n",
            "assembly.glb": "glb\n",
            "part-map.json": "{}\n",
            "metrics.json": "{}\n",
            "parts/PRT-0001.step": "part\n",
        }
        for relative, content in version_files.items():
            target = version / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        manifest = {"label": "v1", "files": {key: hashlib.sha256((version / key).read_bytes()).hexdigest()
                                                  for key in version_files}}
        manifest_path = version / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        product_path.parent.mkdir(parents=True, exist_ok=True)
        frozen_product = {
            "id": "test-project", "units": "mm", "regime": "iso",
            "general_tolerance": "ISO 2768-m",
            "flow": {"stage": "specify", "recheck_from": "release", "frozen": {
                "version": "v1", "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "decision": "DR-001",
            }},
        }
        product_path.write_text(json.dumps(frozen_product), encoding="utf-8")
        stray = self.root / "hw" / "stray.md"
        stray.write_text("stray\n", encoding="utf-8")
        self.git("add", "hw/product.yaml", "hw/versions", "hw/stray.md")

        result = self.verify()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stray.md", result.stderr)

    def test_stamp_refuses_staged_stray_before_recording(self) -> None:
        self.stage_product("design_freeze", "layout")
        stray = self.root / "hw" / "parts" / "PRT-0001" / ".cad-work" / "generated.step"
        stray.parent.mkdir()
        stray.write_bytes(b"hidden generated payload")
        self.git("add", "hw/parts/PRT-0001/.cad-work/generated.step")
        checks = self.root / ".checks.json"
        checks.write_text(json.dumps({"all_passed": True, "checks": []}), encoding="utf-8")
        result = self.run_python(STAMP, "--stage", "design_freeze", "--checks", str(checks), "--passed", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CAD layout has", result.stderr)
        self.assertFalse((self.root / "hw" / ".cad" / "recheck.json").exists())

    def test_stamp_refuses_a_partial_changed_only_check(self) -> None:
        self.stage_product("detail")
        checks = self.root / ".checks.json"
        checks.write_text(json.dumps({"status": "pass", "scope": {"kind": "changed_pairs", "complete": False,
                                                                  "baseline": "v1"}, "checks": {}}), encoding="utf-8")
        result = self.run_python(STAMP, "--stage", "detail", "--checks", str(checks), "--passed", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("is a partial check (changed_pairs scope, complete: false); run the full check", result.stderr)
        self.assertFalse((self.root / "hw" / ".cad" / "recheck.json").exists())
        checks.write_text(json.dumps({"status": "pass", "scope": {"kind": "all_pairs", "complete": True}, "checks": {}}),
                          encoding="utf-8")
        result = self.run_python(STAMP, "--stage", "detail", "--checks", str(checks), "--passed", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("it is not an evidence packet", result.stderr, "a full cad-model check is not the evidence packet")
        self.assertTrue(self.stamp_with(self.evidence_packet("detail"))["passed"])

    def stamp_with(self, checks: Path, stage: str = "detail") -> dict[str, object]:
        result = self.run_python(STAMP, "--stage", stage, "--checks", str(checks), "--passed", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def stamp_refused(self, checks: Path, text: str, stage: str = "detail") -> None:
        result = self.run_python(STAMP, "--stage", stage, "--checks", str(checks), "--passed", cwd=self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(text, result.stderr)
        self.assertFalse((self.root / "hw" / ".cad" / "recheck.json").exists())

    def test_a_record_without_the_current_version_is_neither_stamped_nor_committed_at_the_threshold(self) -> None:
        checks = self.evidence_packet("detail")
        self.write_product("detail", "layout", legacy=True)
        self.git("add", "hw/product.yaml")
        self.stamp_refused(checks, "record.version_unsupported")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("record.version_unsupported", result.stderr)

    def test_a_due_unknown_check_cannot_be_stamped_passed(self) -> None:
        self.stage_product("detail")
        self.stamp_refused(self.evidence_packet("detail", outcome="unknown"), "--passed contradicts the evidence packet")

    def test_a_packet_of_another_record_or_stage_cannot_stamp(self) -> None:
        self.stage_product("detail")
        checks = self.evidence_packet("detail")
        self.add_part("PRT-0002")
        self.git("add", "hw/parts/PRT-0002/part.yaml")
        self.stamp_refused(checks, "computed from another record")
        self.stamp_refused(self.evidence_packet("parts"), "assessed for stage parts, not detail")

    def test_a_stamp_whose_evidence_blocks_is_refused_at_commit_even_if_edited_to_passed(self) -> None:
        self.stage_product("detail")
        self.stamp(passed=False, stage="detail", outcome="unknown")
        path = self.root / "hw" / ".cad" / "recheck.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["passed"] = True
        data["checks"]["gate"] = {"stage": "detail", "passed": True, "findings": []}
        path.write_text(json.dumps(data), encoding="utf-8")
        self.git("add", "hw/.cad/recheck.json")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("blocking finding", result.stderr)

    def test_the_recheck_threshold_may_move_earlier_but_never_later(self) -> None:
        self.stage_product("detail", "release")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("later than HEAD's layout", result.stderr)
        self.stage_product("specify", "intent")
        self.stage_product("ground", "intent")  # an earlier threshold is always allowed
        self.assertEqual(self.verify().returncode, 0, self.verify().stderr)

    def test_editing_staged_file_makes_stamp_stale(self) -> None:
        self.stage_product("detail")
        self.stamp(passed=True, stage="detail")
        self.add_part(title="Edited")
        self.git("add", "hw/parts/PRT-0001/part.yaml")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stamp is stale", result.stderr)

    def run_report(self, packet: Path | None, status: str = "pass") -> Path:
        """An `evidence.py run` report around the evidence packet in `packet` (null when the run stopped)."""
        report = {"kind": "cad-evidence-run", "schema_version": 1, "status": status, "scope": "commit", "stage": "detail",
                  "version": "v1", "version_manifest_sha256": None, "record_sha256": None, "steps": [],
                  "stopped_at": None if packet else "form",
                  "packet": json.loads(packet.read_text(encoding="utf-8")) if packet else None}
        path = self.root / ".run.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_the_packet_of_an_evidence_run_stamps_like_the_packet_check_prints(self) -> None:
        self.stage_product("detail")
        checks = self.evidence_packet("detail")
        stamp = self.stamp_with(self.run_report(checks))
        self.assertEqual(stamp["checks"], json.loads(checks.read_text(encoding="utf-8")))
        self.git("add", "hw/.cad/recheck.json")
        self.assertEqual(self.verify().returncode, 0)

    def test_an_evidence_run_that_stopped_has_no_packet_and_cannot_stamp(self) -> None:
        self.stage_product("detail")
        self.stamp_refused(self.run_report(None, status="fail"), "the evidence run stopped at form")

    def test_verify_passes_a_commit_that_stages_no_hw_change_and_checks_one_that_does(self) -> None:
        self.stage_product("release")
        self.git("commit", "-qm", "release stage")
        (self.root / "notes.md").write_text("notes\n", encoding="utf-8")
        self.git("add", "notes.md")
        verified = self.run_python(STAMP, "--verify", cwd=self.root)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout), {"passed": True, "required": False, "reason": "no staged hw/ change"})
        self.add_part(title="Staged edit")
        self.git("add", "hw/parts/PRT-0001/part.yaml")
        refused = self.run_python(STAMP, "--verify", cwd=self.root)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("no staged hw/.cad/recheck.json", refused.stderr)

    def test_passed_false_is_refused(self) -> None:
        self.stage_product("detail")
        stamp = self.stamp(passed=False, stage="detail")
        self.assertFalse(stamp["passed"])
        self.assertEqual(stamp["tree_hash"], self.staged_hash())
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not say passed: true", result.stderr)

    def move_project(self, subdirectory: str) -> Path:
        """Commit the project one level below the repository root, as an example project sits in examples/."""
        project = self.root / subdirectory
        project.mkdir(parents=True)
        self.git("mv", "hw", f"{subdirectory}/hw")
        self.git("commit", "-qm", "move the project")
        return project

    def stage_subdirectory_stamp(self, subdirectory: str) -> Path:
        """Stage a detail-stage product in the moved project and stamp it with --hw. Return the project."""
        project = self.move_project(subdirectory)
        (project / "hw" / "product.yaml").write_text(
            json.dumps({"record_version": 2, "id": "test-project", "flow": {"stage": "detail", "recheck_from": "layout"},
                        "use_case": acceptance.confirmed_use_case("appearance_concept")}, indent=1) + "\n", encoding="utf-8")
        self.add_profile("detail", project)
        self.git("add", subdirectory)
        checks = self.evidence_packet("detail", project=project)
        result = self.run_python(STAMP, "--hw", f"{subdirectory}/hw", "--stage", "detail", "--checks", str(checks), "--passed",
                                 cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.git("add", f"{subdirectory}/hw/.cad/recheck.json")
        return project

    def test_a_project_below_the_repository_root_stamps_and_verifies_with_hw(self) -> None:
        project = self.stage_subdirectory_stamp("examples/proj")
        self.assertTrue((project / "hw" / ".cad" / "recheck.json").is_file())
        self.assertFalse((self.root / "hw").exists())
        result = self.run_python(STAMP, "--verify", "--hw", "examples/proj/hw", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])

    def test_a_stale_stamp_of_a_project_below_the_repository_root_is_refused(self) -> None:
        project = self.stage_subdirectory_stamp("examples/proj")
        part = project / "hw" / "parts" / "PRT-0001" / "part.yaml"
        part.write_text(part.read_text(encoding="utf-8").replace("Fixture", "Edited"), encoding="utf-8")
        self.git("add", "examples/proj")
        result = self.run_python(STAMP, "--verify", "--hw", "examples/proj/hw", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("stamp is stale", result.stderr)

    def test_hw_must_name_the_hw_directory_not_the_project(self) -> None:
        self.stage_subdirectory_stamp("examples/proj")
        result = self.run_python(STAMP, "--verify", "--hw", "examples/proj", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--hw must name an hw directory", result.stderr)

    def test_verify_without_hw_reads_the_repository_root_from_a_nested_directory(self) -> None:
        self.stage_product("detail")
        self.stamp(passed=True, stage="detail")
        result = self.run_python(STAMP, "--verify", cwd=self.root / "hw" / "parts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])

    def staged_hash(self) -> str:
        entries = subprocess.run(
            ["git", "ls-files", "-s", "--", "hw/"],
            cwd=self.root,
            capture_output=True,
            check=True,
        ).stdout.splitlines(keepends=True)
        digest = hashlib.sha256()
        for entry in entries:
            _, separator, path = entry.partition(b"\t")
            if separator and not path.startswith(b"hw/.cad/"):
                digest.update(entry)
        return digest.hexdigest()


class CommittedFixtureTests(unittest.TestCase):
    """The committed verify project (tests/fixtures/verify-project) holds a record whose layout gate passes. Real
    build and evidence output stamped it. These tests run `stamp.py --verify --hw` on a scratch copy of it with
    every file staged. Staging matters: verify skips a project that has no staged hw/ change."""

    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "verify-project"
    HW = "verify-project/hw"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        # Copy what a checkout holds: the tracked files, not the build outputs a local run left beside them.
        listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=self.FIXTURE,
                                capture_output=True, check=True).stdout.decode().split("\0")
        for name in filter(None, listed):
            target = self.root / "verify-project" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.FIXTURE / name, target)
        self.git("init", "-q")
        self.git("add", "-A")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *args: str) -> None:
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, env=env)

    def verify(self, *options: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        return subprocess.run([sys.executable, str(STAMP), "--verify", *options, "--hw", self.HW], cwd=self.root, text=True,
                              capture_output=True, check=False, env=env)

    def commit(self) -> None:
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")

    def edit_part(self) -> None:
        part = self.root / self.HW / "parts" / "FXT-0001" / "part.yaml"
        part.write_text(part.read_text(encoding="utf-8").replace("title: Test block", "title: Test block (edited)", 1),
                        encoding="utf-8")
        self.git("add", "-A")

    def test_the_committed_stamp_verifies(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["passed"], True)
        self.assertNotIn("required", json.loads(result.stdout))  # a skipped verify would say required: false

    def test_a_staged_edit_of_a_record_input_makes_the_committed_stamp_stale(self) -> None:
        self.edit_part()
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn("stamp is stale", result.stderr)

    def test_verify_committed_checks_a_fresh_stamp_with_nothing_staged(self) -> None:
        self.commit()
        result = self.verify("--committed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["passed"], True)
        self.assertNotIn("required", json.loads(result.stdout))

    def test_verify_committed_refuses_a_stale_edit_that_was_committed(self) -> None:
        self.commit()
        self.edit_part()
        self.commit()
        result = self.verify("--committed")
        self.assertEqual(result.returncode, 2)
        self.assertIn("stamp is stale", result.stderr)

    def test_verify_committed_checks_head_not_the_index(self) -> None:
        self.commit()
        self.edit_part()  # staged, not committed: the index differs from HEAD
        result = self.verify("--committed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["passed"], True)

    def test_verify_committed_refuses_a_stamp_below_the_committed_threshold(self) -> None:
        self.commit()
        product = self.root / self.HW / "product.yaml"
        product.write_text(product.read_text(encoding="utf-8").replace("stage: layout\n  recheck_from: layout",
                                                                      "stage: parts\n  recheck_from: parts", 1), encoding="utf-8")
        self.git("add", "-A")
        self.commit()
        result = self.verify("--committed")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is below flow.recheck_from parts", result.stderr)

    def test_verify_without_committed_still_skips_when_nothing_is_staged(self) -> None:
        self.commit()
        self.edit_part()
        self.commit()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["required"], False)

    def test_committed_needs_verify(self) -> None:
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        result = subprocess.run([sys.executable, str(STAMP), "--committed", "--hw", self.HW, "--stage", "layout",
                                 "--checks", "x.json"], cwd=self.root, text=True, capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--committed needs --verify", result.stderr)


if __name__ == "__main__":
    unittest.main()
