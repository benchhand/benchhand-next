#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""FEA load cases that name the stop reaction they come from (fea_reaction.py, #153).

A load with `reaction: IF-###` is checked against the sealed stop-reaction bundle of the version before anything is
solved. These tests publish real bundles through cad-record's check_packet and layout and drive fea_static.main with
the solve stubbed to fail if it is ever reached. Kernel-free; test_fea_static.py has the FreeCAD and ccx cases.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))

import fea_reaction  # noqa: E402
import fea_static  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from reaction_project import EVIDENCE, INTERFACE, Scenario, bare_end, current_code, end, entry  # noqa: E402


class DesignReaction(unittest.TestCase):
    def test_a_load_below_the_design_reaction_is_refused_before_the_solve(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 343.1), "max": end("bounded", 120.0)})})
        report = scenario.refused("reaction_below_design")
        self.assertIn("50 N", report["error"]["message"])
        self.assertIn("343.1 N", report["error"]["message"])

    def test_a_load_at_or_above_the_design_reaction_proceeds_to_the_solve(self) -> None:
        for design in (50.0, 49.9999999999, 40.0):
            with self.subTest(design=design):
                scenario = Scenario(self)
                scenario.publish({INTERFACE: entry(ends={"min": end("bounded", design)})})
                status, report = scenario.call()
                self.assertEqual((status, report["status"]), (0, "pass"), report)

    def test_a_failing_bundle_still_carries_a_load_that_meets_its_design_reaction(self) -> None:
        # The recorded contact load (20 N) is below the 40 N design reaction, so stop_reaction reports a fail. The design
        # reaction itself is valid: the 50 N FEA case that closes the gap runs, with that reaction as its basis.
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("fail", {"min": end("understated", 40.0)}, recorded_contact_load_n=20.0)}, outcome="fail")
        status, report = scenario.call()
        self.assertEqual((status, report["status"], scenario.solves), (0, "pass", 1), report)
        manifest = json.loads((scenario.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["reactions"][INTERFACE]["design_reaction_n"], 40.0)

    def test_the_larger_of_two_stops_governs(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 30.0), "max": end("understated", 60.0)})})
        scenario.refused("reaction_below_design")

    def test_a_fast_mode_case_is_held_to_its_design_reaction_too(self) -> None:
        # The reaction check is a load check, not a stress check: fast mode, which reports no stress, keeps it.
        scenario = Scenario(self)
        scenario.case.write_text("mode: fast\n" + scenario.case.read_text(encoding="utf-8"), encoding="utf-8")
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 343.1)})})
        report = scenario.refused("reaction_below_design")
        self.assertIn("343.1 N", report["error"]["message"])

    def test_a_load_that_names_no_reaction_is_not_checked(self) -> None:
        scenario = Scenario(self)
        scenario.case.write_text(scenario.case.read_text(encoding="utf-8").replace("    reaction: IF-006\n", ""), encoding="utf-8")
        status, report = scenario.call()
        self.assertEqual((status, report["status"]), (0, "pass"), report)
        manifest = json.loads((scenario.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("reactions", manifest["recipe"], "a case without a reaction load keeps its recipe's shape")


class RefusedReactions(unittest.TestCase):
    def test_no_bundle_is_missing(self) -> None:
        report = Scenario(self).refused("reaction_missing")
        self.assertIn("stop_reaction.py", report["error"]["message"])

    def test_a_bundle_with_no_assessment_of_the_interface_is_missing(self) -> None:
        scenario = Scenario(self)
        scenario.publish({"IF-001": entry(ends={"min": end("bounded", 400.0)})})
        scenario.refused("reaction_missing")

    def test_a_bundle_of_another_build_of_the_version_is_stale(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})})
        manifest = json.loads((scenario.version / "manifest.json").read_text(encoding="utf-8"))
        (scenario.version / "manifest.json").write_text(json.dumps({**manifest, "rebuilt": True}), encoding="utf-8")
        report = scenario.refused("reaction_stale")
        self.assertIn("another build", report["error"]["message"])

    def test_a_bundle_that_fails_its_seal_is_stale(self) -> None:
        scenario = Scenario(self)
        bundle = scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})})
        (bundle / "evidence" / EVIDENCE).write_text('{"interfaces": {}}', encoding="utf-8")
        report = scenario.refused("reaction_stale")
        self.assertIn(f"stale: evidence/{EVIDENCE} changed after it was sealed", report["error"]["message"])

    def test_an_unbounded_stop_is_refused_even_when_the_other_stop_is_bounded(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("unknown", {"min": end("bounded", 40.0), "max": end("unbounded", None)})}, outcome="unknown")
        report = scenario.refused("reaction_unbounded")
        self.assertIn("max", report["error"]["message"])
        self.assertIn("design record", report["error"]["message"])

    def test_an_unknown_or_not_applicable_reaction_is_unknown(self) -> None:
        for outcome, reason in (("unknown", "the parts overlap by 0.18 mm at the max limit: a design defect, not a stop"),
                                ("not_applicable", "no movable joint connects the two parts")):
            with self.subTest(outcome=outcome):
                scenario = Scenario(self)
                scenario.publish({INTERFACE: entry(outcome, reason=reason)}, outcome=outcome)
                report = scenario.refused("reaction_unknown")
                self.assertIn(reason, report["error"]["message"])

    def test_a_standalone_case_cannot_name_a_reaction(self) -> None:
        scenario = Scenario(self)
        output = io.StringIO()
        with patch("fea_static.find_freecad", return_value=Path("/fake/freecadcmd")), \
             patch("fea_static.run_job", side_effect=AssertionError("refused before the solve")), patch("sys.stdout", output):
            status = fea_static.main([str(scenario.case)])
        self.assertEqual((status, json.loads(output.getvalue())["error"]["code"]), (2, "reaction_needs_version"))

    def test_a_reaction_must_name_an_interface(self) -> None:
        for bad in ("stop", "IF-6", "if-006", "IF-006 "):
            with self.subTest(reaction=bad):
                scenario = Scenario(self)
                scenario.case.write_text(scenario.case.read_text(encoding="utf-8").replace("reaction: IF-006", f"reaction: '{bad}'"),
                                         encoding="utf-8")
                self.assertIn("reaction", scenario.refused("invalid_case")["error"]["message"])


