#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Manufacturing guideline discovery and layered resolution (benchhand-lch). Every case names the rule it proves.
The guideline files are synthetic: written to a temporary directory from the dictionaries below, plus the files
under fixtures/guidelines/."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module as load  # noqa: E402

fx = load("cad_record_mi_fixtures", HERE / "fixtures" / "manufacturing_intent.py")
mi = fx.intent_module()
gl = load("cad_record_guidelines", SKILL / "scripts" / "guidelines.py")
FIXTURES = HERE / "fixtures" / "guidelines"
SHA = "a" * 64


def cite() -> list[dict[str, Any]]:
    return [fx.source("datasheet", "TST guide", locator="table 2")]


def limit(characteristic: str, operator: str, value: float | None = None, units: str = "mm", **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"characteristic": characteristic, "operator": operator, "citations": cite()}
    if value is not None:
        data["quantity"] = fx.quantity(value, units)
    data.update(extra)
    return data


def discrete(*sizes: float, units: str = "mm", **extra: Any) -> dict[str, Any]:
    """A one_of limit on nozzle_diameter: the discrete sizes a printer publishes."""
    return {"characteristic": "nozzle_diameter", "operator": "one_of", "quantities": [fx.quantity(size, units) for size in sizes],
            "citations": cite(), **extra}


def microns(*sizes: int) -> list[Any]:
    return [mi.Quantity("um", value=float(size)) for size in sizes]


def per_line(characteristic: str, factor: float, floor: float, base: str = "line_width", **extra: Any) -> dict[str, Any]:
    return limit(characteristic, ">=", relative={"relative_to": base, "factor": factor, "floor": fx.quantity(floor)}, **extra)


def guideline(ident: str, limits: list[dict[str, Any]], revision: int = 1, **scope: Any) -> dict[str, Any]:
    return {"schema_version": 1, "id": ident, "revision": revision, "title": f"{ident} (TST)", "scope": {"process": "fdm", **scope},
            "limits": limits}


def put(directory: Path, name: str, document: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yaml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def record(*, nozzle: float | None = 0.4, family: Any = "pa", filler: Any = None, calibrations: list[dict[str, Any]] | None = None,
           pin: list[str] | None = None, nozzle_material: str | None = None, line_width: float | None = None) -> Any:
    parameters: dict[str, Any] = {}
    if nozzle is not None:
        parameters["nozzle_diameter"] = fx.known(fx.quantity(nozzle))
    if line_width is not None:
        parameters["line_width"] = fx.known(fx.quantity(line_width))
    if nozzle_material is not None:
        parameters["nozzle_material"] = fx.known(nozzle_material)
    extra: dict[str, Any] = {"guidelines": pin} if pin else {}
    printer = fx.capability_profile("tst_printer", "fdm", parameters=parameters, calibrations=calibrations or [], **extra)
    facts: dict[str, Any] = {}
    if family is not None:
        facts["material_family"] = fx.known(family)
    if filler is not None:
        facts["filler"] = fx.known(filler) if filler != "none" else fx.not_applicable("unfilled")
    material = fx.material_profile("tst_pa", level="family", form="printed", **facts)
    return mi.normalize_record(fx.record(capabilities=[printer], materials=[material]))


OP = types.SimpleNamespace(capability="tst_printer")


def resolve(rec: Any, catalog: Any, characteristic: str, **extra: Any) -> Any:
    return gl.resolve(rec, OP, characteristic, catalog=catalog, material="tst_pa", **extra)


class Directories(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.hw, self.shipped = root / "hw", root / "shipped"
        self.project = self.hw / "manufacturing" / "guidelines"

    def catalog(self) -> Any:
        return gl.discover(self.hw, shipped=self.shipped)


class Discovery(Directories):
    def test_a_project_set_shadows_the_shipped_set_of_the_same_id_and_both_revisions_are_reported(self) -> None:
        put(self.shipped, "generic", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)], revision=1))
        put(self.project, "generic", guideline("fdm.generic", [limit("min_wall", ">=", 1.5)], revision=3))
        catalog = self.catalog()
        self.assertEqual(catalog.guidelines["fdm.generic"].revision, 3)
        self.assertEqual(catalog.guidelines["fdm.generic"].origin, "project")
        (shadow,) = catalog.shadows
        self.assertEqual((shadow.id, shadow.winner.revision, [g.revision for g in shadow.hidden]), ("fdm.generic", 3, [1]))
        self.assertEqual(shadow.hidden[0].origin, "shipped")

    def test_an_invalid_file_is_refused_by_name_and_never_skipped_silently(self) -> None:
        put(self.shipped, "ok", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        broken = guideline("fdm.material.pa", [limit("min_wall", ">=", 0.8)])
        broken["limits"][0]["bogus"] = 1
        put(self.project, "broken", broken)
        (self.project / "garbled.yaml").write_text("id: [unclosed\n", encoding="utf-8")
        catalog = self.catalog()
        self.assertEqual(sorted(r.path for r in catalog.refused), ["manufacturing/guidelines/broken.yaml", "manufacturing/guidelines/garbled.yaml"])
        reasons = {r.path: str(r) for r in catalog.refused}
        self.assertIn("broken.yaml is refused", reasons["manufacturing/guidelines/broken.yaml"])
        self.assertIn("bogus", reasons["manufacturing/guidelines/broken.yaml"])
        self.assertIn("cannot read", reasons["manufacturing/guidelines/garbled.yaml"])
        self.assertEqual(sorted(catalog.guidelines), ["fdm.generic"])

    def test_a_refused_project_override_does_not_fall_back_to_the_shipped_set_of_its_id(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 0.8)], material_family=["pa"]))
        broken = guideline("fdm.material.pa", [limit("min_wall", ">=", 0.8)], revision=2, material_family=["pa"])
        broken["limits"][0]["quantity"]["units"] = "parsec"
        put(self.project, "pa", broken)
        catalog = self.catalog()
        self.assertEqual(catalog.guidelines, {})
        self.assertEqual(catalog.blocked, frozenset({"fdm.material.pa"}))

    def test_the_fixture_file_that_breaks_the_schema_is_refused(self) -> None:
        catalog = gl.discover(None, shipped=FIXTURES / "invalid")
        self.assertEqual([r.path for r in catalog.refused], ["bad_operator.yaml"])
        self.assertIn("min", str(catalog.refused[0]))

    def test_two_files_of_one_id_in_one_directory_are_refused(self) -> None:
        put(self.project, "a", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.project, "b", guideline("fdm.generic", [limit("min_wall", ">=", 0.9)]))
        catalog = self.catalog()
        self.assertEqual([r.path for r in catalog.refused], ["manufacturing/guidelines/b.yaml"])
        self.assertEqual(catalog.blocked, frozenset({"fdm.generic"}))

    def test_a_file_in_a_home_like_directory_is_never_discovered_and_the_home_is_never_read(self) -> None:
        home = FIXTURES / "home"
        put(self.shipped, "ok", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}), \
                mock.patch.object(Path, "home", side_effect=AssertionError("the home directory is read")):
            catalog = self.catalog()
        self.assertTrue((home / ".config" / "benchhand" / "guidelines" / "home.yaml").is_file())
        self.assertEqual(sorted(catalog.guidelines), ["fdm.generic"])
        self.assertEqual(catalog.refused, ())

    def test_a_project_file_named_like_a_shipped_copy_is_refused_by_name(self) -> None:
        put(self.project, "shipped--escape", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.project, "generic", guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.2)], nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
        catalog = self.catalog()
        self.assertEqual([r.path for r in catalog.refused], ["manufacturing/guidelines/shipped--escape.yaml"])
        self.assertIn("shipped--", str(catalog.refused[0]))
        self.assertEqual(sorted(catalog.guidelines), ["fdm.nozzle.d0_4"])

    def test_a_snapshot_reads_the_shipped_copies_a_build_wrote(self) -> None:
        put(self.project, "shipped--pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]))
        catalog = gl.discover(self.hw, snapshot=True)
        self.assertEqual((sorted(catalog.guidelines), catalog.refused), (["fdm.material.pa"], ()))

    def test_a_quantity_that_cannot_be_read_is_refused_by_name_and_resolution_goes_on(self) -> None:
        reversed_limit = limit("min_wall", "between")
        reversed_limit["quantity"] = fx.quantity(lower=0.6, upper=0.4)
        not_finite = limit("min_wall", ">=", float("nan"))
        reversed_scope = guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.2)], nozzle_diameter=fx.quantity(lower=0.6, upper=0.4))
        reversed_floor = guideline("fdm.generic", [per_line("min_wall", 3, 0.8)])
        reversed_floor["limits"][0]["relative"]["floor"] = fx.quantity(lower=0.9, upper=0.8)
        cases = {"limit interval": guideline("fdm.a", [reversed_limit]), "limit not finite": guideline("fdm.b", [not_finite]),
                 "scope interval": reversed_scope, "relative floor interval": reversed_floor}
        put(self.shipped, "good", guideline("fdm.good", [limit("min_wall", ">=", 1.0)]))
        for name, document in cases.items():
            put(self.project, name.replace(" ", "_"), document)
        catalog = self.catalog()
        self.assertEqual(sorted(r.path for r in catalog.refused), sorted(f"manufacturing/guidelines/{n.replace(' ', '_')}.yaml" for n in cases))
        self.assertEqual(sorted(catalog.guidelines), ["fdm.good"])
        self.assertEqual(resolve(record(), catalog, "min_wall").value, mi.Quantity("mm", value=1.0))

    def test_a_catalog_digests_are_the_sha256_of_each_file(self) -> None:
        put(self.shipped, "generic", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)], revision=2))
        import hashlib
        expected = hashlib.sha256((self.shipped / "generic.yaml").read_bytes()).hexdigest()
        self.assertEqual(self.catalog().digests(), {"fdm.generic@2": expected})


