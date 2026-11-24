#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""impact.py: dependency-domain fingerprints, what a change makes stale, the decisions it reopens, the
earliest stage it reopens without raising the recheck threshold, explicit carry-forward candidates, and
the selection compared by selection.py's own input digest.

Regression matrix row 13: sealed grade, route and orientation variants of a synthetic TST record make the
dependent FEA, fit, support, mass and test obligations and evidence stale, and never the unaffected ones.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock
import yaml

HERE = Path(__file__).resolve().parent


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402


acceptance = load("cad_record_acceptance_fixtures", HERE / "fixtures" / "acceptance.py")
fx, mi, impact = acceptance.fx, acceptance.mi, acceptance.impact
GEOMETRY = {"TST-0001": "1" * 64, "TST-0002": "2" * 64, "TST-0004": "4" * 64}


def documents() -> dict[str, Any]:
    return {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}


def normalized(docs: dict[str, Any]) -> Any:
    return mi.normalize_record(copy.deepcopy(docs))


def bracket(docs: dict[str, Any]) -> dict[str, Any]:
    return docs["parts/TST-0001/part.yaml"]["intent"]["route"][0]


class Fingerprints(unittest.TestCase):
    def test_each_record_domain_is_fingerprinted_and_stable(self) -> None:
        record = normalized(documents())
        prints = impact.fingerprints(record, {"PN": "TST-0001"}, GEOMETRY)
        self.assertEqual(set(prints), set(impact.DOMAINS) - {"lot"},
                         "the lot belongs to physical evidence; a made part's occurrences are its agreement's placements")
        self.assertEqual(prints, impact.fingerprints(normalized(documents()), {"PN": "TST-0001"}, GEOMETRY))
        self.assertEqual(impact.fingerprints(record, {"PN": "TST-0001", "operation": "print", "feature": "pivot_bore"},
                                             GEOMETRY), prints, "operations and features share their part's fingerprints")

    def test_the_evidence_ledger_is_never_a_dependency(self) -> None:
        docs = documents()
        before = impact.subject_fingerprints(normalized(docs), GEOMETRY)
        docs["manufacturing/evidence.yaml"] = {"entries": [acceptance.entry(normalized(docs), "EV-001", {"PN": "TST-0001"},
                                                                            "cad_valid", "planned", obligation="cad.readback@TST-0001")]}
        self.assertEqual(impact.subject_fingerprints(normalized(docs), GEOMETRY), before, "no ledger-rebuild recursion")


