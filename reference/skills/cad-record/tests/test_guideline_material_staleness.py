#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Guideline staleness per material (benchhand-tw6.1): a part's `source` fingerprint holds only the guideline sets
that apply to its own material profiles, and everything under that capability profile when its material is unknown."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module as load  # noqa: E402

acceptance = load("cad_record_acceptance_fixtures", HERE / "fixtures" / "acceptance.py")
fx, mi, impact = acceptance.fx, acceptance.mi, acceptance.impact
gl = load("cad_record_guidelines", SKILL / "scripts" / "guidelines.py")


def guideline(ident: str, minimum: float = 0.8, **scope: Any) -> dict[str, Any]:
    cite = fx.source("datasheet", "TST guide", locator="table 2")
    return {"schema_version": 1, "id": ident, "revision": 1, "title": f"{ident} (TST)", "scope": {"process": "fdm", **scope},
            "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(minimum), "citations": [cite]}]}


def route_of(profile: str) -> list[dict[str, Any]]:
    return [fx.operation("print", "fdm", profile, output_state="printed")]


def made(pn: str, material: Any, profile: str = "tst_printer", **extra: Any) -> dict[str, Any]:
    return fx.part(pn, process="fdm", part_intent=fx.intent(material_profile=material, route=route_of(profile), **extra))


def without_main_material(part: dict[str, Any]) -> dict[str, Any]:
    """The part with no `material_profile` key at all (the fixture's intent() writes `unknown` for an absent one)."""
    del part["intent"]["material_profile"]
    return part


class MaterialStaleness(unittest.TestCase):
    """Materials A (family pa) and B (family pc) under one printer; PA is made of A, PB of B."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patch = mock.patch.object(gl, "SHIPPED", root / "shipped")
        patch.start()
        self.addCleanup(patch.stop)
        parts = [made("PA", "mat_a"), made("PB", "mat_b"), made("PN", fx.unknown()), made("PU", "mat_ghost"),
                 made("PBA", "mat_b", components=[{"material_profile": "mat_a"}]), made("PO", "mat_a", "tst_other"),
                 made("PG", "mat_b", components=[{"material_profile": "mat_ghost"}]),
                 made("PX", "mat_b", components=[{"material_profile": fx.unknown()}]),
                 made("PI", "mat_b", components=[{}]),
                 without_main_material(made("PM", "mat_b", components=[{"material_profile": "mat_b"}])),
                 made("PNB", fx.not_applicable(), components=[{"material_profile": "mat_b"}])]
        materials = [fx.material_profile("mat_a", level="family", form="printed", material_family=fx.known("pa")),
                     fx.material_profile("mat_b", level="family", form="printed", material_family=fx.known("pc"))]
        printers = [fx.capability_profile(name, "fdm", parameters={"nozzle_diameter": fx.known(fx.quantity(nozzle))})
                    for name, nozzle in (("tst_printer", 0.4), ("tst_other", 0.8))]
        documents = fx.record(parts=parts, capabilities=printers, materials=materials)
        self.hw = fx.write_record(root / "hw", {rel: data for rel, data in documents.items() if not rel.startswith("_")})
        self.project = self.hw / "manufacturing" / "guidelines"

    def put(self, name: str, document: dict[str, Any]) -> None:
        self.project.mkdir(parents=True, exist_ok=True)
        (self.project / f"{name}.yaml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    def sources(self) -> dict[str, str]:
        found = impact.subject_fingerprints(mi.load_record(self.hw))
        return {pn: str(found[pn]["source"]) for pn in ("PA", "PB", "PN", "PU", "PBA", "PO", "PG", "PX", "PI", "PM", "PNB")}

    def edit(self, name: str, ident: str, **scope: Any) -> tuple[dict[str, str], dict[str, str]]:
        self.put(name, guideline(ident, 0.8, **scope))
        before = self.sources()
        self.put(name, guideline(ident, 0.9, **scope))
        return before, self.sources()

    def stale(self, name: str, ident: str, **scope: Any) -> set[str]:
        before, after = self.edit(name, ident, **scope)
        return {pn for pn in before if before[pn] != after[pn]}

    def test_editing_a_set_for_material_a_stales_a_part_of_a_and_leaves_one_of_b_fresh(self) -> None:
        stale = self.stale("pa", "fdm.material.pa", material_family=["pa"])
        self.assertIn("PA", stale)
        self.assertNotIn("PB", stale)

    def test_a_part_with_no_material_goes_stale(self) -> None:
        self.assertIn("PN", self.stale("pa", "fdm.material.pa", material_family=["pa"]))

    def test_a_part_with_a_material_missing_from_the_record_goes_stale(self) -> None:
        self.assertIn("PU", self.stale("pa", "fdm.material.pa", material_family=["pa"]))

    def test_a_part_naming_one_unknown_material_among_known_ones_takes_every_set_of_its_profile(self) -> None:
        # PG is of B plus a material the record lacks, so the set for A counts too
        self.assertIn("PG", self.stale("pa", "fdm.material.pa", material_family=["pa"]))

    def test_a_part_of_b_with_a_component_of_unknown_material_goes_stale(self) -> None:
        self.assertIn("PX", self.stale("pa", "fdm.material.pa", material_family=["pa"]))  # the unknown component could be A

    def test_a_component_that_omits_its_material_inherits_the_part_s_and_stays_narrowed(self) -> None:
        stale = self.stale("pa", "fdm.material.pa", material_family=["pa"])
        self.assertNotIn("PI", stale)  # PI is of B alone: its component inherits B

    def test_a_part_of_b_with_a_component_of_a_goes_stale(self) -> None:
        self.assertIn("PBA", self.stale("pa", "fdm.material.pa", material_family=["pa"]))

    def test_a_part_with_the_main_material_key_absent_and_a_component_of_b_takes_the_whole_profile_and_goes_stale(self) -> None:
        # the absent main could be A, so the A-only set counts although the one material named is B
        self.assertIn("PM", self.stale("pa", "fdm.material.pa", material_family=["pa"]))

    def test_a_not_applicable_main_material_is_decided_so_only_its_components_narrow_the_part(self) -> None:
        # PNB has no main material by declaration: its component of B alone decides, so an A-only edit leaves it fresh
        # and a B-only edit stales it
        self.assertNotIn("PNB", self.stale("pa", "fdm.material.pa", material_family=["pa"]))
        self.assertIn("PNB", self.stale("pc", "fdm.material.pc", material_family=["pc"]))

    def test_a_set_that_applies_to_both_materials_stales_both(self) -> None:
        self.assertLessEqual({"PA", "PB"}, self.stale("both", "fdm.material.both", material_family=["pa", "pc"]))

    def test_a_set_with_no_material_scope_stales_every_part_on_the_profile(self) -> None:
        self.assertEqual(self.stale("generic", "fdm.generic"), {"PA", "PB", "PN", "PU", "PBA", "PO", "PG", "PX", "PI", "PM", "PNB"})

    def test_an_edit_under_one_capability_profile_leaves_a_part_on_another_fresh(self) -> None:
        stale = self.stale("narrow", "fdm.nozzle.d0_4", nozzle_diameter=fx.quantity(lower=0.35, upper=0.45))
        self.assertIn("PA", stale)
        self.assertNotIn("PO", stale)  # PO is of material A too, but its 0.8 mm nozzle profile never resolves through the set

    def test_the_record_digests_nest_profile_then_material_and_keep_an_empty_name_without_materials(self) -> None:
        self.put("pa", guideline("fdm.material.pa", 0.8, material_family=["pa"]))
        self.put("generic", guideline("fdm.generic"))
        digests = mi.load_record(self.hw).guideline_digests
        self.assertEqual({m: sorted(refs) for m, refs in digests["tst_printer"].items()},
                         {"mat_a": ["fdm.generic@1", "fdm.material.pa@1"], "mat_b": ["fdm.generic@1"]})
        bare = mi.normalize_record(fx.record(capabilities=[fx.capability_profile("tst_printer", "fdm")]))
        catalog = gl.discover(self.hw)
        self.assertEqual({m: sorted(refs) for m, refs in gl.record_digests(bare, catalog)["tst_printer"].items()},
                         {"": ["fdm.generic@1", "fdm.material.pa@1"]})  # no material fact: the pa set may still apply


if __name__ == "__main__":
    unittest.main()
