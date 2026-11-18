#!/usr/bin/env python3
"""evidence.py: independent evidence facets, unknown never pass, stale and carried evidence, waivers,
critical findings, progressive stage gates, the selection gate on selection.py's report, the release
service policy and the acceptance digest.

Pure policy over synthetic TST records (no CAD kernel), including U2's selection scenarios
(tests/fixtures/selection/scenarios.py); the inventory tests write small temporary trees.
Regression matrix rows 13 (stale evidence), 16 (missing and unknown never pass) and the release/stamp
boundary cases.
"""

from __future__ import annotations

import copy
import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402


acceptance = load("cad_record_acceptance_fixtures", HERE / "fixtures" / "acceptance.py")
fx, mi, evidence, impact = acceptance.fx, acceptance.mi, acceptance.evidence, acceptance.impact
check_packet = load("cad_record_check_packet", HERE.parent / "scripts" / "check_packet.py")
fail_fast = load("cad_record_fail_fast", HERE.parent / "scripts" / "fail_fast.py")
TODAY = date(2026, 6, 1)
V1 = "a" * 64
APPROVED = frozenset({"DR-001", "DR-002", "DR-003"})

CREEP = "engineering.creep@TST-0001"
STRENGTH = "engineering.strength@TST-0001"
READBACK = "cad.readback@TST-0001"
INSPECTION = "feature.inspection@TST-0001#pivot_bore"
TRIAL = "process.fdm.trial@TST-0001/print"
SUPPORT = "process.fdm.support@TST-0001/print"
SIMULATION = "requirement.simulation_supported@REQ-001"
EXPORT_3MF = "export.3mf@TST-0001"


def approved(decision: str | None) -> bool:
    return decision in APPROVED


def documents(service_class: str | None = None) -> dict[str, Any]:
    """The TST record (fixtures.manufacturing_intent.tst_record) as documents; with `service_class`, its
    use case confirmed for that class, every question resolved and the shaft's critical surfaces recorded
    as none, so no intent input stays unknown."""
    docs = {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}
    if service_class is not None:
        loads = docs["product.yaml"]["use_case"]["loads"]
        docs["product.yaml"]["use_case"] = acceptance.confirmed_use_case(service_class, loads=loads)
        acceptance.resolve_questions(docs["requirements.yaml"])
        docs["parts/TST-0002/part.yaml"]["intent"]["critical_surfaces"] = fx.not_applicable("TST: none on the shaft")
    return docs


def normalized(docs: dict[str, Any], entries: list[dict[str, Any]] = (), dispositions: list[dict[str, Any]] = ()) -> Any:
    docs = copy.deepcopy(docs)
    if entries:
        docs["manufacturing/evidence.yaml"] = {"entries": list(entries)}
    if dispositions:
        docs["manufacturing/findings.yaml"] = {"dispositions": list(dispositions)}
    return mi.normalize_record(docs)


def packet(record: Any, *, outcome: str = "pass", **options: Any) -> Any:
    return evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64,
                                   acceptance.producer_packet(record, outcome=outcome, **options))


def assess(record: Any, *packets: Any, **options: Any) -> Any:
    return evidence.assess(record, version="v1", manifest_sha256=V1, packets=packets, approved=approved, today=TODAY,
                           **options)


def codes(findings: Any, severity: str | None = None) -> set[str]:
    return {f.code for f in findings if severity is None or f.severity == severity}


class UnknownNeverPasses(unittest.TestCase):
    """Row 16: an untested, planned, uncalibrated or merely stated result is never a pass."""

    def test_nothing_shown_is_unknown_and_blocks_from_layout(self) -> None:
        record = normalized(documents())
        result = assess(record)
        statuses = result.results()
        self.assertEqual({r for ident, r in statuses.items() if not ident.startswith("intent.")}, {"unknown"})
        self.assertEqual(result.facets["TST-0001"]["simulation_supported"], "unknown")
        self.assertIn("gate.unresolved", codes(result.gate("parts"), "error"))
        self.assertEqual(codes(result.gate("concept"), "error"), set(), "before layout explicit unknowns only warn")
        self.assertIn("gate.unresolved", codes(result.gate("concept"), "warning"))

    def test_a_producer_pass_counts_at_its_own_level_never_as_physical_validation(self) -> None:
        record = normalized(documents())
        result = assess(record, packet(record))
        self.assertEqual((result.statuses[READBACK].result, result.statuses[STRENGTH].result), ("pass", "pass"))
        for ident in (CREEP, INSPECTION, TRIAL):
            self.assertEqual(result.statuses[ident].result, "unknown", ident)
        self.assertEqual(result.facets["TST-0001"]["physically_validated"], "unknown")
        self.assertEqual(result.facets["TST-0001"]["cad_valid"], "pass")

        claimed = acceptance.producer_packet(record)
        creep = next(o for o in mi.required_checks(record) if o.id == CREEP)
        claimed["expected"].append(creep.as_dict())
        claimed["outcomes"].append({"obligation": CREEP, "outcome": "pass", "method": "TST static FEA", "coverage": "all"})
        result = assess(record, evidence.ProducerPacket("hw/checks/v1/fea", "c" * 64, claimed))
        self.assertEqual(result.statuses[CREEP].result, "unknown", "static simulation is not creep validation")
        self.assertIn("evidence.physical_claim", codes(result.findings))

    def test_an_outcome_at_another_level_does_not_count(self) -> None:
        record = normalized(documents())
        data = acceptance.producer_packet(record)
        for outcome in data["outcomes"]:
            if outcome["obligation"] == STRENGTH:
                outcome["level"] = "geometrically_manufacturable"
        result = assess(record, evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64, data))
        self.assertEqual(result.statuses[STRENGTH].result, "unknown")
        self.assertIn("packet.unexpected", codes(result.findings, "warning"))

    def test_an_uncalibrated_capability_stays_unknown(self) -> None:
        record = normalized(documents())
        result = assess(record, packet(record, outcome="unknown"))
        self.assertEqual(result.statuses[SUPPORT].result, "unknown")
        self.assertIn(SUPPORT, {f.obligation for f in result.gate("detail") if f.severity == "error"})

    def test_planned_simulation_and_an_untested_coupon_stay_planned(self) -> None:
        docs = documents()
        base = normalized(docs)
        entries = [acceptance.entry(base, "EV-001", {"product": True, "requirements": ["REQ-001"]}, "simulation_supported",
                                    "planned", requirement="REQ-001"),
                   acceptance.entry(base, "EV-002", {"PN": "TST-0001", "feature": "pivot_bore"}, "physically_validated",
                                    "planned", obligation=INSPECTION)]
        result = assess(normalized(docs, entries))
        self.assertEqual((result.statuses[SIMULATION].result, result.statuses[INSPECTION].result), ("planned", "planned"))
        analysis = {f.obligation for f in result.gate("analysis") if f.severity == "error"}
        self.assertIn(SIMULATION, analysis, "a planned simulation is not simulation evidence")
        self.assertNotIn(INSPECTION, analysis, "a physical test may stay planned until the release")
        self.assertIn(INSPECTION, {f.obligation for f in result.gate("release") if f.severity == "error"})

    def test_a_verification_csv_pass_is_not_evidence(self) -> None:
        docs = documents()
        record = normalized(docs)
        rows = [{"requirement_id": "REQ-001", "method": "T", "criteria": "TST", "result": "pass", "evidence": "hw/docs/x.md"}]
        result = assess(record, verification=rows)
        self.assertEqual((result.verification[0]["stated"], result.verification[0]["result"]), ("pass", "unknown"))
        self.assertIn("evidence.csv_unsupported", codes(result.findings))
        self.assertIn("evidence.csv_unsupported", codes(result.gate("parts"), "warning"))
        self.assertIn("evidence.csv_unsupported", codes(result.gate("design_freeze"), "error"))
        self.assertEqual([f.severity for f in evidence.csv_findings(record, rows, "parts")], ["warning"])
        self.assertEqual([f.severity for f in evidence.csv_findings(record, rows, "design_freeze")], ["error"])

    def test_verification_rows_show_their_evidence_ties(self) -> None:
        docs = documents()
        base = normalized(docs)
        entry = acceptance.entry(base, "EV-001", {"product": True, "requirements": ["REQ-001"]}, "simulation_supported",
                                 requirement="REQ-001", version="v1", manifest_sha256=V1)
        rows = [{"requirement_id": "REQ-001", "method": "A", "criteria": "TST", "result": "pass", "evidence": ""}]
        result = assess(normalized(docs, [entry]), verification=rows)
        row = result.verification[0]
        self.assertEqual((row["result"], row["method"], row["criterion"]), ("pass", "A", "TST fixture criteria"))
        self.assertEqual(row["evidence"][0]["version"], "v1")
        self.assertTrue({"material", "route", "geometry", "criterion"} <= set(row["evidence"][0]["tied_to"]))
        self.assertNotIn("evidence.csv_unsupported", codes(result.findings))


