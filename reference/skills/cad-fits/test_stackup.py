#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Stack-up tests against an independent hand calculation, and the intent (version 2) stack rules."""

from __future__ import annotations

import contextlib
import copy
from datetime import date
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "scripts" / "stackup.py"
SPEC = importlib.util.spec_from_file_location("cad_stackup", SCRIPT)
assert SPEC and SPEC.loader
stackup = importlib.util.module_from_spec(SPEC)
sys.modules["cad_stackup"] = stackup
SPEC.loader.exec_module(stackup)

FIXTURES = HERE / "tests" / "fixtures"
_FX_SPEC = importlib.util.spec_from_file_location(
    "cad_record_mi_fixtures", HERE.parent / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
assert _FX_SPEC and _FX_SPEC.loader
fx = sys.modules.get("cad_record_mi_fixtures") or importlib.util.module_from_spec(_FX_SPEC)
if "cad_record_mi_fixtures" not in sys.modules:
    sys.modules["cad_record_mi_fixtures"] = fx
    _FX_SPEC.loader.exec_module(fx)
intent = fx.intent_module()
ON = date(2026, 6, 1)

def fixture(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def contributor(stack: dict, ident: str) -> dict:
    return next(c for c in stack["contributors"] if c["id"] == ident)


def codes(result: dict) -> list[str]:
    return sorted(f["code"] for f in result["findings"])


def closing_gap_documents(*, method: str = "worst_case", relevant: tuple[str, ...] = ("manufacture", "coating", "thermal")) -> dict:
    """tst_record with IF-001's stack declared as case closing-gap and a coated spacer shoulder."""
    documents = fx.tst_record()
    functional = documents["interfaces.yaml"]["interfaces"][0]["functional"]
    functional["variation"] = {"stack_case": "closing-gap", "contributors": list(relevant), "method": method}
    if method == "justified_rss":
        functional["variation"]["decision"] = "DR-001"
    shaft = documents["parts/TST-0002/part.yaml"]
    shaft["intent"]["route"].append(fx.operation("coat", "coating", targets=[{"feature": "shoulder_length"}]))
    return documents


def tab_slot_documents() -> dict:
    """Two laser-cut, powder-coated steel plates joined by a critical tab-and-slot interface IF-002."""
    def plate(pn: str, title: str, feature: str) -> dict:
        return fx.part(pn, title, process="laser", material="TST steel sheet", part_intent=fx.intent(
            functions=[{"function": "locating"}], material_profile="tst_steel_sheet",
            critical_surfaces=fx.not_applicable("the stack covers the fit"),
            route=[fx.operation("cut", "laser", "tst_laser"),
                   fx.operation("coat", "coating", targets=[{"feature": feature}])]))

    laser = fx.capability_profile(
        "tst_laser", "laser",
        materials=[{"material": "tst_steel_sheet", "status": "approved", "thickness": fx.known(fx.quantity(3)),
                    "extraction": fx.known("TST extraction"), "operations": ["cut"], "source": fx.source("user")}],
        calibrations=[fx.calibration("tst_slot_coupon", "slot_width_deviation", "tst_steel_sheet",
                                     fx.quantity(lower=-0.05, upper=0.05))])
    interface = fx.interface("IF-002", "TST-0011", "TST-0012", "mounting", functional={
        "critical": fx.known(True), "functions": [{"function": "locating"}],
        "variation": {"stack_case": "tab-slot", "contributors": ["manufacture", "coating"], "method": "worst_case"}})
    return fx.record(parts=[plate("TST-0011", "Slot plate", "slot"), plate("TST-0012", "Tab plate", "tab")],
                     interfaces=[interface], capabilities=[laser],
                     materials=[fx.material_profile("tst_steel_sheet", level="family", form="sheet")])


def write_case(hw: Path, case: str, stack: dict) -> Path:
    path = hw / "analysis" / "cases" / case / "case.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(stack, sort_keys=False), encoding="utf-8")
    return path


def snapshot_version(hw: Path, label: str = "v1") -> str:
    """Seal hw's record documents and frozen sources as the record snapshot of built version `label`;
    the sha256 of its manifest."""
    version = hw / "versions" / label
    record = version / "record"
    for source in hw.rglob("*"):
        rel = source.relative_to(hw)
        if source.is_file() and rel.parts[0] not in ("versions", "analysis", "decisions") \
                and rel.suffix == ".yaml" or (source.is_file() and rel.parts[:2] == ("manufacturing", "sources")):
            target = record / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    files = {path.relative_to(version).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in version.rglob("*") if path.is_file()}
    manifest = version / "manifest.json"
    manifest.write_text(json.dumps({"label": label, "files": files}), encoding="utf-8")
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def evidence_module() -> object:
    """cad-record evidence.py, the one reader of producer check packets."""
    name = "cad_record_evidence"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE.parent / "cad-record" / "scripts" / "evidence.py")
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


def check_result_validator():
    """A validator of cad-record manufacturing-check-result.schema.json, the packet contract, offline."""
    return fx.ref_validator("https://srobroek.com/cad/schemas/manufacturing-check-result.schema.json")


class IntentStackContractTests(unittest.TestCase):
    """Intent stacks: worst case governs, unknown never passes, refused inputs (plan section 11 rows 10 and 14)."""

    def assert_schema_valid(self, result: dict) -> None:
        for finding in result["findings"]:
            errors = list(stackup._validator("finding").iter_errors(finding))
            self.assertEqual(errors, [], finding["id"])
        for row in result["obligations"]:
            self.assertEqual(list(stackup._validator("obligation_outcome").iter_errors(row)), [], row)

    def bound(self, documents: dict, stack: dict, case: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            hw = fx.write_record(Path(directory) / "project" / "hw", documents)
            write_case(hw, case, stack)
            record = intent.load_record(hw)
            result = stackup.compute(stack, record, case=case, on=ON, decisions=frozenset({"DR-001"}))
        self.assert_schema_valid(result)
        return result

    # ---- row 14: nominal clearance fails the stack

    def test_nominal_closing_gap_fails_the_worst_case_stack(self) -> None:
        result = self.bound(closing_gap_documents(), fixture("closing_gap.yaml"), "closing-gap")
        self.assertAlmostEqual(result["remaining"]["nominal"], 0.20, places=6)
        self.assertAlmostEqual(result["remaining"]["after_tolerances"]["min"], -0.10, places=6)
        self.assertAlmostEqual(result["worst_case"]["max"], 0.50, places=6)
        self.assertTrue(result["requirement"]["nominal_pass"])
        self.assertFalse(result["requirement"]["worst_case_pass"])
        self.assertEqual(result["requirement"]["governing"], "worst_case")
        self.assertEqual(result["outcome"], "fail")
        self.assertTrue(result["critical"])
        self.assertEqual(codes(result), ["stack.worst_case_violation"])
        violation = result["findings"][0]
        self.assertEqual(violation["severity"], "critical")
        self.assertEqual(violation["measured"], {"lower": -0.1, "upper": 0.5, "units": "mm"})
        self.assertIn("nominal 0.2 mm meets the requirement", violation["consequence"])
        self.assertEqual(result["obligations"][0]["obligation"], "interface.stack@IF-001")
        self.assertEqual(result["obligations"][0]["outcome"], "fail")
        qualifications = {row["id"]: row["qualification"] for row in result["contributors"]}
        self.assertEqual(qualifications, {"H": "inspection", "B": "source:datasheet", "S": "source:supplier",
                                          "C": "source:datasheet", "T": "source:calculation"})

    def test_unjustified_governing_rss_refuses_critical_acceptance(self) -> None:
        stack = fixture("closing_gap.yaml")
        stack["requirement"]["method"] = "justified_rss"
        result = self.bound(closing_gap_documents(method="justified_rss"), stack, "closing-gap")
        self.assertEqual(result["statistical"]["status"], "refused")
        self.assertEqual(result["requirement"]["governing"], "worst_case")
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("stack.rss_refused", codes(result))
        refused = next(f for f in result["findings"] if f["code"] == "stack.rss_refused")
        self.assertEqual(refused["severity"], "critical")
        self.assertIn("no statistical acceptance", refused["consequence"])

    @staticmethod
    def justified(stack: dict) -> dict:
        stack["requirement"]["method"] = "justified_rss"
        stack["statistics"] = {"decision": "DR-001", "coverage_factor": 3, "probability": 0.9973,
                               "independence": fx.source("test", "TST independent process study")}
        for item in stack["contributors"]:
            item["distribution"] = {"tolerance_divisor": 3, "centred": True, "stable": True,
                                    "source": fx.source("test", f"TST {item['id']} capability study")}
        return stack

    def test_justified_rss_never_permits_a_forbidden_collision(self) -> None:
        stack = self.justified(fixture("closing_gap.yaml"))
        result = self.bound(closing_gap_documents(method="justified_rss"), stack, "closing-gap")
        sigma = math.sqrt(0.08 ** 2 + 0.06 ** 2 + 0.06 ** 2 + 0.02 ** 2 + 0.08 ** 2) / 3
        self.assertEqual(result["statistical"]["status"], "justified")
        self.assertAlmostEqual(result["statistical"]["sigma"], sigma, places=6)
        self.assertAlmostEqual(result["statistical"]["min"], 0.20 - 3 * sigma, places=6)
        self.assertTrue(result["requirement"]["statistical_pass"])
        self.assertEqual(result["requirement"]["governing"], "worst_case")
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("stack.rss_refused", codes(result))

    def test_justified_rss_may_govern_a_performance_limit_with_the_worst_case_shown(self) -> None:
        stack = self.justified(fixture("closing_gap.yaml"))
        stack["consequence"] = "performance"
        result = stackup.compute(stack)
        self.assertEqual(result["requirement"]["governing"], "justified_rss")
        self.assertEqual(result["outcome"], "pass")
        self.assertAlmostEqual(result["worst_case"]["min"], -0.10, places=6)
        self.assertTrue(any("worst case -0.1..0.5 mm violates" in text for text in result["limits"]))
        self.assertTrue(any("not bound to a record" in text for text in result["limits"]))

    def test_correlations_widen_the_interval_and_an_inconsistent_set_is_refused(self) -> None:
        stack = self.justified(fixture("closing_gap.yaml"))
        stack["consequence"] = "performance"
        stack["statistics"]["correlations"] = [{"between": ["B", "S"], "rho": 0.5}]
        correlated = stackup.compute(stack)["statistical"]
        s_b = s_s = 0.06 / 3  # B and S both subtract: weights -s_b and -s_s, covariance term +2 rho s_b s_s
        base = (0.08 ** 2 + 0.06 ** 2 + 0.06 ** 2 + 0.02 ** 2 + 0.08 ** 2) / 9
        self.assertAlmostEqual(correlated["sigma"], math.sqrt(base + 2 * 0.5 * s_b * s_s), places=6)
        stack["statistics"]["correlations"] = [{"between": ["H", "B"], "rho": 0.9}, {"between": ["B", "S"], "rho": 0.9},
                                               {"between": ["H", "S"], "rho": -0.9}]
        inconsistent = stackup.compute(stack)
        self.assertEqual(inconsistent["statistical"]["status"], "refused")
        self.assertEqual(inconsistent["requirement"]["governing"], "worst_case")

    def test_unknown_contributor_or_missing_effect_is_never_a_pass(self) -> None:
        stack = fixture("closing_gap.yaml")
        stack["requirement"]["min"] = -1.0
        thermal = contributor(stack, "T")
        for key in ("direction", "nominal", "tol", "source"):
            thermal.pop(key)
        thermal.update(status="unknown", reason="no thermal expansion analysis yet")
        result = self.bound(closing_gap_documents(), stack, "closing-gap")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["worst_case"]["status"], "unknown")
        self.assertEqual(result["worst_case"]["unknown_contributors"], ["T"])
        self.assertEqual(codes(result), ["stack.contributor_unknown"])

        missing = fixture("closing_gap.yaml")
        missing["relevant"].append("moisture")
        result = self.bound(closing_gap_documents(relevant=("manufacture", "coating", "thermal", "moisture")),
                            missing, "closing-gap")
        self.assertEqual(result["outcome"], "unknown")
        self.assertIn("stack.effect_missing", codes(result))

    def test_an_effect_the_interface_declares_relevant_cannot_be_dropped(self) -> None:
        result = self.bound(closing_gap_documents(relevant=("manufacture", "coating", "thermal", "moisture")),
                            fixture("closing_gap.yaml"), "closing-gap")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.record_mismatch"])
        self.assertIn("moisture", result["findings"][0]["uncertainty"])

    def test_an_iso_designation_is_not_achievable_precision(self) -> None:
        stack = fixture("closing_gap.yaml")
        housing = contributor(stack, "H")
        housing.pop("inspection")
        housing["designation"] = "20 H7"
        housing["source"] = fx.source("standard", "ISO 286-1 H7 limits")
        result = self.bound(closing_gap_documents(), stack, "closing-gap")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.designation_not_capability"])

    def test_a_drawn_tolerance_alone_does_not_qualify_manufacturing_variation(self) -> None:
        stack = fixture("closing_gap.yaml")
        spacer = contributor(stack, "S")
        spacer["source"] = fx.source("user", "drawing tolerance")
        self.assertEqual(stackup.compute(stack)["outcome"], "unknown")

    def test_as_manufactured_size_of_a_reamed_feature_is_a_state_mismatch(self) -> None:
        stack = fixture("closing_gap.yaml")
        housing = contributor(stack, "H")
        housing.pop("inspection")
        housing["state"] = "as_manufactured"
        housing["operation"] = "print"
        result = self.bound(closing_gap_documents(), stack, "closing-gap")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.state_mismatch"])
        self.assertIn("ream", result["findings"][0]["uncertainty"])

    def test_perfect_dimensions_and_double_counting_are_refused(self) -> None:
        def zero_width(s: dict) -> None:
            contributor(s, "B")["tol"] = 0.0

        def twice(s: dict) -> None:
            extra = copy.deepcopy(contributor(s, "H"))
            extra.update(id="H2", state="as_manufactured")
            s["contributors"].append(extra)

        def coat_on_finished(s: dict) -> None:
            coat = copy.deepcopy(contributor(s, "C"))
            coat.update(id="C2", subject={"PN": "TST-0001", "feature": "pivot_bore"})
            s["contributors"].append(coat)

        def legacy_method(s: dict) -> None:
            s["requirement"]["method"] = "rss"

        def undeclared_effect(s: dict) -> None:
            s["relevant"].remove("thermal")

        def no_requirement_source(s: dict) -> None:
            s["requirement"].pop("source")

        for mutate in (zero_width, twice, coat_on_finished, legacy_method, undeclared_effect, no_requirement_source):
            stack = fixture("closing_gap.yaml")
            mutate(stack)
            with self.subTest(case=mutate.__name__), self.assertRaises(stackup.StackError):
                stackup.compute(stack)

    def test_a_stack_without_intent_version_2_is_refused(self) -> None:
        stack = fixture("closing_gap.yaml")
        for version in (1, "2", True):
            with self.subTest(intent_version=version), self.assertRaisesRegex(stackup.StackError, "intent_version must be 2"):
                stackup.compute({**stack, "intent_version": version})
        del stack["intent_version"]
        with self.assertRaisesRegex(stackup.StackError, "intent_version must be 2"):
            stackup.compute(stack)

    def test_contribution_shares_sum_to_100(self) -> None:
        # Hand derivation from closing_gap.yaml: half-tolerances H 0.08, B 0.06, S 0.06, C 0.02, T 0.08 sum to
        # 0.30, so each share is 100 * half / 0.30:
        #   H = T = 26.666667 (80/3)   B = S = 20   C = 6.666667 (20/3)
        # The result rounds each share to 6 decimals, so the shares sum to 100 within 5 * 0.5e-6; allow 1e-5.
        # Dropped from the v1 test: the rss_contribution_pct half (that field is not in a v2 result) and the flat
        # row key (v2 keeps the share under row["resolved"]).
        rows = stackup.compute(fixture("closing_gap.yaml"))["contributors"]
        expected = {"H": 80 / 3, "B": 20.0, "S": 20.0, "C": 20 / 3, "T": 80 / 3}
        self.assertEqual(len(rows), 5)
        shares = {row["id"]: row["resolved"]["wc_contribution_pct"] for row in rows}
        self.assertEqual(shares.keys(), expected.keys())
        for ident, share in expected.items():
            with self.subTest(contributor=ident):
                self.assertAlmostEqual(shares[ident], share, delta=1e-6)
        self.assertAlmostEqual(sum(shares.values()), 100.0, delta=1e-5)

    def test_invalid_contributors_are_rejected(self) -> None:
        # Dropped from the v1 test: the legacy requirement method rss case, which
        # test_perfect_dimensions_and_double_counting_are_refused already covers. One bad change per case.
        baseline = fixture("closing_gap.yaml")
        self.assertEqual(stackup.compute(baseline)["outcome"], "fail")  # a valid v2 stack that computes

        def negative_tolerance(s: dict) -> None:
            contributor(s, "H")["tol"] = -0.08

        def both_tolerance_forms(s: dict) -> None:
            contributor(s, "H").update(tol_plus=0.08, tol_minus=0.08)

        def missing_tol_minus(s: dict) -> None:
            entry = contributor(s, "H")
            del entry["tol"]
            entry["tol_plus"] = 0.08

        def non_numeric_nominal(s: dict) -> None:
            contributor(s, "H")["nominal"] = "20.22"

        def bad_direction(s: dict) -> None:
            contributor(s, "H")["direction"] = 2

        def no_contributors(s: dict) -> None:
            s["contributors"] = []

        cases = [
            (negative_tolerance, "tolerances are magnitudes and must be >= 0"),
            (both_tolerance_forms, "give either tol or tol_plus/tol_minus, not both"),
            (missing_tol_minus, "needs tol, or both tol_plus and tol_minus"),
            (non_numeric_nominal, r"contributors\[0\]\.nominal must be a finite number, got '20\.22'"),
            (bad_direction, r"contributors\[0\]\.direction must be 1 or -1, got 2"),
            (no_contributors, "contributors must be a non-empty list"),
        ]
        for mutate, message in cases:
            stack = copy.deepcopy(baseline)
            mutate(stack)
            with self.subTest(case=mutate.__name__), self.assertRaisesRegex(stackup.StackError, message):
                stackup.compute(stack)

    # ---- row 10: laser tab-and-slot

    def test_nominal_laser_tab_slot_fails_its_kerf_thickness_and_coating_interval(self) -> None:
        result = self.bound(tab_slot_documents(), fixture("laser_tab_slot.yaml"), "tab-slot")
        self.assertAlmostEqual(result["remaining"]["nominal"], 0.10, places=6)
        self.assertAlmostEqual(result["worst_case"]["min"], -0.15, places=6)
        self.assertAlmostEqual(result["worst_case"]["max"], 0.20, places=6)
        self.assertTrue(result["requirement"]["nominal_pass"])
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(codes(result), ["stack.worst_case_violation"])
        self.assertEqual(result["obligations"][0]["obligation"], "interface.stack@IF-002")
        slot = next(row for row in result["contributors"] if row["id"] == "W")
        self.assertEqual(slot["qualification"], "capability")
        self.assertEqual(slot["resolved"]["calibration"], "tst_slot_coupon")
        self.assertIn("process.laser.fit_coupon", {e.get("family") for e in result["required_evidence"]})

    def test_a_passing_tab_slot_interval_still_requires_its_fit_coupon(self) -> None:
        stack = fixture("laser_tab_slot.yaml")
        contributor(stack, "W")["nominal"] = 3.30
        result = self.bound(tab_slot_documents(), stack, "tab-slot")
        self.assertEqual(result["outcome"], "pass")
        self.assertAlmostEqual(result["worst_case"]["min"], 0.05, places=6)
        coupon = [e for e in result["required_evidence"] if e.get("family") == "process.laser.fit_coupon"]
        self.assertEqual(len(coupon), 1)
        self.assertEqual(coupon[0]["level"], "physically_validated")
        self.assertTrue(any("not physical validation" in text for text in result["limits"]))

    def test_slot_limits_tighter_than_the_calibration_stay_unknown(self) -> None:
        stack = fixture("laser_tab_slot.yaml")
        contributor(stack, "W")["tol"] = 0.02
        result = self.bound(tab_slot_documents(), stack, "tab-slot")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.limits_unqualified"])

    def test_an_uncounted_coating_on_the_slot_is_a_state_mismatch(self) -> None:
        stack = fixture("laser_tab_slot.yaml")
        stack["contributors"] = [c for c in stack["contributors"] if c["id"] != "CS"]
        result = self.bound(tab_slot_documents(), stack, "tab-slot")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.state_mismatch"])

    def test_an_uncalibrated_capability_stays_unknown(self) -> None:
        documents = tab_slot_documents()
        documents["manufacturing/capabilities.yaml"]["profiles"][0]["calibrations"] = []
        result = self.bound(documents, fixture("laser_tab_slot.yaml"), "tab-slot")
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(codes(result), ["stack.capability_unresolved"])


class StackPacketTests(unittest.TestCase):
    """A record-bound intent stack at hw/analysis/cases/<case>/case.yaml publishes its analysis bundle as
    hw/analysis/<V>/<case>/ (the bundle release.py requires for the case) and the interface.stack / feature.fit
    outcome it judges as a required-check packet at hw/checks/<V>/stack-<case>/, beside it, where cad-record
    evidence.py reads producer packets; the governing results and unknowns are kept."""

    PACKET = "hw/checks/v1/stack-closing-gap"
    OBLIGATION = "interface.stack@IF-001"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hw = Path(directory.name) / "project" / "hw"

    def build(self, documents: dict, stack: dict) -> None:
        fx.write_record(self.hw, documents)
        self.case = write_case(self.hw, "closing-gap", stack)
        self.manifest_sha = snapshot_version(self.hw)

    def run_stack(self) -> tuple[int, dict]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = stackup.main([str(self.case), "--hw", str(self.hw), "--version", "v1"])
        self.assertIn(status, (0, 1), err.getvalue())
        return status, json.loads(out.getvalue())

    def packet(self) -> tuple[dict, dict]:
        """(result.json, evidence/analysis.json) of the published packet, after validating the packet."""
        bundle = self.hw.parent / self.PACKET
        packet = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
        errors = [error.message for error in check_result_validator().iter_errors(packet)]
        self.assertEqual(errors, [])
        return packet, json.loads((bundle / "evidence" / "analysis.json").read_text(encoding="utf-8"))

    def assessed(self) -> object:
        """The evidence status of IF-001's stack obligation, from the packets evidence.py collects."""
        evidence = evidence_module()
        packets, findings = evidence.collect_packets(self.hw, "v1", self.manifest_sha)
        self.assertEqual((findings, [p.bundle for p in packets]), ([], [self.PACKET]))
        assessment = evidence.assess(intent.load_record(self.hw), version="v1", manifest_sha256=self.manifest_sha,
                                     packets=packets)
        self.assertNotIn("packet.invalid", [f.code for f in assessment.findings])
        return assessment.statuses[self.OBLIGATION]

    def test_a_failed_worst_case_is_the_stack_outcome_evidence_reads_and_a_rerun_reuses_it(self) -> None:
        self.build(closing_gap_documents(), fixture("closing_gap.yaml"))
        status, output = self.run_stack()
        self.assertEqual((status, output["check_bundle"]), (1, self.PACKET))
        packet, detail = self.packet()
        self.assertEqual([o["id"] for o in packet["expected"]], [self.OBLIGATION])
        self.assertEqual((packet["result"], packet["complete"], packet["record_version"]), ("fail", True, 2))
        row = packet["outcomes"][0]
        self.assertEqual((row["obligation"], row["outcome"], row["level"], row["method"]),
                         (self.OBLIGATION, "fail", "process_planned", "1D worst-case tolerance stack"))
        self.assertEqual([f["code"] for f in packet["findings"]], ["stack.worst_case_violation"])
        self.assertEqual(packet["dependencies"], {"stack_case": hashlib.sha256(self.case.read_bytes()).hexdigest()})
        analysis = self.hw / "analysis" / "v1" / "closing-gap"
        self.assertEqual(json.loads((analysis / "results.json").read_text(encoding="utf-8"))["id"], "STK-014")
        self.assertEqual(detail["analysis"], {"bundle": "hw/analysis/v1/closing-gap", "manifest_sha256": hashlib.sha256(
            (analysis / "manifest.json").read_bytes()).hexdigest()})
        self.assertEqual((detail["worst_case"]["min"], detail["worst_case"]["max"]), (-0.1, 0.5))
        self.assertEqual((detail["requirement"]["governing"], detail["requirement"]["nominal_pass"]), ("worst_case", True))
        status_of = self.assessed()
        self.assertEqual((status_of.result, status_of.sources), ("fail", (self.PACKET,)))
        sealed = (self.hw.parent / self.PACKET / "manifest.json").read_bytes()
        status, again = self.run_stack()
        self.assertEqual((status, again["reused"], again["check_bundle"]), (1, True, self.PACKET))
        self.assertEqual((self.hw.parent / self.PACKET / "manifest.json").read_bytes(), sealed)

    def test_an_unknown_contributor_is_published_unknown_never_pass(self) -> None:
        stack = fixture("closing_gap.yaml")
        stack["requirement"]["min"] = -1.0
        thermal = contributor(stack, "T")
        for key in ("direction", "nominal", "tol", "source"):
            thermal.pop(key)
        thermal.update(status="unknown", reason="no thermal expansion analysis yet")
        self.build(closing_gap_documents(), stack)
        status, output = self.run_stack()
        self.assertEqual((status, output["check_bundle"]), (1, self.PACKET))
        packet, detail = self.packet()
        self.assertEqual((packet["result"], packet["outcomes"][0]["outcome"]), ("unknown", "unknown"))
        self.assertIn("no thermal expansion analysis yet", packet["outcomes"][0]["uncertainty"])
        self.assertEqual([f["code"] for f in packet["findings"]], ["stack.contributor_unknown"])
        self.assertEqual((detail["worst_case"]["status"], detail["worst_case"]["unknown_contributors"]), ("unknown", ["T"]))
        self.assertEqual(self.assessed().result, "unknown")

    def test_a_justified_rss_publishes_its_statistical_outcome_and_approving_decision(self) -> None:
        """A performance limit an approved, sourced statistical interval meets passes by justified RSS; the
        worst case that violates it stays in the packet's evidence, never hidden."""
        stack = IntentStackContractTests.justified(fixture("closing_gap.yaml"))
        stack["consequence"] = "performance"
        self.build(closing_gap_documents(method="justified_rss"), stack)
        decision = self.hw / "decisions" / "DR-001.md"
        status, output = self.run_stack()
        self.assertEqual((status, output["check_bundle"]), (0, self.PACKET))
        packet, detail = self.packet()
        self.assertEqual((packet["result"], packet["outcomes"][0]["outcome"], packet["outcomes"][0]["method"]),
                         ("pass", "pass", "1D justified statistical tolerance stack"))
        self.assertEqual((detail["requirement"]["governing"], detail["statistical"]["status"]), ("justified_rss", "justified"))
        self.assertEqual((detail["worst_case"]["min"], detail["worst_case"]["max"]), (-0.1, 0.5))
        self.assertFalse(detail["requirement"]["worst_case_pass"])
        self.assertEqual(packet["dependencies"]["decision_dr_001"], hashlib.sha256(decision.read_bytes()).hexdigest())
        self.assertEqual(self.assessed().result, "pass")

    def test_a_stack_whose_obligation_the_record_does_not_expect_publishes_no_packet(self) -> None:
        documents = closing_gap_documents()
        documents["interfaces.yaml"]["interfaces"][0]["functional"]["critical"] = fx.known(False)
        self.build(documents, fixture("closing_gap.yaml"))
        status, output = self.run_stack()
        self.assertEqual((status, output["check_bundle"]), (1, None))
        self.assertFalse((self.hw / "checks").exists())


@unittest.skipUnless(shutil.which("uv"), "uv is required to run the PEP 723 script end to end")
class StackupCliTests(unittest.TestCase):
    def run_cli(self, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stack.yaml"
            path.write_text(text, encoding="utf-8")
            return subprocess.run(
                ["uv", "run", "--quiet", "--script", str(SCRIPT), str(path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )

    def test_malformed_yaml_exits_2(self) -> None:
        proc = self.run_cli("contributors: [unclosed\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid YAML", proc.stderr)

    def test_intent_stack_binds_the_version_record_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hw = fx.write_record(Path(directory) / "project" / "hw", closing_gap_documents())
            case = write_case(hw, "closing-gap", fixture("closing_gap.yaml"))
            snapshot_version(hw)
            proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), str(case), "--hw", str(hw),
                                   "--version", "v1"], capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("requirement not met (worst_case)", proc.stderr)
            output = json.loads(proc.stdout)
            self.assertTrue(output["record_bound"])
            self.assertEqual(output["case"], "closing-gap")
            self.assertEqual(output["outcome"], "fail")
            manifest = json.loads((hw / "analysis" / "v1" / "closing-gap" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "fail")
            self.assertEqual(manifest["recipe"]["options"]["intent_version"], 2)
            self.assertEqual(output["check_bundle"], "hw/checks/v1/stack-closing-gap")

    def assembly_stack(self) -> dict:
        """A PN-subject stack of two sourced assembly contributors that passes: 0.2 mm +/- 0.1 against 0.0 to 0.4."""
        source = {"kind": "user", "reference": "TST stack input", "origin": "TST fixture user"}
        return {"intent_version": 2, "id": "STK-021", "title": "PN stack", "units": "mm",
                "subject": {"PN": "TST-0001", "feature": "pivot_bore"}, "dimension_state": "assembled",
                "consequence": "performance", "relevant": ["assembly"],
                "requirement": {"min": 0.0, "max": 0.4, "method": "worst_case", "source": source},
                "contributors": [{"id": "A", "category": "assembly", "nominal": 50.2, "tol": 0.05, "direction": 1, "source": source},
                                 {"id": "B", "category": "assembly", "nominal": 50.0, "tol": 0.05, "direction": -1, "source": source}]}

    def test_a_snapshot_that_is_not_record_version_2_is_refused_and_nothing_is_published(self) -> None:
        for label, change in (("absent", lambda text: text.replace("record_version: 2\n", "")),
                              ("unknown", lambda text: text.replace("record_version: 2", "record_version: 3")),
                              ("non-mapping", lambda text: "- not\n- a mapping\n")):
            with self.subTest(snapshot=label), tempfile.TemporaryDirectory() as directory:
                hw = fx.write_record(Path(directory) / "project" / "hw", closing_gap_documents())
                case = write_case(hw, "pn-stack", self.assembly_stack())
                snapshot_version(hw)
                product = hw / "versions" / "v1" / "record" / "product.yaml"
                product.write_text(change(product.read_text(encoding="utf-8")), encoding="utf-8")
                version = hw / "versions" / "v1"  # reseal the manifest over the edited snapshot, so only the version is wrong
                files = {path.relative_to(version).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in version.rglob("*") if path.is_file() and path.name != "manifest.json"}
                (version / "manifest.json").write_text(json.dumps({"label": "v1", "files": files}), encoding="utf-8")
                args = ["uv", "run", "--quiet", "--script", str(SCRIPT), str(case), "--hw", str(hw), "--version", "v1"]
                proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn("record_version", proc.stderr)
                self.assertFalse((hw / "analysis" / "v1").exists(), "no analysis bundle")
                self.assertFalse((hw / "checks").exists(), "no check packet")

    def test_the_same_pn_stack_passes_against_a_record_version_2_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hw = fx.write_record(Path(directory) / "project" / "hw", closing_gap_documents())
            case = write_case(hw, "pn-stack", self.assembly_stack())
            snapshot_version(hw)
            proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), str(case), "--hw", str(hw),
                                   "--version", "v1"], capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((hw / "analysis" / "v1" / "pn-stack").is_dir())

    def test_rerun_reuses_bundle_and_recipe_change_requires_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            hw = fx.write_record(project / "hw", closing_gap_documents())
            case = write_case(hw, "closing-gap", fixture("closing_gap.yaml"))
            snapshot_version(hw)
            args = ["uv", "run", "--quiet", "--script", str(SCRIPT), str(case), "--hw", str(hw), "--version", "v1"]
            first = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(first.returncode, 1, first.stderr)
            bundle = hw / "analysis" / "v1" / "closing-gap"
            original = {path.relative_to(bundle).as_posix(): path.read_bytes()
                        for path in bundle.rglob("*") if path.is_file()}
            second = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(second.returncode, 1, second.stderr)
            self.assertTrue(json.loads(second.stdout)["reused"])
            self.assertEqual(original, {path.relative_to(bundle).as_posix(): path.read_bytes()
                                        for path in bundle.rglob("*") if path.is_file()})

            case.write_text(case.read_text(encoding="utf-8").replace("Cover closing gap", "Cover closing gap, rechecked"),
                            encoding="utf-8")
            changed = subprocess.run(args, capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(changed.returncode, 2)
            self.assertIn("--replace", changed.stderr)
            self.assertEqual(original, {path.relative_to(bundle).as_posix(): path.read_bytes()
                                        for path in bundle.rglob("*") if path.is_file()})
            replaced = subprocess.run([*args, "--replace"], capture_output=True, text=True, check=False, timeout=300)
            self.assertEqual(replaced.returncode, 1, replaced.stderr)
            self.assertFalse(json.loads(replaced.stdout)["reused"])
            replaced_path = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["replaces"]["moved_to"]
            replaced_bundle = project / replaced_path
            self.assertEqual(original, {path.relative_to(replaced_bundle).as_posix(): path.read_bytes()
                                         for path in replaced_bundle.rglob("*") if path.is_file()})

    def test_standalone_output_override_outside_cad_work_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack_path = root / "stack.yaml"
            stack_path.write_text((FIXTURES / "closing_gap.yaml").read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), str(stack_path),
                                  "--out", str(root / "outside.json")], capture_output=True, text=True,
                                 check=False, timeout=300)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("--out must be under", proc.stderr)


if __name__ == "__main__":
    unittest.main()