class Variants(unittest.TestCase):
    """A sealed grade, route or orientation variant of the bracket against the same record before it."""

    def setUp(self) -> None:
        self.docs = documents()
        self.before = normalized(self.docs)

    def compare(self, change: Any, geometry: dict[str, str] | None = None) -> Any:
        after = copy.deepcopy(self.docs)
        change(after)
        return impact.compare(self.before, normalized(after), before_geometry=GEOMETRY,
                              after_geometry=geometry or GEOMETRY, since="v1", version="v2")

    def assertStale(self, result: Any, stale: tuple[str, ...], kept: tuple[str, ...]) -> None:
        for ident in stale:
            self.assertIn(ident, result.stale_obligations, ident)
        for ident in kept:
            self.assertNotIn(ident, result.stale_obligations, ident)

    def test_a_grade_change_stales_engineering_fit_support_and_tests_not_geometry(self) -> None:
        def grade(docs: dict[str, Any]) -> None:
            docs["manufacturing/materials.yaml"]["profiles"][0]["grade"] = fx.known("TST other grade")
        result = self.compare(grade)
        self.assertEqual(result.changed["TST-0001"], ("material",))
        self.assertIn("material_condition", result.groups()["TST-0001"])
        self.assertStale(result, ("engineering.strength@TST-0001", "engineering.creep@TST-0001", "feature.fit@TST-0001#pivot_bore",
                                  "process.fdm.support@TST-0001/print", "process.fdm.trial@TST-0001/print"),
                         ("cad.readback@TST-0001", "cad.readback@TST-0002", "process.cnc.stock@TST-0002/turn"))
        self.assertEqual(result.earliest_stage, "parts")

    def test_a_route_change_stales_the_process_plan_and_its_consumers(self) -> None:
        def route(docs: dict[str, Any]) -> None:
            docs["manufacturing/capabilities.yaml"]["profiles"].append(fx.capability_profile("tst_printer_2", "fdm"))
            bracket(docs)["capability"] = "tst_printer_2"
        result = self.compare(route)
        self.assertTrue({"capability", "route"} <= set(result.changed["TST-0001"]))
        self.assertStale(result, ("process.fdm.geometry@TST-0001/print", "route.operation_plan@TST-0001/print",
                                  "feature.fit@TST-0001#pivot_bore", "process.reaming.allowance@TST-0001/ream"),
                         ("cad.readback@TST-0001", "process.laser.kerf@TST-0004/cut"))

    def test_an_orientation_change_stales_support_anisotropy_and_fit_and_reopens_its_approval(self) -> None:
        def orientation(docs: dict[str, Any]) -> None:
            bracket(docs)["orientation"]["rotation"] = {"axis": [1, 0, 0], "angle_deg": 90}
        result = self.compare(orientation)
        self.assertEqual(result.changed["TST-0001"], ("orientation",))
        self.assertStale(result, ("process.fdm.support@TST-0001/print", "engineering.anisotropy@TST-0001",
                                  "feature.fit@TST-0001#pivot_bore"),
                         ("cad.readback@TST-0001", "assembly.order@op:fit_bearing"))
        self.assertIn("DR-001", result.reopened_decisions)
        self.assertEqual(result.earliest_stage, "detail")

    def test_a_geometry_change_stales_the_readback(self) -> None:
        result = self.compare(lambda docs: None, geometry={**GEOMETRY, "TST-0001": "9" * 64})
        self.assertStale(result, ("cad.readback@TST-0001", "interface.fit@IF-001"), ("cad.readback@TST-0002",))
        self.assertEqual(result.earliest_stage, "layout")

    def test_a_declared_heat_set_hole_change_stales_its_declared_dimensions_check_and_not_the_readback(self) -> None:
        """The declared hole_d is an input of cad.declared_dimensions: changing it in interfaces.yaml, with the
        geometry unchanged, makes that obligation stale. The part read-back does not read it."""
        entry = {"pair": ["TST-0001", "TST-0004"], "hole_d": 4.0, "insert": "M3 x 5.7", "source": "https://example.com/insert"}
        self.docs["interfaces.yaml"]["interfaces"].append(
            fx.interface("IF-002", "TST-0001", "TST-0004", limits={"heat_set": [entry]}))
        self.before = normalized(self.docs)

        def widen(docs: dict[str, Any]) -> None:
            docs["interfaces.yaml"]["interfaces"][-1]["limits"]["heat_set"][0]["hole_d"] = 4.2
        result = self.compare(widen)
        self.assertStale(result, ("cad.declared_dimensions@IF-002#heat_set_1",),
                         ("cad.readback@TST-0001", "cad.glb_step_agreement@TST-0001"))

    def placed_bracket(self) -> None:
        """The bracket TST-0001 part-local and placed once, as occurrence bracket-a, held to the shaft by joint J-001."""
        self.docs["parts/TST-0001/part.yaml"]["model_frame"] = "part_local"
        assembly = self.docs["assembly.yaml"]
        assembly["subassemblies"][0]["parts"] = [pn for pn in assembly["subassemblies"][0]["parts"] if pn != "TST-0001"]
        assembly["subassemblies"][0]["occurrences"] = ["@bracket-a"]
        assembly["occurrences"] = [{"id": "bracket-a", "PN": "TST-0001", "placement": {"translation_mm": [0, 0, 0]}}]
        assembly["joints"] = [{"id": "J-001", "type": "fixed", "parent": "TST-0002", "child": "@bracket-a",
                               "axis": [0, 0, 1], "origin": [0, 0, 0], "min": 0, "max": 0, "nominal": 0}]
        self.before = normalized(self.docs)
        self.assertEqual([p.code for p in self.before.problems if p.severity == "error"], [])

    def test_an_added_moved_or_rejointed_occurrence_stales_the_glb_step_agreement_of_its_part_not_its_readback(self) -> None:
        """The agreement judges each occurrence's GLB node at its nominal placement. An occurrence the version never
        built, or one the record now places elsewhere, was never judged. The part's model is unchanged, so its
        read-back stays current. The fixed joint's origin is a deliberate dependency, not an exact one: any
        assembly.yaml edit stales the agreement (#174 option A), whether or not it moves this part."""
        self.placed_bracket()

        def add(docs: dict[str, Any]) -> None:
            assembly = docs["assembly.yaml"]
            assembly["occurrences"].append({"id": "bracket-b", "PN": "TST-0001", "placement": {"translation_mm": [40, 0, 0]}})
            assembly["subassemblies"][0]["occurrences"].append("@bracket-b")

        def move(docs: dict[str, Any]) -> None:
            docs["assembly.yaml"]["occurrences"][0]["placement"] = {"translation_mm": [5, 0, 0]}

        def rejoint(docs: dict[str, Any]) -> None:
            docs["assembly.yaml"]["joints"][0]["origin"] = [0, 0, 5]

        for name, change in (("added", add), ("moved", move), ("rejointed", rejoint)):
            with self.subTest(change=name):
                result = self.compare(change)
                self.assertEqual(result.stale_obligations.get("cad.glb_step_agreement@TST-0001"), ("occurrences",))
                self.assertNotIn("cad.readback@TST-0001", result.stale_obligations)
                self.assertNotIn("export.3mf@TST-0001", result.stale_obligations)

    def test_a_heat_set_host_named_apart_from_the_interface_endpoints_stales_its_declared_dimension_on_a_model_change(self) -> None:
        """The interface's endpoints are descriptive words, so only the heat-set pair names the host: as a bare PN or as
        an occurrence the inventory resolves. A new host model must make the declared dimension stale."""
        self.placed_bracket()
        entry = {"hole_d": 4.0, "insert": "M3 x 5.7", "source": "https://example.com/insert"}
        self.docs["interfaces.yaml"]["interfaces"].append(fx.interface("IF-002", "bracket", "insert", limits={"heat_set": [
            {**entry, "pair": ["@bracket-a", "TST-0004"]}, {**entry, "pair": ["TST-0002", "TST-0004"]}]}))
        self.before = normalized(self.docs)
        for host, owed in (("TST-0001", "cad.declared_dimensions@IF-002#heat_set_1"),
                           ("TST-0002", "cad.declared_dimensions@IF-002#heat_set_2")):
            with self.subTest(host=host):
                result = self.compare(lambda docs: None, geometry={**GEOMETRY, host: "9" * 64})
                self.assertIn(owed, result.stale_obligations)
                self.assertEqual(result.stale_obligations[owed], ("occurrences",))

    def test_swapping_the_parts_of_two_heat_set_host_occurrences_stales_both_declared_dimensions(self) -> None:
        """interfaces.yaml is unchanged: each entry still names its host occurrence. assembly.yaml now gives each of the
        two host occurrences the other's part, so each entry's host has another model and both outcomes must go stale."""
        self.placed_bracket()
        assembly = self.docs["assembly.yaml"]
        self.docs["parts/TST-0002/part.yaml"]["model_frame"] = "part_local"
        assembly["subassemblies"][0]["parts"] = [pn for pn in assembly["subassemblies"][0]["parts"] if pn != "TST-0002"]
        assembly["occurrences"].append({"id": "shaft-a", "PN": "TST-0002", "placement": {"translation_mm": [0, 0, 0]}})
        assembly["subassemblies"][0]["occurrences"].append("@shaft-a")
        assembly["joints"] = []
        entry = {"hole_d": 4.0, "insert": "M3 x 5.7", "source": "https://example.com/insert"}
        self.docs["interfaces.yaml"]["interfaces"].append(fx.interface("IF-002", "hosts", "insert", limits={"heat_set": [
            {**entry, "pair": ["@bracket-a", "TST-0004"]}, {**entry, "pair": ["@shaft-a", "TST-0004"]}]}))
        self.before = normalized(self.docs)
        self.assertEqual([p.code for p in self.before.problems if p.severity == "error"], [])

        def swap(docs: dict[str, Any]) -> None:
            first, second = docs["assembly.yaml"]["occurrences"][0], docs["assembly.yaml"]["occurrences"][1]
            first["PN"], second["PN"] = second["PN"], first["PN"]

        result = self.compare(swap)
        for owed in ("cad.declared_dimensions@IF-002#heat_set_1", "cad.declared_dimensions@IF-002#heat_set_2"):
            with self.subTest(obligation=owed):
                self.assertIn(owed, result.stale_obligations)

    def test_a_colour_change_stales_only_a_check_family_that_declares_appearance(self) -> None:
        """Of the obligations the record owes, only the FDM part's `export.3mf` declares the appearance domain."""
        def colour(docs: dict[str, Any]) -> None:
            docs["parts/TST-0001/part.yaml"]["intent"]["color"] = "#FF8000"
        entry = acceptance.entry(self.before, "EV-001", {"PN": "TST-0001"}, "simulation_supported",
                                 obligation="engineering.strength@TST-0001", version="v1", manifest_sha256="a" * 64,
                                 geometry=GEOMETRY)
        self.assertIn("appearance", entry["fingerprints"], "the ledger records every domain, appearance included")
        self.docs["manufacturing/evidence.yaml"] = {"entries": [entry]}
        self.before = normalized(self.docs)
        result = self.compare(colour)
        self.assertEqual(dict(result.changed), {"TST-0001": ("appearance",)})
        self.assertEqual(result.stale_obligations, {"export.3mf@TST-0001": ("appearance",)})
        self.assertEqual(result.stale_evidence, {})

    def test_a_color_change_stales_export_3mf_evidence_and_no_other_accepted_evidence(self) -> None:
        def colour(docs: dict[str, Any]) -> None:
            docs["parts/TST-0001/part.yaml"]["intent"]["color"] = "#FF8000"
        entries = [acceptance.entry(self.before, "EV-001", {"PN": "TST-0001"}, "simulation_supported",
                                    obligation="engineering.strength@TST-0001", version="v1", manifest_sha256="a" * 64,
                                    geometry=GEOMETRY),
                   acceptance.entry(self.before, "EV-002", {"PN": "TST-0001"}, "cad_valid",
                                    obligation="export.3mf@TST-0001", version="v1", manifest_sha256="a" * 64,
                                    geometry=GEOMETRY)]
        self.docs["manufacturing/evidence.yaml"] = {"entries": entries}
        self.before = normalized(self.docs)
        self.assertEqual(self.compare(colour).stale_evidence, {"EV-002": ("appearance",)})

    def test_a_colour_change_leaves_every_catch_all_family_current_but_a_geometry_change_stales_it(self) -> None:
        """policy.*, requirement.* and an unlisted family depend on every domain except appearance."""
        cases = {
            "part-scoped policy": ("policy.simulation_supported", {"PN": "TST-0001"}, "TST-0001"),
            "requirement": ("requirement.cad_valid", {"product": True, "requirements": ("REQ-001",)}, "REQ-001"),
            "unlisted family": ("tst_unlisted.check", {"PN": "TST-0001"}, "TST-0001"),
        }
        for label, (family, subject, key) in cases.items():
            with self.subTest(label):
                obligation = mi.Obligation(f"{family}@{key}", family, subject, "cad_valid", "layout", "test")
                self.assertEqual(impact.stale_obligations([obligation], {key: ("appearance",)}), {})
                self.assertEqual(impact.stale_obligations([obligation], {key: ("appearance", "geometry")}),
                                 {obligation.id: ("geometry",)})

    def test_a_material_change_stales_the_3mf_family_of_that_part_only(self) -> None:
        three_mf = [mi.Obligation(f"export.3mf@{pn}", "export.3mf", {"PN": pn}, "cad_valid", "layout", "test")
                    for pn in ("TST-0001", "TST-0002")]
        changes = {
            "declared material": lambda docs: docs["parts/TST-0001/part.yaml"].update(material="TST other material"),
            "material profile": lambda docs: docs["parts/TST-0001/part.yaml"]["intent"].update(material_profile="tst_metal_rod"),
        }
        for label, change in changes.items():
            with self.subTest(label):
                result = self.compare(change)
                self.assertEqual(result.changed["TST-0001"], ("material",))
                self.assertEqual(impact.stale_obligations(three_mf, result.changed),
                                 {"export.3mf@TST-0001": ("material",)})

    def test_record_derived_obligations_are_recomputed_never_stale(self) -> None:
        def use_case(docs: dict[str, Any]) -> None:
            docs["product.yaml"]["use_case"]["purpose"] = fx.known("TST another purpose")
        result = self.compare(use_case)
        self.assertFalse([ident for ident in result.stale_obligations if ident.startswith("intent.")])
        self.assertEqual(result.earliest_stage, "intent")

    def test_an_interface_only_edit_stales_the_stop_reaction(self) -> None:
        """The stop reaction reads the interface's recorded contact load and its load references, so an edit that
        touches nothing but the interface must stale it. The generic engineering. domains leave `interface` out."""
        extra = {"id": "static_b", "kind": "static", "direction": [0, 0, -1], "requirements": ["REQ-001"],
                 "magnitude": fx.known(fx.quantity(20, "N"))}
        self.docs["product.yaml"]["use_case"]["loads"].append(extra)
        self.docs["interfaces.yaml"]["interfaces"].append(fx.interface("IF-011", "TST-0001", "TST-0002", "other", {
            "critical": fx.known(True), "functions": [{"function": "structural"}], "loads": ["head_load", "static_b"],
            "contact": {"materials": [fx.unknown("fixture"), fx.unknown("fixture")],
                        "load": fx.known(fx.quantity(240, "N"))}}))
        self.before = normalized(self.docs)

        def contact_load(docs: dict[str, Any]) -> None:
            docs["interfaces.yaml"]["interfaces"][-1]["functional"]["contact"]["load"] = fx.known(fx.quantity(400, "N"))

        def load_reference(docs: dict[str, Any]) -> None:
            docs["interfaces.yaml"]["interfaces"][-1]["functional"]["loads"] = ["head_load"]
        for name, change in (("contact.load", contact_load), ("load reference", load_reference)):
            with self.subTest(edit=name):
                result = self.compare(change)
                self.assertEqual(result.changed.get("IF-011"), ("interface",))
                self.assertIn("engineering.stop_reaction@IF-011", result.stale_obligations)

    def test_nothing_changed_is_no_impact(self) -> None:
        result = self.compare(lambda docs: None)
        self.assertFalse(result.any)
        self.assertEqual((result.changed, result.earliest_stage, result.proposed_flow), ({}, None, None))