class StaleEvidence(unittest.TestCase):
    """Row 13: evidence counts only for its own configuration and dependencies; carry-forward is explicit."""

    def setUp(self) -> None:
        self.docs = documents()
        self.base = normalized(self.docs)

    def simulation(self, **options: Any) -> dict[str, Any]:
        options.setdefault("version", "v1")
        options.setdefault("manifest_sha256", V1)
        return acceptance.entry(self.base, "EV-001", {"product": True, "requirements": ["REQ-001"]},
                                "simulation_supported", requirement="REQ-001", **options)

    def test_current_qualified_evidence_passes(self) -> None:
        result = assess(normalized(self.docs, [self.simulation()]))
        self.assertEqual(result.statuses[SIMULATION].result, "pass")
        self.assertEqual(result.facets["REQ-001"]["simulation_supported"], "pass")

    def test_evidence_of_another_version_is_stale(self) -> None:
        result = assess(normalized(self.docs, [self.simulation(version="v2")]))
        self.assertEqual(result.statuses[SIMULATION].result, "stale")
        self.assertIn(SIMULATION, {f.obligation for f in result.gate("analysis") if f.code == "gate.stale"})

    def test_a_changed_material_grade_makes_the_evidence_stale(self) -> None:
        entry = self.simulation()
        changed = copy.deepcopy(self.docs)
        changed["manufacturing/materials.yaml"]["profiles"][0]["grade"] = fx.known("TST other grade")
        result = assess(normalized(changed, [entry]))
        self.assertEqual(result.statuses[SIMULATION].result, "stale")
        self.assertIn("material", " ".join(result.statuses[SIMULATION].reasons))

    def colored(self) -> dict[str, Any]:
        changed = copy.deepcopy(self.docs)
        changed["parts/TST-0001/part.yaml"]["intent"]["color"] = "#FF8000"
        return changed

    def export_3mf(self) -> dict[str, Any]:
        return acceptance.entry(self.base, "EV-003", {"PN": "TST-0001"}, "cad_valid", obligation=EXPORT_3MF,
                                version="v1", manifest_sha256=V1)

    def test_a_color_change_makes_accepted_export_3mf_evidence_stale_even_when_the_sealed_files_match(self) -> None:
        entry = self.export_3mf()
        self.assertEqual(assess(normalized(self.docs, [entry])).statuses[EXPORT_3MF].result, "pass")
        result = assess(normalized(self.colored(), [entry]), stale_since_build={EXPORT_3MF: ("appearance",)})
        self.assertEqual(result.statuses[EXPORT_3MF].result, "stale")
        self.assertIn("appearance", " ".join(result.statuses[EXPORT_3MF].reasons))

    def test_a_color_change_leaves_accepted_evidence_of_a_family_without_appearance_current(self) -> None:
        entries = [self.simulation(), acceptance.entry(self.base, "EV-002", {"PN": "TST-0001"}, "simulation_supported",
                                                       obligation=STRENGTH, version="v1", manifest_sha256=V1)]
        result = assess(normalized(self.colored(), entries))
        self.assertEqual((result.statuses[SIMULATION].result, result.statuses[STRENGTH].result), ("pass", "pass"))

    def test_export_3mf_evidence_that_records_no_appearance_fingerprint_is_unqualified(self) -> None:
        domains = tuple(d for d in impact.DOMAINS if d not in ("appearance", "lot"))
        entry = acceptance.entry(self.base, "EV-003", {"PN": "TST-0001"}, "cad_valid", obligation=EXPORT_3MF,
                                 version="v1", manifest_sha256=V1, domains=domains)
        result = assess(normalized(self.docs, [entry]))
        self.assertEqual(result.statuses[EXPORT_3MF].result, "unknown")
        self.assertIn("evidence.unqualified", codes(result.findings))
        control = acceptance.entry(self.base, "EV-004", {"PN": "TST-0001"}, "cad_valid", obligation=STRENGTH,
                                   version="v1", manifest_sha256=V1, domains=domains)
        self.assertEqual(assess(normalized(self.docs, [control])).statuses[STRENGTH].result, "pass",
                         "a family without appearance needs no appearance fingerprint")

    def test_evidence_that_omits_a_domain_its_family_declares_is_not_accepted(self) -> None:
        declared = impact.family_domains("engineering.strength")
        omitted = tuple(d for d in impact.DOMAINS if d in declared and d not in ("orientation", "finish", "lot"))
        entry = acceptance.entry(self.base, "EV-005", {"PN": "TST-0001"}, "simulation_supported", obligation=STRENGTH,
                                 version="v1", manifest_sha256=V1, domains=omitted)
        result = assess(normalized(self.docs, [entry]))
        self.assertEqual(result.statuses[STRENGTH].result, "unknown")
        found = [f for f in result.findings if f.code == "evidence.unqualified"]
        self.assertEqual(len(found), 1)
        self.assertIn("finish, orientation", found[0].message)
        self.assertIn("recheck", found[0].message)

    def test_evidence_that_records_every_domain_its_family_declares_is_accepted(self) -> None:
        declared = impact.family_domains("engineering.strength")
        entry = acceptance.entry(self.base, "EV-005", {"PN": "TST-0001"}, "simulation_supported", obligation=STRENGTH,
                                 version="v1", manifest_sha256=V1, domains=tuple(d for d in impact.DOMAINS if d in declared))
        self.assertEqual(assess(normalized(self.docs, [entry])).statuses[STRENGTH].result, "pass")

    def test_evidence_without_an_obligation_needs_no_family_domains(self) -> None:
        domains = tuple(d for d in impact.DOMAINS if d not in ("orientation", "finish", "appearance", "lot"))
        entry = self.simulation(domains=domains)
        self.assertNotIn("obligation", entry)
        self.assertEqual(assess(normalized(self.docs, [entry])).statuses[SIMULATION].result, "pass")

    def test_evidence_that_records_no_fingerprint_of_its_dependencies_is_unqualified(self) -> None:
        result = assess(normalized(self.docs, [self.simulation(domains=("use_case",))]))
        self.assertEqual(result.statuses[SIMULATION].result, "unknown")
        self.assertIn("evidence.unqualified", codes(result.findings))

    def test_carrying_evidence_of_another_build_forward_needs_an_approving_decision(self) -> None:
        carried = self.simulation(artifacts=["hw/analysis/v2/case/results.json"])  # sealed for another build
        result = assess(normalized(self.docs, [carried]))
        self.assertEqual(result.statuses[SIMULATION].result, "stale")
        self.assertIn("evidence.carry_forward", codes(result.findings))
        approved_entry = {**carried, "decisions": ["DR-003"]}
        self.assertEqual(assess(normalized(self.docs, [approved_entry])).statuses[SIMULATION].result, "pass")

    def test_altered_cited_bytes_void_the_evidence(self) -> None:
        result = assess(normalized(self.docs, [self.simulation()]), artifact_sha=lambda rel: "f" * 64)
        self.assertEqual(result.statuses[SIMULATION].result, "unknown")
        self.assertIn("evidence.altered", codes(result.findings))

    def test_physical_evidence_covers_its_own_subject_only(self) -> None:
        coupon = acceptance.entry(self.base, "EV-002", {"PN": "TST-0001", "feature": "pivot_bore"}, "physically_validated",
                                  obligation=CREEP, version="v1", manifest_sha256=V1)
        result = assess(normalized(self.docs, [coupon]))
        self.assertEqual(result.statuses[CREEP].result, "unknown", "a coupon is not the part's creep life")
        self.assertIn("evidence.subject", codes(result.findings))
        part = acceptance.entry(self.base, "EV-002", {"PN": "TST-0001"}, "physically_validated", obligation=CREEP,
                                version="v1", manifest_sha256=V1)
        self.assertEqual(assess(normalized(self.docs, [part])).statuses[CREEP].result, "pass")

    def test_a_producer_outcome_whose_inputs_changed_since_the_build_is_stale(self) -> None:
        result = assess(self.base, packet(self.base), stale_since_build={SUPPORT: ("material",)})
        self.assertEqual((result.statuses[SUPPORT].result, result.statuses[READBACK].result), ("stale", "pass"))