class Specificity(Directories):
    def test_the_most_specific_scope_wins_whatever_the_load_order(self) -> None:
        put(self.shipped, "a_pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]))
        put(self.shipped, "z_generic", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=1.5)))
        self.assertEqual([p.guideline for p in found.provenance], ["fdm.material.pa@1"])
        self.assertEqual([(s.guideline, s.layer) for s in found.provenance[0].shadowed], [("fdm.generic@1", "generic")])

    def test_a_scope_that_does_not_match_does_not_apply(self) -> None:
        put(self.shipped, "a_pc", guideline("fdm.material.pc", [limit("min_wall", ">=", 3.0)], material_family=["pc"]))
        put(self.shipped, "z_generic", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.0))

    def test_the_number_of_selectors_ranks_a_set_whatever_the_discovery_order(self) -> None:
        relaxes = {"reason": "the nozzle set prints thinner walls", "citation": cite()[0]}
        for first, second in (("a_two", "b_one"), ("b_two", "a_one")):
            with self.subTest(order=(first, second)):
                shipped = Path(self.temp.name) / f"order_{first}"
                put(shipped, first, guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.0, relaxes=relaxes)],
                                              material_family=["pa"], nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
                put(shipped, second, guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]))
                found = resolve(record(), gl.discover(None, shipped=shipped), "min_wall")
                self.assertEqual((found.value, found.provenance[0].guideline), (mi.Quantity("mm", value=1.0), "fdm.nozzle.d0_4@1"))
                self.assertTrue(any("relaxed to >= 1 mm by fdm.nozzle.d0_4@1" in w for w in found.warnings), found.warnings)

    def test_a_set_with_two_selectors_that_loosens_without_relaxes_stays_under_one_with_a_single_selector(self) -> None:
        for first, second in (("a_two", "b_one"), ("b_two", "a_one")):
            with self.subTest(order=(first, second)):
                shipped = Path(self.temp.name) / f"loose_{first}"
                put(shipped, first, guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.0)], material_family=["pa"],
                                              nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
                put(shipped, second, guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]))
                found = resolve(record(), gl.discover(None, shipped=shipped), "min_wall")
                self.assertEqual((found.value, found.provenance[0].guideline), (mi.Quantity("mm", value=1.5), "fdm.material.pa@1"))
                self.assertTrue(any("without `relaxes`" in w for w in found.warnings), found.warnings)

    def test_a_nozzle_interval_selects_by_the_profile_nozzle(self) -> None:
        put(self.shipped, "n04", guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.2)],
                                           nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
        put(self.shipped, "n06", guideline("fdm.nozzle.d0_6", [limit("min_wall", ">=", 1.8)],
                                           nozzle_diameter=fx.quantity(lower=0.55, upper=0.65)))
        self.assertEqual(resolve(record(nozzle=0.4), self.catalog(), "min_wall").value, mi.Quantity("mm", value=1.2))
        self.assertEqual(resolve(record(nozzle=0.6), self.catalog(), "min_wall").value, mi.Quantity("mm", value=1.8))
        self.assertEqual(resolve(record(nozzle=0.8), self.catalog(), "min_wall").status, "unknown")

    def test_equally_specific_sets_that_disagree_keep_the_stricter_value(self) -> None:
        put(self.shipped, "x", guideline("fdm.material.x", [limit("min_wall", ">=", 1.0)], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [limit("min_wall", ">=", 1.4)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.4))
        self.assertEqual([p.guideline for p in found.provenance], ["fdm.material.y@1"])
        self.assertEqual([s.guideline for s in found.provenance[0].shadowed], ["fdm.material.x@1"])

    def test_a_maximum_keeps_the_smaller_value_when_equally_specific(self) -> None:
        put(self.shipped, "x", guideline("fdm.material.x", [limit("overhang_angle", "<=", 50, "deg")], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [limit("overhang_angle", "<=", 40, "deg")], material_family=["pa"]))
        self.assertEqual(resolve(record(), self.catalog(), "overhang_angle").value, mi.Quantity("deg", value=40))

    def test_an_orientation_scoped_limit_applies_only_to_that_orientation(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0),
                                                         limit("min_wall", ">=", 1.6, applies_to={"orientation": "vertical"})]))
        catalog = self.catalog()
        self.assertEqual(resolve(record(), catalog, "min_wall").value, mi.Quantity("mm", value=1.0))
        self.assertEqual(resolve(record(), catalog, "min_wall", orientation="vertical").value, mi.Quantity("mm", value=1.6))


class TightenOnly(Directories):
    def setUp(self) -> None:
        super().setUp()
        put(self.shipped, "generic", guideline("fdm.generic", [limit("min_wall", ">=", 1.2)]))

    def test_a_more_specific_limit_that_relaxes_without_relaxes_is_ignored_with_a_warning(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 0.8)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.2))
        self.assertTrue(any("without `relaxes`" in w and "fdm.material.pa@1" in w for w in found.warnings), found.warnings)
        self.assertIn("weaker than a less specific limit", found.provenance[0].shadowed[0].why)

    def test_a_relaxation_with_relaxes_is_taken_with_a_warning(self) -> None:
        relaxes = {"reason": "vendor profile prints thinner walls", "citation": cite()[0]}
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 0.8, relaxes=relaxes)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=0.8)))
        self.assertTrue(any("relaxed to >= 0.8 mm by fdm.material.pa@1" in w for w in found.warnings), found.warnings)

    def test_a_tightening_limit_needs_no_relaxes_and_gives_no_warning(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.6)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.value, found.warnings), (mi.Quantity("mm", value=1.6), ()))

    def test_a_less_specific_set_cannot_loosen_a_more_specific_one(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.6)], material_family=["pa"]))
        put(self.shipped, "loose", guideline("fdm.loose", [limit("min_wall", ">=", 0.5)]))
        self.assertEqual(resolve(record(), self.catalog(), "min_wall").value, mi.Quantity("mm", value=1.6))


