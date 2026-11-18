"""route.operation_plan: an absent plan field FAILs and names the field. A field recorded as open (an unknown
fact with its reason) stays UNKNOWN. A complete plan PASSes.

Run: python3 -m unittest discover -s skills/cad-design/tests -p test_route_operation_plan.py
Needs PyYAML and jsonschema (the CI uv command supplies them). Every value is a synthetic TST value.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
DEPS = importlib.util.find_spec("yaml") is not None and importlib.util.find_spec("jsonschema") is not None
MISSING = "route.operation_plan_field_missing"
OPEN = "route.plan_incomplete"
POLYMER, ALUMINIUM, ACRYLIC = "tst_polymer", "tst_alu", "tst_acrylic"
APPROVED = {"status": "approved", "rotation": {"quaternion": [1, 0, 0, 0]}, "decision": "DR-001"}

FX: Any = None
pc: Any = None
if DEPS:
    sys.path.insert(0, str(SKILLS / "cad-design" / "scripts"))
    import process_checks as pc

    _spec = importlib.util.spec_from_file_location("cad_record_mi_fixtures",
                                                   SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
    assert _spec and _spec.loader
    FX = importlib.util.module_from_spec(_spec)
    sys.modules["cad_record_mi_fixtures"] = FX
    _spec.loader.exec_module(FX)


def made(pn: str, op: dict[str, Any] | list[dict[str, Any]], process: str, material: str) -> dict[str, Any]:
    route = op if isinstance(op, list) else [op]
    intent = FX.intent(functions=[{"function": "cosmetic"}], material_profile=material, route=route,
                       critical_surfaces=FX.not_applicable("none here"))
    part: dict[str, Any] = FX.part(pn, process=process, part_intent=intent)
    return part


def fdm(**plan: Any) -> dict[str, Any]:
    return made("TST-0001", FX.operation("print", "fdm", "tst_printer", output_state="printed", **plan), "fdm", POLYMER)


def cnc(setup: dict[str, Any] | None = None) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "stock": {"material_profile": ALUMINIUM, "grade": FX.known("TST 6061-T6"), "dimensions": FX.known("45 x 35 x 30")},
        "datums": ["datum_a"], "workholding": {"method": FX.known("vice on the datum faces")}}
    if setup is not None:
        plan = setup
    return made("TST-0002", FX.operation("mill", "cnc", "tst_mill", setup=plan) if plan else FX.operation("mill", "cnc", "tst_mill"),
                "cnc", ALUMINIUM)


def milled(**plan: Any) -> dict[str, Any]:
    """A complete first cnc operation: the valid predecessor of a secondary operation."""
    setup = {"stock": {"material_profile": ALUMINIUM, "grade": FX.known("TST 6061-T6"), "dimensions": FX.known("45 x 35 x 30")},
             "datums": ["datum_a"], "workholding": {"method": FX.known("vice on the datum faces")}, **plan}
    return FX.operation("mill", "cnc", "tst_mill", setup=setup, output_state="milled")


def secondary(kind: str, **plan: Any) -> dict[str, Any]:
    """A part milled first, then one `kind` operation (its capability is `tst_<kind>`) taking the milled state."""
    return made("TST-0003", [milled(), FX.operation("second", kind, f"tst_{kind}", input_state="milled", **plan)], "cnc", ALUMINIUM)


def sheet(kind: str, stock: dict[str, Any]) -> dict[str, Any]:
    """A sheet cut by `kind` (laser, waterjet or plasma) from `stock`."""
    return made("TST-0004", FX.operation("cut", kind, f"tst_{kind}", setup={"stock": stock}), kind, ACRYLIC)


def operation_plan(part: dict[str, Any]) -> Any:
    """The assessment of `part`. The tests look at its process-plan obligation."""
    profiles = [FX.material_profile(POLYMER, form="printed"), FX.material_profile(ALUMINIUM, form="wrought", family="TST aluminium"),
                FX.material_profile(ACRYLIC, form="sheet", family="TST cast acrylic")]
    capabilities = [FX.capability_profile("tst_printer", "fdm"),
                    FX.capability_profile("tst_mill", "cnc", parameters={"axes": FX.known(FX.quantity(3, units="count"))}),
                    *(FX.capability_profile(f"tst_{kind}", kind) for kind in
                      ("drilling", "coating", "inspection", "laser", "waterjet", "plasma"))]
    with tempfile.TemporaryDirectory() as tmp:
        hw = FX.write_record(Path(tmp) / "project" / "hw", FX.record(parts=[part], capabilities=capabilities, materials=profiles))
        record, problems = pc.intent().check_record(hw)
    errors = [p.message for p in problems if p.severity == "error"]
    if errors:
        raise ValueError(f"the fixture record is invalid: {errors}")
    return pc.assess(record, {}, today=date(2026, 6, 1))


@unittest.skipUnless(DEPS, "pyyaml and jsonschema are required")
class OperationPlanTests(unittest.TestCase):
    def judge(self, part: dict[str, Any], operation: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        """The outcome and findings of the plan obligation of `operation` (the only one when None)."""
        result = operation_plan(part)
        plans = [o.id for o in result.expected if o.family == "route.operation_plan"]
        obligation = next(o for o in plans if operation is None or o.endswith(f"/{operation}"))
        found = result.outcome(obligation)
        findings = [f for f in result.findings if f.get("obligation") == obligation]
        return found["outcome"], findings

    def assert_missing(self, part: dict[str, Any], *fields: str, operation: str | None = None) -> None:
        outcome, findings = self.judge(part, operation)
        self.assertEqual(outcome, "fail", findings)
        gaps = [f for f in findings if f["code"] == MISSING]
        self.assertEqual(len(gaps), len(fields), [f["measured"] for f in gaps])
        for field, finding in zip(fields, gaps, strict=True):
            self.assertEqual(finding["outcome"], "fail")
            self.assertIn(field, finding["measured"]["text"])
        self.assertEqual([f for f in findings if f["code"] == OPEN], [])

    def test_a_printed_part_with_no_plan_fails_naming_orientation_and_supports(self) -> None:
        self.assert_missing(fdm(), "orientation", "supports")

    def test_a_printed_part_without_orientation_fails_naming_it(self) -> None:
        self.assert_missing(fdm(supports={"strategy": "none"}), "orientation")

    def test_a_printed_part_without_supports_fails_naming_them(self) -> None:
        self.assert_missing(fdm(orientation=dict(APPROVED)), "supports")

    def test_a_milled_part_with_no_setup_fails_naming_stock_and_workholding(self) -> None:
        self.assert_missing(cnc({}), "stock", "workholding")

    def test_a_milled_part_without_workholding_fails_naming_it(self) -> None:
        setup = {"stock": {"material_profile": ALUMINIUM, "grade": FX.known("TST 6061-T6")}, "datums": ["datum_a"]}
        self.assert_missing(cnc(setup), "workholding")

    def test_a_milled_part_without_stock_fails_naming_it(self) -> None:
        self.assert_missing(cnc({"datums": ["datum_a"], "workholding": {"method": FX.known("vice")}}), "stock")

    def test_a_drilling_without_datums_fails_naming_them(self) -> None:
        self.assert_missing(secondary("drilling", targets=[{"feature": "hole_a"}]), "datums", operation="second")

    def test_a_drilling_without_targets_fails_naming_them(self) -> None:
        self.assert_missing(secondary("drilling", setup={"datums": ["datum_a"]}), "targets", operation="second")

    def test_a_sheet_without_stock_thickness_fails_naming_it(self) -> None:
        stock = {"material_profile": ACRYLIC, "dimensions": FX.known("600 x 400")}
        for kind in ("laser", "waterjet", "plasma"):
            with self.subTest(kind=kind):
                self.assert_missing(sheet(kind, stock), "stock thickness")

    def test_a_coating_and_an_inspection_need_no_targets(self) -> None:
        for kind, plan, expected in (("coating", {}, "not_applicable"), ("inspection", {"setup": {"datums": ["datum_a"]}}, "pass")):
            with self.subTest(kind=kind):
                outcome, findings = self.judge(secondary(kind, **plan), "second")
                self.assertEqual((outcome, findings), (expected, []))

    def test_an_orientation_marked_open_with_a_reason_stays_unknown(self) -> None:
        outcome, findings = self.judge(fdm(orientation=FX.unknown("print pose awaits the fixture design"),
                                           supports={"strategy": "none"}))
        self.assertEqual(outcome, "unknown")
        self.assertEqual([f["code"] for f in findings], [OPEN])

    def test_supports_marked_open_with_a_reason_stay_unknown(self) -> None:
        outcome, findings = self.judge(fdm(orientation=dict(APPROVED), supports=FX.unknown("slicer run pending")))
        self.assertEqual(outcome, "unknown")
        self.assertEqual([f["code"] for f in findings], [OPEN])

    def test_a_missing_field_fails_even_when_another_is_open(self) -> None:
        outcome, findings = self.judge(fdm(supports=FX.unknown("slicer run pending")))
        self.assertEqual(outcome, "fail")
        self.assertEqual(sorted(f["code"] for f in findings), [MISSING, OPEN])

    def test_a_complete_printed_plan_passes(self) -> None:
        outcome, findings = self.judge(fdm(orientation=dict(APPROVED), supports={"strategy": "none"}))
        self.assertEqual((outcome, findings), ("pass", []))

    def test_a_complete_milled_plan_passes(self) -> None:
        outcome, findings = self.judge(cnc())
        self.assertEqual((outcome, findings), ("pass", []))


if __name__ == "__main__":
    unittest.main()