class Waivers(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = documents("fit_assembly")
        self.base = normalized(self.docs)
        self.subject = {"PN": "TST-0001", "operation": "print"}

    def waived(self, **waiver: Any) -> Any:
        entry = acceptance.entry(self.base, "EV-003", self.subject, "physically_validated", "waived", obligation=TRIAL,
                                 waiver=acceptance.waiver(self.subject, **waiver))
        return normalized(self.docs, [entry])

    def test_a_valid_waiver_stays_waived_never_pass(self) -> None:
        record = self.waived()
        result = assess(record, packet(record))
        self.assertEqual(result.statuses[TRIAL].result, "waived")
        self.assertEqual(result.facets["TST-0001"]["physically_validated"], "unknown", "the other tests still lack evidence")
        self.assertEqual(evidence.ledger_findings(record, approved=approved, today=TODAY), [])

    def test_an_unapproved_expired_or_misscoped_waiver_counts_as_nothing(self) -> None:
        for waiver, code in (({"decision": "DR-009"}, "waiver.unapproved"),
                             ({"expires": "2026-01-01", "until_change": None}, "waiver.expired"),
                             ({"subject": {"PN": "TST-0002"}}, "waiver.scope"),
                             ({"obligation": SUPPORT}, "waiver.scope")):
            with self.subTest(code=code, waiver=waiver):
                options = {k: v for k, v in waiver.items() if v is not None}
                entry = acceptance.entry(self.base, "EV-003", self.subject, "physically_validated", "waived", obligation=TRIAL,
                                         waiver=acceptance.waiver(options.pop("subject", self.subject), **options))
                if waiver.get("until_change", 1) is None:
                    entry["waiver"].pop("until_change")
                record = normalized(self.docs, [entry])
                result = assess(record)
                self.assertEqual(result.statuses[TRIAL].result, "unknown")
                self.assertIn(code, codes(result.findings))
                self.assertIn(code, codes(evidence.ledger_findings(record, approved=approved, today=TODAY)))

    def test_governing_safety_and_geometry_integrity_cannot_be_waived(self) -> None:
        readback = {"PN": "TST-0001"}
        entry = acceptance.entry(self.base, "EV-004", readback, "cad_valid", "waived", obligation=READBACK,
                                 waiver=acceptance.waiver(readback))
        result = assess(normalized(self.docs, [entry]))
        self.assertEqual(result.statuses[READBACK].result, "unknown")
        self.assertIn("waiver.forbidden", codes(result.gate("concept"), "error"), "forbidden at every stage")
        for change in ({"waiver_policy": "forbidden"}, {"risk": {"severity": "critical", "consequence": "TST injury"}}):
            with self.subTest(change=change):
                docs = copy.deepcopy(self.docs)
                docs["requirements.yaml"]["requirements"][0].update(change)
                subject = {"product": True, "requirements": ["REQ-001"]}
                entry = acceptance.entry(normalized(docs), "EV-005", subject, "simulation_supported", "waived",
                                         requirement="REQ-001", waiver=acceptance.waiver(subject))
                result = assess(normalized(docs, [entry]))
                self.assertEqual(result.statuses[SIMULATION].result, "unknown")
                self.assertIn("waiver.forbidden", codes(result.findings))


class CriticalFindings(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = documents("working_prototype")
        self.base = normalized(self.docs)
        self.finding = {"id": "overhang_1", "code": "process.fdm.overhang", "obligation": SUPPORT,
                        "subject": {"PN": "TST-0001", "operation": "print"}, "severity": "critical", "outcome": "fail",
                        "measured": fx.quantity(70, "deg"), "criterion": fx.criterion("overhang_angle", "<=", 45, "deg"),
                        "method": {"name": "TST synthetic check"}, "uncertainty": "TST", "consequence": "TST: the arm sags",
                        "recheck": {"families": ["process.fdm.support"], "earliest_stage": "detail"}}

    def result(self, *dispositions: dict[str, Any], docs: dict[str, Any] | None = None) -> Any:
        """The assessment with a producer packet that fails SUPPORT with the critical finding."""
        docs = docs or self.docs
        record = normalized(docs, dispositions=list(dispositions))
        data = acceptance.producer_packet(self.base, findings=(self.finding,))
        for outcome in data["outcomes"]:
            if outcome["obligation"] == SUPPORT:
                outcome["outcome"] = "fail"
        data["result"] = "fail"
        return assess(record, evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64, data))

    def test_a_finding_that_contradicts_its_outcome_voids_the_packet(self) -> None:
        data = acceptance.producer_packet(self.base, findings=(self.finding,))
        result = assess(self.base, evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64, data))
        self.assertIn("packet.invalid", codes(result.findings), "a passing outcome cannot mask a critical failure")
        self.assertEqual(result.statuses[SUPPORT].result, "unknown")

    def disposition(self, status: str, **extra: Any) -> dict[str, Any]:
        return {"finding": "overhang_1", "producer": {"bundle": "hw/checks/v1/tst", "manifest_sha256": "b" * 64},
                "status": status, "reason": "TST", **extra}

    def test_an_unresolved_critical_finding_blocks_freeze_and_release(self) -> None:
        result = self.result()
        self.assertIn("finding.critical", codes(result.gate("design_freeze"), "error"))
        self.assertIn("finding.critical", codes(result.gate("release"), "error"))
        declined = self.result(self.disposition("declined", decision="DR-001"))
        self.assertIn("finding.critical", codes(declined.gate("release"), "error"), "declining is not resolving")

    def test_an_accepted_waiver_settles_it_and_the_obligation_stays_waived(self) -> None:
        subject = {"PN": "TST-0001", "operation": "print"}
        result = self.result(self.disposition("accepted_waiver", decision="DR-002",
                                              waiver=acceptance.waiver(subject, obligation=SUPPORT)))
        self.assertEqual(result.critical, ())
        self.assertEqual(result.statuses[SUPPORT].result, "waived")

    def test_a_safety_critical_critical_finding_cannot_be_waived(self) -> None:
        docs = documents("safety_critical")
        subject = {"PN": "TST-0001", "operation": "print"}
        result = self.result(self.disposition("accepted_waiver", decision="DR-002",
                                              waiver=acceptance.waiver(subject, obligation=SUPPORT)), docs=docs)
        self.assertEqual(len(result.critical), 1)
        self.assertIn("waiver.forbidden", codes(result.findings))


class ProducerPackets(unittest.TestCase):
    def setUp(self) -> None:
        self.record = normalized(documents())

    def test_a_packet_carries_no_version_of_its_own_its_path_binds_it(self) -> None:
        data = acceptance.producer_packet(self.record)
        self.assertNotIn("version", data)
        result = assess(self.record, evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64, data))
        self.assertNotIn("packet.invalid", codes(result.findings))
        self.assertEqual(result.statuses[READBACK].result, "pass")

    def test_a_packet_contradicting_itself_is_refused(self) -> None:
        lying = acceptance.producer_packet(self.record, complete=False)
        lying["complete"] = True
        mismatched = acceptance.producer_packet(self.record)
        mismatched["result"] = "unknown"
        for data in (evidence.ProducerPacket("hw/checks/v1/x", "b" * 64, lying),
                     evidence.ProducerPacket("hw/checks/v1/y", "b" * 64, mismatched)):
            with self.subTest(data=data.bundle):
                result = assess(self.record, data)
                self.assertIn("packet.invalid", codes(result.findings))
                self.assertFalse(result.complete)
                self.assertEqual(result.statuses[READBACK].result, "unknown")

    def test_a_partial_packet_counts_what_it_covers_and_makes_the_assessment_partial(self) -> None:
        result = assess(self.record, packet(self.record, complete=False))
        self.assertFalse(result.complete)
        self.assertNotIn("packet.invalid", codes(result.findings))
        self.assertEqual(result.statuses[READBACK].result, "pass")


