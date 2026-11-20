# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The shipped FDM guideline files (benchhand-3g4): each validates against the guideline schema, ids are
unique and match the file name, every limit is cited to a dated, located source, and nothing the schema
rules out (layer height, shrinkage, Z strength, a press fit) ships."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

SKILL = Path(__file__).resolve().parents[1]
GUIDELINES = SKILL / "assets" / "manufacturing" / "guidelines"
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

fx = load("cad_record_mi_fixtures", Path(__file__).resolve().parent / "fixtures" / "manufacturing_intent.py")
registry = fx.schema_registry_module()
gl = load("cad_record_guidelines", SKILL / "scripts" / "guidelines.py")
SCHEMA = "manufacturing-guideline.schema.json"
ACCESSED = {"2026-11-18", "2026-11-19"}  # the survey day, and the day the H2D tech-specs page was added
EXPECTED_IDS = {
    "fdm.generic",
    "fdm.nozzle.d0_2", "fdm.nozzle.d0_4", "fdm.nozzle.d0_6", "fdm.nozzle.d0_8",
    "fdm.material.pla", "fdm.material.petg", "fdm.material.abs", "fdm.material.asa", "fdm.material.tpu_95a",
    "fdm.material.tpu_85a", "fdm.material.pa", "fdm.material.pc", "fdm.material.pa_cf",
    "fdm.filler.cf", "fdm.filler.gf",
    "fdm.compat.tpu_85a",
    "fdm.machine.bambu_h2d",
}
FORBIDDEN = {"layer_height", "shrinkage", "z_strength", "z_ratio", "press_fit", "percent_deviation"}


def shipped() -> dict[str, dict[str, Any]]:
    return {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(GUIDELINES.glob("*.yaml"))}


def limits_of(guideline_id: str) -> list[dict[str, Any]]:
    return next(doc for doc in shipped().values() if doc["id"] == guideline_id)["limits"]


def limit_of(guideline_id: str, characteristic: str) -> dict[str, Any]:
    return next(item for item in limits_of(guideline_id) if item["characteristic"] == characteristic)


def bare(item: dict[str, Any]) -> tuple[str, Any]:
    quantity = item["quantity"]
    return item["operator"], (quantity["value"], quantity["units"])


class ShippedFiles(unittest.TestCase):
    def test_the_expected_set_ships_and_each_file_is_named_for_its_id(self) -> None:
        files = shipped()
        self.assertEqual({doc["id"] for doc in files.values()}, EXPECTED_IDS)
        self.assertEqual(len(files), len(EXPECTED_IDS), "an id ships twice")
        for name, doc in files.items():
            with self.subTest(name):
                self.assertEqual(name, f"{doc['id']}.yaml")

    def test_every_file_validates_against_the_guideline_schema(self) -> None:
        validator = registry.document_validator(SKILL / "schemas", SCHEMA)
        for name, doc in shipped().items():
            with self.subTest(name):
                self.assertEqual([e.message for e in validator.iter_errors(doc)], [])

    def test_every_extends_names_a_shipped_file(self) -> None:
        for name, doc in shipped().items():
            for parent in doc.get("extends", []):
                with self.subTest(name, parent=parent):
                    self.assertIn(parent, EXPECTED_IDS)

    def test_every_limit_cites_a_dated_located_url_source(self) -> None:
        for name, doc in shipped().items():
            for item in doc["limits"]:
                for citation in item["citations"]:
                    with self.subTest(name, characteristic=item["characteristic"], reference=citation["reference"]):
                        self.assertNotEqual(citation["kind"], "guideline")
                        self.assertTrue(citation["url"].startswith("https://"))
                        self.assertIn(citation["accessed"], ACCESSED)
                        self.assertTrue(citation["locator"].strip())

    def test_no_forbidden_characteristic_and_no_machine_scope_ships(self) -> None:
        for name, doc in shipped().items():
            with self.subTest(name):
                self.assertFalse(FORBIDDEN & {item["characteristic"] for item in doc["limits"]})
                self.assertNotIn("machine", doc["scope"])