class Extends(Directories):
    def test_an_abstract_set_is_only_inherited_never_matched(self) -> None:
        base = guideline("fdm.base", [limit("overhang_angle", "<=", 40, "deg")])
        base["abstract"] = True
        child = guideline("fdm.material.pa", [limit("min_wall", ">=", 1.0)], material_family=["pa"])
        child["extends"] = ["fdm.base"]
        put(self.shipped, "base", base)
        put(self.shipped, "pa", child)
        catalog = self.catalog()
        self.assertNotIn("fdm.base", [g.id for g in gl.applicable(catalog, gl.context_for(record().capabilities["tst_printer"]))])
        found = resolve(record(), catalog, "overhang_angle")
        self.assertEqual((found.value, [p.guideline for p in found.provenance]), (mi.Quantity("deg", value=40), ["fdm.base@1"]))

    def test_a_child_that_relaxes_its_parent_with_relaxes_wins_over_the_parent(self) -> None:
        relaxes = {"reason": "the child prints thinner walls", "citation": cite()[0]}
        put(self.shipped, "base", {**guideline("fdm.base", [limit("min_wall", ">=", 1.5)]), "abstract": True})
        put(self.shipped, "pa", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.0, relaxes=relaxes)], material_family=["pa"]),
                                 "extends": ["fdm.base"]})
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.value, [p.guideline for p in found.provenance]), (mi.Quantity("mm", value=1.0), ["fdm.material.pa@1"]))
        self.assertTrue(any("relaxed to >= 1 mm by fdm.material.pa@1" in w for w in found.warnings), found.warnings)
        self.assertEqual([(s.guideline, s.layer) for s in found.provenance[0].shadowed], [("fdm.base@1", "material")])

    def test_a_child_that_loosens_its_parent_without_relaxes_keeps_the_parent_value_with_a_warning(self) -> None:
        put(self.shipped, "base", {**guideline("fdm.base", [limit("min_wall", ">=", 1.5)]), "abstract": True})
        put(self.shipped, "pa", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.0)], material_family=["pa"]),
                                 "extends": ["fdm.base"]})
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.value, [p.guideline for p in found.provenance]), (mi.Quantity("mm", value=1.5), ["fdm.base@1"]))
        self.assertTrue(any("without `relaxes`" in w for w in found.warnings), found.warnings)

    def test_the_pin_holds_across_the_whole_extends_closure(self) -> None:
        put(self.shipped, "base", {**guideline("fdm.base", [limit("min_wall", ">=", 1.5)]), "abstract": True})
        put(self.shipped, "pa", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.0)], material_family=["pa"]),
                                 "extends": ["fdm.base"]})
        catalog = self.catalog()
        pinned = record(pin=["fdm.base@2"])
        found = resolve(pinned, catalog, "min_wall")
        self.assertEqual(found.status, "unknown", "revision 1 of fdm.base must not be used under a pin at revision 2")
        self.assertIn("fdm.base", found.reasons[0])
        self.assertIn("pinned at revision 2", found.reasons[0])
        context = gl.context_for(pinned.capabilities["tst_printer"], pinned.materials["tst_pa"])
        self.assertNotIn("fdm.base@1", gl.applicable_digests(catalog, context))
        held = resolve(record(pin=["fdm.base@1"]), catalog, "min_wall")
        self.assertEqual((held.status, held.value), ("guideline", mi.Quantity("mm", value=1.5)))

    def test_an_abstract_set_alone_resolves_nothing(self) -> None:
        base = guideline("fdm.base", [limit("overhang_angle", "<=", 40, "deg")])
        base["abstract"] = True
        put(self.shipped, "base", base)
        self.assertEqual(resolve(record(), self.catalog(), "overhang_angle").status, "unknown")

    def test_parents_are_read_in_order_and_the_child_may_tighten_them(self) -> None:
        put(self.shipped, "a", {**guideline("fdm.a", [limit("min_wall", ">=", 1.0)]), "abstract": True})
        put(self.shipped, "b", {**guideline("fdm.b", [limit("min_wall", ">=", 1.3)]), "abstract": True})
        put(self.shipped, "c", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]),
                                "extends": ["fdm.a", "fdm.b"]})
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.5))
        self.assertEqual(sorted(s.guideline for s in found.provenance[0].shadowed), ["fdm.a@1", "fdm.b@1"])

    def test_a_parent_that_is_missing_makes_the_limit_unknown_with_the_reason(self) -> None:
        put(self.shipped, "c", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]),
                                "extends": ["fdm.nowhere"]})
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("fdm.nowhere is not a known guideline set", found.reasons[0])

    def test_a_cycle_makes_the_limit_unknown(self) -> None:
        put(self.shipped, "a", {**guideline("fdm.a", [limit("min_wall", ">=", 1.0)]), "extends": ["fdm.b"]})
        put(self.shipped, "b", {**guideline("fdm.b", [limit("min_wall", ">=", 1.0)]), "extends": ["fdm.a"]})
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("extends itself", found.reasons[0])


class LineWidth(Directories):
    def test_a_line_width_limit_uses_the_line_width_and_a_nozzle_limit_uses_the_nozzle(self) -> None:
        for base, nozzle, width, expected in (("line_width", 0.4, 0.5, 1.5), ("nozzle_diameter", 0.4, 0.5, 1.2),
                                              ("line_width", 0.4, None, 1.2), ("nozzle_diameter", 0.6, 0.5, 1.8)):
            with self.subTest(base=base, nozzle=nozzle, width=width):
                shipped = Path(self.temp.name) / f"shipped_{base}_{nozzle}_{width}"
                put(shipped, "g", guideline("fdm.generic", [per_line("min_wall", 3, 0.8, base=base)]))
                catalog = gl.discover(None, shipped=shipped)
                self.assertAlmostEqual(resolve(record(nozzle=nozzle, line_width=width), catalog, "min_wall").value.value, expected)

    def test_a_nozzle_limit_without_a_nozzle_is_unknown_and_does_not_borrow_the_line_width(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [per_line("min_wall", 3, 0.8, base="nozzle_diameter")]))
        found = resolve(record(nozzle=None, line_width=0.5), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("no nozzle diameter", found.reasons[0])

    def test_the_floor_holds_when_the_multiple_is_smaller(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [per_line("min_wall", 3, 0.8)]))
        self.assertEqual(resolve(record(nozzle=0.2), self.catalog(), "min_wall").value, mi.Quantity("mm", value=0.8))

    def test_a_profile_with_neither_line_width_nor_nozzle_is_unknown_never_the_floor(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [per_line("min_wall", 3, 0.8)]))
        found = resolve(record(nozzle=None), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("neither a line width nor a nozzle diameter", found.reasons[0])

    def test_a_factor_that_is_not_finite_refuses_the_file_by_name(self) -> None:
        for name, factor in (("inf", float("inf")), ("nan", float("nan"))):
            put(self.project, name, guideline(f"fdm.{name}", [per_line("min_wall", factor, 0.8)]))
        catalog = self.catalog()
        self.assertEqual(sorted(r.path for r in catalog.refused),
                         ["manufacturing/guidelines/inf.yaml", "manufacturing/guidelines/nan.yaml"])
        self.assertTrue(all("factor" in str(r) for r in catalog.refused))

    def test_a_computed_limit_that_is_not_finite_is_unknown_and_reaches_no_trace(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [per_line("min_wall", 1e308, 0.8)]))
        found = resolve(record(nozzle=10.0), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("not finite", found.reasons[0])
        self.assertNotIn("Infinity", gl.trace_bytes([found]).decode("utf-8"))

    def specific_over_generic(self, specific: dict[str, Any]) -> Any:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.shipped, "n", guideline("fdm.nozzle.d2", [specific], nozzle_diameter=fx.quantity(lower=1.9, upper=2.1)))
        return resolve(record(nozzle=2.0), self.catalog(), "min_wall")

    def test_a_more_specific_limit_that_overflows_is_unknown_and_never_loses_to_the_generic_one(self) -> None:
        found = self.specific_over_generic(per_line("min_wall", 1e308, 0.8, base="nozzle_diameter"))
        self.assertEqual(found.status, "unknown")
        self.assertIn("fdm.nozzle.d2@1 min_wall: the computed limit inf mm is not finite", found.reasons[0])
        self.assertTrue(any("not finite" in w for w in found.warnings), found.warnings)
        self.assertIn("not finite", gl.trace_bytes([found]).decode("utf-8"))

    def test_the_same_specific_limit_without_the_overflow_still_wins(self) -> None:
        found = self.specific_over_generic(per_line("min_wall", 4, 0.8, base="nozzle_diameter"))
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=8.0)))

    def test_a_more_specific_limit_without_a_base_is_unknown_and_never_loses_to_the_generic_one(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.shipped, "n", guideline("fdm.pa", [per_line("min_wall", 3, 0.8)], material_family=["pa"]))
        found = resolve(record(nozzle=None), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("neither a line width nor a nozzle diameter", found.reasons[0])

    def test_an_unresolved_limit_of_the_same_set_leaves_the_plain_floor(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8), per_line("min_wall", 3, 0.8)]))
        found = resolve(record(nozzle=None), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=0.8)))

    def test_an_unresolved_limit_keeps_the_equally_specific_plain_floor_above_a_generic_one(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.2), per_line("min_wall", 3, 0.8)],
                                          material_family=["pa"]))
        found = resolve(record(nozzle=None), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=1.2)))

    def test_an_unresolved_limit_below_a_higher_ranked_survivor_does_not_block_it(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [per_line("min_wall", 3, 0.8)], material_family=["pa"]))
        put(self.shipped, "cf", guideline("fdm.material.pa_cf", [limit("min_wall", ">=", 2.0)], material_family=["pa"], filler=["cf"]))
        found = resolve(record(nozzle=None, filler="cf"), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.value), ("guideline", mi.Quantity("mm", value=2.0)))

    def test_an_unresolved_limit_is_not_hidden_by_a_higher_candidate_that_is_rejected_as_a_relaxation(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [per_line("min_wall", 3, 0.8)], material_family=["pa"]))
        put(self.shipped, "cf", guideline("fdm.material.pa_cf", [limit("min_wall", ">=", 0.5)], material_family=["pa"], filler=["cf"]))
        found = resolve(record(nozzle=None, filler="cf"), self.catalog(), "min_wall")
        self.assertEqual(found.status, "unknown")
        self.assertIn("fdm.material.pa@1 min_wall: the profile states neither a line width nor a nozzle diameter", found.reasons[0])

    def test_a_relative_limit_on_an_angle_is_refused_by_name(self) -> None:
        bad = guideline("fdm.generic", [])
        bad["limits"] = [limit("overhang_angle", "<=", relative={"relative_to": "line_width", "factor": 1, "floor": fx.quantity(40, "deg")})]
        put(self.shipped, "g", bad)
        self.assertEqual([r.path for r in self.catalog().refused], ["g.yaml"])


