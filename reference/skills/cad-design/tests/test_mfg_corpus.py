#!/usr/bin/env python3
"""Tests for the mutation-corpus harness itself (mfg_corpus/): rate arithmetic, registry, the rates command.

Run: python3 -m unittest discover -s skills/cad-design/tests -p test_mfg_corpus.py
Pure standard library; the families' own checks run through mfg_corpus/rates.py.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "mfg_corpus"
sys.path.insert(0, str(CORPUS))
import corpus  # noqa: E402


def pair(ident: str, mutant: str, twin: str = "pass") -> corpus.Pair:
    return corpus.Pair(ident, "d", lambda is_mutant: mutant if is_mutant else twin)


def skipping(is_mutant: bool) -> str:
    raise corpus.Skip("no ocp")


def crashing(is_mutant: bool) -> str:
    raise RuntimeError("boom")


class RateTests(unittest.TestCase):
    def rows(self, *pairs: corpus.Pair) -> dict:
        return corpus.evaluate([corpus.Family("f", "chk", tuple(pairs))])[0]

    def test_rates_are_counted_per_variant(self) -> None:
        row = self.rows(pair("a", "fail"), pair("b", "fail"), pair("c", "unknown"), pair("d", "pass", "fail"))
        self.assertEqual((row["detection_rate"], row["abstention_rate"], row["false_positive_rate"]), (0.5, 0.25, 0.25))
        self.assertEqual((row["detected"], row["abstained"], row["missed"], row["false_positives"]), (2, 1, 1, 1))

    def test_skipped_pairs_leave_the_rates_and_are_counted(self) -> None:
        row = self.rows(pair("a", "fail"), corpus.Pair("b", "d", skipping))
        self.assertEqual((row["pairs"], row["ran"], row["skipped"], row["detection_rate"]), (2, 1, 1, 1.0))

    def test_a_crashing_check_is_a_miss_not_a_detection(self) -> None:
        row = self.rows(corpus.Pair("a", "d", crashing))
        self.assertEqual((row["errors"], row["detected"], row["missed"], row["detection_rate"]), (1, 0, 1, 0.0))
        self.assertIn("boom", row["results"][0]["error"])

    def test_a_twin_crash_voids_the_mutant_verdict_too(self) -> None:
        def run(is_mutant: bool) -> str:
            if is_mutant:
                return "fail"
            raise RuntimeError("twin boom")

        row = self.rows(corpus.Pair("a", "d", run))
        self.assertEqual((row["errors"], row["detected"], row["missed"], row["detection_rate"]), (1, 0, 1, 0.0))
        self.assertIn("twin boom", row["results"][0]["error"])
        self.assertIsNone(row["results"][0]["mutant"])

    def test_a_rejected_packet_is_a_miss_with_its_reason_not_a_detection(self) -> None:
        def refused(is_mutant: bool) -> str:
            raise corpus.Rejected("packet.invalid: it gives an obligation two outcomes")

        row = self.rows(corpus.Pair("a", "d", refused), pair("b", "fail"))
        self.assertEqual((row["rejected"], row["errors"], row["detected"], row["missed"]), (1, 0, 1, 1))
        self.assertIn("two outcomes", row["results"][0]["rejected"])

    def test_a_known_gap_is_a_miss_whatever_the_mutant_returns_and_its_twin_still_counts(self) -> None:
        row = self.rows(corpus.Pair("a", "d", lambda m: "fail", known_gap="fails for the wrong reason"),
                        corpus.Pair("b", "d", lambda m: "unknown" if m else "pass", known_gap="abstains for the wrong reason"),
                        pair("c", "fail"))
        self.assertEqual((row["ran"], row["detected"], row["abstained"], row["missed"], row["known_gaps"]), (3, 1, 0, 2, 2))
        self.assertEqual((row["detection_rate"], row["false_positive_rate"]), (0.3333, 0.3333))
        self.assertEqual(row["results"][0]["known_gap"], "fails for the wrong reason")

    def test_a_family_with_nothing_run_has_no_rate(self) -> None:
        row = self.rows(corpus.Pair("a", "d", skipping))
        self.assertIsNone(row["detection_rate"])

    def test_an_unknown_outcome_word_is_an_error(self) -> None:
        self.assertEqual(self.rows(pair("a", "maybe"))["errors"], 1)


class RegistryTests(unittest.TestCase):
    def test_duplicate_family_ids_and_pair_ids_are_rejected(self) -> None:
        one = corpus.Family("f", "c", (pair("a", "fail"),))
        with self.assertRaises(ValueError):
            corpus.validate([one, one])
        with self.assertRaises(ValueError):
            corpus.validate([corpus.Family("g", "c", (pair("a", "fail"), pair("a", "fail")))])

    def test_a_family_module_dropped_in_the_directory_is_registered_and_underscore_files_are_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mine.py").write_text(
                "from corpus import Family, Pair\nFAMILY = Family('mine', 'c', (Pair('p', 'd', lambda m: 'fail' if m else 'pass'),))\n")
            (Path(tmp) / "_skip.py").write_text("raise SystemExit('must not load')\n")
            self.assertEqual([f.id for f in corpus.load_families(Path(tmp))], ["mine"])

    def test_the_shipped_registry_loads_with_unique_ids(self) -> None:
        corpus.load_families()


def write_family(directory: Path, name: str, mutant: str = "fail", twin: str = "pass", known_gap: str | None = None) -> None:
    (directory / f"{name}.py").write_text(
        "from corpus import Family, Pair\n"
        f"FAMILY = Family('{name}', 'c', (Pair('p', 'd', lambda m: '{mutant}' if m else '{twin}', known_gap={known_gap!r}),))\n")


def write_baseline(directory: Path, name: str, detection: float = 1.0, false_positive: float = 0.0, ran: int = 1) -> None:
    (directory / f"{name}.json").write_text(json.dumps(
        {"detection_rate": detection, "abstention_rate": 0.0, "false_positive_rate": false_positive, "ran": ran}))


class BaselineTests(unittest.TestCase):
    """corpus.check_baseline: the registry and baseline/ match one-to-one and no family regresses."""

    def problems(self, families: list[corpus.Family], baselines: dict[str, dict]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            for name, kwargs in baselines.items():
                write_baseline(Path(tmp), name, **kwargs)
            return corpus.check_baseline(corpus.evaluate(families), Path(tmp))

    def family(self, name: str, *pairs: corpus.Pair) -> corpus.Family:
        return corpus.Family(name, "c", pairs or (pair("a", "fail"),))

    def test_matching_baselines_have_no_problem(self) -> None:
        self.assertEqual(self.problems([self.family("f")], {"f": {}}), [])

    def test_a_family_without_a_baseline_file_is_a_problem(self) -> None:
        self.assertEqual(self.problems([self.family("f"), self.family("g")], {"f": {}}),
                         ["g: no baseline file baseline/g.json"])

    def test_a_restricted_run_still_needs_a_baseline_for_each_family_it_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_baseline(Path(tmp), "f")
            rows = corpus.evaluate([self.family("g")])
            self.assertEqual(corpus.check_baseline(rows, Path(tmp), whole_registry=False),
                             ["g: no baseline file baseline/g.json"])

    def test_a_restricted_run_ignores_baselines_of_families_it_did_not_evaluate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("f", "other"):
                write_baseline(Path(tmp), name)
            rows = corpus.evaluate([self.family("f")])
            self.assertEqual(corpus.check_baseline(rows, Path(tmp), whole_registry=False), [])

    def test_a_baseline_file_without_a_family_is_a_problem(self) -> None:
        self.assertEqual(self.problems([self.family("f")], {"f": {}, "gone": {}}),
                         ["gone: baseline file without a registered family"])

    def test_fewer_pairs_run_than_recorded_is_a_problem(self) -> None:
        skipped = corpus.Pair("b", "d", skipping)
        [problem] = self.problems([self.family("f", pair("a", "fail"), skipped)], {"f": {"ran": 2}})
        self.assertEqual(problem, "f: ran 1 pairs, baseline 2 (1 skipped)")

    def test_lower_detection_and_higher_false_positives_are_problems(self) -> None:
        problems = self.problems([self.family("f", pair("a", "pass", "fail"))], {"f": {}})
        self.assertEqual(problems, ["f: detection 0.0 below baseline 1.0", "f: false positives 1.0 above baseline 0.0"])

    def test_a_family_that_beats_its_baseline_is_fine(self) -> None:
        self.assertEqual(self.problems([self.family("f")], {"f": {"detection": 0.5, "false_positive": 0.5}}), [])


class RatchetTests(unittest.TestCase):
    """The shipped families against baseline/, run as rates.py --check-baseline in its own uv script environment
    (it carries OCP, which the test interpreter may lack). Under CI=true a missing uv fails instead of skipping.
    MFG_CORPUS_RATCHET_IN_CI_STEP=1 (set on the rest shard) skips it there: the freecad-gated shard's
    "Mutation corpus rates and baseline ratchet" step enforces the same check."""

    def test_no_family_regresses_from_its_baseline(self) -> None:
        if os.environ.get("MFG_CORPUS_RATCHET_IN_CI_STEP") == "1":
            self.skipTest("enforced by the freecad-gated shard's 'Mutation corpus rates and baseline ratchet' CI step")
        if shutil.which("uv") is None:
            if os.environ.get("CI") == "true":
                self.fail("uv is required for the corpus ratchet in CI")
            self.skipTest("uv is required to run rates.py in its own environment")
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(["uv", "run", "--script", str(CORPUS / "rates.py"), "--check-baseline", "--out",
                                   str(Path(tmp) / "r.json")], capture_output=True, text=True, check=False, timeout=1800)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class RatchetGuardTests(unittest.TestCase):
    """RatchetTests with uv unavailable: it fails under CI=true, and skips there only for the dedupe marker."""

    METHOD = "test_no_family_regresses_from_its_baseline"
    MARKER = "MFG_CORPUS_RATCHET_IN_CI_STEP"

    def outcome(self, **env: str) -> unittest.TestResult:
        """Run the ratchet test. Hide uv from PATH, apply `env`, and remove the marker unless `env` has it."""
        result = unittest.TestResult()
        with mock.patch.dict(os.environ, env), mock.patch("shutil.which", return_value=None):
            if self.MARKER not in env:
                os.environ.pop(self.MARKER, None)
            RatchetTests(self.METHOD).run(result)
        return result

    def test_in_ci_without_uv_and_without_the_marker_it_fails_and_does_not_skip(self) -> None:
        result = self.outcome(CI="true")
        self.assertEqual((len(result.failures), result.skipped, result.errors), (1, [], []))
        self.assertIn("uv is required", result.failures[0][1])

    def test_only_the_marker_value_1_skips_it_and_the_reason_names_the_ci_step(self) -> None:
        skipped = self.outcome(CI="true", **{self.MARKER: "1"})
        [(_, reason)] = skipped.skipped
        self.assertIn("Mutation corpus rates and baseline ratchet", reason)
        self.assertEqual((skipped.failures, skipped.errors), ([], []))
        for value in ("", "0", "true", "yes"):
            with self.subTest(marker=value):
                result = self.outcome(CI="true", **{self.MARKER: value})
                self.assertEqual((len(result.failures), result.skipped), (1, []))

    def test_outside_ci_without_uv_it_skips_for_the_missing_tool(self) -> None:
        result = self.outcome(CI="")
        [(_, reason)] = result.skipped
        self.assertIn("uv is required", reason)
        self.assertEqual((result.failures, result.errors), ([], []))


DEPS = importlib.util.find_spec("yaml") is not None and importlib.util.find_spec("jsonschema") is not None


@unittest.skipUnless(DEPS, "pyyaml and jsonschema are required")
class ProfileTests(unittest.TestCase):
    def test_the_test_profile_is_a_valid_record_with_the_calibrations_the_additive_checks_read(self) -> None:
        import capability_profile

        sys.path.insert(0, str(CORPUS.parents[1] / "scripts"))
        import process_checks

        fx_path = CORPUS.parents[2] / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py"
        spec = importlib.util.spec_from_file_location("mfg_corpus_fx", fx_path)
        assert spec and spec.loader
        fx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fx)
        documents = fx.record(capabilities=capability_profile.capabilities(), materials=capability_profile.materials())
        with tempfile.TemporaryDirectory() as tmp:
            hw = fx.write_record(Path(tmp) / "project" / "hw", documents)
            _, problems = process_checks.intent().check_record(hw)
        self.assertEqual([p.code for p in problems if p.severity == "error"], [])
        found = {c["characteristic"] for c in capability_profile.capabilities()[0]["calibrations"]}
        self.assertEqual(found, {"overhang_angle", "bridge_span", "min_wall", "min_feature", "min_bed_contact_area"})


INNER_CHECKS = frozenset({"check_order", "check_joints", "check_version", "check_record", "assess", "probe",
                          "assess_printed", "access_outcomes", "load"})  # inner check functions, and the old helpers that called them
ALLOWED_IMPORTS = frozenset({"corpus", "support", "doc_support", "OCP"})


def inner_check_uses(directory: Path) -> list[str]:
    """Where a family module imports or calls a check below the packet: a check function by name, subprocess (a check script
    run for its own report), or any module that is neither the standard library nor the corpus helpers. Families take
    their verdicts from support.py / doc_support.py, which run the real path to the packet and evidence."""
    import ast

    found = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)):
                continue
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
                found += [f"{path.name}:{node.lineno} imports {alias.name}" for alias in node.names if alias.name in INNER_CHECKS]
            found += [f"{path.name}:{node.lineno} imports {root}" for root in roots
                      if root == "subprocess" or (root not in sys.stdlib_module_names and root not in ALLOWED_IMPORTS)]
            if isinstance(node, ast.Call):
                callee = node.func
                name = callee.id if isinstance(callee, ast.Name) else callee.attr if isinstance(callee, ast.Attribute) else ""
                if name in INNER_CHECKS:
                    found.append(f"{path.name}:{node.lineno} calls {name}")
    return found


class PacketVerdictGuardTests(unittest.TestCase):
    """A verdict is what the packet and evidence conclude, so a family may not run an inner check itself."""

    def test_no_shipped_family_imports_or_calls_a_check_below_the_packet(self) -> None:
        self.assertEqual(inner_check_uses(corpus.FAMILIES_DIR), [])

    def test_the_guard_names_a_family_that_calls_the_check_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "import subprocess\nfrom support import check_order, verdict\n\n"
                "def run(mutant):\n    return verdict(check_order([]).values())\n", encoding="utf-8")
            self.assertEqual(inner_check_uses(Path(tmp)), ["bad.py:1 imports subprocess", "bad.py:2 imports check_order",
                                                          "bad.py:5 calls check_order"])


@unittest.skipUnless(DEPS, "pyyaml and jsonschema are required")
class PacketRefusalTests(unittest.TestCase):
    """A packet that the schema or evidence refuses is a miss with its reason, never a verdict."""

    @classmethod
    def setUpClass(cls) -> None:
        import support

        cls.support = support
        cls.record, pc = support.printed_record()
        # with no geometry the checks give every obligation the outcome unknown, so the packet result reads unknown
        cls.packet = pc.assess(cls.record, {}, today=support.TODAY).packet({"version_manifest": "0" * 64, "producer_code": "0" * 64})

    def pair_result(self, packet: dict) -> corpus.PairResult:
        def run(is_mutant: bool) -> str:
            return self.support.release_verdict(self.record, packet, "process.fdm.", today=self.support.TODAY)

        return corpus.run_pair(corpus.Pair("p", "d", run))

    def test_a_schema_invalid_packet_is_rejected_with_the_schema_reason(self) -> None:
        result = self.pair_result({"schema_version": 1})
        self.assertIsNone(result.error)
        self.assertTrue((result.rejected or "").startswith("schema: packet does not match manufacturing-check-result.schema.json"),
                        result.rejected)

    def test_a_schema_valid_packet_that_contradicts_its_outcomes_is_rejected_with_the_evidence_reason(self) -> None:
        self.assertEqual(self.packet["result"], "unknown")
        lying = {**self.packet, "result": "pass"}
        result = self.pair_result(lying)
        self.assertIsNone(result.error)
        self.assertIn("evidence: ", result.rejected or "")
        self.assertIn("its result 'pass' is not what its outcomes show (unknown)", result.rejected or "")

    def test_a_rejected_packet_is_a_miss_in_the_family_row_never_a_detection(self) -> None:
        def run(is_mutant: bool) -> str:
            return self.support.release_verdict(self.record, {"schema_version": 1}, "process.fdm.")

        row = corpus.evaluate([corpus.Family("f", "c", (corpus.Pair("p", "d", run),))])[0]
        self.assertEqual((row["ran"], row["rejected"], row["errors"], row["detected"], row["abstained"], row["missed"]),
                         (1, 1, 0, 0, 0, 1))


@unittest.skipUnless(DEPS and shutil.which("uv"), "pyyaml, jsonschema and uv are required")
class NativeExitCodeTests(unittest.TestCase):
    """cad_model documents exit 0 and 1 (and 2 for usage). A build or check killed by a signal is a harness error, not an abstention."""

    def verdict_row(self, run_code: int, check_code: int, manifest: bool) -> dict:
        import support

        def fake(argv: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            step = argv[5]  # uv run --quiet --script <cad_model.py> <step> ...
            if step == "run":
                if manifest:
                    target = Path(argv[6]) / "versions" / "v1" / "manifest.json"
                    target.parent.mkdir(parents=True)
                    target.write_text("{}", encoding="utf-8")
                return subprocess.CompletedProcess(argv, run_code, "", "")
            return subprocess.CompletedProcess(argv, check_code, "", "")

        def run(is_mutant: bool) -> str:
            return support.readback_verdict("KERNEL = 'cadquery'\nPARAMS = {}\n")

        with mock.patch("subprocess.run", fake):
            return corpus.evaluate([corpus.Family("f", "c", (corpus.Pair("p", "d", run),))])[0]

    def test_a_build_killed_by_a_signal_is_an_error_and_a_miss_not_an_abstention(self) -> None:
        row = self.verdict_row(-9, 0, manifest=False)
        self.assertEqual((row["errors"], row["abstained"], row["missed"]), (1, 0, 1))
        self.assertIn("cad_model run exited -9", row["results"][0]["error"])

    def test_a_check_killed_by_a_signal_is_an_error_and_a_miss_not_an_abstention(self) -> None:
        row = self.verdict_row(0, -9, manifest=True)
        self.assertEqual((row["errors"], row["abstained"], row["missed"]), (1, 0, 1))
        self.assertIn("cad_model check exited -9", row["results"][0]["error"])

    def test_a_build_that_refuses_the_part_with_exit_1_and_no_version_is_unevidenced_not_an_error(self) -> None:
        row = self.verdict_row(1, 0, manifest=False)
        self.assertEqual((row["errors"], row["abstained"], row["results"][0]["mutant"]), (0, 1, "unknown"))


class DependencyGuardTests(unittest.TestCase):
    """A family whose tool is absent skips its pairs: neither an error nor a verdict."""

    NEEDS = {"yaml": {"assembly_operations_order", "access_assembly", "additive_min_feature", "additive_stability",
                      "additive_support_overhang_bridge", "stability_contact_hull"},
             "OCP": {"additive_min_feature", "additive_stability", "additive_support_overhang_bridge",
                     "stability_contact_hull"}}

    def test_pairs_skip_when_their_module_is_absent(self) -> None:
        """Absent for real: find_spec says so and `import <module>` raises ImportError, with any cached submodule gone."""
        real = importlib.util.find_spec
        families = {f.id: f for f in corpus.load_families()}
        for module, needing in self.NEEDS.items():
            hidden = {name: None for name in list(sys.modules) if name == module or name.startswith(module + ".")}
            with mock.patch("importlib.util.find_spec", lambda name, *a, _m=module: None if name == _m else real(name, *a)), \
                    mock.patch.dict(sys.modules, {**hidden, module: None}):
                for family in sorted(needing):
                    for item in families[family].pairs:
                        with self.subTest(module=module, family=family, pair=item.id):
                            result = corpus.run_pair(item)
                            self.assertEqual((result.skipped is not None, result.error), (True, None))


class CommandTests(unittest.TestCase):
    def run_rates(self, tmp: str, *args: str, families: tuple[str, ...] = ("alpha", "beta")) -> subprocess.CompletedProcess[str]:
        directory = Path(tmp) / "families"
        directory.mkdir(exist_ok=True)
        for name in families:
            write_family(directory, name)
        return subprocess.run([sys.executable, str(CORPUS / "rates.py"), "--families-dir", str(directory), "--out",
                               str(Path(tmp) / "r.json"), *args], capture_output=True, text=True, check=False)

    def test_a_known_gap_pair_is_listed_on_the_console_and_counted_as_a_miss_in_the_report(self) -> None:
        why = "fails because the span is measured along the roof"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "families"
            directory.mkdir()
            write_family(directory, "alpha", known_gap=why)
            write_family(directory, "beta")
            out = Path(tmp) / "r.json"
            done = subprocess.run([sys.executable, str(CORPUS / "rates.py"), "--families-dir", str(directory), "--out", str(out)],
                                  capture_output=True, text=True, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([line for line in done.stdout.splitlines() if line.startswith("known gap:")],
                             [f"known gap: alpha/p: {why}"])
            alpha, beta = json.loads(out.read_text())["families"]
        self.assertEqual((alpha["ran"], alpha["detected"], alpha["missed"], alpha["known_gaps"], alpha["detection_rate"]),
                         (1, 0, 1, 1, 0.0))
        self.assertEqual((alpha["results"][0]["mutant"], alpha["results"][0]["known_gap"]), ("fail", why))
        self.assertEqual((beta["detected"], beta["known_gaps"]), (1, 0))

    def test_the_rate_command_writes_json_and_prints_its_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.json"
            done = self.run_rates(tmp)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn(f"report: {out}", done.stdout)
            data = json.loads(out.read_text())
            self.assertEqual(data["format"], 1)
            self.assertEqual([f["family"] for f in data["families"]], ["alpha", "beta"])

    def test_repeated_family_options_restrict_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_rates(tmp, "--family", "beta", "--family", "gamma", families=("alpha", "beta", "gamma"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([f["family"] for f in json.loads((Path(tmp) / "r.json").read_text())["families"]],
                             ["beta", "gamma"])

    def test_an_unknown_family_id_exits_non_zero_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_rates(tmp, "--family", "alpha", "--family", "nope")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("unknown family: nope", done.stderr)
            self.assertFalse((Path(tmp) / "r.json").exists())

    def test_check_baseline_exits_one_and_names_the_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baselines = Path(tmp) / "baseline"
            baselines.mkdir()
            write_baseline(baselines, "alpha")
            done = self.run_rates(tmp, "--check-baseline", "--baseline-dir", str(baselines))
            self.assertEqual(done.returncode, 1)
            self.assertIn("baseline: beta: no baseline file", done.stdout)

    def test_check_baseline_on_a_restricted_run_needs_that_familys_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baselines = Path(tmp) / "baseline"
            baselines.mkdir()
            write_baseline(baselines, "alpha")
            done = self.run_rates(tmp, "--family", "beta", "--check-baseline", "--baseline-dir", str(baselines))
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertIn("baseline: beta: no baseline file", done.stdout)

    def test_check_baseline_on_a_restricted_run_ignores_other_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baselines = Path(tmp) / "baseline"
            baselines.mkdir()
            write_baseline(baselines, "alpha")
            done = self.run_rates(tmp, "--family", "alpha", "--check-baseline", "--baseline-dir", str(baselines))
            self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