class RecipeCoversTheBundle(unittest.TestCase):
    def solved(self) -> Scenario:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})})
        self.assertEqual(scenario.call()[0], 0)
        return scenario

    def test_the_recipe_names_the_bundle_it_read(self) -> None:
        scenario = self.solved()
        manifest = json.loads((scenario.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        basis = manifest["recipe"]["reactions"][INTERFACE]
        bundle = scenario.hw / "checks" / "v1" / "stop-reaction"
        self.assertEqual(basis, {"bundle": "hw/checks/v1/stop-reaction", "design_reaction_n": 40.0,
                                 "manifest_sha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()})

    def test_an_unchanged_bundle_reuses_the_fea_result(self) -> None:
        scenario = self.solved()
        status, report = scenario.call()
        self.assertEqual((status, report["reused"], scenario.solves), (0, True, 1), "one solve in all, the first")

    def test_a_new_stop_reaction_result_needs_a_new_fea_run(self) -> None:
        scenario = self.solved()
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 45.0)})}, replace=True)
        status, report = scenario.call()
        self.assertEqual(status, 2)
        self.assertIn("--replace", report["error"]["message"])
        status, report = scenario.call(replace=True)
        self.assertEqual((status, report["reused"]), (0, False))
        manifest = json.loads((scenario.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["reactions"][INTERFACE]["design_reaction_n"], 45.0)


class NamedLimit(unittest.TestCase):
    """`limit: min | max` on a reaction load names the joint limit it reacts against."""

    def test_a_named_limit_uses_only_its_stop(self) -> None:
        # The latched stop (min) carries 40 N, the open stop (max) is unbounded. The 50 N load reacts against the latched stop.
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("unknown", {"min": end("bounded", 40.0), "max": end("unbounded", None)})}, outcome="unknown")
        scenario.name_limit("min")
        status, report = scenario.call()
        self.assertEqual((status, report["status"]), (0, "pass"), report)
        manifest = json.loads((scenario.hw / "analysis" / "v1" / "cantilever" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["recipe"]["reactions"][f"{INTERFACE}:min"]["design_reaction_n"], 40.0)

    def test_a_named_unbounded_limit_is_refused_as_unbounded(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("unknown", {"min": end("bounded", 40.0), "max": end("unbounded", None)})}, outcome="unknown")
        scenario.name_limit("max")
        self.assertIn("max", scenario.refused("reaction_unbounded")["error"]["message"])

    def test_each_named_limit_is_held_to_its_own_reaction(self) -> None:
        # min needs 60 N and max 30 N; the load is 50 N.
        for limit, code in (("max", None), ("min", "reaction_below_design")):
            with self.subTest(limit=limit):
                scenario = Scenario(self)
                scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 60.0), "max": end("bounded", 30.0)})})
                scenario.name_limit(limit)
                if code is None:
                    self.assertEqual(scenario.call()[0], 0)
                else:
                    scenario.refused(code)

    def test_an_absent_limit_takes_the_larger_of_the_two_stops(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 60.0), "max": end("bounded", 30.0)})})
        scenario.refused("reaction_below_design")

    def test_a_limit_the_bundle_has_no_stop_for_is_an_invalid_case(self) -> None:
        for name, ends in (("absent", {"min": end("bounded", 40.0)}),
                           ("not touching", {"min": end("bounded", 40.0), "max": bare_end(touching=False)})):
            with self.subTest(max=name):
                scenario = Scenario(self)
                scenario.publish({INTERFACE: entry(ends=ends)})
                scenario.name_limit("max")
                message = scenario.refused("invalid_case")["error"]["message"]
                self.assertIn("max", message)
                self.assertIn(INTERFACE, message)

    def test_a_named_stop_with_no_known_force_is_unknown_with_the_producers_reason(self) -> None:
        # The min limit touches but its force is unknown, so stop_reaction.py emits no reaction for it.
        reason = "IF-006 is a stop at the min limit of J1, but no load on it is recorded"
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("unknown", {"min": bare_end(), "max": bare_end(touching=False)}, reason=reason)},
                         outcome="unknown")
        scenario.name_limit("min")
        self.assertIn(reason, scenario.refused("reaction_unknown")["error"]["message"])

    def test_a_named_limit_of_an_interface_that_is_no_stop_is_unknown(self) -> None:
        reason = "IF-006: the parts are not in contact at either limit of J1: not a stop"
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry("not_applicable", {"min": bare_end(touching=False), "max": bare_end(touching=False)},
                                           reason=reason)}, outcome="not_applicable")
        scenario.name_limit("min")
        self.assertIn(reason, scenario.refused("reaction_unknown")["error"]["message"])

    def test_a_limit_is_min_or_max_and_needs_a_reaction(self) -> None:
        for edit in (lambda text: text.replace("    reaction: IF-006\n", "    reaction: IF-006\n    limit: left\n"),
                     lambda text: text.replace("    reaction: IF-006\n", "    limit: min\n")):
            with self.subTest():
                scenario = Scenario(self)
                scenario.case.write_text(edit(scenario.case.read_text(encoding="utf-8")), encoding="utf-8")
                self.assertIn("limit", scenario.refused("invalid_case")["error"]["message"])