class StrictBounds(Directories):
    """The strict operators `<` and `>` (#244) and main's `tightens` as the one tighten-or-relax order."""

    def shipped_pair(self, general: str, specific: str, **extra: Any) -> Any:
        put(self.shipped, "g", guideline("fdm.generic", [limit("bridge_span", general, 5)]))
        put(self.shipped, "n", guideline("fdm.nozzle.d0_4", [limit("bridge_span", specific, 5, **extra)], material_family=["pa"],
                                         nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
        return resolve(record(), self.catalog(), "bridge_span")

    def test_a_strict_bound_resolves_with_its_operator_and_value(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("bridge_span", "<", 5), limit("min_wall", ">", 0.8)]))
        catalog = self.catalog()
        found = resolve(record(), catalog, "bridge_span")
        self.assertEqual((found.status, found.operator, found.value), ("guideline", "<", mi.Quantity("mm", value=5)))
        self.assertEqual((resolve(record(), catalog, "min_wall").operator, resolve(record(), catalog, "min_wall").value),
                         (">", mi.Quantity("mm", value=0.8)))

    def test_at_the_5_mm_boundary_a_strict_bound_tightens_a_non_strict_one(self) -> None:
        found = self.shipped_pair("<=", "<")
        self.assertEqual((found.operator, found.value, found.warnings), ("<", mi.Quantity("mm", value=5), ()))
        self.assertEqual(found.provenance[0].guideline, "fdm.nozzle.d0_4@1")

    def test_at_the_5_mm_boundary_a_non_strict_bound_does_not_relax_a_strict_one_without_relaxes(self) -> None:
        found = self.shipped_pair("<", "<=")
        self.assertEqual((found.operator, found.value, found.provenance[0].guideline), ("<", mi.Quantity("mm", value=5), "fdm.generic@1"))
        self.assertTrue(any("without `relaxes`" in w for w in found.warnings), found.warnings)

    def test_at_the_5_mm_boundary_a_non_strict_bound_relaxes_a_strict_one_with_relaxes(self) -> None:
        found = self.shipped_pair("<", "<=", relaxes={"reason": "the nozzle set bridges to the limit", "citation": cite()[0]})
        self.assertEqual((found.operator, found.value), ("<=", mi.Quantity("mm", value=5)))
        self.assertTrue(any("relaxed to" in w for w in found.warnings), found.warnings)

    def test_a_strict_lower_bound_tightens_its_non_strict_one_at_an_equal_limit(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        put(self.shipped, "n", guideline("fdm.nozzle.d0_4", [limit("min_wall", ">", 1.0)], material_family=["pa"],
                                         nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.operator, found.value, found.warnings), (">", mi.Quantity("mm", value=1.0), ()))

    def test_equally_specific_sets_keep_the_strict_bound(self) -> None:
        put(self.shipped, "x", guideline("fdm.material.x", [limit("bridge_span", "<=", 5)], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [limit("bridge_span", "<", 5)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "bridge_span")
        self.assertEqual((found.operator, found.provenance[0].guideline), ("<", "fdm.material.y@1"))

    def test_the_one_sided_operators_are_those_of_manufacturing_intent(self) -> None:
        self.assertEqual((gl.LOWER_OPERATORS, gl.UPPER_OPERATORS), (mi.LOWER_BOUND_OPERATORS, mi.UPPER_BOUND_OPERATORS))

    def test_an_operator_the_resolver_does_not_support_is_unknown(self) -> None:
        odd = gl.Guideline("fdm.odd", 1, "TST", (), False, {"process": "fdm"},
                           ({"characteristic": "bridge_span", "operator": "~=", "quantity": fx.quantity(5), "citations": cite()},),
                           "odd.yaml", "shipped", "0" * 64)
        found = gl.resolve_guidelines(gl.Catalog({"fdm.odd": odd}), gl.Context("fdm", {}, 0.4), "bridge_span")
        self.assertEqual(found.status, "unknown")
        self.assertIn("operator ~= is not supported", found.reasons[0])


class Between(Directories):
    """A valid `between` through public resolution (benchhand-lch, round 4)."""

    def two(self, first: dict[str, Any], second: dict[str, Any]) -> Any:
        put(self.shipped, "x", guideline("fdm.material.x", [first], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [second], material_family=["pa"]))
        return resolve(record(), self.catalog(), "bridge_span")

    def between(self, low: float, high: float, **extra: Any) -> dict[str, Any]:
        return limit("bridge_span", "between", quantity=fx.quantity(lower=low, upper=high), **extra)

    def test_a_between_limit_resolves_to_its_interval(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [self.between(3, 5)]))
        found = resolve(record(), self.catalog(), "bridge_span")
        self.assertEqual((found.status, found.operator, found.value), ("guideline", "between", mi.Quantity("mm", lower=3, upper=5)))

    def test_equally_specific_between_and_one_sided_bounds_intersect(self) -> None:
        found = self.two(self.between(3, 5), limit("bridge_span", ">=", 4))
        self.assertEqual((found.status, found.operator, found.value), ("guideline", "between", mi.Quantity("mm", lower=4, upper=5)))

    def test_equally_specific_between_and_a_bound_beyond_it_share_no_value(self) -> None:
        found = self.two(self.between(3, 4), limit("bridge_span", ">=", 5))
        self.assertEqual(found.status, "unknown")
        self.assertIn("share no value", found.reasons[0])


class EndpointStrictness(Directories):
    """Endpoint openness survives intersection and containment (benchhand-lch, round 4)."""

    def pair(self, general: dict[str, Any], specific: dict[str, Any]) -> Any:
        put(self.shipped, "g", guideline("fdm.generic", [general]))
        put(self.shipped, "n", guideline("fdm.nozzle.d0_4", [specific], material_family=["pa"],
                                         nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))
        return resolve(record(), self.catalog(), "bridge_span")

    def equal_rank(self, first: dict[str, Any], second: dict[str, Any]) -> Any:
        put(self.shipped, "x", guideline("fdm.material.x", [first], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [second], material_family=["pa"]))
        return resolve(record(), self.catalog(), "bridge_span")

    def test_a_closed_between_ending_at_5_does_not_loosen_a_strict_5_without_relaxes(self) -> None:
        found = self.pair(limit("bridge_span", "<", 5), limit("bridge_span", "between", quantity=fx.quantity(lower=3, upper=5)))
        self.assertEqual((found.operator, found.value, found.provenance[0].guideline), ("<", mi.Quantity("mm", value=5), "fdm.generic@1"))
        self.assertTrue(any("without `relaxes`" in w for w in found.warnings), found.warnings)

    def test_a_closed_between_ending_at_5_loosens_a_strict_5_with_relaxes(self) -> None:
        relaxes = {"reason": "the nozzle set bridges to the limit", "citation": cite()[0]}
        found = self.pair(limit("bridge_span", "<", 5),
                          limit("bridge_span", "between", quantity=fx.quantity(lower=3, upper=5), relaxes=relaxes))
        self.assertEqual((found.operator, found.value), ("between", mi.Quantity("mm", lower=3, upper=5)))
        self.assertTrue(any("relaxed to" in w for w in found.warnings), found.warnings)

    def test_contradictory_equally_specific_bounds_do_not_collapse_into_a_singleton(self) -> None:
        found = self.equal_rank(limit("bridge_span", "<", 5), limit("bridge_span", ">=", 5))
        self.assertEqual((found.status, found.value), ("unknown", None))
        self.assertIn("share no value", found.reasons[0])

    def test_a_closed_singleton_from_two_closed_bounds_is_a_valid_result(self) -> None:
        found = self.equal_rank(limit("bridge_span", "<=", 5), limit("bridge_span", ">=", 5))
        self.assertEqual((found.operator, found.value), ("between", mi.Quantity("mm", lower=5, upper=5)))

    def test_a_result_with_one_open_end_that_no_operator_can_state_is_unknown(self) -> None:
        found = self.equal_rank(limit("bridge_span", ">", 3), limit("bridge_span", "<=", 5))
        self.assertEqual((found.status, found.value), ("unknown", None))
        self.assertIn("cannot be stated", found.reasons[0])


class Unknowns(Directories):
    def test_a_missing_value_falls_through_to_unknown(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 0.8)]))
        found = resolve(record(), self.catalog(), "bridge_span")
        self.assertEqual((found.status, found.value, found.source), ("unknown", None, None))
        self.assertIn("no applicable guideline states bridge_span", found.reasons[0])

    def test_a_missing_value_falls_through_to_a_less_specific_layer(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("bridge_span", "<=", 5)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.6)], material_family=["pa"]))
        self.assertEqual(resolve(record(), self.catalog(), "bridge_span").value, mi.Quantity("mm", value=5))

    def test_a_requirement_with_an_unknown_scope_fact_stays_unknown_and_does_not_fall_through(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [{"characteristic": "enclosure", "operator": "equals", "value": False,
                                                          "citations": cite()}]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [{"characteristic": "enclosure", "operator": "equals", "value": True,
                                                               "citations": cite()}], material_family=["pa"]))
        found = resolve(record(family=None), self.catalog(), "enclosure")
        self.assertEqual(found.status, "unknown")
        self.assertIn("scope fact is unknown", found.reasons[0])
        self.assertIn("material_family", found.reasons[0])

    def test_a_requirement_with_a_known_scope_resolves_and_the_stricter_value_wins(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [{"characteristic": "enclosure", "operator": "equals", "value": True,
                                                          "citations": cite()}]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [{"characteristic": "nozzle_material", "operator": "one_of",
                                                               "value": ["hardened_steel", "brass"], "citations": cite()}],
                                          material_family=["pa"]))
        catalog = self.catalog()
        found = resolve(record(), catalog, "enclosure")
        self.assertEqual((found.status, found.operator, found.value), ("guideline", "equals", True))
        self.assertEqual(resolve(record(), catalog, "nozzle_material").value, ["brass", "hardened_steel"])

    def test_a_numeric_limit_with_an_unknown_scope_fact_does_not_apply_and_warns(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.6)], material_family=["pa"]))
        found = resolve(record(family=None), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.0))
        self.assertTrue(any("fdm.material.pa@1 min_wall not applied: material_family unknown" in w for w in found.warnings))

    def test_a_filler_selector_matches_an_unfilled_material_as_none_only(self) -> None:
        put(self.shipped, "cf", guideline("fdm.filler.cf", [limit("min_wall", ">=", 2.0)], filler=["cf"]))
        self.assertEqual(resolve(record(filler="none"), self.catalog(), "min_wall").status, "unknown")
        self.assertEqual(resolve(record(filler="cf"), self.catalog(), "min_wall").value, mi.Quantity("mm", value=2.0))

    def test_equally_specific_requirements_that_share_no_value_are_unknown(self) -> None:
        put(self.shipped, "x", guideline("fdm.material.x", [{"characteristic": "enclosure", "operator": "equals", "value": True,
                                                             "citations": cite()}], material_family=["pa"]))
        put(self.shipped, "y", guideline("fdm.material.y", [{"characteristic": "enclosure", "operator": "equals", "value": False,
                                                             "citations": cite()}], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "enclosure")
        self.assertEqual(found.status, "unknown")
        self.assertIn("share no value", found.reasons[0])


class DiscreteNozzleDiameters(Directories):
    """A one_of limit on nozzle_diameter holds a set of sizes, compared as whole micrometres (benchhand-tw6.5)."""

    PARENT = (0.2, 0.4, 0.6, 0.8)

    def setUp(self) -> None:
        super().setUp()
        put(self.shipped, "generic", guideline("fdm.generic", [discrete(*self.PARENT)]))

    def child(self, limits: list[dict[str, Any]]) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", limits, material_family=["pa"]))

    def test_a_set_resolves_to_its_sizes_in_whole_micrometres(self) -> None:
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual((found.status, found.operator, found.value, found.warnings),
                         ("guideline", "one_of", microns(200, 400, 600, 800), ()))

    def test_a_set_in_millimetres_and_one_in_micrometres_meet_without_float_noise(self) -> None:
        # 0.563 mm converts to 562.9999999999999 um in floating point; as whole micrometres it is 563 um
        put(self.shipped, "generic", guideline("fdm.generic", [discrete(0.563, 0.8, 1.0)]))
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(563, 800, 1000, units="um")], material_family=["pa"]))
        put(self.shipped, "pb", guideline("fdm.material.pb", [discrete(0.563, 0.8)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.value, microns(563, 800))

    def test_a_duplicate_after_conversion_is_an_invalid_file_refused_by_name(self) -> None:
        cases = {"mm and um": discrete(0.4), "same size twice": discrete(0.40, 0.4), "not whole micrometres": discrete(0.4005)}
        cases["mm and um"]["quantities"] = [fx.quantity(0.4), fx.quantity(400, "um")]
        for name, limit_ in cases.items():
            put(self.project, name.replace(" ", "_"), guideline(f"fdm.{name.replace(' ', '_')}", [limit_]))
        catalog = self.catalog()
        self.assertEqual(sorted(r.path for r in catalog.refused), sorted(f"manufacturing/guidelines/{n.replace(' ', '_')}.yaml" for n in cases))
        self.assertEqual(sorted(catalog.guidelines), ["fdm.generic"])
        self.assertIn("duplicate", " ".join(" ".join(r.problems) for r in catalog.refused if "mm_and_um" in r.path))
        self.assertIn("whole number of micrometres", " ".join(" ".join(r.problems) for r in catalog.refused if "not_whole" in r.path))

    def test_a_subset_of_the_parent_set_tightens_without_relaxes(self) -> None:
        self.child([discrete(0.4, 0.6)])
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual((found.value, found.warnings), (microns(400, 600), ()))

    def test_a_superset_of_the_parent_set_without_relaxes_is_ignored_with_a_warning(self) -> None:
        self.child([discrete(0.2, 0.4, 0.6, 0.8, 1.0)])
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.value, microns(200, 400, 600, 800))
        self.assertTrue(any("without `relaxes`" in w and "fdm.material.pa@1" in w for w in found.warnings), found.warnings)

    def test_a_superset_with_relaxes_is_taken_with_a_warning(self) -> None:
        relaxes = {"reason": "this printer also ships a 1.0 mm nozzle", "citation": cite()[0]}
        self.child([discrete(0.2, 0.4, 0.6, 0.8, 1.0, relaxes=relaxes)])
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.value, microns(200, 400, 600, 800, 1000))
        self.assertTrue(any("relaxed to" in w and "this printer also ships" in w for w in found.warnings), found.warnings)

    def test_a_set_wholly_inside_a_parent_interval_tightens_without_relaxes(self) -> None:
        for operator, quantity in (("between", fx.quantity(lower=0.2, upper=0.8)), (">=", fx.quantity(0.2)), ("<=", fx.quantity(0.8))):
            with self.subTest(operator):
                put(self.shipped, "generic", guideline("fdm.generic", [limit("nozzle_diameter", operator, quantity=quantity)]))
                self.child([discrete(0.4, 0.6)])
                found = resolve(record(), self.catalog(), "nozzle_diameter")
                self.assertEqual((found.value, found.warnings), (microns(400, 600), ()))

    def test_a_set_partly_outside_a_parent_interval_keeps_the_sizes_inside_it_unless_it_declares_relaxes(self) -> None:
        put(self.shipped, "generic", guideline("fdm.generic", [limit("nozzle_diameter", "between", quantity=fx.quantity(lower=0.3, upper=0.7))]))
        self.child([discrete(0.2, 0.4)])
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual((found.operator, found.value, found.warnings), ("one_of", microns(400), ()))
        relaxes = {"reason": "the vendor ships a 0.2 mm nozzle", "citation": cite()[0]}
        self.child([discrete(0.2, 0.4, relaxes=relaxes)])
        self.assertEqual(resolve(record(), self.catalog(), "nozzle_diameter").value, microns(200, 400))

    def test_equally_specific_sets_that_share_no_size_are_unknown(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(0.2, 0.4)], material_family=["pa"]))
        put(self.shipped, "pb", guideline("fdm.material.pb", [discrete(0.6, 0.8)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.status, "unknown")
        self.assertIn("share no value", found.reasons[0])

    def test_equally_specific_set_and_interval_keep_the_sizes_inside_the_interval(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(0.2, 0.4, 0.6)], material_family=["pa"]))
        put(self.shipped, "pb", guideline("fdm.material.pb", [limit("nozzle_diameter", ">=", quantity=fx.quantity(0.4))], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.value, microns(400, 600))
        shown = {p.guideline: (p.value, p.units) for p in found.provenance}
        sizes = [{"value": float(size), "units": "um"} for size in (200, 400, 600)]
        self.assertEqual(shown, {"fdm.material.pa@1": (sizes, "um"), "fdm.material.pb@1": ({"value": 0.4, "units": "mm"}, "mm")})

    def test_a_strict_parent_bound_drops_the_child_set_size_on_its_boundary(self) -> None:
        for operator, sizes in (("<", (0.4, 0.8)), (">", (0.2, 0.4))):
            with self.subTest(operator):
                boundary = 0.8 if operator == "<" else 0.2
                put(self.shipped, "generic", guideline("fdm.generic", [limit("nozzle_diameter", operator, quantity=fx.quantity(boundary))]))
                self.child([discrete(*sizes)])
                found = resolve(record(), self.catalog(), "nozzle_diameter")
                self.assertEqual((found.operator, found.value, found.warnings), ("one_of", microns(400), ()))

    def test_a_strict_parent_bound_accepts_a_child_set_clear_of_its_boundary_size(self) -> None:
        put(self.shipped, "generic", guideline("fdm.generic", [limit("nozzle_diameter", "<", quantity=fx.quantity(0.8))]))
        self.child([discrete(0.4, 0.6)])
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        self.assertEqual((found.value, found.warnings), (microns(400, 600), ()))

    def test_an_equally_specific_strict_interval_excludes_its_boundary_size(self) -> None:
        for operator, sizes in (("<", (0.4, 0.6, 0.8)), (">", (0.2, 0.4, 0.6))):
            with self.subTest(operator):
                boundary = 0.8 if operator == "<" else 0.2
                put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(*sizes)], material_family=["pa"]))
                put(self.shipped, "pb", guideline("fdm.material.pb", [limit("nozzle_diameter", operator, quantity=fx.quantity(boundary))],
                                                  material_family=["pa"]))
                self.assertEqual(resolve(record(), self.catalog(), "nozzle_diameter").value, microns(400, 600))

    def test_a_set_under_an_unknown_scope_fact_stays_unknown_and_does_not_fall_through(self) -> None:
        self.child([discrete(0.4)])
        found = resolve(record(family=None), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.status, "unknown")
        self.assertIn("scope fact is unknown", found.reasons[0])

    def test_a_set_scoped_to_a_nozzle_interval_is_unknown_for_a_profile_without_a_nozzle(self) -> None:
        put(self.shipped, "narrow", guideline("fdm.nozzle.narrow", [discrete(0.2, 0.4)], nozzle_diameter=fx.quantity(lower=0.2, upper=0.4)))
        found = resolve(record(nozzle=None), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.status, "unknown")
        self.assertIn("nozzle_diameter", found.reasons[0])

    def test_a_set_reaches_the_trace_as_plain_json(self) -> None:
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        document = gl.trace_document([found])
        self.assertEqual(document["resolutions"][0]["value"], [{"value": float(v), "units": "um"} for v in (200, 400, 600, 800)])
        json.dumps(document, allow_nan=False)
        self.assertEqual(document["resolutions"][0]["provenance"][0]["value"], document["resolutions"][0]["value"])