class ShippedValues(unittest.TestCase):
    """Expected values are the survey's figures, written out here apart from the files."""

    def test_the_generic_set_carries_the_surveyed_limits(self) -> None:
        plain = [(item["characteristic"], *bare(item)) for item in limits_of("fdm.generic") if "quantity" in item]
        self.assertEqual(plain, [
            ("overhang_angle", "<=", (45, "deg")),
            ("bridge_span", "<", (5, "mm")),
            ("min_wall", ">=", (0.8, "mm")),
            ("min_feature", ">=", (2.0, "mm")),
            ("min_hole", ">=", (2.0, "mm")),
        ])
        relative = [(item["characteristic"], item["relative"]) for item in limits_of("fdm.generic") if "relative" in item]
        self.assertEqual(relative, [("min_wall", {"relative_to": "line_width", "factor": 3, "floor": {"value": 0.8, "units": "mm"}})])

    def test_single_source_limits_have_one_citation_and_two_source_limits_two(self) -> None:
        counts = [(item["characteristic"], "relative" in item, len(item["citations"])) for item in limits_of("fdm.generic")]
        self.assertEqual(counts, [("overhang_angle", False, 2), ("bridge_span", False, 1), ("min_wall", False, 2),
                                  ("min_wall", True, 2), ("min_feature", False, 1), ("min_hole", False, 1)])

    def test_each_nozzle_set_is_three_line_widths_with_a_floor_of_0_8_mm(self) -> None:
        for diameter in ("0_2", "0_4", "0_6", "0_8"):
            with self.subTest(diameter):
                self.assertEqual(limit_of(f"fdm.nozzle.d{diameter}", "min_wall")["relative"],
                                 {"relative_to": "line_width", "factor": 3, "floor": {"value": 0.8, "units": "mm"}})

    def test_enclosure_is_required_for_the_warping_materials_and_pa_cf_is_disputed(self) -> None:
        for material in ("abs", "asa", "pa", "pc"):
            with self.subTest(material):
                item = limit_of(f"fdm.material.{material}", "enclosure")
                self.assertEqual((item["operator"], item["value"]), ("equals", True))
                self.assertNotIn("disputed", item)
        disputed = limit_of("fdm.material.pa_cf", "enclosure")
        self.assertEqual((disputed["operator"], disputed["value"], disputed["disputed"]), ("equals", True, True))
        self.assertGreaterEqual(len(disputed["citations"]), 2)

    def test_pa_cf_extends_pa_and_the_cf_filler_and_the_fillers_need_hardened_steel(self) -> None:
        self.assertEqual(next(d for d in shipped().values() if d["id"] == "fdm.material.pa_cf")["extends"],
                         ["fdm.material.pa", "fdm.filler.cf"])
        for filler in ("cf", "gf"):
            with self.subTest(filler):
                item = limit_of(f"fdm.filler.{filler}", "nozzle_material")
                self.assertEqual((item["operator"], item["value"]), ("one_of", ["hardened_steel"]))
                self.assertEqual(bare(limit_of(f"fdm.filler.{filler}", "nozzle_diameter")), (">=", (0.4, "mm")))

    def test_tpu_85a_needs_a_nozzle_of_at_least_0_6_mm(self) -> None:
        self.assertEqual(bare(limit_of("fdm.compat.tpu_85a", "nozzle_diameter")), (">=", (0.6, "mm")))


CATALOG = gl.discover(None)  # the shipped sets only, as the program reads them


def resolved(characteristic: str, pin: tuple[str, ...] | None = None, nozzle: float | None = None,
             line_width: float | None = None, **facts: str) -> Any:
    """What a profile with these scope facts, nozzle diameter and line width (mm) and, with `pin`, this guidelines pin
    resolves `characteristic` to."""
    return gl.resolve_guidelines(CATALOG, gl.Context("fdm", facts, nozzle, line_width, pin), characteristic)


def stated(found: Any) -> tuple[Any, ...]:
    """(status, operator, number or text, units, limits ignored as relaxations) of a resolved limit."""
    value = found.value
    ignored = tuple(w for w in found.warnings if "would relax" in w)
    return (found.status, found.operator, getattr(value, "value", value), getattr(value, "units", None), ignored)


