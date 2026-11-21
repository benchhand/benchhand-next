#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""machine_profile.py: the sourcing rules of a guided machine setup, and a write that never stores a failing profile."""

from __future__ import annotations

import copy
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module as load  # noqa: E402

SKILL = HERE.parent
machine_profile = load("cad_record_machine_profile", SKILL / "scripts" / "machine_profile.py")
LAMP_ARM = HERE.parents[2] / "examples" / "lamp-arm" / "hw"

DATASHEET = {"kind": "datasheet", "reference": "Vendor tech specs", "url": "https://example.com/specs", "accessed": "2026-11-18"}


def known(value: float, units: str, *sources: dict[str, Any]) -> dict[str, Any]:
    return {"status": "known", "value": {"value": value, "units": units}, "basis": "supplier_typical",
            "sources": list(sources or [DATASHEET])}


def profile(**changes: Any) -> dict[str, Any]:
    """A local FDM profile that passes every rule; `changes` replaces top-level keys."""
    base: dict[str, Any] = {
        "id": "bench", "revision": 1, "title": "Bench printer", "process": "fdm", "provider": "local",
        "machine": {"identity": {"status": "known", "value": "Vendor X1", "basis": "supplier_typical", "sources": [DATASHEET]}},
        "envelope": {"x": known(200, "mm"), "y": known(200, "mm"), "z": known(200, "mm")},
        "parameters": {"nozzle_diameter": known(0.4, "mm"),
                       "layer_height": {"status": "unknown", "reason": "the vendor publishes no layer-height range"}},
        "materials": {"status": "unknown", "reason": "no material is approved yet"}, "calibrations": [],
    }
    base.update(changes)
    return base


def user(note: str = "the installed nozzle") -> dict[str, Any]:
    return {"kind": "user", "reference": note, "origin": "the machine owner"}


class Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hw = Path(tmp.name) / "hw"
        (self.hw / "manufacturing").mkdir(parents=True)
        self.path = self.hw / "manufacturing" / "capabilities.yaml"
        self.product = self.hw / "product.yaml"
        self.product.write_text(f"record_version: {machine_profile.intent.RECORD_VERSION}\n", encoding="utf-8")

    def put(self, *profiles: dict[str, Any]) -> None:
        self.path.write_text(yaml.safe_dump({"profiles": list(profiles)}, sort_keys=False), encoding="utf-8")

    def messages(self) -> list[str]:
        return machine_profile.check(self.hw)