class CoupledMechanismStaleness(unittest.TestCase):
    """cad-motion's V6 test engine as a record: the crank J-001 drives both cams through linear couplings, the pistons
    and rods through slider-crank mechanisms and the valves through a lift profile. A placement of an occurrence follows
    joints that are not on its own parent chain, so the GLB-STEP agreement depends on all of assembly.yaml."""

    def setUp(self) -> None:
        engine = load("cad_motion_v6_record", HERE.parents[1] / "cad-motion" / "tests" / "fixtures" / "v6_record.py")
        parts = [fx.part(pn, title, process="cnc", model_frame=frame) for pn, (title, frame) in engine.PARTS.items()]
        self.docs = {rel: data for rel, data in fx.record(parts=parts).items() if not rel.startswith("_")}
        self.docs["assembly.yaml"] = {**engine.record(), "operations": fx.unknown()}
        self.before = normalized(self.docs)
        self.assertEqual([p.code for p in self.before.problems if p.severity == "error"], [])

    def stale(self, change: Any) -> dict[str, tuple[str, ...]]:
        after = copy.deepcopy(self.docs)
        change(after["assembly.yaml"])
        return impact.compare(self.before, normalized(after), before_geometry={}, after_geometry={}, since="v1",
                              version="v2").stale_obligations

    def test_a_crank_nominal_that_turns_the_coupled_cams_stales_the_camshaft_agreement(self) -> None:
        def turn(assembly: dict[str, Any]) -> None:
            next(j for j in assembly["joints"] if j["id"] == "J-001")["nominal"] = 90

        stale = self.stale(turn)
        self.assertIn("cad.glb_step_agreement@VSX-0301", stale)
        self.assertNotIn("cad.readback@VSX-0301", stale)

    def test_a_lift_profile_or_mechanism_edit_stales_the_agreement_of_the_parts_it_moves(self) -> None:
        def profile(assembly: dict[str, Any]) -> None:
            assembly["profiles"]["lift"]["samples"][1][1] += 0.5

        def mechanism(assembly: dict[str, Any]) -> None:
            assembly["mechanisms"][0]["rod_length_mm"] += 1.0

        for name, change, moved in (("profile", profile, "VSX-0401"), ("mechanism", mechanism, "VSX-0201")):
            with self.subTest(edit=name):
                self.assertIn(f"cad.glb_step_agreement@{moved}", self.stale(change))