class CodeFingerprint(unittest.TestCase):
    """A bundle made by other stop-reaction code than the code now in the tree is stale."""

    def test_a_bundle_made_by_other_code_is_stale(self) -> None:
        scenario = Scenario(self)
        other = {**current_code(), "cad-analysis/scripts/stop_reaction.py": "0" * 64}
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})}, code=other)
        message = scenario.refused("reaction_stale")["error"]["message"]
        self.assertIn("stop-reaction code changed", message)
        self.assertIn("stop_reaction.py", message)

    def test_a_bundle_that_records_no_code_is_stale(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})}, code=None)
        self.assertIn("no code fingerprint", scenario.refused("reaction_stale")["error"]["message"])

    def test_editing_stop_reaction_in_a_copied_tree_makes_its_bundle_stale(self) -> None:
        scenario = Scenario(self)
        scenario.publish({INTERFACE: entry(ends={"min": end("bounded", 40.0)})})
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / "skills"
            shutil.copytree(SKILLS, copy, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
            self.assertEqual(self.read_in(copy, scenario), {"design": 40.0})
            with (copy / "cad-analysis" / "scripts" / "stop_reaction.py").open("a", encoding="utf-8") as script:
                script.write("\n# edited\n")
            read = self.read_in(copy, scenario)
        self.assertEqual(read["code"], "reaction_stale")
        self.assertIn("stop-reaction code changed", read["message"])

    @staticmethod
    def read_in(copy: Path, scenario: Scenario) -> dict[str, object]:
        """fea_reaction.read, run from the tree at `copy`, on the scenario's version and bundle."""
        driver = (
            "import json, pathlib, sys\n"
            f"sys.path.insert(0, {str(copy / 'cad-analysis' / 'scripts')!r})\n"
            "import fea_reaction, fea_static\n"
            "try:\n"
            f"    basis = fea_reaction.read(fea_static.LAYOUT, pathlib.Path({str(scenario.hw)!r}), 'v1', pathlib.Path({str(scenario.version)!r}), 'IF-006')\n"
            "    print(json.dumps({'design': basis.design_n}))\n"
            "except fea_reaction.ReactionRefused as refusal:\n"
            "    print(json.dumps({'code': refusal.code, 'message': str(refusal)}))\n")
        done = subprocess.run([sys.executable, "-B", "-c", driver], capture_output=True, text=True, timeout=300, check=False)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)  # type: ignore[no-any-return]


class BundleNameMatchesTheProducer(unittest.TestCase):
    def test_a_bundle_the_producer_publishes_is_found_and_read(self) -> None:
        """stop_reaction.py publishes for a record that owes no stop-reaction check (the scenario's record has no stop). The
        reader finds that bundle and its evidence file: it reports the interface unassessed, not the bundle missing or unreadable."""
        import stop_reaction

        scenario = Scenario(self)
        with patch("sys.stdout", io.StringIO()):
            status = stop_reaction.main(["--hw", str(scenario.hw), "--version", "v1"])
        self.assertEqual(status, 0)
        with self.assertRaises(fea_reaction.ReactionRefused) as raised:
            fea_reaction.read(fea_static.LAYOUT, scenario.hw, "v1", scenario.version, INTERFACE)
        self.assertEqual(raised.exception.code, "reaction_missing")
        self.assertIn("holds no assessment of IF-006", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