class JointNozzleConstraints(Directories):
    """A discrete nozzle-diameter set meeting a range keeps the sizes the range admits (benchhand-tw6.9), whichever of the
    two sits in the more specific layer. The sizes are those of the Bambu H2D, 0.2 to 0.8 mm."""

    H2D = (0.2, 0.4, 0.6, 0.8)
    PIN = ["fdm.machine.tst@1"]

    def rng(self, operator: str, value: float, units: str = "mm", **extra: Any) -> dict[str, Any]:
        return limit("nozzle_diameter", operator, value, units, **extra)

    def between(self, low: float, high: float) -> dict[str, Any]:
        return limit("nozzle_diameter", "between", quantity=fx.quantity(lower=low, upper=high))

    def stack(self, general: dict[str, Any], material: dict[str, Any] | None = None, machine: dict[str, Any] | None = None) -> None:
        """General, material and (pinned) machine layers, each given the limit it states."""
        put(self.shipped, "g", guideline("fdm.generic", [general]))
        if material is not None:
            put(self.shipped, "pa", guideline("fdm.material.pa", [material], material_family=["pa"]))
        if machine is not None:
            put(self.shipped, "m", guideline("fdm.machine.tst", [machine]))

    def found(self, **extra: Any) -> Any:
        return resolve(record(pin=self.PIN, **extra), self.catalog(), "nozzle_diameter")

    def test_a_range_above_a_pinned_set_keeps_the_sizes_it_admits_without_a_warning(self) -> None:
        cases = {"> 0.6": (">", 0.6, (800,)), ">= 0.6": (">=", 0.6, (600, 800)), "< 0.6": ("<", 0.6, (200, 400)),
                 "<= 0.6": ("<=", 0.6, (200, 400, 600))}
        for name, (operator, value, expected) in cases.items():
            with self.subTest(name):
                self.stack(self.rng(operator, value), machine=discrete(*self.H2D))
                found = self.found()
                self.assertEqual((found.status, found.operator, found.value, found.warnings),
                                 ("guideline", "one_of", microns(*expected), ()))

    def test_an_inclusive_between_keeps_both_end_sizes(self) -> None:
        self.stack(self.between(0.4, 0.6), machine=discrete(*self.H2D))
        self.assertEqual(self.found().value, microns(400, 600))

    def test_a_range_in_micrometres_meets_a_set_in_millimetres(self) -> None:
        self.stack(self.rng(">=", 600, "um"), machine=discrete(*self.H2D))
        found = self.found()
        self.assertEqual((found.value, found.warnings), (microns(600, 800), ()))

    def test_a_range_below_a_set_keeps_the_sizes_it_admits_without_a_warning(self) -> None:
        self.stack(discrete(*self.H2D), machine=self.rng(">=", 0.6))
        found = self.found()
        self.assertEqual((found.value, found.warnings), (microns(600, 800), ()))

    def test_a_range_that_admits_no_size_is_unknown_with_a_conflict_reason(self) -> None:
        for name, general, machine in (("range above", self.rng(">=", 1.0), discrete(*self.H2D)),
                                       ("range below", discrete(*self.H2D), self.rng(">=", 1.0))):
            with self.subTest(name):
                self.stack(general, machine=machine)
                found = self.found()
                self.assertEqual((found.status, found.value, found.provenance), ("unknown", None, ()))
                self.assertIn("share no size", found.reasons[0])
                self.assertIn("fdm.machine.tst@1", found.reasons[0])
                self.assertFalse(any("would relax" in w for w in found.warnings), found.warnings)

    def test_a_set_and_a_range_of_equal_rank_give_the_same_result_whatever_the_discovery_order(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(*self.H2D)], material_family=["pa"]))
        put(self.shipped, "pb", guideline("fdm.material.pb", [self.rng(">=", 0.6)], material_family=["pa"]))
        real = gl.applicable
        results = []
        for name, order in (("id order", list), ("reversed", lambda found: found[::-1])):
            with self.subTest(name), mock.patch.object(gl, "applicable", lambda catalog, context: order(real(catalog, context))):
                found = resolve(record(), self.catalog(), "nozzle_diameter")
                dropped = [(s.value, s.guideline, s.why) for s in found.provenance[0].shadowed if "dropped" in s.why]
                results.append((found.value, found.warnings, found.source, [p.guideline for p in found.provenance],
                                [(s.guideline, s.why) for s in found.provenance[0].shadowed if "disputed" in s.why], dropped))
        self.assertEqual(results[0][:2], (microns(600, 800), ()))
        self.assertEqual(results[0][2]["reference"], "fdm.material.pa")
        self.assertEqual(results[0], results[1])
        self.assertEqual(sorted(g for g, _ in results[0][4]), ["fdm.material.pa@1", "fdm.material.pb@1"])
        self.assertEqual(results[0][5], [("200 um, 400 um", "fdm.material.pa@1", "sizes dropped by fdm.material.pb@1 (material)")])

    def test_a_set_and_a_range_of_equal_rank_from_different_sets_are_recorded_as_disputed(self) -> None:
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(*self.H2D)], material_family=["pa"]))
        put(self.shipped, "pb", guideline("fdm.material.pb", [self.rng(">=", 0.6)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "nozzle_diameter")
        disputed = [s for s in found.provenance[0].shadowed if "disputed" in s.why]
        self.assertEqual(sorted(s.guideline for s in disputed), ["fdm.material.pa@1", "fdm.material.pb@1"])
        self.assertTrue(all("equally specific" in s.why and "600 um, 800 um" in s.why for s in disputed), disputed)

    def test_the_sizes_a_range_drops_reach_the_provenance_with_the_range_that_dropped_them(self) -> None:
        self.stack(self.rng(">=", 0.6), machine=discrete(*self.H2D))
        found = self.found()
        dropped = [s for s in found.provenance[0].shadowed if "dropped" in s.why]
        self.assertEqual([(s.value, s.guideline, s.layer) for s in dropped], [("200 um, 400 um", "fdm.machine.tst@1", "machine")])
        self.assertIn("fdm.generic@1", dropped[0].why)
        self.assertIn("generic", dropped[0].why)

    def test_a_general_range_a_material_range_and_a_machine_set_keep_the_sizes_inside_both(self) -> None:
        self.stack(self.rng(">=", 0.2), self.rng(">=", 0.6), discrete(*self.H2D))
        found = self.found()
        self.assertEqual((found.value, found.warnings), (microns(600, 800), ()))

    def test_a_general_set_a_material_range_and_a_wider_machine_set_keep_the_general_sizes_inside_the_range(self) -> None:
        self.stack(discrete(0.4, 0.6), self.rng("<=", 0.6), discrete(*self.H2D))
        found = self.found()
        self.assertEqual(found.value, microns(400, 600))
        self.assertEqual([w for w in found.warnings if "would relax" not in w], [])
        self.assertEqual(len(found.warnings), 1)
        self.assertIn("fdm.machine.tst@1", found.warnings[0])

    def test_a_single_surviving_size_stays_a_one_of_with_one_member(self) -> None:
        self.stack(self.rng(">", 0.6), machine=discrete(*self.H2D))
        found = self.found()
        self.assertEqual((found.operator, found.value), ("one_of", microns(800)))

    def test_a_set_that_declares_relaxes_replaces_the_range_with_a_warning(self) -> None:
        relaxes = {"reason": "this printer ships small nozzles", "citation": cite()[0]}
        self.stack(self.rng(">=", 0.6), machine=discrete(*self.H2D, relaxes=relaxes))
        found = self.found()
        self.assertEqual(found.value, microns(200, 400, 600, 800))
        self.assertTrue(any("relaxed to" in w and "this printer ships small nozzles" in w for w in found.warnings), found.warnings)

    def test_a_range_that_declares_relaxes_replaces_the_set_with_a_warning(self) -> None:
        relaxes = {"reason": "the vendor ships a 1.0 mm nozzle", "citation": cite()[0]}
        self.stack(discrete(*self.H2D), machine=self.rng(">=", 0.6, relaxes=relaxes))
        found = self.found()
        self.assertEqual((found.operator, found.value), (">=", mi.Quantity("mm", value=0.6)))
        self.assertTrue(any("relaxed to" in w and "the vendor ships a 1.0 mm nozzle" in w for w in found.warnings), found.warnings)

    def test_a_calibration_still_beats_the_joint_constraint(self) -> None:
        self.stack(self.rng(">=", 0.6), machine=discrete(*self.H2D))
        calibration = fx.calibration("cal_nozzle", "nozzle_diameter", "tst_pa", fx.quantity(lower=0.4, upper=0.4))
        found = self.found(calibrations=[calibration])
        self.assertEqual((found.status, found.provenance[0].layer), ("calibrated", "L4"))

    def test_an_unknown_scope_fact_keeps_the_set_unknown_and_does_not_fall_through_to_the_range(self) -> None:
        self.stack(self.rng(">=", 0.6))
        put(self.shipped, "pa", guideline("fdm.material.pa", [discrete(*self.H2D)], material_family=["pa"]))
        found = resolve(record(family=None), self.catalog(), "nozzle_diameter")
        self.assertEqual(found.status, "unknown")
        self.assertIn("scope fact is unknown", found.reasons[0])


class Pin(Directories):
    def setUp(self) -> None:
        super().setUp()
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        put(self.shipped, "n", guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.2)], material_family=["pa"],
                                         nozzle_diameter=fx.quantity(lower=0.35, upper=0.45)))

    def machine(self, value: float, **extra: Any) -> None:
        put(self.shipped, "m", guideline("fdm.machine.tst", [limit("min_wall", ">=", value, **extra)]))

    def test_a_pinned_machine_set_outranks_every_scope_matched_set(self) -> None:
        relaxes = {"reason": "the vendor prints thinner walls", "citation": cite()[0]}
        self.machine(0.9, relaxes=relaxes)
        found = resolve(record(pin=["fdm.machine.tst@1"]), self.catalog(), "min_wall")
        self.assertEqual((found.value, [(p.guideline, p.layer) for p in found.provenance]),
                         (mi.Quantity("mm", value=0.9), [("fdm.machine.tst@1", "machine")]))
        self.assertTrue(any("relaxed to >= 0.9 mm by fdm.machine.tst@1" in w for w in found.warnings), found.warnings)
        self.assertEqual(sorted((s.guideline, s.layer) for s in found.provenance[0].shadowed),
                         [("fdm.generic@1", "generic"), ("fdm.nozzle.d0_4@1", "material_nozzle")])

    def test_a_pinned_machine_sets_tighter_value_beats_a_material_nozzle_value(self) -> None:
        self.machine(1.4)
        found = resolve(record(pin=["fdm.machine.tst@1"]), self.catalog(), "min_wall")
        self.assertEqual((found.value, found.provenance[0].layer, found.warnings), (mi.Quantity("mm", value=1.4), "machine", ()))

    def test_an_abstract_machine_set_applies_only_when_the_profile_pins_it(self) -> None:
        put(self.shipped, "m", {**guideline("fdm.machine.tst", [limit("min_wall", ">=", 1.4)]), "abstract": True})
        catalog = self.catalog()
        unpinned = record()
        found = resolve(unpinned, catalog, "min_wall")
        self.assertEqual((found.value, found.provenance[0].guideline), (mi.Quantity("mm", value=1.2), "fdm.nozzle.d0_4@1"))
        context = gl.context_for(unpinned.capabilities["tst_printer"], unpinned.materials["tst_pa"])
        self.assertNotIn("fdm.machine.tst", [g.id for g in gl.applicable(catalog, context)])
        self.assertNotIn("fdm.machine.tst@1", gl.applicable_digests(catalog, context))
        pinned = record(pin=["fdm.machine.tst@1"])
        held = resolve(pinned, catalog, "min_wall")
        self.assertEqual((held.value, held.provenance[0].guideline, held.provenance[0].layer),
                         (mi.Quantity("mm", value=1.4), "fdm.machine.tst@1", "machine"))
        pinned_context = gl.context_for(pinned.capabilities["tst_printer"], pinned.materials["tst_pa"])
        self.assertIn("fdm.machine.tst@1", gl.applicable_digests(catalog, pinned_context))

    def test_a_pinned_set_that_loosens_without_relaxes_is_ignored_with_a_warning(self) -> None:
        self.machine(0.9)
        found = resolve(record(pin=["fdm.machine.tst@1"]), self.catalog(), "min_wall")
        self.assertEqual((found.value, found.provenance[0].guideline), (mi.Quantity("mm", value=1.2), "fdm.nozzle.d0_4@1"))
        self.assertTrue(any("fdm.machine.tst@1" in w and "without `relaxes`" in w for w in found.warnings), found.warnings)

    def test_the_same_set_unpinned_ranks_by_its_scope_and_is_not_a_machine_set(self) -> None:
        relaxes = {"reason": "the vendor prints thinner walls", "citation": cite()[0]}
        self.machine(0.9, relaxes=relaxes)
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual((found.value, found.provenance[0].layer), (mi.Quantity("mm", value=1.2), "material_nozzle"))

    def test_a_calibration_beats_the_pinned_machine_set(self) -> None:
        self.machine(1.4)
        calibration = fx.calibration("cal_wall", "min_wall", "tst_pa", fx.quantity(lower=0.7, upper=0.7))
        found = resolve(record(pin=["fdm.machine.tst@1"], calibrations=[calibration]), self.catalog(), "min_wall")
        self.assertEqual((found.status, found.provenance[0].layer), ("calibrated", "L4"))

    def test_a_pin_of_another_revision_excludes_the_set_and_warns(self) -> None:
        self.machine(1.4)
        found = resolve(record(pin=["fdm.machine.tst@2", "fdm.absent@1"]), self.catalog(), "min_wall")
        self.assertEqual(found.value, mi.Quantity("mm", value=1.2))
        self.assertIn("pinned fdm.machine.tst@2, but the catalog has revision 1: not applied", found.warnings)
        self.assertIn("pinned fdm.absent@1 is not in the catalog", found.warnings)