class ProductOrderStaleness(unittest.TestCase):
    """assembly.order@product must go stale when the whole assembly sequence changes, including an installer
    that names its parts by occurrence (`@id`), and only then."""

    PRODUCT = "assembly.order@product"

    def occurrence_docs(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        docs = fx.record(parts=[fx.part("TST-0101", "Housing", process="cnc"), fx.part("TST-0102", "Clip", process="cnc")],
                         operations=operations)
        docs["assembly.yaml"]["subassemblies"] = [{"id": "main", "title": "Main",
                                                    "occurrences": ["@housing", "@clip-a", "@clip-b"]}]
        docs["assembly.yaml"]["occurrences"] = [{"id": "housing", "PN": "TST-0101"}, {"id": "clip-a", "PN": "TST-0102"},
                                                {"id": "clip-b", "PN": "TST-0102"}]
        return {rel: data for rel, data in docs.items() if not rel.startswith("_")}

    @staticmethod
    def join(ident: str, part: str) -> dict[str, Any]:
        return {"id": ident, "kind": "join", "part": part, "into": "@housing", "direction": [0, 0, -1],
                "acceptance": {"kind": "standoff", "features": ["foot", "top"]}}

    def compare(self, before: dict[str, Any], after: dict[str, Any], after_geometry: dict[str, str] | None = None) -> Any:
        return impact.compare(normalized(before), normalized(after), before_geometry={}, after_geometry=after_geometry or {},
                              since="v1", version="v2")

    def test_deleting_an_installer_named_by_occurrence_stales_the_product_order(self) -> None:
        both = [self.join("mount-a", "@clip-a"), self.join("mount-b", "@clip-b")]
        result = self.compare(self.occurrence_docs(both), self.occurrence_docs(both[:1]))
        self.assertIn(self.PRODUCT, result.stale_obligations)

    def test_an_occurrence_no_operation_names_stales_the_product_order(self) -> None:
        both = [self.join("mount-a", "@clip-a"), self.join("mount-b", "@clip-b")]
        before = self.occurrence_docs(both)
        after = copy.deepcopy(before)
        after["assembly.yaml"]["occurrences"].append({"id": "clip-c", "PN": "TST-0102"})
        after["assembly.yaml"]["subassemblies"][0]["occurrences"].append("@clip-c")
        self.assertIn(self.PRODUCT, self.compare(before, after).stale_obligations)

    def test_a_sequence_only_change_stales_the_product_order(self) -> None:
        """The operations swap places and nothing else changes. access.py plans paths in sequence order."""
        both = [self.join("mount-a", "@clip-a"), self.join("mount-b", "@clip-b")]
        result = self.compare(self.occurrence_docs(both), self.occurrence_docs(both[::-1]))
        self.assertIn(self.PRODUCT, result.stale_obligations)

    def test_a_product_policy_obligation_goes_stale_on_the_same_change_through_everything(self) -> None:
        """A non-assembly family, shown for reference. policy.*@product depends on every domain (_EVERYTHING), so it
        already goes stale on any change, including the sequence-only one that stales the product order."""
        both = [self.join("mount-a", "@clip-a"), self.join("mount-b", "@clip-b")]
        docs = self.occurrence_docs(both)
        docs["product.yaml"]["use_case"] = acceptance.confirmed_use_case(
            "prototype", evidence_policy={"obligations": [{"subject": {"product": True}, "level": "cad_valid"}],
                                          "decision": "DR-001"})
        reordered = copy.deepcopy(docs)
        reordered["assembly.yaml"]["operations"] = both[::-1]
        self.assertIn("policy.cad_valid@product", {o.id for o in impact.mi.required_checks(normalized(docs))})
        result = self.compare(docs, reordered)
        self.assertEqual(result.stale_obligations.get("policy.cad_valid@product"), ("interface",))
        self.assertIn(self.PRODUCT, result.stale_obligations)

    def test_an_edit_outside_the_assembly_domains_leaves_the_product_order_fresh(self) -> None:
        """A finish edit moves the part's finish fingerprint, which no assembly.* check depends on (geometry and
        interface are the assembly domains)."""
        both = [self.join("mount-a", "@clip-a"), self.join("mount-b", "@clip-b")]
        docs = self.occurrence_docs(both)
        after = copy.deepcopy(docs)
        after["parts/TST-0102/part.yaml"]["finish"] = "TST bead blasted"
        result = self.compare(docs, after)
        self.assertNotIn(self.PRODUCT, result.stale_obligations)
        self.assertEqual(result.changed["TST-0102"], ("finish",), "the edit is seen, just not by the order check")


class OptInDomain(unittest.TestCase):
    """A domain `_EVERYTHING` leaves out is opt-in: it counts for evidence only when the entry's family declares it
    and the subject has it. The synthetic domain below stands in for any later one."""

    NEW = "tst_opt_in"
    DECLARING = "tst_declares.check@TST-0001"
    OTHER = "engineering.strength@TST-0001"

    def setUp(self) -> None:
        domains = (*impact.DOMAINS, self.NEW)
        family = ("tst_declares.", frozenset({"geometry", self.NEW}))
        patch = mock.patch.multiple(impact, DOMAINS=domains, FAMILY_DOMAINS=(family, *impact.FAMILY_DOMAINS))
        patch.start()
        self.addCleanup(patch.stop)
        self.current = {"geometry": "g", "load": "l", self.NEW: "n2"}

    def entry(self, obligation: str, **recorded: str) -> dict[str, Any]:
        return {"obligation": obligation, "fingerprints": {"geometry": "g", "load": "l", **recorded}}

    def test_a_family_that_declares_it_goes_stale_when_only_that_domain_changes(self) -> None:
        entry = self.entry(self.DECLARING, **{self.NEW: "n1"})
        self.assertEqual(impact.evidence_staleness(entry, self.current), (self.NEW,))
        self.assertEqual(impact.unrecorded_domains(entry, self.current), ())

    def test_a_family_that_declares_it_must_record_it(self) -> None:
        entry = self.entry(self.DECLARING)
        self.assertEqual(impact.unrecorded_domains(entry, self.current), (self.NEW,))
        self.assertEqual(impact.evidence_staleness(entry, self.current), (self.NEW,))

    def test_a_family_that_does_not_declare_it_ignores_a_change_in_it(self) -> None:
        entry = self.entry(self.OTHER, **{self.NEW: "n1"})
        self.assertEqual(impact.evidence_staleness(entry, self.current), ())
        self.assertEqual(impact.evidence_staleness(self.entry(self.OTHER), self.current), ())

    def test_a_declared_domain_the_subject_lacks_counts_only_when_the_entry_recorded_it(self) -> None:
        current = {"geometry": "g", "load": "l"}
        self.assertEqual(impact.evidence_staleness(self.entry(self.DECLARING, **{self.NEW: "n1"}), current), (self.NEW,))
        self.assertEqual(impact.evidence_staleness(self.entry(self.DECLARING), current), ())
        self.assertEqual(impact.unrecorded_domains(self.entry(self.DECLARING), current), ())

    def test_export_3mf_evidence_that_recorded_appearance_goes_stale_when_the_subject_has_none(self) -> None:
        """The same transition for the family that declares `appearance`: the rule is not specific to purchase.*."""
        current = {"geometry": "g", "material": "m"}
        recorded = {"obligation": "export.3mf@TST-0001", "fingerprints": {"geometry": "g", "material": "m", "appearance": "a"}}
        unrecorded = {"obligation": "export.3mf@TST-0001", "fingerprints": {"geometry": "g", "material": "m"}}
        self.assertEqual(impact.evidence_staleness(recorded, current), ("appearance",))
        self.assertEqual(impact.evidence_staleness(unrecorded, current), ())

LEGACY_INTERFACE_DIGEST = "919639c091011df20121336be1bb29f1a123a5a422d75fbffcd3eff8b602ed40"  # impact.py on origin/main bc8d3f94
# The interface digest of TST-0103 in PurchaseMountingStaleness.documents(), computed with origin/main's impact.py.
OCCURRENCE_INTERFACE_DIGEST = "25016f8a4c143f1b7f00ff2ac329d64b72375dcf55b3c64f4412bea46e8b866c"
# The fingerprint domains on origin/main bc8d3f94, sorted.
MAIN_DOMAINS = ("capability", "condition", "criterion", "environment", "finish", "geometry", "interface", "load", "lot",
                "material", "orientation", "process", "route", "setup", "source", "use_case")
# Per case and family prefix, the digest of the fingerprints of every subject in the family's origin/main domains,
# computed with impact.py of origin/main a69bbb46 (cad-record unchanged since 4a8916f8).
MAIN_FAMILY_DIGESTS: dict[str, dict[str, str]] = {
    "occurrence-placed": {
        "cad.": "573156ddba3e6bd069d5e9b862fb776a3ff83d095b155568d72a16d723ca5b56",
        "route.": "49248d3142a21391c8eae67178fbdc43dab9bc4c276cdebe72cf308bcf5c325c",
        "process.": "9c67614853d423da5712d35a4784611f8b0558886efbc5881a0277811fa4f570",
        "optical.": "ea9f72b837e030fd22c329918f3e5f7a03287ecadea8b277f337b90f92a3955c",
        "engineering.": "7e777a8020773a3e550e4d90606496bcbec18b9557f103b05f04866a5cb1f1ba",
        "feature.": "7302d9165857612dc7a10b888fea1b837dd86e8c8f23ff02724531429b79efa2",
        "interface.": "b2a95ced884053db6226d05aba17af7aaf55f3ea3ba58cafa723171aa238301f",
        "contact.": "6dc6bdafa3baa71b397dcb831f6715e48b4a054151ac34eceef36410e400f5a2",
        "motion.": "767a132e7d21821407b618f88e29af54bf42f998f3f5fa874e17dd58d148892b",
        "assembly.": "790afb7ac9ed872d78a1e355c7719e2f43c4530f102328ab5498dfb771eb64cb",
        "export.3mf": "57b05be936547f3302bcb984594b44edeaa9412dd9a8c0f0bcb1957781ba6677",
        "function.": "7575681d57fb9d88388d93c384af9436c452ce3cfd236687df30d7c05f2425f8",
        "requirement.": "e60c578893c6a9d0740164788d1d70d7eeec85278977e42ca05f665807f726ec",
        "policy.": "e60c578893c6a9d0740164788d1d70d7eeec85278977e42ca05f665807f726ec",
    },
    "broken inventory": {
        "cad.": "573156ddba3e6bd069d5e9b862fb776a3ff83d095b155568d72a16d723ca5b56",
        "route.": "49248d3142a21391c8eae67178fbdc43dab9bc4c276cdebe72cf308bcf5c325c",
        "process.": "9c67614853d423da5712d35a4784611f8b0558886efbc5881a0277811fa4f570",
        "optical.": "ea9f72b837e030fd22c329918f3e5f7a03287ecadea8b277f337b90f92a3955c",
        "engineering.": "7e777a8020773a3e550e4d90606496bcbec18b9557f103b05f04866a5cb1f1ba",
        "feature.": "7302d9165857612dc7a10b888fea1b837dd86e8c8f23ff02724531429b79efa2",
        "interface.": "b2a95ced884053db6226d05aba17af7aaf55f3ea3ba58cafa723171aa238301f",
        "contact.": "6dc6bdafa3baa71b397dcb831f6715e48b4a054151ac34eceef36410e400f5a2",
        "motion.": "767a132e7d21821407b618f88e29af54bf42f998f3f5fa874e17dd58d148892b",
        "assembly.": "790afb7ac9ed872d78a1e355c7719e2f43c4530f102328ab5498dfb771eb64cb",
        "export.3mf": "57b05be936547f3302bcb984594b44edeaa9412dd9a8c0f0bcb1957781ba6677",
        "function.": "7575681d57fb9d88388d93c384af9436c452ce3cfd236687df30d7c05f2425f8",
        "requirement.": "e60c578893c6a9d0740164788d1d70d7eeec85278977e42ca05f665807f726ec",
        "policy.": "e60c578893c6a9d0740164788d1d70d7eeec85278977e42ca05f665807f726ec",
    },
}


def family_digest(prints: dict[str, dict[str, str]], domains: tuple[str, ...]) -> str:
    """One digest over every subject's fingerprints restricted to `domains`."""
    return impact.digest({subject: {d: values[d] for d in sorted(domains) if d in values}
                          for subject, values in sorted(prints.items())})


class PurchaseMountingStaleness(unittest.TestCase):
    """purchase.mounting depends on the assembly inventory, the operations resolved through occurrences and each part's
    model_frame, and no other family takes those inputs."""

    OBLIGATION = "purchase.mounting@TST-0103/buy"
    # The domain set of every family prefix on origin/main 88be42e, worked out from FAMILY_DOMAINS there.
    MAIN_FAMILIES: dict[str, tuple[str, ...]] = {
        "cad.": ("geometry",),
        "route.": ("capability", "condition", "criterion", "finish", "material", "orientation", "process", "route", "setup",
                   "source"),
        "process.": ("capability", "condition", "criterion", "finish", "geometry", "material", "orientation", "process",
                     "route", "setup", "source"),
        "optical.": ("criterion", "finish", "material", "process", "route", "source"),
        "engineering.": ("condition", "criterion", "environment", "finish", "geometry", "load", "material", "orientation",
                         "process", "route", "source", "use_case"),
        "feature.": ("capability", "condition", "criterion", "finish", "geometry", "interface", "material", "orientation",
                     "process", "route", "setup", "source"),
        "interface.": ("capability", "condition", "criterion", "environment", "finish", "geometry", "interface", "load",
                       "material", "process", "route", "source"),
        "contact.": ("condition", "criterion", "environment", "finish", "geometry", "interface", "load", "material",
                     "source"),
        "motion.": ("criterion", "finish", "geometry", "interface", "load", "material", "process", "source"),
        "assembly.": ("criterion", "geometry", "interface", "source"),
        "export.3mf": ("appearance", "geometry", "material"),
        "function.": ("condition", "criterion", "environment", "finish", "geometry", "interface", "load", "material",
                      "process", "source"),
        "requirement.": MAIN_DOMAINS,
        "policy.": MAIN_DOMAINS,
    }

    def documents(self, rings: tuple[str, ...] = ("ring-a", "ring-b"), operations: list[dict[str, Any]] | None = None,
                  frame: str | None = "part_local", placements: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        ring = fx.part("TST-0103", "Ring", process="purchased", make_buy="buy", **({"model_frame": frame} if frame else {}),
                       part_intent=fx.intent(route=[fx.operation("buy", "purchased")],
                                             material_profile=fx.not_applicable("catalogue item")))
        housing = fx.part("TST-0104", "Housing", process="cnc", model_frame="part_local")
        plate = fx.part("TST-0105", "Plate", process="cnc")
        if operations is None:
            operations = [self.install(f"mount-{name.split('-')[1]}", f"@{name}") for name in rings]
        docs = fx.record(parts=[ring, housing, plate], operations=operations)
        docs["assembly.yaml"]["subassemblies"] = [{"id": "main", "title": "Main", "occurrences": [
            "@housing", *(f"@{name}" for name in rings), "@plate"]}]
        docs["assembly.yaml"]["occurrences"] = [
            {"id": "housing", "PN": "TST-0104"}, {"id": "plate", "PN": "TST-0105"},
            *({"id": name, **({"placement": placements[name]} if placements and name in placements else {}), "PN": "TST-0103"}
              for name in rings)]
        return {rel: data for rel, data in docs.items() if not rel.startswith("_")}

    @staticmethod
    def install(ident: str, part: str, into: str = "@housing") -> dict[str, Any]:
        return {"id": ident, "kind": "join", "part": part, "into": into, "direction": [0, 0, -1],
                "acceptance": {"kind": "standoff", "features": ["foot", "top"]}}

    def compare(self, before: dict[str, Any], after: dict[str, Any]) -> Any:
        return impact.compare(normalized(before), normalized(after), before_geometry={}, after_geometry={},
                              since="v1", version="v2")

    def test_an_added_occurrence_with_its_operation_stales_the_mounting_check(self) -> None:
        after = self.documents(rings=("ring-a", "ring-b", "ring-c"))
        self.assertIn(self.OBLIGATION, self.compare(self.documents(), after).stale_obligations)

    def test_an_added_occurrence_no_operation_installs_stales_the_mounting_check(self) -> None:
        after = self.documents(rings=("ring-a", "ring-b", "ring-c"),
                               operations=[self.install("mount-a", "@ring-a"), self.install("mount-b", "@ring-b")])
        self.assertIn(self.OBLIGATION, self.compare(self.documents(), after).stale_obligations)

    def test_a_moved_occurrence_stales_the_mounting_check(self) -> None:
        moved = {"ring-a": {"translation_mm": [5, 0, 0]}}
        result = self.compare(self.documents(), self.documents(placements=moved))
        self.assertIn(self.OBLIGATION, result.stale_obligations)

    def test_a_moved_occurrence_leaves_an_unrelated_part_alone_but_for_its_coarse_agreement(self) -> None:
        """Moving the ring changes nothing the plate's checks read, except all of assembly.yaml, which its GLB-STEP
        agreement depends on by design (#174 option A)."""
        moved = {"ring-a": {"translation_mm": [5, 0, 0]}}
        result = self.compare(self.documents(), self.documents(placements=moved))
        self.assertEqual(result.changed.get("TST-0105"), ("occurrences",))
        self.assertEqual({i: d for i, d in result.stale_obligations.items() if "TST-0105" in i},
                         {"cad.glb_step_agreement@TST-0105": ("occurrences",)})

    def test_a_part_with_no_explicit_occurrence_keeps_its_fingerprint(self) -> None:
        ring = fx.part("TST-0103", "Ring", process="purchased", make_buy="buy",
                       part_intent=fx.intent(route=[fx.operation("buy", "purchased")],
                                             material_profile=fx.not_applicable("catalogue item")))
        legacy = [{"id": "mount", "kind": "join", "part": "TST-0103", "into": "TST-0104", "direction": [0, 0, -1],
                   "acceptance": {"kind": "standoff", "features": ["foot", "top"]}}]
        docs = fx.record(parts=[ring, fx.part("TST-0104", "Housing", process="cnc")], operations=legacy)
        docs = {rel: data for rel, data in docs.items() if not rel.startswith("_")}
        prints = impact.fingerprints(normalized(docs), {"PN": "TST-0103"})
        self.assertEqual(prints["interface"], LEGACY_INTERFACE_DIGEST)
        self.assertNotIn("occurrences", prints)

    def test_an_occurrence_placed_part_keeps_its_interface_fingerprint(self) -> None:
        moved = {"ring-a": {"translation_mm": [5, 0, 0]}}
        for name, docs in (("placed", self.documents()), ("one moved", self.documents(placements=moved))):
            with self.subTest(case=name):
                prints = impact.fingerprints(normalized(docs), {"PN": "TST-0103"})
                self.assertEqual(prints["interface"], OCCURRENCE_INTERFACE_DIGEST)
                self.assertIn("occurrences", prints)

    def test_only_an_occurrence_placed_bought_part_and_the_made_parts_carry_the_occurrences_domain(self) -> None:
        prints = impact.subject_fingerprints(normalized(self.documents()))
        self.assertEqual(sorted(key for key, domains in prints.items() if "occurrences" in domains),
                         ["TST-0103", "TST-0104", "TST-0105"],
                         "the bought ring placed as occurrences, and each made part: its agreement reads its placements")

    def test_a_non_part_subject_carries_no_opt_in_domain_whatever_its_name(self) -> None:
        """The synthetic domain stands for any later opt-in domain: only a part carries one."""
        record = normalized(self.documents())
        with mock.patch.object(impact, "DOMAINS", (*impact.DOMAINS, "tst_opt_in")):
            prints = impact.subject_fingerprints(record)
        for key in ("product", "op:mount-a"):
            with self.subTest(subject=key):
                self.assertNotIn("tst_opt_in", prints[key])

    def accepted_result(self, docs: dict[str, Any], current: dict[str, Any]) -> Any:
        """The assessment of `current` with an accepted purchase.mounting entry (level process_planned) recorded against
        `docs` at every fingerprint domain the part has now, `occurrences` included."""
        from datetime import date  # noqa: PLC0415 - used by these tests alone

        entry = acceptance.entry(normalized(docs), "EV-010", {"PN": "TST-0103", "operation": "buy"}, "process_planned",
                                 obligation=self.OBLIGATION, version="v1", manifest_sha256="a" * 64)
        after = copy.deepcopy(current)
        after["manufacturing/evidence.yaml"] = {"entries": [entry]}
        return acceptance.evidence.assess(normalized(after), version="v1", manifest_sha256="a" * 64, packets=(),
                                          approved=lambda decision: True, today=date(2026, 11, 18))

    def test_an_accepted_entry_is_current_while_nothing_changed(self) -> None:
        result = self.accepted_result(self.documents(), self.documents())
        self.assertEqual(result.statuses[self.OBLIGATION].result, "pass", result.statuses[self.OBLIGATION])

    def test_an_accepted_entry_goes_stale_when_only_an_occurrence_moves(self) -> None:
        moved = self.documents(placements={"ring-a": {"translation_mm": [5, 0, 0]}})
        result = self.accepted_result(self.documents(), moved)
        self.assertEqual(result.statuses[self.OBLIGATION].result, "stale", result.statuses[self.OBLIGATION])
        self.assertIn("occurrences", " ".join(result.statuses[self.OBLIGATION].reasons))

    def test_an_accepted_entry_goes_stale_when_only_an_uninstalled_occurrence_is_added(self) -> None:
        added = self.documents(rings=("ring-a", "ring-b", "ring-c"),
                               operations=[self.install("mount-a", "@ring-a"), self.install("mount-b", "@ring-b")])
        result = self.accepted_result(self.documents(), added)
        self.assertEqual(result.statuses[self.OBLIGATION].result, "stale", result.statuses[self.OBLIGATION])
        self.assertIn("occurrences", " ".join(result.statuses[self.OBLIGATION].reasons))

    def legacy_documents(self) -> dict[str, Any]:
        """A bought part and its housing in one subassembly of plain part numbers: no explicit occurrence, so no
        membership error can compete with a shape error."""
        ring = fx.part("TST-0103", "Ring", process="purchased", make_buy="buy",
                       part_intent=fx.intent(route=[fx.operation("buy", "purchased")],
                                             material_profile=fx.not_applicable("catalogue item")))
        mount = [{"id": "mount", "kind": "join", "part": "TST-0103", "into": "TST-0104", "direction": [0, 0, -1],
                  "acceptance": {"kind": "standoff", "features": ["foot", "top"]}}]
        docs = fx.record(parts=[ring, fx.part("TST-0104", "Housing", process="cnc")], operations=mount)
        return {rel: data for rel, data in docs.items() if not rel.startswith("_")}

    def plain_documents(self) -> dict[str, Any]:
        """The bought part and its housing with no explicit occurrence and no operation."""
        docs = self.legacy_documents()
        docs["assembly.yaml"]["operations"] = []
        return docs

    def test_an_accepted_entry_goes_stale_when_the_part_loses_its_last_explicit_occurrence(self) -> None:
        before, after = self.documents(rings=("ring-a",)), self.plain_documents()
        interface = [impact.fingerprints(normalized(docs), {"PN": "TST-0103"})["interface"] for docs in (before, after)]
        self.assertEqual(interface[0], interface[1], "only the occurrences domain can tell these two records apart")
        result = self.accepted_result(before, after)
        self.assertEqual(result.statuses[self.OBLIGATION].result, "stale", result.statuses[self.OBLIGATION])
        self.assertIn("occurrences", " ".join(result.statuses[self.OBLIGATION].reasons))

    def test_an_accepted_entry_that_never_recorded_occurrences_stays_current_while_the_part_has_none(self) -> None:
        result = self.accepted_result(self.plain_documents(), self.plain_documents())
        self.assertEqual(result.statuses[self.OBLIGATION].result, "pass", result.statuses[self.OBLIGATION])

    def wrong_shapes(self) -> list[tuple[str, str, Any, str]]:
        """(name, fixture, edit of assembly.yaml, exact problem). The "legacy" fixtures have no explicit occurrence,
        so the shape is the only problem. The one "placed" mapping case cannot be that clean: `_list_of`
        (assembly_data.py:216) reads a mapping as an empty list, so the explicit occurrences stay ungrouped and the
        membership loop (assembly_data.py:295-297) always reports them next to the shape message. That case keeps
        the references as mapping keys, which is the shape that would read as valid without the check."""
        def subassembly(key: str, value: Any) -> Any:
            return lambda assembly: assembly["subassemblies"][0].__setitem__(key, value)

        def top(key: str, value: Any) -> Any:
            return lambda assembly: assembly.__setitem__(key, value)

        every_reference = {f"@{o['id']}": 1 for o in self.documents()["assembly.yaml"]["occurrences"]}
        return [
            ("subassembly occurrences is a mapping", "placed", subassembly("occurrences", every_reference),
             "subassembly main: occurrences must be a list"),
            ("subassembly occurrences is a mapping and nothing else is wrong", "legacy",
             subassembly("occurrences", {"@ring-a": 1}), "subassembly main: occurrences must be a list"),
            ("subassembly occurrences is an integer", "legacy", subassembly("occurrences", 1),
             "subassembly main: occurrences must be a list"),
            ("subassembly parts is an integer", "legacy", subassembly("parts", 1),
             "subassembly main: parts must be a list"),
            ("subassemblies is an integer", "legacy", top("subassemblies", 1), "subassemblies must be a list"),
            ("a subassembly is a string", "legacy", top("subassemblies", ["main"]),
             "subassemblies/0 must be a mapping"),
            ("occurrences is an integer", "placed", top("occurrences", 1), "occurrences must be a list"),
            ("an occurrence is a string", "legacy", top("occurrences", ["ring-a"]), "occurrences/0 must be a mapping"),
            ("an occurrence is an integer", "legacy", top("occurrences", [1]), "occurrences/0 must be a mapping"),
            ("a placement is a string", "placed", lambda assembly: assembly["occurrences"][2].__setitem__(
                "placement", "left"), "occurrences/2.placement must be a mapping of translation_mm and rotation")]

    def test_a_wrong_container_shape_is_a_named_inventory_problem(self) -> None:
        valid = impact.fingerprints(normalized(self.documents()), {"PN": "TST-0103"})["occurrences"]
        for name, fixture, edit, message in self.wrong_shapes():
            with self.subTest(shape=name):
                docs = self.documents() if fixture == "placed" else self.legacy_documents()
                edit(docs["assembly.yaml"])
                record = normalized(docs)
                found = impact.part_occurrences(record, "TST-0103")
                self.assertIsInstance(found, impact.InventoryProblem)
                problems = found.message.split("; ")
                self.assertEqual(found.field, "assembly_inventory")
                self.assertIn(message, problems)
                if fixture == "legacy":
                    self.assertEqual(problems, [message], "the shape is the only thing wrong with this inventory")
                self.assertNotEqual(impact.fingerprints(record, {"PN": "TST-0103"})["occurrences"], valid)

    def old_entry_result(self, docs: dict[str, Any], current: dict[str, Any]) -> Any:
        """The assessment of `current` with a purchase.mounting entry recorded against `docs` before the
        occurrences domain existed: it holds every domain fingerprint but that one, the appearance and the lot."""
        from datetime import date  # noqa: PLC0415 - used by these tests alone

        before = normalized(docs)
        old = tuple(d for d in impact.DOMAINS if d not in ("occurrences", "appearance", "lot"))
        entry = acceptance.entry(before, "EV-009", {"PN": "TST-0103", "operation": "buy"}, "cad_valid",
                                 obligation=self.OBLIGATION, version="v1", manifest_sha256="a" * 64, domains=old)
        after = copy.deepcopy(current)
        after["manufacturing/evidence.yaml"] = {"entries": [entry]}
        return acceptance.evidence.assess(normalized(after), version="v1", manifest_sha256="a" * 64, packets=(),
                                          approved=lambda decision: True, today=date(2026, 11, 18))

    def test_an_old_entry_is_unqualified_once_a_bought_part_is_placed_as_occurrences(self) -> None:
        unmounted = [self.install("mount-a", "@ring-a"), self.install("mount-b", "@ring-b")]
        result = self.old_entry_result(self.documents(), self.documents(rings=("ring-a", "ring-b", "ring-c"),
                                                                         operations=unmounted))
        self.assertEqual(result.statuses[self.OBLIGATION].result, "unknown")
        self.assertIn("evidence.unqualified", {finding.code for finding in result.findings})

    def test_an_old_entry_of_a_bought_part_without_occurrences_stays_current(self) -> None:
        ring = fx.part("TST-0103", "Ring", process="purchased", make_buy="buy",
                       part_intent=fx.intent(route=[fx.operation("buy", "purchased")],
                                             material_profile=fx.not_applicable("catalogue item")))
        legacy = [{"id": "mount", "kind": "join", "part": "TST-0103", "into": "TST-0104", "direction": [0, 0, -1],
                   "acceptance": {"kind": "standoff", "features": ["foot", "top"]}}]
        docs = fx.record(parts=[ring, fx.part("TST-0104", "Housing", process="cnc")], operations=legacy)
        docs = {rel: data for rel, data in docs.items() if not rel.startswith("_")}
        result = self.old_entry_result(docs, docs)
        self.assertEqual(result.statuses[self.OBLIGATION].result, "pass")
        self.assertNotIn("evidence.unqualified", {finding.code for finding in result.findings})

    def test_every_family_but_purchase_fingerprints_byte_identically_to_main(self) -> None:
        cases = (("occurrence-placed", self.documents()), ("broken inventory", self.documents(frame=None)))
        for case, docs in cases:
            prints = impact.subject_fingerprints(normalized(docs))
            for prefix, domains in self.MAIN_FAMILIES.items():
                with self.subTest(case=case, family=prefix):
                    self.assertEqual(family_digest(prints, domains), MAIN_FAMILY_DIGESTS[case][prefix])

    def test_every_other_family_keeps_its_domains_and_purchase_depends_on_occurrences(self) -> None:
        for prefix, domains in self.MAIN_FAMILIES.items():
            with self.subTest(family=prefix):
                self.assertEqual(tuple(sorted(impact.family_domains(prefix))), domains)
        main_purchase = {"criterion", "source", "process", "route", "load", "environment", "geometry"}
        self.assertEqual(impact.family_domains("purchase."), main_purchase | {"occurrences"})

    def test_a_part_without_a_valid_inventory_reports_the_problem_and_never_an_empty_result(self) -> None:
        broken = normalized(self.documents(frame=None))
        found = impact.part_occurrences(broken, "TST-0103")
        self.assertIsInstance(found, impact.InventoryProblem)
        self.assertEqual(found.field, "assembly_inventory")
        self.assertIn("TST-0103 is placed 2 times", found.message)

    def test_an_occurrence_view_lists_occurrences_by_id_with_placement_and_operations(self) -> None:
        operations = [self.install("mount-b", "@ring-b"), self.install("seat-a", "@housing", into="@ring-a")]
        moved = {"ring-b": {"translation_mm": [5, 0, 0]}}
        found = impact.part_occurrences(normalized(self.documents(operations=operations, placements=moved)), "TST-0103")
        self.assertIsInstance(found, impact.PartOccurrences)
        self.assertEqual([(o.id, o.operations) for o in found.occurrences],
                         [("ring-a", ("seat-a",)), ("ring-b", ("mount-b",))])
        self.assertEqual(found.occurrences[1].placement["translation_mm"], [5.0, 0.0, 0.0])
        self.assertEqual(found.model_frame, "part_local")

    def test_a_broken_inventory_never_fingerprints_like_a_valid_one(self) -> None:
        valid = impact.fingerprints(normalized(self.documents()), {"PN": "TST-0103"})["occurrences"]
        broken = impact.fingerprints(normalized(self.documents(frame=None)), {"PN": "TST-0103"})["occurrences"]
        self.assertNotEqual(valid, broken)


class EvidenceAndFlow(unittest.TestCase):
    def test_changed_evidence_is_stale_and_unchanged_evidence_is_only_a_carry_forward_candidate(self) -> None:
        docs = documents()
        before = normalized(docs)
        entries = [acceptance.entry(before, "EV-001", {"PN": "TST-0001"}, "simulation_supported",
                                    obligation="engineering.strength@TST-0001", version="v1", manifest_sha256="a" * 64,
                                    geometry=GEOMETRY),
                   acceptance.entry(before, "EV-002", {"PN": "TST-0004"}, "geometrically_manufacturable",
                                    obligation="process.laser.kerf@TST-0004/cut", version="v1", manifest_sha256="a" * 64,
                                    geometry=GEOMETRY),
                   {"id": "EV-003", "subject": {"PN": "TST-0002"}, "level": "cad_valid", "result": "planned",
                    "method": "TST", "obligation": "cad.readback@TST-0002"}]
        after_docs = copy.deepcopy(docs)
        after_docs["manufacturing/materials.yaml"]["profiles"][0]["grade"] = fx.known("TST other grade")
        after_docs["manufacturing/evidence.yaml"] = {"entries": entries}
        result = impact.compare(before, normalized(after_docs), before_geometry=GEOMETRY, after_geometry=GEOMETRY,
                                since="v1", version="v2")
        self.assertEqual(result.stale_evidence["EV-001"], ("material",))
        self.assertEqual(result.stale_evidence["EV-003"], ("unrecorded",), "absent dependency metadata is never current")
        self.assertEqual([item["evidence"] for item in result.carry_forward], ["EV-002"])
        self.assertIn("candidate only", result.carry_forward[0]["note"])

    def test_a_reopened_stage_never_raises_the_recheck_threshold(self) -> None:
        docs = documents()
        docs["product.yaml"]["flow"] = {"stage": "analysis", "recheck_from": "layout"}
        before = normalized(docs)
        after = copy.deepcopy(docs)
        bracket(after)["orientation"]["rotation"] = {"axis": [0, 1, 0], "angle_deg": 90}
        result = impact.compare(before, normalized(after), before_geometry=GEOMETRY, after_geometry=GEOMETRY)
        self.assertEqual(result.proposed_flow, {"stage": "detail", "recheck_from": "layout"})
        after["product.yaml"]["use_case"]["purpose"] = fx.known("TST changed purpose")
        result = impact.compare(before, normalized(after), before_geometry=GEOMETRY, after_geometry=GEOMETRY)
        self.assertEqual(result.proposed_flow, {"stage": "intent", "recheck_from": "intent"})


class Selection(unittest.TestCase):
    """A confirmed selection (U2's qualified polymer cover, confirmed by DR-001) against changed records."""

    def setUp(self) -> None:
        self.docs, self.digest = acceptance.recorded_selection(acceptance.selection_scenarios().qualified_polymer_cover(),
                                                               primary="printed_cover")

    def compare(self, after: dict[str, Any]) -> Any:
        return impact.compare(normalized(self.docs), normalized(after), before_selection_sha256=self.digest,
                              after_selection_sha256=acceptance.evidence.selection.input_digest(after))

    def test_a_changed_selection_input_reopens_the_confirmed_choice(self) -> None:
        after = copy.deepcopy(self.docs)
        after["manufacturing/materials.yaml"]["profiles"][0]["revision"] = 2
        result = self.compare(after)
        self.assertEqual((result.selection["changed"], result.selection["stale"], result.selection["recorded"]),
                         (True, True, self.digest))
        self.assertIn("the selection inputs changed (selection.input_digest)", result.reopened_decisions["DR-001"])
        self.assertTrue(result.any)

    def part(self, docs: dict[str, Any]) -> dict[str, Any]:
        rel = sorted(rel for rel in docs if rel.startswith("parts/") and rel.endswith("/part.yaml"))[0]
        return docs[rel]

    def test_a_colour_change_keeps_a_confirmed_selection_current(self) -> None:
        after = copy.deepcopy(self.docs)
        self.part(after)["intent"]["color"] = "#FF8000"
        self.assertEqual(acceptance.evidence.selection.input_digest(after), self.digest)
        result = self.compare(after)
        self.assertEqual((result.selection["changed"], result.selection["stale"]), (False, False))
        self.assertEqual(result.reopened_decisions, {})

    def test_a_material_profile_change_still_reopens_a_confirmed_selection(self) -> None:
        after = copy.deepcopy(self.docs)
        self.part(after)["intent"]["material_profile"] = "tst_other_profile"
        self.assertNotEqual(acceptance.evidence.selection.input_digest(after), self.digest)
        result = self.compare(after)
        self.assertEqual((result.selection["changed"], result.selection["stale"]), (True, True))
        self.assertIn("DR-001", result.reopened_decisions)

    def test_records_without_a_colour_keep_their_recorded_selection_digest(self) -> None:
        """Digests recorded in selection.yaml (assessment.input_sha256) stay valid. The pins come from the
        digest before color left the scope."""
        digest = acceptance.evidence.selection.input_digest
        self.assertEqual(digest(documents()), "14eefb6b8e5cb822baae30ec3612eefefac8d22e55482ef23227234fa73ea01d")
        self.assertEqual(self.digest, "d22bad8dfe54d21aea9dc9248ae15c665d0be4741a70b097e292379955387645")

    def test_confirming_the_choice_is_no_selection_input(self) -> None:
        before, _ = acceptance.recorded_selection(acceptance.selection_scenarios().qualified_polymer_cover())
        result = impact.compare(normalized(before), normalized(self.docs),
                                before_selection_sha256=acceptance.evidence.selection.input_digest(before),
                                after_selection_sha256=self.digest)
        self.assertEqual((result.selection["changed"], result.selection["stale"]), (False, False))
        self.assertEqual((result.reopened_decisions, result.any), ({}, False))

    def test_an_assessment_of_other_inputs_is_reopened_without_a_change(self) -> None:
        stale, digest = acceptance.recorded_selection(self.docs, primary="printed_cover", digest="0" * 64)
        result = impact.compare(normalized(stale), normalized(stale), before_selection_sha256=digest,
                                after_selection_sha256=digest)
        self.assertEqual((result.selection["changed"], result.selection["stale"], result.any), (False, True, False))
        self.assertEqual(result.reopened_decisions["DR-001"], ("the recorded selection assessment is not of the current inputs",))

    def test_without_digests_the_selection_is_not_compared(self) -> None:
        after = copy.deepcopy(self.docs)
        after["manufacturing/materials.yaml"]["profiles"][0]["revision"] = 2
        result = impact.compare(normalized(self.docs), normalized(after))
        self.assertIsNone(result.selection)
        self.assertNotIn("DR-001", result.reopened_decisions)


class Cli(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-impact-test-")
        self.addCleanup(temporary.cleanup)
        self.hw = fx.write_record(Path(temporary.name) / "hw", fx.tst_record())
        for pn in GEOMETRY:
            (self.hw / "parts" / pn / "model.py").write_text(f"# {pn}\n", encoding="utf-8")

    def build(self, label: str) -> None:
        folder = self.hw / "versions" / label
        pns = sorted(p.parent.name for p in (self.hw / "parts").glob("*/part.yaml"))
        acceptance.write_version_record(self.hw, folder, pns)
        files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(folder.rglob("*")) if p.is_file()}
        parts = {path.parent.name: {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in sorted(self.hw.glob("parts/*/model.py"))}
        (folder / "manifest.json").write_text(json.dumps({"label": label, "parts": parts, "files": files}), encoding="utf-8")

    def run_cli(self, *args: str) -> tuple[int, dict[str, Any]]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = impact.main(["--hw", str(self.hw), *args])
        return code, json.loads(out.getvalue())

    def test_a_material_change_since_a_built_version_is_reported_and_nothing_is_written(self) -> None:
        self.build("v1")
        code, report = self.run_cli("--since-version", "v1")
        self.assertEqual((code, report["status"]), (0, "unchanged"))
        self.assertEqual((report["selection"]["changed"], report["selection"]["recorded"]), (False, None))
        materials = self.hw / "manufacturing" / "materials.yaml"
        data = yaml.safe_load(materials.read_text(encoding="utf-8"))
        data["profiles"][0]["revision"] = 2
        materials.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        before = {p: p.read_bytes() for p in self.hw.rglob("*") if p.is_file()}
        code, report = self.run_cli("--since-version", "v1", "--out", str(self.hw.parent / ".cad-work" / "impact.json"))
        self.assertEqual((code, report["status"]), (1, "impact"))
        self.assertIn("material", report["changed"]["TST-0001"])
        self.assertIn("engineering.creep@TST-0001", report["stale_obligations"])
        self.assertTrue(report["selection"]["changed"], "materials.yaml is a selection input")
        self.assertEqual({p: p.read_bytes() for p in self.hw.rglob("*") if p.is_file()}, before, "report only")
        self.assertTrue((self.hw.parent / ".cad-work" / "impact.json").is_file())

    def test_an_unsupported_record_version_refuses(self) -> None:
        product = self.hw / "product.yaml"
        data = yaml.safe_load(product.read_text(encoding="utf-8"))
        del data["record_version"]
        product.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.build("v1")
        code, report = self.run_cli("--since-version", "v1")
        self.assertEqual((code, report["code"]), (2, "record.version_unsupported"))
        self.assertIn("record version 2 only", report["message"])


if __name__ == "__main__":
    unittest.main()