class CheckTests(Case):
    def test_complete_profile_passes(self) -> None:
        self.put(profile())
        self.assertEqual(self.messages(), [])

    def test_shipped_example_passes(self) -> None:
        self.assertEqual(machine_profile.check(LAMP_ARM), [])

    def test_value_without_source_is_refused(self) -> None:
        p = profile()
        del p["envelope"]["x"]["sources"]
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: envelope/x") for m in found), found)

    def test_estimated_source_is_refused(self) -> None:
        p = profile()
        p["envelope"]["y"] = known(200, "mm", {"kind": "estimate", "reference": "guess", "reason": "looked about right"})
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: envelope/y") and "estimate" in m for m in found), found)

    def test_estimate_with_url_and_date_is_still_refused(self) -> None:
        p = profile()
        p["envelope"]["y"] = known(200, "mm", {**DATASHEET, "kind": "estimate", "reason": "read off a forum post"})
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: envelope/y") and "estimate" in m for m in found), found)

    def test_datasheet_without_access_date_is_refused(self) -> None:
        p = profile()
        p["envelope"]["z"] = known(200, "mm", {"kind": "supplier", "reference": "shop", "artifact": "a.pdf", "sha256": "0" * 64})
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: envelope/z") for m in found), found)

    def test_user_source_on_machine_fact_is_refused(self) -> None:
        p = profile()
        p["parameters"]["hotend_max_temperature"] = known(300, "deg_C", user("my belief"))
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: parameters/hotend_max_temperature") and "user" in m for m in found), found)

    def test_user_source_on_machine_identity_is_refused(self) -> None:
        p = profile()
        p["machine"]["identity"]["sources"] = [user("I own it")]
        self.put(p)
        self.assertTrue(any(m.startswith("bench: machine/identity") for m in self.messages()))

    def test_user_source_on_installed_configuration_is_accepted(self) -> None:
        p = profile()
        p["parameters"]["nozzle_diameter"] = known(0.6, "mm", user())
        p["parameters"]["nozzle_material"] = {"status": "known", "value": "hardened steel", "basis": "user_declared", "sources": [user()]}
        p["envelope"]["x"] = known(180, "mm", user("usable after the clips"))
        self.put(p)
        self.assertEqual(self.messages(), [])

    def test_unknown_with_reason_is_accepted(self) -> None:
        p = profile()
        p["parameters"]["bed_max_temperature"] = {"status": "unknown", "reason": "not published"}
        self.put(p)
        self.assertEqual(self.messages(), [])

    def test_pin_to_missing_set_is_refused(self) -> None:
        self.put(profile(guidelines=["no.such.set@1"]))
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: guidelines") and "no.such.set@1" in m for m in found), found)

    def test_pin_to_catalog_set_is_accepted(self) -> None:
        catalog = machine_profile.guidelines.discover(self.hw)
        ref = next(g.ref for g in catalog.guidelines.values())
        self.put(profile(guidelines=[ref]))
        self.assertEqual(self.messages(), [])

    def test_pin_without_machine_is_refused(self) -> None:
        catalog = machine_profile.guidelines.discover(self.hw)
        ref = next(g.ref for g in catalog.guidelines.values())
        p = profile(guidelines=[ref])
        del p["machine"]
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: guidelines") and "machine" in m for m in found), found)

    def test_schema_failure_is_reported(self) -> None:
        p = profile()
        del p["title"]
        self.put(p)
        found = self.messages()
        self.assertTrue(any("capabilities.yaml" in m and "title" in m for m in found), found)

    def slicer_file(self, content: bytes = b"frozen slicer export") -> tuple[str, str]:
        directory = self.hw / "manufacturing" / "sources"
        directory.mkdir(parents=True)
        (directory / "bench.3mf").write_bytes(content)
        return "manufacturing/sources/bench.3mf", hashlib.sha256(content).hexdigest()

    def max_speed(self, source: dict[str, Any]) -> dict[str, Any]:
        p = profile()
        p["parameters"]["max_speed"] = known(500, "mm_s", source)
        return p

    def test_user_max_speed_from_a_frozen_slicer_file_is_accepted(self) -> None:
        artifact, digest = self.slicer_file()
        self.put(self.max_speed({**user("slicer export"), "artifact": artifact, "sha256": digest}))
        self.assertEqual(self.messages(), [])

    def test_user_max_speed_without_a_frozen_file_is_refused(self) -> None:
        self.put(self.max_speed(user("I read it off the screen")))
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: parameters/max_speed") and "frozen" in m for m in found), found)

    def test_user_max_speed_whose_file_changed_is_refused(self) -> None:
        artifact, _ = self.slicer_file()
        self.put(self.max_speed({**user("slicer export"), "artifact": artifact, "sha256": "0" * 64}))
        found = self.messages()
        self.assertTrue(any("manufacturing/sources/bench.3mf" in m and "sha256" in m for m in found), found)

    def test_missing_product_file_is_reported_not_skipped(self) -> None:
        artifact, _ = self.slicer_file()
        self.product.unlink()
        self.put(self.max_speed({**user("slicer export"), "artifact": artifact, "sha256": "0" * 64}))
        found = self.messages()
        self.assertTrue(any(m.startswith("hw/product.yaml") and "record_version" in m for m in found), found)

    def test_unsupported_record_version_is_reported_not_skipped(self) -> None:
        self.product.write_text("record_version: 0\n", encoding="utf-8")
        self.put(profile())
        found = self.messages()
        self.assertTrue(any(m.startswith("hw/product.yaml") and "not supported" in m for m in found), found)

    def test_user_tool_max_speed_needs_a_frozen_file_too(self) -> None:
        p = profile(tools=[{"id": "t1", "description": "hotend", "parameters": {"max_speed": known(500, "mm_s", user())}}])
        self.put(p)
        found = self.messages()
        self.assertTrue(any(m.startswith("bench: tools/0/parameters/max_speed") for m in found), found)

    def test_user_source_on_tool_nozzle_fields_is_accepted(self) -> None:
        nozzle = {"status": "known", "value": "hardened steel", "basis": "user_declared", "sources": [user()]}
        p = profile(tools=[{"id": "t1", "description": "hotend",
                            "parameters": {"nozzle_diameter": known(0.6, "mm", user()), "nozzle_material": nozzle}}])
        self.put(p)
        self.assertEqual(self.messages(), [])

    def test_cli_exits_nonzero_and_names_problem(self) -> None:
        p = profile()
        p["envelope"]["y"] = known(200, "mm", {"kind": "estimate", "reference": "guess", "reason": "r"})
        self.put(p)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = machine_profile.main(["check", str(self.hw)])
        self.assertEqual(code, 1)
        self.assertIn("bench: envelope/y", out.getvalue() + err.getvalue())