class PacketFiles(unittest.TestCase):
    """A bundle under hw/checks/<V>/ that is no readable, sealed required-check packet is reported, never
    silently dropped; and a packet that breaks its schema is never published."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-evidence-test-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "hw"
        self.record = normalized(documents())

    def bundle(self, subject: str, result: str, manifest: bool = True) -> None:
        folder = self.hw / "checks" / "v1" / subject
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(result, encoding="utf-8")
        if manifest:
            (folder / "manifest.json").write_text("{}\n", encoding="utf-8")

    def test_an_unreadable_unsealed_or_non_packet_result_is_packet_invalid(self) -> None:
        self.bundle("broken", "{not json")
        self.bundle("legacy", json.dumps({"status": "pass"}))
        self.bundle("unsealed", json.dumps(acceptance.producer_packet(self.record)), manifest=False)
        packets, findings = evidence.collect_packets(self.hw, "v1", V1)
        self.assertEqual(packets, [])
        found = {f.path: f.message for f in findings if f.code == "packet.invalid"}
        self.assertEqual(set(found), {"hw/checks/v1/broken", "hw/checks/v1/legacy", "hw/checks/v1/unsealed"})
        self.assertIn("cannot read result.json", found["hw/checks/v1/broken"])
        self.assertIn("no expected and outcomes", found["hw/checks/v1/legacy"])
        self.assertIn("no manifest.json", found["hw/checks/v1/unsealed"])

    def test_emit_refuses_a_packet_that_breaks_its_schema_and_writes_nothing(self) -> None:
        good = acceptance.producer_packet(self.record)
        check_packet.validate(good)
        bad = {**good, "result": "maybe"}
        with self.assertRaisesRegex(check_packet.PacketError, "manufacturing-check-result.schema.json: result"):
            check_packet.emit(acceptance.layout, self.hw, "v1", "tst", "tst", bad, {}, "tst.json", {}, out=None,
                              replace=False, record_version=mi.RECORD_VERSION)
        self.assertFalse((self.hw / "checks").exists())
        self.assertFalse((self.hw.parent / ".cad-work").exists())


def joint_ready(docs: dict[str, Any]) -> dict[str, Any]:
    """The TST press fit with the joint evidence assembly_operations.check_joints passes: a sourced retention
    test, a known service temperature and the printed host's datasheet temperature limit above it (synthetic values)."""
    docs["assembly.yaml"]["operations"][0]["retention"] = fx.known("TST press-fit retention test", "measured",
                                                                   [fx.source("test", "TST retention coupon")])
    docs["product.yaml"]["use_case"]["environment"]["temperature"] = fx.known(fx.quantity(lower=15, upper=30, units="deg_C"))
    host = next(p for p in docs["manufacturing/materials.yaml"]["profiles"] if p["id"] == "tst_polymer_printed")
    host["properties"].append(fx.material_property("max_service_temperature", 60, "deg_C", orientation=fx.known("XY"),
                                                   basis="supplier_typical",
                                                   sources=[fx.source("datasheet", "TST polymer datasheet")]))
    return docs


class ProgressiveGates(unittest.TestCase):
    def test_detail_requires_due_checks_and_leaves_later_ones(self) -> None:
        record = normalized(joint_ready(documents("working_prototype")))
        result = assess(record, packet(record, obligations=[o for o in mi.required_checks(record)
                                                             if mi.STAGES.index(o.stage) <= mi.STAGES.index("detail")]))
        self.assertEqual(result.statuses["assembly.joint@op:fit_bearing"].result, "pass")
        self.assertEqual(codes(result.gate("detail"), "error"), set(), [f.message for f in result.gate("detail")])
        self.assertIn(STRENGTH, {f.obligation for f in result.gate("analysis") if f.severity == "error"})

    def test_the_joint_is_judged_from_the_record_and_stays_unknown_without_sourced_evidence(self) -> None:
        """assembly.joint has no producer packet: check_joints judges the declared joint facts on every read, an
        unsourced retention keeps it unknown (blocking from detail), and a packet cannot claim it."""
        record = normalized(documents("working_prototype"))
        joint = "assembly.joint@op:fit_bearing"
        claimed = evidence.ProducerPacket("hw/checks/v1/tst", "b" * 64, acceptance.producer_packet(
            record, obligations=[o for o in mi.required_checks(record) if o.id != joint]))
        claimed.data["expected"].append(next(o for o in mi.required_checks(record) if o.id == joint).as_dict())
        claimed.data["outcomes"].append({"obligation": joint, "outcome": "pass", "level": "process_planned",
                                         "method": "TST synthetic check", "coverage": "TST"})
        result = assess(record, claimed)
        status = result.statuses[joint]
        self.assertEqual((status.result, status.sources), ("unknown", ("record",)))
        self.assertIn("retention", " ".join(status.reasons))
        self.assertIn("packet.unexpected", codes(result.findings))
        self.assertIn(joint, {f.obligation for f in result.gate("detail") if f.severity == "error"})

    def test_a_failure_blocks_even_while_exploring(self) -> None:
        record = normalized(documents())
        result = assess(record, packet(record, outcome="fail"))
        self.assertIn("gate.fail", codes(result.gate("concept"), "error"))

    def test_a_freeze_needs_a_use_case_fit_for_the_final_choice(self) -> None:
        record = normalized(documents())
        self.assertIn("gate.use_case", codes(assess(record, packet(record)).gate("design_freeze"), "error"))

    def test_a_record_of_an_unsupported_version_gets_one_version_gate(self) -> None:
        old = mi.normalize_record({"product.yaml": {"id": "old", "flow": {"stage": "parts"}}})
        gate = evidence.assess(old).gate("parts")
        self.assertEqual([f.code for f in gate], ["gate.record"])
        self.assertIn("record_version None is not supported", gate[0].message)


class ReleasePolicy(unittest.TestCase):
    def released(self, service_class: str | None, *entries_for: Any) -> Any:
        docs = documents(service_class)
        base = normalized(docs)
        entries = [make(base) for make in entries_for]
        record = normalized(docs, entries)
        return assess(record, packet(base)).release()

    def trial_waiver(self, base: Any) -> dict[str, Any]:
        subject = {"PN": "TST-0001", "operation": "print"}
        return acceptance.entry(base, "EV-003", subject, "physically_validated", "waived", obligation=TRIAL,
                                waiver=acceptance.waiver(subject))

    def test_an_unknown_service_class_blocks_the_release(self) -> None:
        self.assertIn("release.service_class", codes(self.released(None).findings))

    def test_an_appearance_release_leaves_physical_and_engineering_obligations_open_and_unclaimed(self) -> None:
        policy = self.released("appearance_concept")
        blocking = {f.obligation for f in policy.blocking}
        self.assertNotIn(CREEP, blocking)
        self.assertNotIn(STRENGTH, blocking)
        self.assertIn(CREEP, policy.open_obligations)
        self.assertTrue(evidence.in_release_scope({"family": "requirement.physically_validated",
                                                   "level": "physically_validated"}, "appearance_concept"),
                        "an approved requirement's evidence is always in scope")
        self.assertEqual(policy.blocking, ())
        self.assertEqual(policy.scope["service_class"], "appearance_concept")

    def test_a_release_of_every_service_class_blocks_on_an_unresolved_or_failing_3mf_export(self) -> None:
        """export.3mf is a make-stage check: the lower service classes list its family in the release policy,
        so a forgotten, stale or failing export check blocks them like cad.readback does."""
        owed = {"id": "export.3mf@TST-0001", "family": "export.3mf", "subject": {"PN": "TST-0001"},
                "level": "cad_valid", "stage": "layout", "basis": "TST-0001: part.3mf"}
        for service_class in ("appearance_concept", "fit_assembly", "functional_demo", "working_prototype",
                              "production", "safety_critical"):
            for result, code in (("unknown", "gate.unresolved"), ("stale", "gate.stale"), ("fail", "gate.fail"),
                                 ("pass", None)):
                with self.subTest(service_class=service_class, result=result):
                    found = evidence.obligation_gate([owed], {owed["id"]: result}, "release", service_class)
                    self.assertEqual([(f.code, f.severity, f.obligation) for f in found],
                                     [(code, "error", owed["id"])] if code else [])

    def test_a_fit_prototype_needs_its_trial_tested_or_waived_as_a_trial(self) -> None:
        self.assertIn(TRIAL, {f.obligation for f in self.released("fit_assembly").blocking})
        policy = self.released("fit_assembly", self.trial_waiver)
        self.assertNotIn(TRIAL, {f.obligation for f in policy.blocking})
        self.assertTrue(policy.trial)
        self.assertTrue(policy.scope["trial"])
        self.assertEqual(policy.waivers[0]["decision"], "DR-002")
        self.assertIn(TRIAL, policy.open_obligations, "a waived trial stays open, never pass")

    def test_production_is_never_an_unvalidated_trial_and_safety_critical_takes_no_waiver(self) -> None:
        self.assertIn("release.trial_not_permitted", codes(self.released("production", self.trial_waiver).findings))
        self.assertIn("release.waiver_forbidden", codes(self.released("safety_critical", self.trial_waiver).findings))

    def test_claims_list_only_passing_levels_the_class_may_claim(self) -> None:
        def simulation(base: Any) -> dict[str, Any]:
            return acceptance.entry(base, "EV-001", {"product": True, "requirements": ["REQ-001"]}, "simulation_supported",
                                    requirement="REQ-001", version="v1", manifest_sha256=V1)
        appearance = self.released("appearance_concept", simulation).claims["REQ-001"]
        self.assertNotIn("simulation_supported", appearance, "an appearance release claims no engineering evidence")
        self.assertIn("cad_valid", appearance)
        self.assertIn("simulation_supported", self.released("working_prototype", simulation).claims["REQ-001"])