class ShippedResolution(unittest.TestCase):
    """The shipped catalog resolved through the program, with no set patched in: each case fails when its limit is
    deleted or changed, or when another shipped set overrides it. Expected values are the surveyed figures."""

    def test_a_wall_is_three_line_widths_for_a_nozzle_no_nozzle_set_names(self) -> None:
        """0.5 mm is no nozzle set's diameter, so only the generic set can give 3 x 0.5 = 1.5 mm."""
        self.assertEqual(stated(resolved("min_wall", nozzle=0.5, line_width=0.5)), ("guideline", ">=", 1.5, "mm", ()))

    def test_a_wall_is_three_line_widths_when_the_profile_knows_only_its_line_width(self) -> None:
        self.assertEqual(stated(resolved("min_wall", line_width=0.45)), ("guideline", ">=", 1.35, "mm", ()))

    def test_a_wall_keeps_the_0_8_mm_floor_when_the_profile_states_no_width_or_nozzle(self) -> None:
        """The generic set also states the plain 0.8 mm floor, and the resolver leaves out a relative limit whose base is
        unknown, so the floor is what remains; without that plain limit the result would be UNKNOWN."""
        self.assertEqual(stated(resolved("min_wall")), ("guideline", ">=", 0.8, "mm", ()))

    def test_a_wall_is_the_nozzle_rule_when_a_nozzle_set_matches(self) -> None:
        self.assertEqual(stated(resolved("min_wall", nozzle=0.4)), ("guideline", ">=", 1.2, "mm", ()))
        self.assertEqual(stated(resolved("min_wall", nozzle=0.4, line_width=0.45)), ("guideline", ">=", 1.35, "mm", ()))

    def test_pc_needs_a_nozzle_of_at_least_0_4_mm(self) -> None:
        self.assertEqual(stated(resolved("nozzle_diameter", material_family="pc")), ("guideline", ">=", 0.4, "mm", ()))

    def test_tpu_95a_needs_a_nozzle_of_at_least_0_4_mm(self) -> None:
        self.assertEqual(stated(resolved("nozzle_diameter", material_family="tpu", shore="95a")),
                         ("guideline", ">=", 0.4, "mm", ()))

    def test_tpu_85a_needs_a_nozzle_of_at_least_0_6_mm_unpinned(self) -> None:
        self.assertEqual(stated(resolved("nozzle_diameter", material_family="tpu", shore="85a")),
                         ("guideline", ">=", 0.6, "mm", ()))

    def test_a_filler_needs_a_hardened_steel_nozzle_of_at_least_0_4_mm(self) -> None:
        for filler in ("cf", "gf"):
            with self.subTest(filler):
                facts = {"material_family": "pla", "filler": filler}
                self.assertEqual(stated(resolved("nozzle_diameter", **facts)), ("guideline", ">=", 0.4, "mm", ()))
                self.assertEqual(stated(resolved("nozzle_material", **facts)),
                                 ("guideline", "equals", "hardened_steel", None, ()))


class BridgeBoundary(unittest.TestCase):
    def test_a_bridge_must_be_strictly_under_5_mm(self) -> None:
        found = resolved("bridge_span")
        self.assertEqual(stated(found), ("guideline", "<", 5, "mm", ()))
        allows = {"<": lambda span, limit: span < limit}[found.operator]
        self.assertFalse(allows(5.0, found.value.value))
        self.assertTrue(allows(4.99, found.value.value))


class H2DSample(unittest.TestCase):
    """The sample machine set is reached only through a profile pin that names it (abstract sets apply only when pinned)."""

    H2D = "fdm.machine.bambu_h2d"
    FACTS = {"material_family": "tpu", "shore": "85a"}

    def applying(self, pin: tuple[str, ...] | None) -> set[str]:
        return {g.id for g in gl.applicable(CATALOG, gl.Context("fdm", self.FACTS, pin=pin))}

    def test_an_unpinned_profile_never_sees_the_h2d_sample(self) -> None:
        self.assertNotIn(self.H2D, self.applying(None))
        self.assertNotIn(self.H2D, self.applying(("fdm.generic@1",)))

    def test_a_profile_that_pins_the_h2d_sample_gets_it(self) -> None:
        self.assertIn(self.H2D, self.applying((f"{self.H2D}@1",)))