class WriteTests(Case):
    def answers(self, data: dict[str, Any]) -> Path:
        path = self.hw.parent / "answers.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def run_write(self, answers: Path) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return int(machine_profile.main(["write", str(self.hw), str(answers)]))

    def stored(self) -> list[dict[str, Any]]:
        return list(yaml.safe_load(self.path.read_text(encoding="utf-8"))["profiles"])

    def test_write_adds_a_profile_to_a_missing_file(self) -> None:
        self.assertEqual(self.run_write(self.answers(profile())), 0)
        self.assertEqual([p["id"] for p in self.stored()], ["bench"])

    def test_write_refuses_failing_profile_and_leaves_file_unchanged(self) -> None:
        self.put(profile(id="other"))
        before = self.path.read_bytes()
        bad = profile()
        bad["envelope"]["y"] = known(200, "mm", {"kind": "estimate", "reference": "guess", "reason": "r"})
        self.assertEqual(self.run_write(self.answers(bad)), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_write_replaces_by_id(self) -> None:
        self.put(profile(title="old"), profile(id="other"))
        self.assertEqual(self.run_write(self.answers(profile(title="new"))), 0)
        stored = self.stored()
        self.assertEqual([(p["id"], p["title"]) for p in stored], [("bench", "new"), ("other", "Bench printer")])

    def test_write_copies_the_starter_material_profile(self) -> None:
        material = "fdm_petg_polylite"
        entry = {"material": material, "status": "approved", "operations": ["print"],
                 "source": user("owner approved it")}
        self.assertEqual(self.run_write(self.answers(profile(materials=[entry]))), 0)
        copied = yaml.safe_load((self.hw / "manufacturing" / "materials.yaml").read_text(encoding="utf-8"))["profiles"]
        self.assertEqual([m["id"] for m in copied], [material])

    def test_write_keeps_an_existing_material_profile(self) -> None:
        material = "fdm_petg_polylite"
        starter = yaml.safe_load((SKILL / "assets" / "manufacturing" / "material-profiles" / f"{material}.yaml").read_text(encoding="utf-8"))
        mine = copy.deepcopy(starter["profiles"][0])
        mine["title"] = "my edit"
        (self.hw / "manufacturing" / "materials.yaml").write_text(yaml.safe_dump({"profiles": [mine]}, sort_keys=False), encoding="utf-8")
        entry = {"material": material, "status": "approved", "operations": ["print"],
                 "source": user("owner approved it")}
        self.assertEqual(self.run_write(self.answers(profile(materials=[entry]))), 0)
        copied = yaml.safe_load((self.hw / "manufacturing" / "materials.yaml").read_text(encoding="utf-8"))["profiles"]
        self.assertEqual([m["title"] for m in copied], ["my edit"])

    def approval(self, material: str, status: str = "approved") -> dict[str, Any]:
        entry = {"material": material, "status": status, "operations": ["print"],
                 "source": user("owner decided it")}
        if status == "forbidden":
            entry["reason"] = "the owner rules it out"
        return entry

    def materials_path(self) -> Path:
        return self.hw / "manufacturing" / "materials.yaml"

    def test_family_material_does_not_copy_a_grade_starter(self) -> None:
        shipped = (LAMP_ARM / "manufacturing" / "materials.yaml").read_text(encoding="utf-8")
        self.materials_path().write_text(shipped, encoding="utf-8")
        self.assertEqual(self.run_write(self.answers(profile(materials=[self.approval("petg")]))), 0)
        stored = yaml.safe_load(self.materials_path().read_text(encoding="utf-8"))["profiles"]
        self.assertEqual([m["id"] for m in stored], ["petg"])

    def test_forbidden_material_copies_no_starter(self) -> None:
        # No profile declares the material, so the record refuses the write. A copied starter would have declared it.
        self.assertEqual(self.run_write(self.answers(profile(materials=[self.approval("fdm_petg_polylite", "forbidden")]))), 1)
        self.assertFalse(self.materials_path().exists())
        self.assertFalse(self.path.exists())

    def test_answers_wrapped_in_a_profile_key_is_an_operational_error(self) -> None:
        self.assertEqual(self.run_write(self.answers({"profile": profile()})), 2)
        self.assertFalse(self.path.exists())

    def test_non_mapping_answers_exit_2_with_an_error_line(self) -> None:
        path = self.hw.parent / "answers.yaml"
        path.write_text("- not a profile\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = machine_profile.main(["write", str(self.hw), str(path)])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("error:"), err.getvalue())

    def test_non_mapping_capabilities_file_exits_2_with_an_error_line(self) -> None:
        self.path.write_text("- a list\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = machine_profile.main(["check", str(self.hw)])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("error:"), err.getvalue())

    def test_non_mapping_profile_entry_exits_2_on_write(self) -> None:
        self.path.write_text("profiles:\n  - just text\n", encoding="utf-8")
        self.assertEqual(self.run_write(self.answers(profile())), 2)

    def test_failed_replace_leaves_both_files_byte_identical(self) -> None:
        self.put(profile(id="other"))
        self.materials_path().write_text("profiles: []\n", encoding="utf-8")
        before = (self.path.read_bytes(), self.materials_path().read_bytes())
        answers = self.answers(profile(materials=[self.approval("fdm_petg_polylite")]))
        with mock.patch.object(machine_profile.os, "replace", side_effect=OSError("disk full")):
            self.assertEqual(self.run_write(answers), 2)
        self.assertEqual((self.path.read_bytes(), self.materials_path().read_bytes()), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["capabilities.yaml", "materials.yaml"])


if __name__ == "__main__":
    unittest.main()