class Grade(Directories):
    def calibration(self) -> dict[str, Any]:
        return fx.calibration("cal_wall", "min_wall", "tst_pa", fx.quantity(lower=0.7, upper=0.7))

    def test_a_guideline_resolves_as_guideline_and_cites_a_guideline_source(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)], revision=4))
        found = resolve(record(), self.catalog(), "min_wall")
        self.assertEqual(found.status, "guideline")
        self.assertEqual((found.source["kind"], found.source["reference"], found.source["revision"]), ("guideline", "fdm.generic", "4"))
        self.assertEqual(found.source["sha256"], self.catalog().guidelines["fdm.generic"].sha256)
        self.assertNotEqual(found.status, "calibrated")

    def test_a_calibration_beats_a_guideline_and_is_the_only_calibrated_value(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        catalog = self.catalog()
        found = resolve(record(calibrations=[self.calibration()]), catalog, "min_wall")
        self.assertEqual((found.status, found.source["kind"]), ("calibrated", "calibration"))
        self.assertEqual(found.value, mi.Quantity("mm", lower=0.7, upper=0.7))
        self.assertEqual((found.provenance[0].layer, found.provenance[0].status, found.provenance[0].guideline), ("L4", "calibrated", "cal_wall"))
        self.assertEqual(resolve(record(), catalog, "min_wall").status, "guideline", "removing the calibration reverts the grade")

    def test_a_source_locator_survives_from_normalization_to_the_trace(self) -> None:
        calibration = self.calibration()
        calibration["source"]["locator"] = "table 2"
        rec = record(calibrations=[calibration])
        self.assertEqual(rec.capabilities["tst_printer"].calibrations[0].source.locator, "table 2")
        found = resolve(rec, gl.Catalog(), "min_wall")
        self.assertEqual(found.source["locator"], "table 2")
        self.assertEqual(json.loads(gl.trace_bytes([found]))["resolutions"][0]["source"]["locator"], "table 2")

    def test_a_calibration_of_another_material_does_not_beat_the_guideline(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        other = fx.calibration("cal_other", "min_wall", "tst_other", fx.quantity(lower=0.7, upper=0.7))
        self.assertEqual(resolve(record(calibrations=[other]), self.catalog(), "min_wall").status, "guideline")

    def test_an_operation_with_no_capability_profile_is_unknown(self) -> None:
        found = gl.resolve(record(), types.SimpleNamespace(capability=fx.unknown("not chosen")), "min_wall", catalog=gl.Catalog())
        self.assertEqual(found.status, "unknown")


class Provenance(Directories):
    def test_every_resolved_value_carries_its_provenance(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)], revision=2))
        put(self.shipped, "pa", guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]))
        found = resolve(record(), self.catalog(), "min_wall")
        (p,) = found.provenance
        self.assertEqual((p.value, p.units, p.layer, p.guideline, p.status),
                         ({"value": 1.5, "units": "mm"}, "mm", "material", "fdm.material.pa@1", "guideline"))
        self.assertEqual(p.path, "pa.yaml")
        self.assertEqual((p.citations[0]["kind"], p.citations[0]["locator"]), ("datasheet", "table 2"))
        (shadowed,) = p.shadowed
        self.assertEqual((shadowed.value, shadowed.guideline, shadowed.layer), (">= 1 mm", "fdm.generic@2", "generic"))

    def test_the_layer_follows_what_the_scope_selects(self) -> None:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0)]))
        put(self.shipped, "n", guideline("fdm.nozzle.d0_4", [limit("min_wall", ">=", 1.2)], nozzle_diameter=fx.quantity(lower=0.4, upper=0.4)))
        self.assertEqual(resolve(record(), self.catalog(), "min_wall").provenance[0].layer, "material_nozzle")