class AcceptanceDigest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-evidence-test-")
        self.addCleanup(temporary.cleanup)
        self.hw = fx.write_record(Path(temporary.name) / "hw", fx.tst_record())
        self.record = impact.read_record(self.hw)

    def inventory(self) -> dict[str, str]:
        return evidence.acceptance_inventory(self.hw, impact.read_record(self.hw))

    def test_the_inventory_covers_evidence_and_sources_but_not_workflow_or_decisions(self) -> None:
        inventory = self.inventory()
        self.assertEqual(set(inventory), {"hw/verification.csv", "hw/manufacturing/sources/tst-sheet.pdf"})
        digest = evidence.acceptance_digest(inventory)
        (self.hw / "decisions" / "DR-001.md").write_text("Status: APPROVED\n\n# changed\n", encoding="utf-8")
        product = self.hw / "product.yaml"
        product.write_text(product.read_text(encoding="utf-8").replace("stage: parts", "stage: detail"), encoding="utf-8")
        self.assertEqual(evidence.acceptance_digest(self.inventory()), digest)
        acceptance.write_ledger(self.hw, [])
        self.assertNotEqual(evidence.acceptance_digest(self.inventory()), digest)

    def test_a_missing_linked_or_escaping_path_refuses(self) -> None:
        source = self.hw / "manufacturing" / "sources" / "tst-sheet.pdf"
        source.unlink()
        with self.assertRaisesRegex(evidence.EvidenceError, "missing"):
            self.inventory()
        source.symlink_to(self.hw / "verification.csv")
        with self.assertRaisesRegex(evidence.EvidenceError, "symbolic link"):
            self.inventory()
        source.unlink()
        source.write_bytes(b"%PDF-1.4 TST fixture datasheet\n")
        entry = acceptance.entry(self.record, "EV-001", {"product": True, "requirements": ["REQ-001"]}, "cad_valid",
                                 requirement="REQ-001", version="v1", manifest_sha256=V1,
                                 artifacts=["hw/../outside.txt"])
        acceptance.write_ledger(self.hw, [entry])
        with self.assertRaisesRegex(evidence.EvidenceError, "not a normalized path"):
            self.inventory()


class StampedPacket(unittest.TestCase):
    """What cad-recheck checks before it stamps: the packet is this record's, complete, at this stage."""

    def setUp(self) -> None:
        self.record = normalized(documents())
        self.digest = "d" * 64
        self.selection_digest = evidence.selection.input_digest(documents())
        self.packet = assess(self.record, packet(self.record), selection_sha256=self.selection_digest).packet("concept",
                                                                                                           self.digest)

    def test_the_packet_of_this_record_and_stage_has_no_problem(self) -> None:
        self.assertEqual(evidence.packet_problems(self.packet, record=self.record, record_sha256=self.digest,
                                                  stage="concept"), [])
        self.assertEqual(evidence.packet_blocking(self.packet, record=self.record, stage="concept",
                                                  selection_sha256=self.selection_digest), [])

    def test_another_record_stage_or_a_partial_packet_cannot_stamp(self) -> None:
        self.assertIn("another record", " ".join(evidence.packet_problems(
            self.packet, record=self.record, record_sha256="e" * 64, stage="concept")))
        self.assertIn("stage concept, not detail", " ".join(evidence.packet_problems(
            self.packet, record=self.record, record_sha256=self.digest, stage="detail")))
        partial = {**self.packet, "complete": False}
        self.assertIn("partial", " ".join(evidence.packet_problems(partial, record=self.record, record_sha256=self.digest,
                                                                    stage="concept")))
        missing = {**self.packet, "statuses": {k: v for k, v in self.packet["statuses"].items() if k != READBACK}}
        self.assertIn("missing expected check", " ".join(evidence.packet_problems(
            missing, record=self.record, record_sha256=self.digest, stage="concept")))
        self.assertIn("not an evidence packet", evidence.packet_problems({"all_passed": True}, record=self.record,
                                                                         record_sha256=self.digest, stage="concept")[0])

    def test_a_packet_flagged_passing_cannot_hide_a_due_unknown(self) -> None:
        forged = copy.deepcopy(assess(self.record).packet("parts", self.digest))
        forged["gate"] = {"stage": "parts", "passed": True, "findings": []}
        self.assertTrue(evidence.packet_blocking(forged, record=self.record, stage="parts",
                                                 selection_sha256=self.selection_digest))

    def test_a_packet_flagged_passing_cannot_hide_a_selection_contradiction(self) -> None:
        docs, digest = recorded(scenarios.mandatory_vs_score())
        record = selected(docs)
        forged = copy.deepcopy(assess(record, selection_sha256=digest).packet("intent", self.digest))
        self.assertIn("gate.selection", {item["code"] for item in forged["gate"]["findings"] if item["severity"] == "error"})
        forged["gate"] = {"stage": "intent", "passed": True, "findings": []}
        blocking = evidence.packet_blocking(forged, record=record, stage="intent", selection_sha256=digest)
        self.assertTrue(any(item.startswith("gate.selection: selection.final_unsupported") for item in blocking), blocking)
        self.assertEqual(forged["selection"]["status"], "blocked")


scenarios = acceptance.selection_scenarios()
recorded = acceptance.recorded_selection


def selected(docs: dict[str, Any]) -> Any:
    record = mi.normalize_record(copy.deepcopy(docs))
    assert not record.problems, [p.message for p in record.problems]
    return record


