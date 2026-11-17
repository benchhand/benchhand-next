#!/usr/bin/env python3
"""migrate.py: record version 1 to 2. A dry run reports the exact changes and writes nothing; --apply
adds explicit unknowns and open questions, moves drawing.operations to top-level operations, writes a
migration note, and leaves model.py, geometry, versions, releases, bundles, decisions, BOM and
verification untouched. It is idempotent, crash-safe and refuses what it cannot migrate faithfully."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
MIGRATE = SKILL / "scripts" / "migrate.py"
VALIDATOR = SKILL / "scripts" / "validate.py"
TEMPLATE = SKILL / "assets" / "project-template" / "hw"
V1_MINIMAL = HERE / "fixtures" / "record_v1_minimal" / "hw"  # a minimal record version 1: one part, four decisions


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load, result_payload  # noqa: E402


fx = load("cad_record_mi_fixtures", HERE / "fixtures" / "manufacturing_intent.py")
mi = fx.intent_module()
migrate = fx.migrate_module()
TODAY = date(2026, 1, 2)


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class MigrationCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-migrate-test-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.hw = self.project / "hw"
        shutil.copytree(fx.LAMP, self.hw)

    def run_cli(self, *args: str) -> tuple[int, Any]:
        result = subprocess.run([sys.executable, str(MIGRATE), str(self.project), *args], capture_output=True, text=True,
                                timeout=120, check=False)
        output = result.stdout if result.stdout.strip() else result.stderr
        return result.returncode, (json.loads(output) if "--json" in args and result.stdout.strip() else output)

    def edit_yaml(self, rel: str, change: Any) -> None:
        path = self.hw / rel
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def assert_refused(self, expected: str) -> None:
        before = tree(self.project)
        code, report = self.run_cli("--apply", "--json")
        self.assertEqual((code, report["status"]), (2, "refused"))
        self.assertIn(expected, report["message"])
        self.assertEqual(tree(self.project), before, "a refusal writes nothing")

    def assert_version_1(self) -> None:
        product = yaml.safe_load((self.hw / "product.yaml").read_text(encoding="utf-8"))
        self.assertEqual(mi.record_version(product), 1, "the input is a record version 1, or the test proves nothing")


class VersionOneCase(MigrationCase):
    """A per-test copy of the minimal record version 1 fixture."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-migrate-v1-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.hw = self.project / "hw"
        shutil.copytree(V1_MINIMAL, self.hw)

    def add_interface(self) -> None:
        fx.add_v1_interface(self.hw)

    def add_operations(self) -> None:
        fx.add_v1_operations(self.hw)