class Trace(Directories):
    def resolutions(self) -> list[Any]:
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.0), limit("bridge_span", "<=", 5)]))
        catalog = self.catalog()
        return [resolve(record(), catalog, "min_wall"), resolve(record(), catalog, "bridge_span"), resolve(record(), catalog, "min_hole")]

    def test_the_trace_is_a_stable_json_artifact_named_by_its_hash(self) -> None:
        items = self.resolutions()
        document = json.loads(gl.trace_bytes(items))
        self.assertEqual([r["characteristic"] for r in document["resolutions"]], ["bridge_span", "min_hole", "min_wall"])
        self.assertEqual(document["resolutions"][2]["provenance"][0]["guideline"], "fdm.generic@1")
        self.assertEqual(document["resolutions"][1]["status"], "unknown")
        self.assertEqual(gl.trace_sha256(items), gl.trace_sha256(list(reversed(items))))
        directory = Path(self.temp.name) / "sources"
        path = gl.write_trace(directory, items)
        self.assertEqual(path.name, f"guideline-trace-{gl.trace_sha256(items)[:16]}.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), document)

    def test_a_changed_guideline_changes_the_trace_hash(self) -> None:
        before = gl.trace_sha256(self.resolutions())
        put(self.shipped, "g", guideline("fdm.generic", [limit("min_wall", ">=", 1.1), limit("bridge_span", "<=", 5)]))
        catalog = self.catalog()
        after = gl.trace_sha256([resolve(record(), catalog, c) for c in ("min_wall", "bridge_span", "min_hole")])
        self.assertNotEqual(before, after)


class Applicable(Directories):
    def test_the_digests_cover_the_applicable_sets_and_their_parents_only(self) -> None:
        put(self.shipped, "base", {**guideline("fdm.base", [limit("min_wall", ">=", 1.0)]), "abstract": True})
        put(self.shipped, "pa", {**guideline("fdm.material.pa", [limit("min_wall", ">=", 1.5)], material_family=["pa"]),
                                 "extends": ["fdm.base"]})
        put(self.shipped, "pc", guideline("fdm.material.pc", [limit("min_wall", ">=", 2.0)], material_family=["pc"]))
        catalog = self.catalog()
        context = gl.context_for(record().capabilities["tst_printer"], record().materials["tst_pa"])
        self.assertEqual(sorted(gl.applicable_digests(catalog, context)), ["fdm.base@1", "fdm.material.pa@1"])
        edited = copy.deepcopy(guideline("fdm.material.pc", [limit("min_wall", ">=", 2.1)], material_family=["pc"]))
        put(self.shipped, "pc", edited)
        self.assertEqual(gl.applicable_digests(self.catalog(), context), gl.applicable_digests(catalog, context),
                         "a set the profile cannot resolve through does not stale it")


if __name__ == "__main__":
    unittest.main()