class SelectionGate(unittest.TestCase):
    """The INTENT gate on selection.py's report: a recorded final choice must be one the assessment supports,
    on current inputs and the user's approval; an open choice is exploration until the freeze."""

    def gate(self, docs: dict[str, Any], digest: str | None, stage: str, *, approved: bool | None = True) -> list[Any]:
        report = evidence.selection.assess(selected(docs), input_sha256=digest)
        return evidence.selection_gate(report, stage, approved=approved)

    def test_nothing_is_gated_before_intent(self) -> None:
        docs, digest = recorded(scenarios.mandatory_vs_score())
        self.assertEqual(self.gate(docs, digest, "ground"), [])

    def test_a_confirmed_supported_choice_passes_every_stage(self) -> None:
        docs, digest = recorded(scenarios.qualified_polymer_cover(), primary="printed_cover")
        for stage in ("intent", "layout", "design_freeze", "release"):
            self.assertEqual(self.gate(docs, digest, stage), [], stage)
        gate = assess(selected(docs), selection_sha256=digest).gate("design_freeze")
        self.assertFalse({f.code for f in gate} & {"gate.selection", "gate.selection_approval"})

    def test_a_confirmed_choice_on_changed_inputs_blocks_at_every_stage(self) -> None:
        docs, _ = recorded(scenarios.qualified_polymer_cover(), primary="printed_cover")
        docs["requirements.yaml"]["requirements"][0]["text"] = "TST: the requirement changed after the confirmation"
        changed = evidence.selection.input_digest(docs)
        for stage in ("intent", "parts"):
            found = self.gate(docs, changed, stage)
            self.assertEqual([(f.code, f.severity) for f in found], [("gate.selection", "error")], stage)
            self.assertIn("stale", found[0].message)
        unchecked = self.gate(docs, None, "intent")
        self.assertEqual([(f.code, f.severity) for f in unchecked], [("gate.selection", "error")])
        self.assertIn("was not checked", unchecked[0].message)

    def test_a_confirmation_that_is_not_the_users_approval_blocks(self) -> None:
        docs, digest = recorded(scenarios.qualified_polymer_cover(), primary="printed_cover", decision="DR-009")
        gate = assess(selected(docs), selection_sha256=digest).gate("intent")
        self.assertIn("gate.selection_approval", codes(gate, "error"))

    def test_a_recorded_final_choice_the_assessment_refuses_blocks_even_while_exploring(self) -> None:
        docs, digest = recorded(scenarios.mandatory_vs_score())  # selection.yaml confirms the eliminated cheapest lever
        messages = [f.message for f in self.gate(docs, digest, "intent") if f.severity == "error"]
        for code in ("selection.final_unsupported", "selection.recorded_recommendation_eliminated",
                     "selection.recorded_route_eliminated"):
            self.assertTrue(any(m.startswith(code) for m in messages), (code, messages))

    def test_an_eliminated_record_route_blocks_even_while_exploring(self) -> None:
        docs, digest = recorded(scenarios.transparent_cover())  # the window is recorded as a 'clear' FDM print
        errors = [f for f in self.gate(docs, digest, "intent") if f.severity == "error"]
        self.assertTrue(errors)
        self.assertTrue(all(f.message.startswith("selection.recorded_route_eliminated (TST-0601)") for f in errors), errors)

    def test_an_open_choice_is_exploration_until_the_freeze(self) -> None:
        docs, digest = recorded(scenarios.unassessed_case())  # conditional: the use case is not assessed
        self.assertEqual({(f.code, f.severity) for f in self.gate(docs, digest, "intent")}, {("gate.selection", "warning")})
        self.assertEqual({(f.code, f.severity) for f in self.gate(docs, digest, "design_freeze")}, {("gate.selection", "error")})
        unconfirmed, digest = recorded(scenarios.qualified_polymer_cover())  # final-ready, but not confirmed
        self.assertEqual({f.severity for f in self.gate(unconfirmed, digest, "concept")}, {"warning"})
        found = self.gate(unconfirmed, digest, "release")
        self.assertEqual({(f.code, f.severity) for f in found}, {("gate.selection", "error")})
        self.assertIn("not confirmed", found[0].message)

    def test_a_record_without_candidates_is_exploration_until_the_freeze_and_then_blocks(self) -> None:
        """No material and process selection recorded is an unknown like any other: a warning while exploring,
        an error at the design freeze and the release (decision 1 of the manufacturing-intent plan review)."""
        docs = documents("production")
        result = assess(normalized(docs), selection_sha256=evidence.selection.input_digest(docs))
        for stage, severity in (("intent", "warning"), ("detail", "warning"), ("design_freeze", "error"), ("release", "error")):
            found = [f for f in result.gate(stage) if f.code == "gate.selection"]
            self.assertEqual({f.severity for f in found}, {severity}, stage)
            self.assertTrue(any("no material, process and architecture selection is recorded" in f.message for f in found),
                            [f.message for f in found])

    def test_a_made_part_no_candidate_covers_is_exploration_until_the_freeze_and_then_blocks(self) -> None:
        """A freeze and a release need a confirmed selection for every made part (decision 1): a made part no
        candidate names has an unknown material and process choice, a warning while exploring and an error from
        the design freeze, even beside a confirmed final choice for the others. A catalogue buy needs none."""
        docs = scenarios.qualified_polymer_cover()
        docs["parts/TST-0302/part.yaml"] = scenarios.made_part("TST-0302", "TST bezel", "fdm", "tst_polymer_c_printed",
                                                               "tst_printer")
        docs["parts/TST-0303/part.yaml"] = fx.part("TST-0303", "TST screw", process="purchased", make_buy="buy")
        docs, digest = recorded(docs, primary="printed_cover")
        report = evidence.selection.assess(selected(docs), input_sha256=digest)
        self.assertEqual((report["status"], report["coverage"]), ("final_ready", {"made": ["TST-0301", "TST-0302"],
                                                                                  "unselected": ["TST-0302"]}))
        for stage, severity in (("intent", "warning"), ("detail", "warning"), ("design_freeze", "error"), ("release", "error")):
            found = self.gate(docs, digest, stage)
            self.assertEqual([(f.code, f.severity) for f in found], [("gate.selection", severity)], stage)
            self.assertIn("TST-0302 is a made part no selection candidate covers", found[0].message)
        blocking = evidence.packet_blocking({}, record=selected(docs), stage="design_freeze", selection_sha256=digest)
        self.assertTrue(any("TST-0302 is a made part no selection candidate covers" in item for item in blocking), blocking)


class Producer:
    """A fake producer step that passed and reported a JSON result."""

    def ended(self) -> bool:
        return True

    def stop(self) -> int:
        return 0

    def result(self) -> dict[str, Any]:
        return {"status": "pass", "reported": True}


def launcher(path: Path, body: str) -> Path:
    """A stand-in for cad-flow run.py: `body` runs with sys.argv[1] the producer script that the caller names."""
    path.write_text("import json, sys\n" + body, encoding="utf-8")
    return path


PRODUCER = """# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
import importlib.util
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("emit", SKILLS / "cad-record" / "scripts" / "emit.py")
emit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emit)
hw = Path(sys.argv[sys.argv.index("--hw") + 1] if "--hw" in sys.argv else sys.argv[1])  # render.py takes hw first
result = %(result)s
result.setdefault("notes", ["a long note that makes the result longer than its compact summary"] * 30)
emit.emit(result, tool="fake", name="fake", code=%(code)d, scratch=emit.work_dir(hw))
sys.exit(%(code)d)
"""


def real_skills(root: Path, producers: dict[str, tuple[str, dict[str, Any], int]]) -> Path:
    """A skills tree with the real cad-flow run.py, its scriptenv and the real emit.py, and fake producers
    that print through emit.py as the real ones do: `producers` maps a script path to (label, result, exit)."""
    skills = HERE.parents[1]
    tree = root / "skills"
    for source in (skills / "cad-flow" / "scripts" / "run.py", skills / "cad-record" / "scripts" / "emit.py",
                   skills / "cad-model" / "scripts" / "cadmodel" / "__init__.py",
                   skills / "cad-model" / "scripts" / "cadmodel" / "scriptenv.py"):
        target = tree / source.relative_to(skills)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    passing = {"status": "pass"}
    for script in ("cad-design/scripts/form_check.py", "cad-model/scripts/cad_model.py", "cad-render/scripts/render.py",
                   "cad-motion/scripts/sweep.py", "cad-motion/scripts/motion.py"):
        _, result, code = producers.get(script, ("", passing, 0))
        target = tree / script
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PRODUCER % {"result": repr(result), "code": code}, encoding="utf-8")
    return tree / "cad-flow" / "scripts" / "run.py"


PASSING = "print(json.dumps({'status': 'pass'}))\n"