class Version1Record(VersionOneCase):
    """migrate.py on the minimal record version 1 fixture: the only migrate input in this file that is version 1."""

    def test_a_dry_run_reports_every_change_and_writes_nothing(self) -> None:
        self.assert_version_1()
        self.add_interface()
        self.add_operations()
        before = tree(self.project)
        code, report = self.run_cli("--json")
        self.assertEqual((code, report["status"], report["record_version"]), (1, "pending", {"from": 1, "to": 2}))
        self.assertEqual(tree(self.project), before, "a dry run moves, writes and deletes nothing")
        paths = {change["path"]: change for change in report["changes"]}
        # One part, the one interface added above, and its two installation operations to move.
        expected = {"hw/product.yaml", "hw/requirements.yaml", "hw/assembly.yaml", "hw/parts/LMP-0001/part.yaml",
                    "hw/interfaces.yaml",
                    "hw/manufacturing/capabilities.yaml", "hw/manufacturing/materials.yaml", "hw/manufacturing/selection.yaml",
                    f"hw/docs/record-migration-v2-{date.today().isoformat()}.md"}
        self.assertEqual(set(paths), expected)
        self.assertEqual(paths["hw/manufacturing/selection.yaml"]["action"], "create")
        self.assertIn("+record_version: 2\n", paths["hw/product.yaml"]["diff"])
        self.assertIn("+  functional:", paths["hw/interfaces.yaml"]["diff"])
        self.assertIn("-  operations:\n", paths["hw/assembly.yaml"]["diff"])
        self.assertIn("+operations:\n", paths["hw/assembly.yaml"]["diff"])
        self.assertEqual(paths["hw/assembly.yaml"]["summary"],
                         ["moves drawing.operations (2 operations) to top-level operations, unchanged"])  # the two added above
        self.assertEqual(report["questions"][0]["id"], "Q-001")
        # 11 use-case questions, 1 for the part and 1 for the interface. The operations exist, so none asks about them.
        self.assertEqual(len(report["questions"]), 11 + 1 + 1)
        self.assertEqual(report["findings"], [])
        code, text = self.run_cli("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("== hw/parts/LMP-0001/part.yaml (modify)", text)
        self.assertIn("+intent:", text)
        self.assertIn("Nothing was changed.", text)
        self.assertEqual(tree(self.project), before)

    def test_an_interrupted_apply_completes_on_the_next_run(self) -> None:
        self.add_interface()
        self.add_operations()
        self.assert_version_1()
        plan = migrate.plan(self.hw, TODAY)
        self.assertEqual(plan.status, "pending")
        # Planning order is requirements.yaml, then each part.yaml, and product.yaml last.
        self.assertEqual([c.path for c in plan.changes[:2]], ["hw/requirements.yaml", "hw/parts/LMP-0001/part.yaml"])
        partial = migrate.Plan(plan.hw, plan.status, plan.source_version, plan.changes[:2], plan.questions, plan.unknown, plan.findings)
        migrate.apply(partial)  # requirements and the part written, product.yaml still version 1
        self.assert_version_1()
        rest = migrate.plan(self.hw, TODAY)
        self.assertEqual(rest.status, "pending")
        self.assertNotIn("hw/requirements.yaml", {c.path for c in rest.changes})
        self.assertNotIn("hw/parts/LMP-0001/part.yaml", {c.path for c in rest.changes})
        migrate.apply(rest)
        record, problems = mi.check_record(self.hw)
        self.assertEqual((record.version, [p.finding() for p in problems]), (2, []))
        self.assertEqual(list(record.interfaces), ["IF-001"], "the interface and its operations were left for the next run")
        self.assertEqual(len(record.assembly_operations), 2)

    def test_a_record_without_installation_operations_gets_an_unknown(self) -> None:
        self.assert_version_1()
        self.assertNotIn("operations", yaml.safe_load((self.hw / "assembly.yaml").read_text(encoding="utf-8"))["drawing"])
        migrate.apply(migrate.plan(self.hw, TODAY))
        record, problems = mi.check_record(self.hw)
        self.assertEqual([p.finding() for p in problems], [])
        self.assertTrue(record.assembly_operations.unknown)
        self.assertIn(record.assembly_operations.question, record.questions)

    def test_apply_writes_a_valid_version_2_record_of_explicit_unknowns(self) -> None:
        self.add_interface()
        self.add_operations()
        assembly_before = (self.hw / "assembly.yaml").read_text(encoding="utf-8")
        untouched = {rel: digest for rel, digest in tree(self.hw).items()
                     if rel.endswith("model.py") or rel in ("bom.csv", "verification.csv") or rel.startswith("decisions/")}
        self.assertEqual(len(untouched), 1 + 2 + 4, "one model, the BOM and verification sheets, four decisions")
        code, report = self.run_cli("--apply", "--json")
        self.assertEqual((code, report["status"]), (0, "applied"))
        after = tree(self.hw)
        self.assertEqual({rel: after[rel] for rel in untouched}, untouched)
        record, problems = mi.check_record(self.hw)
        self.assertEqual([p.finding() for p in problems], [])
        self.assertEqual(record.version, 2)
        self.assertEqual(record.use_case.status, "unknown")
        self.assertTrue(all(fact.unknown and fact.question for fact in record.use_case.facts.values()))
        self.assertTrue(record.use_case.service_class.unknown)
        self.assertEqual(list(record.parts), ["LMP-0001"])
        part = record.parts["LMP-0001"]
        for name in ("functions", "material_profile", "service", "critical_surfaces", "route"):
            value = getattr(part.intent, name)
            self.assertTrue(mi.is_fact(value) and value.unknown and value.question in record.questions, (name, value))
        self.assertIn(part.material, part.intent.material_profile.reason, "the legacy material is named, not adopted")
        self.assertEqual(list(record.interfaces), ["IF-001"])
        for interface in record.interfaces.values():
            self.assertTrue(interface.functional.critical.unknown and interface.functional.functions.unknown)
        self.assertEqual((dict(record.capabilities), dict(record.materials), record.selection.status), ({}, {}, "not_assessed"))
        assembly = yaml.safe_load((self.hw / "assembly.yaml").read_text(encoding="utf-8"))
        self.assertEqual(len(record.assembly_operations), 2)  # the two operations added above
        self.assertNotIn("operations", assembly["drawing"])
        self.assertEqual(assembly["operations"], yaml.safe_load(assembly_before)["drawing"]["operations"])
        comment = "# Assembly drawing intent (cad-drawings assembly_drawing.py): sheet 1 is the whole arm, then one"
        self.assertIn(comment, (self.hw / "assembly.yaml").read_text(encoding="utf-8"), "comments survive the edit")
        self.assertFalse(mi.assess_use_case(record).final_ready)
        note = (self.hw / "docs" / f"record-migration-v2-{date.today().isoformat()}.md").read_text(encoding="utf-8")
        for text in ("Nothing was approved", "no process, material, capability, criterion", "| Q-012 |", "LMP-0001",
                     "`hw/versions/`, `hw/releases/`"):
            self.assertIn(text, note)
        validated = subprocess.run([sys.executable, str(VALIDATOR), str(self.project)], capture_output=True, text=True,
                                   timeout=120, check=False)
        self.assertEqual((validated.returncode, result_payload(validated.stdout)), (0, {"ok": True, "findings": []}))

    def test_a_second_run_changes_nothing(self) -> None:
        self.assertEqual(self.run_cli("--apply")[0], 0)
        migrated = tree(self.project)
        for args in (("--apply", "--json"), ("--json",)):
            with self.subTest(args=args):
                code, report = self.run_cli(*args)
                self.assertEqual((code, report["status"], report["changes"]), (0, "current", []))
                self.assertEqual(tree(self.project), migrated)

    def test_dry_run_is_the_default_and_reports_what_no_flag_reports(self) -> None:
        before = tree(self.project)
        dry = self.run_cli("--dry-run", "--json")
        self.assertEqual(dry[1]["status"], "pending", "a version 1 record has changes, so the dry run has a plan")
        self.assertEqual(dry, self.run_cli("--json"))
        self.assertEqual(tree(self.project), before)

    def test_sealed_versions_releases_bundles_and_geometry_are_never_touched(self) -> None:
        write(self.hw / "versions" / "v1" / "record" / "product.yaml", "id: lamp-arm\n")
        write(self.hw / "versions" / "v1" / "manifest.json", json.dumps({"label": "v1", "files": {}}))
        write(self.hw / "releases" / "A" / "manifest.json", "{}")
        write(self.hw / "checks" / "v1" / "LMP-0001" / "result.json", "{}")
        write(self.hw / "parts" / "LMP-0005" / "sources" / "quote.pdf", "%PDF quote\n")
        sealed = {rel: digest for rel, digest in tree(self.hw).items() if rel.split("/")[0] in ("versions", "releases", "checks")
                  or "/sources/" in rel}
        plan = migrate.plan(self.hw, TODAY)
        self.assertEqual(plan.status, "pending", "the migration must have changes to apply, or the check below is vacuous")
        migrate.apply(plan)
        self.assertEqual(yaml.safe_load((self.hw / "product.yaml").read_text(encoding="utf-8"))["record_version"], 2,
                         "the migration was applied")
        self.assertEqual({rel: digest for rel, digest in tree(self.hw).items() if rel in sealed}, sealed)
        self.assertFalse((self.project / ".cad-work" / "migration").exists() and any((self.project / ".cad-work" / "migration").iterdir()),
                         "staging is cleaned up")

    def test_crlf_files_keep_their_newlines(self) -> None:
        path = self.hw / "parts" / "LMP-0001" / "part.yaml"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        plan = migrate.plan(self.hw, TODAY)
        self.assertEqual(plan.status, "pending", "the migration must have changes to apply, or the check below is vacuous")
        migrate.apply(plan)
        self.assertEqual(yaml.safe_load((self.hw / "product.yaml").read_text(encoding="utf-8"))["record_version"], 2,
                         "the migration was applied")
        data = path.read_bytes()
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertIn(b"intent:\r\n", data)


class Version1Refusals(VersionOneCase):
    def test_a_frozen_record_needs_an_open_change(self) -> None:
        self.assert_version_1()
        frozen = {"version": "v1", "manifest_sha256": "a" * 64, "decision": "DR-001"}
        self.edit_yaml("product.yaml", lambda d: d["flow"].update(frozen=frozen))
        self.assert_refused("open an approved change")
        self.edit_yaml("product.yaml", lambda d: d["flow"].update(change={"decision": "DR-002", "baseline_version": "v1",
                                                                          "affected_parts": ["LMP-0001"]}))
        plan = migrate.plan(self.hw, TODAY)
        self.assertEqual(plan.status, "pending")
        self.assertEqual([(f["code"], f["severity"]) for f in plan.findings], [("record.legacy_freeze", "warning")],
                         "the old freeze stays readable but anchors no evidence, so no release accepts it")

    def test_unreadable_and_invalid_records_are_refused(self) -> None:
        self.assert_version_1()
        self.assertEqual(migrate.plan(self.hw, TODAY).status, "pending", "the untouched fixture migrates")
        part = self.hw / "parts" / "LMP-0001" / "part.yaml"
        original = part.read_text(encoding="utf-8")
        part.write_text(original + "  bad: [\n", encoding="utf-8")
        self.assert_refused("does not parse")
        part.write_text(original.replace("finish: ", "finished: "), encoding="utf-8")
        self.assertNotEqual(part.read_text(encoding="utf-8"), original, "the fixture part declares a finish to misspell")
        self.assert_refused("would not validate")

    def test_a_layout_the_textual_edit_cannot_place_is_refused(self) -> None:
        self.assert_version_1()
        interface = {"id": "IF-001", "from": "base_sub", "to": "base_sub", "type": "motion", "description": "TST interface"}
        path = self.hw / "interfaces.yaml"
        path.write_text(yaml.safe_dump({"interfaces": [interface]}, sort_keys=False), encoding="utf-8")
        self.assertEqual(migrate.plan(self.hw, TODAY).status, "pending", "the same interface in block style is placed")
        path.write_text(yaml.safe_dump({"interfaces": [interface]}, default_flow_style=True, width=100000), encoding="utf-8")
        self.assert_refused("interfaces")


class Refusals(MigrationCase):
    def test_an_unknown_record_version_is_refused(self) -> None:
        self.edit_yaml("product.yaml", lambda d: d.update(record_version=3))
        self.assert_refused("record_version 3 is not supported")

    def test_dry_run_and_apply_are_exclusive(self) -> None:
        before = tree(self.project)
        code, message = self.run_cli("--dry-run", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", message)
        self.assertEqual(tree(self.project), before)


class EdgeCases(MigrationCase):
    def test_the_project_template_is_already_current(self) -> None:
        shutil.rmtree(self.hw)
        shutil.copytree(TEMPLATE, self.hw)
        self.assertEqual(migrate.plan(self.hw, TODAY).status, "current")



if __name__ == "__main__":
    unittest.main()