def sizes_um(found: Any) -> list[int]:
    """The discrete sizes of a resolved one_of nozzle limit, in whole micrometres."""
    assert found.operator == "one_of", found.operator
    assert all(item.units == "um" for item in found.value)
    return [round(item.value) for item in found.value]


class H2DNozzleSizes(unittest.TestCase):
    """The H2D sample states Bambu's supported nozzle diameters; a profile that pins it gets them, nobody else does."""

    PIN = ("fdm.machine.bambu_h2d@1",)

    def test_a_profile_pinned_to_the_h2d_sample_resolves_the_four_supported_sizes(self) -> None:
        found = resolved("nozzle_diameter", pin=self.PIN)
        self.assertEqual((found.status, sizes_um(found)), ("guideline", [200, 400, 600, 800]))

    def test_the_h2d_sizes_admit_0_4_mm_for_pc_and_refuse_it_for_tpu_85a_and_0_3_mm_for_both(self) -> None:
        """Admission is read off what each pinned profile resolves to, so the material minimum is part of the check."""
        pc = sizes_um(resolved("nozzle_diameter", pin=self.PIN, material_family="pc"))
        tpu = sizes_um(resolved("nozzle_diameter", pin=self.PIN, material_family="tpu", shore="85a"))
        self.assertEqual((400 in pc, 400 in tpu), (True, False))
        self.assertEqual((300 in pc, 300 in tpu), (False, False))

    def test_an_unpinned_profile_resolves_no_nozzle_sizes(self) -> None:
        self.assertEqual(resolved("nozzle_diameter").status, "unknown")

    def test_a_pinned_h2d_keeps_the_sizes_a_material_minimum_admits_without_a_warning(self) -> None:
        """The H2D lists 0.2 mm, below every minimum here; the minimum drops it, and the sizes at or above the minimum stay.
        A TPU 85A profile pinned to the H2D gets 0.6 and 0.8 mm; PC, TPU 95A and the fillers get 0.4, 0.6 and 0.8 mm."""
        cases = {
            "pc": ({"material_family": "pc"}, 0.4, [400, 600, 800]),
            "tpu 95a": ({"material_family": "tpu", "shore": "95a"}, 0.4, [400, 600, 800]),
            "tpu 85a": ({"material_family": "tpu", "shore": "85a"}, 0.6, [600, 800]),
            "cf filler": ({"material_family": "pla", "filler": "cf"}, 0.4, [400, 600, 800]),
            "gf filler": ({"material_family": "pla", "filler": "gf"}, 0.4, [400, 600, 800]),
        }
        for name, (facts, minimum, sizes) in cases.items():
            with self.subTest(name):
                self.assertEqual(stated(resolved("nozzle_diameter", **facts)), ("guideline", ">=", minimum, "mm", ()))
                pinned = resolved("nozzle_diameter", pin=self.PIN, **facts)
                self.assertEqual((pinned.status, sizes_um(pinned)), ("guideline", sizes))
                self.assertEqual([w for w in pinned.warnings if "relax" in w], [])


class SnapshotInventory(unittest.TestCase):
    def test_a_version_snapshot_copies_exactly_the_18_shipped_sets(self) -> None:
        """The list is typed out here, so a set a helper leaves out or adds fails here and not in a computed list."""
        by_hand = {
            "fdm.generic", "fdm.nozzle.d0_2", "fdm.nozzle.d0_4", "fdm.nozzle.d0_6", "fdm.nozzle.d0_8",
            "fdm.material.pla", "fdm.material.petg", "fdm.material.abs", "fdm.material.asa", "fdm.material.tpu_95a",
            "fdm.material.tpu_85a", "fdm.material.pa", "fdm.material.pc", "fdm.material.pa_cf",
            "fdm.filler.cf", "fdm.filler.gf", "fdm.compat.tpu_85a", "fdm.machine.bambu_h2d"}
        self.assertEqual(len(by_hand), 18)
        with tempfile.TemporaryDirectory() as hw:
            copies = gl.snapshot_files(Path(hw))
        self.assertEqual(set(copies), {f"manufacturing/guidelines/shipped--{name}.yaml" for name in by_hand})
        self.assertTrue(all(copies.values()))


if __name__ == "__main__":
    unittest.main()