class BuiltRecord(unittest.TestCase):
    """The TST record built as v1, with no independent movable joint."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-evidence-run-test-")
        self.addCleanup(temporary.cleanup)
        self.hw = fx.write_record(Path(temporary.name) / "hw", fx.tst_record())
        for pn in ("TST-0001", "TST-0002", "TST-0004"):
            (self.hw / "parts" / pn / "model.py").write_text(f"# {pn}\n", encoding="utf-8")
        folder = self.hw / "versions" / "v1"
        pns = sorted(p.parent.name for p in (self.hw / "parts").glob("*/part.yaml"))
        for name in acceptance.layout.snapshot_names(self.hw, pns):
            target = folder / "record" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.hw / name).read_bytes())
        files = {p.relative_to(folder).as_posix(): acceptance.sha(p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}
        parts = {p.parent.name: {"source_sha256": acceptance.sha(p.read_bytes())} for p in sorted(self.hw.glob("parts/*/model.py"))}
        (folder / "manifest.json").write_text(json.dumps({"label": "v1", "parts": parts, "joints": [], "files": files}),
                                              encoding="utf-8")
        self.spawned: list[str] = []

    def spawn(self, step: Any) -> Producer:
        self.spawned.append(step.id)
        return Producer()

    def run_scope(self, scope: str, stage: str) -> tuple[int, dict[str, Any]]:
        return evidence.run(self.hw, "v1", scope, stage=stage, spawn=self.spawn, strays=list)

    def pass_every_producer_obligation(self) -> None:
        acceptance.publish_packet(self.hw, "v1", acceptance.producer_packet(impact.read_record(self.hw)))


class EvidenceRun(BuiltRecord):
    """`evidence.py run` with its producers faked."""

    def test_every_matrix_row_is_a_step_some_scope_runs(self) -> None:
        self.assertEqual(set(evidence.MATRIX), set(fail_fast.STEP_ORDER))
        for ident, row in evidence.MATRIX.items():
            with self.subTest(ident):
                self.assertTrue({"R", "C"} & set(row.cells), f"{ident} runs in no scope")

    def test_the_packet_of_a_run_is_the_packet_check_prints_for_the_same_inputs(self) -> None:
        self.pass_every_producer_obligation()
        code, report = self.run_scope("commit", "parts")
        out = io.StringIO()
        with redirect_stdout(out):
            evidence.main(["check", "--hw", str(self.hw), "--version", "v1", "--stage", "parts"])
        self.assertEqual((code, report["status"], report["stopped_at"]), (0, "pass", None))
        self.assertEqual(report["packet"], json.loads(out.getvalue()))
        schema = json.loads((HERE.parent / "schemas" / "evidence-run.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([e.message for e in Draft202012Validator(schema).iter_errors(report)], [])

    def test_a_c_step_runs_only_while_an_obligation_it_covers_is_stale_or_open_and_due(self) -> None:
        def material_changed() -> None:
            self.pass_every_producer_obligation()
            materials = self.hw / "manufacturing" / "materials.yaml"
            data = yaml.safe_load(materials.read_text(encoding="utf-8"))
            data["profiles"][0]["revision"] = 2
            materials.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        cases = {  # the TST record's form-check obligations are due from parts
            "not yet due": ("layout", lambda: None, ["static.changed", "render"]),
            "due and unknown": ("parts", lambda: None, ["form", "static.changed", "render"]),
            "due and passed": ("parts", self.pass_every_producer_obligation, ["static.changed", "render"]),
            "passed, then a material changed": ("parts", material_changed, ["form", "static.changed", "render"]),
        }
        for label, (stage, change, spawned) in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.hw / "checks", ignore_errors=True)
                change()
                self.spawned = []
                code, report = self.run_scope("commit", stage)
                self.assertEqual((code, self.spawned), (0, spawned))
                self.assertEqual({s["id"]: s["status"] for s in report["steps"] if s["id"].startswith(("sweep", "motion"))},
                                 {"sweep.smoke": "skipped", "motion.default": "skipped"})

    def test_a_flow_edit_stales_no_producer_packet(self) -> None:
        self.pass_every_producer_obligation()
        _, before = self.run_scope("commit", "parts")
        product = self.hw / "product.yaml"
        data = yaml.safe_load(product.read_text(encoding="utf-8"))
        data["flow"].update(stage="detail", recheck_from="detail")
        product.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.spawned = []
        _, after = self.run_scope("commit", "parts")
        self.assertNotEqual(before["record_sha256"], after["record_sha256"], "flow is a record input")
        self.assertEqual(after["packet"]["statuses"], before["packet"]["statuses"])
        self.assertNotIn("form", self.spawned, "the form check is not due again")

    def test_a_version_that_is_not_built_or_fails_its_manifest_is_refused_as_stale_and_runs_nothing(self) -> None:
        code, report = evidence.run(self.hw, "v2", "commit", stage="parts", spawn=self.spawn, strays=list)
        self.assertEqual((code, report["status"], report["steps"], report["packet"], self.spawned), (1, "refused", [], None, []))
        self.assertEqual([f["code"] for f in report["findings"]], ["run.not_built"])
        (self.hw / "versions" / "v1" / "record" / "product.yaml").write_text("edited\n", encoding="utf-8")
        code, report = self.run_scope("commit", "parts")
        self.assertEqual((code, report["status"], self.spawned), (1, "refused", []))
        self.assertIn("stale: build the version again", report["findings"][0]["message"])

    def test_a_record_version_other_than_2_is_refused_and_runs_nothing(self) -> None:
        product = self.hw / "product.yaml"
        original = yaml.safe_load(product.read_text(encoding="utf-8"))
        for version in (1, 3, None):
            with self.subTest(record_version=version):
                data = {key: value for key, value in original.items() if key != "record_version"}
                if version is not None:
                    data["record_version"] = version
                product.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
                code, report = self.run_scope("commit", "parts")
                self.assertEqual((code, report["status"], report["steps"], report["packet"], self.spawned),
                                 (1, "refused", [], None, []))
                self.assertEqual([f["code"] for f in report["findings"]], ["record.version_unsupported"])

    def test_a_full_run_whose_steps_pass_fails_when_the_packet_gate_blocks(self) -> None:
        code, report = self.run_scope("full", "parts")  # nothing shows the obligations due at parts
        self.assertEqual((code, report["status"], report["stopped_at"]), (1, "fail", None))
        self.assertEqual({step["status"] for step in report["steps"]} - {"skipped"}, {"pass"})
        self.assertFalse(report["packet"]["gate"]["passed"])

    def test_the_smoke_and_the_full_sweep_publish_to_different_bundles(self) -> None:
        manifest_path = self.hw / "versions" / "v1" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["joints"] = [{"id": "elbow", "type": "revolute", "min": 0, "max": 90, "nominal": 0}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        def case(argv: list[str]) -> str:
            return argv[argv.index("--case") + 1] if "--case" in argv else "sweep"  # sweep.py's default case

        cases = {}
        for scope, ident in (("commit", "sweep.smoke"), ("full", "sweep.full")):
            _, report = self.run_scope(scope, "layout")
            cases[ident] = case(next(step["argv"] for step in report["steps"] if step["id"] == ident))
        self.assertNotEqual(cases["sweep.smoke"], cases["sweep.full"])

    def test_a_commit_run_without_stage_uses_the_flow_stage(self) -> None:
        product = self.hw / "product.yaml"
        product.write_text(product.read_text(encoding="utf-8").replace("stage: parts", "stage: layout"), encoding="utf-8")
        code, report = evidence.run(self.hw, "v1", "commit", spawn=self.spawn, strays=list)
        form = next(step for step in report["steps"] if step["id"] == "form")
        self.assertEqual((report["stage"], form["argv"][form["argv"].index("--fidelity") + 1], report["packet"]["stage"]),
                         ("layout", "F1", "layout"))

    def test_the_full_scope_refuses_to_default_to_an_advanced_flow_stage(self) -> None:
        self.assertEqual(impact.plain(impact.read_record(self.hw).product)["flow"]["stage"], "parts")  # past the layout gate
        with self.assertRaisesRegex(ValueError, "--stage"):
            evidence.run(self.hw, "v1", "full", spawn=self.spawn, strays=list)
        self.assertEqual(self.spawned, [])
        out = io.StringIO()
        with redirect_stdout(out):
            code = evidence.main(["run", "--hw", str(self.hw), "--version", "v1", "--scope", "full"])
        self.assertEqual((code, json.loads(out.getvalue())["status"]), (2, "error"))

    def test_a_full_run_after_provisional_advancement_evaluates_the_stage_of_its_gate(self) -> None:
        code, report = self.run_scope("full", "layout")  # flow.stage is already parts
        form = next(step for step in report["steps"] if step["id"] == "form")
        self.assertEqual((report["stage"], form["argv"][form["argv"].index("--fidelity") + 1]), ("layout", "F1"))
        self.assertEqual(report["packet"]["stage"], "layout")

    def test_both_sweeps_forward_the_attachments_of_the_built_manifest(self) -> None:
        manifest_path = self.hw / "versions" / "v1" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["joints"] = [{"id": "elbow", "type": "revolute", "min": 0, "max": 90, "nominal": 0}]
        manifest["attach"] = ["TST-0002=TST-0001", "TST-0004=TST-0001"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for scope, ident in (("commit", "sweep.smoke"), ("full", "sweep.full")):
            with self.subTest(ident):
                _, report = self.run_scope(scope, "layout")
                argv = next(step["argv"] for step in report["steps"] if step["id"] == ident)
                forwarded = [argv[i + 1] for i, word in enumerate(argv) if word == "--attach"]
                self.assertEqual(forwarded, ["TST-0002=TST-0001", "TST-0004=TST-0001"])


class EvidenceRunProducers(BuiltRecord):
    """`evidence.py run` starting real processes through a stand-in for cad-flow run.py."""

    def run_with(self, body: str, scope: str, stage: str) -> tuple[int, dict[str, Any]]:
        with mock.patch.object(evidence, "RUN_PY", launcher(self.hw.parent / "run.py", body)):
            return evidence.run(self.hw, "v1", scope, stage=stage, strays=list)

    def test_each_producer_runs_through_run_py_with_its_output_in_scratch(self) -> None:
        code, report = self.run_with("print(json.dumps({'status': 'fail', 'argv': sys.argv[1:]}))\nsys.exit(1)\n",
                                     "commit", "layout")
        self.assertEqual((code, report["status"], report["stopped_at"], report["packet"]), (1, "fail", "static.changed", None))
        step = next(item for item in report["steps"] if item["id"] == "static.changed")
        self.assertEqual((step["exit"], step["argv"][1:3]), (1, [str(self.hw.parent / "run.py"), "cad-model/scripts/cad_model.py"]))
        self.assertEqual(step["result"]["status"], "fail")
        output = self.hw.parent / step["result"]["stdout"]
        self.assertEqual(output.parent.parent, self.hw.parent / ".cad-work" / "evidence-run")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["argv"][0], "cad-model/scripts/cad_model.py")

    def test_a_producer_that_exits_0_without_a_json_report_gives_no_result(self) -> None:
        for label, body in (("empty", ""), ("not json", "print('done')\n"), ("not an object", "print('[1]')\n")):
            with self.subTest(label):
                code, report = self.run_with(body, "commit", "layout")
                step = next(item for item in report["steps"] if item["id"] == "static.changed")
                self.assertEqual((step["exit"], step["status"], code, report["status"]), (0, "no_result", 2, "no_result"))

    def test_a_form_check_open_only_on_obligations_not_yet_due_does_not_block(self) -> None:
        parts = next(o.id for o in mi.required_checks(impact.read_record(self.hw))
                     if o.family.startswith("process.") and o.stage == "parts")
        body = ("if sys.argv[1] != 'cad-design/scripts/form_check.py':\n    print(json.dumps({'status': 'pass'})); sys.exit(0)\n"
                f"print(json.dumps({{'status': 'pass', 'manufacturing': {{'status': 'unknown', "
                f"'open': [{{'obligation': {parts!r}, 'outcome': 'unknown'}}]}}}}))\nsys.exit(1)\n")  # form_check.py exits 1
        for stage, status, stopped in (("layout", "pass", None), ("parts", "fail", "form")):
            with self.subTest(stage):
                _, report = self.run_with(body, "full", stage)
                form = next(item for item in report["steps"] if item["id"] == "form")
                self.assertEqual((form["exit"], form["status"], report["stopped_at"]), (1, status, stopped))

    def run_real(self, producers: dict[str, tuple[str, dict[str, Any], int]], scope: str, stage: str) -> tuple[int, dict[str, Any]]:
        """`evidence.run` with the real run.py (default output mode) and producers that print through emit.py."""
        run_py = real_skills(self.hw.parent / "tree", producers)
        with mock.patch.object(evidence, "RUN_PY", run_py):
            return evidence.run(self.hw, "v1", scope, stage=stage, strays=list)

    def test_a_passing_static_check_through_the_real_launcher_gives_pass(self) -> None:
        code, report = self.run_real({}, "commit", "layout")
        statuses = {item["id"]: item["status"] for item in report["steps"]}
        self.assertEqual((code, report["status"], statuses["static.changed"]), (0, "pass", "pass"))
        self.assertEqual(report["steps"][0]["status"], "pass")

    def test_a_form_report_open_only_on_obligations_not_yet_due_does_not_block_through_the_real_launcher(self) -> None:
        parts = next(o.id for o in mi.required_checks(impact.read_record(self.hw))
                     if o.family.startswith("process.") and o.stage == "parts")
        form = {"status": "pass", "manufacturing": {"status": "unknown", "open": [{"obligation": parts, "outcome": "unknown"}]}}
        producers = {"cad-design/scripts/form_check.py": ("form", form, 1)}  # form_check.py exits 1
        for stage, status, stopped in (("layout", "pass", None), ("parts", "fail", "form")):
            with self.subTest(stage):
                _, report = self.run_real(producers, "full", stage)
                step = next(item for item in report["steps"] if item["id"] == "form")
                self.assertEqual((step["exit"], step["status"], report["stopped_at"]), (1, status, stopped))

    def form_blocks(self, report: dict[str, Any], stage: str) -> None:
        """A form_check.py exit 1 with `report` stops the run at the form step at `stage`, with no packet."""
        producers = {"cad-design/scripts/form_check.py": ("form", report, 1)}
        code, run_report = self.run_real(producers, "full", stage)
        form = next(item for item in run_report["steps"] if item["id"] == "form")
        self.assertEqual((code, form["exit"], form["status"], run_report["stopped_at"], run_report["packet"]),
                         (1, 1, "fail", "form", None))

    def test_a_fidelity_failing_form_report_blocks_even_when_its_open_obligations_are_not_yet_due(self) -> None:
        parts = next(o.id for o in mi.required_checks(impact.read_record(self.hw))
                     if o.family.startswith("process.") and o.stage == "parts")
        self.form_blocks({"status": "fail", "manufacturing": {"status": "unknown",
                                                              "open": [{"obligation": parts, "outcome": "unknown"}]}}, "layout")

    def test_a_failed_outcome_blocks_even_when_its_obligation_is_not_yet_due(self) -> None:
        parts = next(o.id for o in mi.required_checks(impact.read_record(self.hw))
                     if o.family.startswith("process.") and o.stage == "parts")
        self.form_blocks({"status": "pass", "manufacturing": {"status": "fail",
                                                              "open": [{"obligation": parts, "outcome": "fail"}]}}, "layout")


class EvidenceRunCli(BuiltRecord):
    """`evidence.py run` through its command line."""

    def main(self, *args: str) -> tuple[int, Any]:
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(evidence, "RUN_PY", launcher(self.hw.parent / "run.py", PASSING)):
            code = evidence.main(["run", "--hw", str(self.hw), "--version", "v1", *args])
        return code, json.loads(out.getvalue())

    def test_run_prints_its_report_writes_it_under_cad_work_and_exits_with_its_status(self) -> None:
        target = self.hw.parent / ".cad-work" / "runs" / "commit.json"
        code, report = self.main("--scope", "commit", "--stage", "layout", "--out", str(target))
        self.assertEqual((code, report["kind"], report["status"], report["scope"]), (0, "cad-evidence-run", "pass", "commit"))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), report)

    def test_an_out_path_outside_cad_work_is_a_usage_error_before_any_producer_starts(self) -> None:
        code, report = self.main("--scope", "commit", "--stage", "layout", "--out", str(self.hw / "run.json"))
        self.assertEqual((code, report["status"]), (2, "error"))
        self.assertIn("--out must be under", report["message"])
        self.assertFalse((self.hw.parent / ".cad-work" / "evidence-run").exists())

    def test_an_unknown_scope_is_a_usage_error(self) -> None:
        for scope in ("inner", "provisional"):
            with self.subTest(scope), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                evidence.main(["run", "--hw", str(self.hw), "--version", "v1", "--scope", scope])
            self.assertEqual(raised.exception.code, 2)

    def test_a_stray_run_ends_the_run_with_no_result_and_its_stop_command(self) -> None:
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)
        lifecycle = evidence._lifecycle()
        record = lifecycle.runs_dir(self.hw) / "orphan.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"schema": 1, "kind": "sweep", "run_id": "orphan", "host": socket.gethostname(),
                                      "pid": int(ended.stdout), "identity": "ended", "pgid": None, "argv": [], "started": "",
                                      "groups": [{"pgid": sleeper.pid, "identity": lifecycle.identity(sleeper.pid)}]}),
                          encoding="utf-8")
        code, report = self.main("--scope", "commit", "--stage", "layout")
        self.assertEqual((code, report["status"], report["stop_commands"]), (2, "no_result", [f"kill -TERM -- -{sleeper.pid}"]))
        self.assertEqual({s["status"] for s in report["steps"] if s["argv"] is not None} - {"skipped"}, {"stopped"})
        self.assertIsNone(sleeper.poll(), "the run signals no stray")


if __name__ == "__main__":
    unittest.main()
