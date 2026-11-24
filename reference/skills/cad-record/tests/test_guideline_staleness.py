#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Staleness of guideline sets (benchhand-lch): the digests a loaded record carries, their place in the `source`
fingerprint of impact.py, and the packet key of a resolved set. Every case names the rule it proves."""

from __future__ import annotations

import copy
import hashlib
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
registry = fx.schema_registry_module()


def guideline(ident: str, minimum: float = 0.8, revision: int = 1, **scope: Any) -> dict[str, Any]:
    cite = fx.source("datasheet", "TST guide", locator="table 2")
    return {"schema_version": 1, "id": ident, "revision": revision, "title": f"{ident} (TST)", "scope": {"process": "fdm", **scope},
            "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(minimum), "citations": [cite]}]}


def put(directory: Path, name: str, document: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


class Staleness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.shipped = root / "shipped"
        patch = mock.patch.object(gl, "SHIPPED", self.shipped)
        patch.start()
        self.addCleanup(patch.stop)
        documents = {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}
        self.hw = fx.write_record(root / "hw", copy.deepcopy(documents))
        self.project = self.hw / "manufacturing" / "guidelines"

    def record(self) -> Any:
        return mi.load_record(self.hw)

    def source(self, record: Any) -> str:
        return str(impact.subject_fingerprints(record)["TST-0001"]["source"])

    def test_a_loaded_record_carries_the_digest_of_each_applicable_set_by_profile(self) -> None:
        path = put(self.project, "generic", guideline("fdm.generic"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(self.record().guideline_digests["tst_printer"]["tst_polymer_printed"], {"fdm.generic@1": digest})

    def test_checking_a_record_carries_the_same_digests(self) -> None:
        put(self.project, "generic", guideline("fdm.generic"))
        record, _problems = mi.check_record(self.hw)
        self.assertEqual(list(record.guideline_digests["tst_printer"]["tst_polymer_printed"]), ["fdm.generic@1"])

    def test_a_record_normalized_without_a_project_directory_carries_no_digests(self) -> None:
        put(self.project, "generic", guideline("fdm.generic"))
        documents = {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}
        self.assertEqual(dict(mi.normalize_record(documents).guideline_digests), {})

    def test_editing_an_applicable_set_changes_the_source_fingerprint_and_no_other_domain(self) -> None:
        put(self.project, "generic", guideline("fdm.generic", 0.8))
        before = impact.subject_fingerprints(self.record())["TST-0001"]
        put(self.project, "generic", guideline("fdm.generic", 0.9))
        after = impact.subject_fingerprints(self.record())["TST-0001"]
        self.assertNotEqual(before["source"], after["source"])
        self.assertEqual({d: v for d, v in before.items() if d != "source"}, {d: v for d, v in after.items() if d != "source"})

    def test_editing_a_set_that_cannot_apply_leaves_the_fingerprints_alone(self) -> None:
        put(self.project, "generic", guideline("fdm.generic", 0.8))
        put(self.project, "wide", guideline("fdm.nozzle.d0_8", 1.6, nozzle_diameter=fx.quantity(lower=0.75, upper=0.85)))
        before = impact.subject_fingerprints(self.record())["TST-0001"]
        put(self.project, "wide", guideline("fdm.nozzle.d0_8", 1.7, nozzle_diameter=fx.quantity(lower=0.75, upper=0.85)))
        self.assertEqual(impact.subject_fingerprints(self.record())["TST-0001"], before)

    def test_a_project_set_that_shadows_a_shipped_set_changes_the_source_fingerprint(self) -> None:
        put(self.shipped, "generic", guideline("fdm.generic", 0.8, revision=1))
        before = self.source(self.record())
        put(self.project, "generic", guideline("fdm.generic", 0.8, revision=2))
        self.assertNotEqual(self.source(self.record()), before)

    def test_removing_the_last_set_changes_the_source_fingerprint_back(self) -> None:
        bare = self.source(self.record())
        path = put(self.project, "generic", guideline("fdm.generic"))
        self.assertNotEqual(self.source(self.record()), bare)
        path.unlink()
        self.assertEqual(self.source(self.record()), bare)

    def test_a_refused_project_file_is_a_problem_of_the_loaded_record(self) -> None:
        broken = guideline("fdm.generic")
        broken["limits"][0]["bogus"] = 1
        put(self.project, "broken", broken)
        found = [p for p in self.record().problems if p.code == "intent.guideline"]
        self.assertEqual([p.path for p in found], ["hw/manufacturing/guidelines/broken.yaml"])
        self.assertIn("bogus", found[0].message)


class Fingerprints(unittest.TestCase):
    def test_a_source_without_a_locator_fingerprints_as_it_did_before_the_field_existed(self) -> None:
        plain = impact.plain(mi.Source.from_data(fx.source("datasheet", "TST guide")))
        self.assertNotIn("locator", plain)

    def test_a_source_locator_is_part_of_the_fingerprint_when_stated(self) -> None:
        stated = impact.plain(mi.Source.from_data(fx.source("datasheet", "TST guide", locator="table 2")))
        self.assertEqual(stated["locator"], "table 2")

    def test_a_locator_with_a_value_changes_the_fingerprint(self) -> None:
        plain = mi.Source.from_data(fx.source("datasheet", "TST guide"))
        located = mi.Source.from_data(fx.source("datasheet", "TST guide", locator="table 2"))
        moved = mi.Source.from_data(fx.source("datasheet", "TST guide", locator="table 3"))
        self.assertEqual(len({impact.digest(plain), impact.digest(located), impact.digest(moved)}), 3)


class PacketKeys(unittest.TestCase):
    def test_a_resolved_set_has_a_dependency_key_the_check_result_schema_accepts(self) -> None:
        key = gl.packet_key("fdm.material.pa_cf@12")
        self.assertEqual(key, "guideline_fdm_material_pa_cf_r12")
        check = registry.ref_validator(SKILL / "schemas", "https://srobroek.com/cad/schemas/manufacturing.schema.json#/$defs/semantic_id")
        self.assertEqual(list(check.iter_errors(key)), [])

    def test_the_dependencies_map_each_key_to_its_digest(self) -> None:
        self.assertEqual(gl.packet_dependencies({"fdm.generic@1": "a" * 64, "fdm.nozzle.d0_4@2": "b" * 64}),
                         {"guideline_fdm_generic_r1": "a" * 64, "guideline_fdm_nozzle_d0_4_r2": "b" * 64})

    def test_two_ids_that_give_one_key_are_an_error(self) -> None:
        with self.assertRaisesRegex(gl.GuidelineError, "guideline_fdm_a_b_r1.*fdm.a.b@1.*fdm.a_b@1"):
            gl.packet_dependencies({"fdm.a_b@1": "a" * 64, "fdm.a.b@1": "b" * 64})

    def test_discovery_refuses_the_second_of_two_ids_that_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shipped = Path(directory)
            put(shipped, "a", guideline("fdm.a.b"))
            put(shipped, "b", guideline("fdm.a_b"))
            catalog = gl.discover(None, shipped=shipped)
        self.assertEqual(sorted(catalog.guidelines), ["fdm.a.b"])
        self.assertEqual([r.path for r in catalog.refused], ["b.yaml"])
        self.assertIn("guideline_fdm_a_b_r1", str(catalog.refused[0]))


if __name__ == "__main__":
    unittest.main()
