#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""End to end: the readers that impact and evidence use see a guideline edit, in the current record and in a version
snapshot (benchhand-lch, review P1). Every case names the rule it proves."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import subprocess
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
build = load("cad_model_record_for_lch", SKILL.parent / "cad-model" / "scripts" / "cadmodel" / "record.py")


def guideline(minimum: float, ident: str = "fdm.generic", revision: int = 1) -> dict[str, Any]:
    cite = fx.source("datasheet", "TST guide")
    return {"schema_version": 1, "id": ident, "revision": revision, "title": "TST", "scope": {"process": "fdm"},
            "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(minimum), "citations": [cite]}]}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shipped = self.root / "shipped"
        patch = mock.patch.object(gl, "SHIPPED", self.shipped)
        patch.start()
        self.addCleanup(patch.stop)
        documents = {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}
        self.hw = fx.write_record(self.root / "hw", copy.deepcopy(documents))
        self.path = self.hw / "manufacturing" / "guidelines" / "generic.yaml"
        self.path.parent.mkdir(parents=True)

    def write(self, minimum: float) -> None:
        self.path.write_text(yaml.safe_dump(guideline(minimum), sort_keys=False), encoding="utf-8")

    def ship(self, minimum: float) -> Path:
        self.shipped.mkdir(parents=True, exist_ok=True)
        path = self.shipped / "pa.yaml"
        path.write_text(yaml.safe_dump(guideline(minimum, "fdm.material.pa"), sort_keys=False), encoding="utf-8")
        return path

    def version(self, name: str = "v1") -> Path:
        """A version's record/ folder, written the way a build writes it."""
        pns = sorted(path.parent.name for path in (self.hw / "parts").glob("*/part.yaml"))
        folder = self.root / name / "record"
        build.write_snapshot(folder, build.snapshot(self.hw, pns))
        return folder

    def source_of(self, record: Any) -> str:
        return str(impact.subject_fingerprints(record)["TST-0001"]["source"])


class ProductionReaders(Base):
    def test_the_impact_reader_stales_a_part_when_an_applicable_guideline_is_edited(self) -> None:
        self.write(0.8)
        before = impact.read_record(self.hw)
        self.write(0.9)
        after = impact.read_record(self.hw)
        changed = impact.changed_domains(impact.subject_fingerprints(before), impact.subject_fingerprints(after))
        self.assertIn("source", changed.get("TST-0001", ()))

    def test_the_evidence_reader_carries_the_guideline_digests(self) -> None:
        self.write(0.8)
        _documents, record = impact.read_inputs(self.hw)
        self.assertEqual(list(record.guideline_digests["tst_printer"]), ["fdm.generic@1"])


class VersionSnapshots(Base):
    def test_a_build_copies_the_winning_sets_byte_identically(self) -> None:
        self.write(0.8)
        shipped = self.ship(1.5)
        hidden = self.shipped / "generic.yaml"
        hidden.write_text(yaml.safe_dump(guideline(0.1, "fdm.generic", 9), sort_keys=False), encoding="utf-8")
        folder = self.version()
        found = {path.relative_to(folder).as_posix(): path.read_bytes() for path in (folder / "manufacturing" / "guidelines").glob("*.yaml")}
        self.assertEqual(found, {"manufacturing/guidelines/generic.yaml": self.path.read_bytes(),
                                 "manufacturing/guidelines/shipped--pa.yaml": shipped.read_bytes()},
                         "the project set shadows the shipped generic set, so only its own bytes are copied")

    def test_a_version_build_with_no_edit_stales_nothing(self) -> None:
        self.write(0.8)
        self.ship(1.5)
        folder = self.version()
        _documents, built = impact.read_inputs(folder, ledgers_from=self.hw)
        _documents, current = impact.read_inputs(self.hw)
        self.assertEqual(self.source_of(built), self.source_of(current))
        self.assertEqual(dict(built.guideline_digests["tst_printer"]), dict(current.guideline_digests["tst_printer"]))

    def test_editing_a_project_set_after_the_build_stales_the_part(self) -> None:
        self.write(0.8)
        folder = self.version()
        self.write(0.9)
        _documents, built = impact.read_inputs(folder, ledgers_from=self.hw)
        _documents, current = impact.read_inputs(self.hw)
        changed = impact.changed_domains(impact.subject_fingerprints(built), impact.subject_fingerprints(current))
        self.assertIn("source", changed.get("TST-0001", ()))

    def test_editing_a_shipped_set_after_the_build_stales_the_part(self) -> None:
        self.ship(1.5)
        folder = self.version()
        self.ship(1.6)
        _documents, built = impact.read_inputs(folder, ledgers_from=self.hw)
        _documents, current = impact.read_inputs(self.hw)
        changed = impact.changed_domains(impact.subject_fingerprints(built), impact.subject_fingerprints(current))
        self.assertIn("source", changed.get("TST-0001", ()))

    def test_a_build_refuses_a_project_file_named_like_a_shipped_copy(self) -> None:
        pns = sorted(path.parent.name for path in (self.hw / "parts").glob("*/part.yaml"))
        (self.hw / "manufacturing" / "guidelines" / "shipped--escape.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        with self.assertRaises(build.RecordError) as raised:
            build.snapshot(self.hw, pns)
        self.assertIn("shipped--escape.yaml", str(raised.exception))

    def test_an_edited_shipped_copy_in_the_snapshot_stales_the_part(self) -> None:
        self.ship(1.5)
        folder = self.version()
        copy = folder / "manufacturing" / "guidelines" / "shipped--pa.yaml"
        copy.write_text(yaml.safe_dump(guideline(1.9, "fdm.material.pa"), sort_keys=False), encoding="utf-8")
        _documents, built = impact.read_inputs(folder, ledgers_from=self.hw)
        _documents, current = impact.read_inputs(self.hw)
        changed = impact.changed_domains(impact.subject_fingerprints(built), impact.subject_fingerprints(current))
        self.assertIn("source", changed.get("TST-0001", ()))

    def test_load_record_in_snapshot_mode_reads_the_copies_and_accepts_the_shipped_ones(self) -> None:
        self.ship(1.5)
        folder = self.version()
        digests = dict(mi.load_record(folder, snapshot=True).guideline_digests["tst_printer"])
        self.assertEqual(sorted(digests), ["fdm.material.pa@1"])
        self.ship(1.6)  # the live install changes after the build
        again = mi.load_record(folder, snapshot=True)
        self.assertEqual(dict(again.guideline_digests["tst_printer"]), digests, "the digests come from the snapshot")
        self.assertEqual([p for p in again.problems if p.code == "intent.guideline"], [], "a shipped copy is accepted")

    def test_check_record_in_snapshot_mode_accepts_the_shipped_copies(self) -> None:
        self.ship(1.5)
        record, problems = mi.check_record(self.version(), snapshot=True)
        self.assertEqual([p for p in problems if p.code == "intent.guideline"], [])
        self.assertEqual(sorted(record.guideline_digests["tst_printer"]), ["fdm.material.pa@1"])

    def test_the_cad_model_snapshot_reader_carries_the_digests_of_the_copies(self) -> None:
        self.write(0.8)
        self.ship(1.5)
        pns = sorted(path.parent.name for path in (self.hw / "parts").glob("*/part.yaml"))
        snapshot = build.read_snapshot(build.snapshot(self.hw, pns))
        self.assertEqual(sorted(snapshot.intent.guideline_digests["tst_printer"]), ["fdm.generic@1", "fdm.material.pa@1"])

    def test_the_cad_model_snapshot_reader_reads_only_its_own_copies(self) -> None:
        pns = sorted(path.parent.name for path in (self.hw / "parts").glob("*/part.yaml"))
        files = build.snapshot(self.hw, pns)
        self.ship(1.5)
        self.assertEqual(dict(build.read_snapshot(files).intent.guideline_digests), {}, "a set shipped after the build is not in it")

    def test_a_snapshot_is_read_only_from_its_own_copies(self) -> None:
        folder = self.version()
        self.ship(1.5)
        _documents, built = impact.read_inputs(folder, ledgers_from=self.hw)
        self.assertEqual(dict(built.guideline_digests), {}, "a shipped set added after the build is not part of the version")


class Built(Base):
    """A hw/ with one built version, laid out the way test_impact's CLI cases do."""

    def build_version(self, label: str = "v1") -> None:
        for pn in ("TST-0001", "TST-0002", "TST-0004"):
            (self.hw / "parts" / pn / "model.py").write_text(f"# {pn}\n", encoding="utf-8")
        folder = self.hw / "versions" / label
        pns = sorted(p.parent.name for p in (self.hw / "parts").glob("*/part.yaml"))
        build.write_snapshot(folder / "record", build.snapshot(self.hw, pns))
        files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}
        parts = {path.parent.name: {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(self.hw.glob("parts/*/model.py"))}
        (folder / "manifest.json").write_text(json.dumps({"label": label, "parts": parts, "files": files}), encoding="utf-8")


class IsolatedCli(Built):
    def test_the_script_in_its_own_environment_reports_an_edited_guideline(self) -> None:
        self.write(0.8)
        self.build_version()
        self.write(0.9)
        result = subprocess.run(["uv", "run", "--script", str(SKILL / "scripts" / "impact.py"), "--hw", str(self.hw),
                                 "--since-version", "v1"], capture_output=True, text=True, timeout=600, check=False)
        report = json.loads(result.stdout)
        self.assertEqual((result.returncode, report["status"]), (1, "impact"), result.stderr[-400:])
        self.assertIn("source", report["changed"]["TST-0001"])

    def test_every_script_that_reads_a_record_declares_the_validator_discovery_needs(self) -> None:
        for relative in ("cad-record/scripts/impact.py", "cad-record/scripts/evidence.py", "cad-fits/scripts/stackup.py",
                         "cad-motion/scripts/play.py", "cad-motion/scripts/access.py", "cad-analysis/scripts/stop_reaction.py"):
            with self.subTest(relative):
                header = (SKILL.parent / relative).read_text(encoding="utf-8").split("# ///")[1]
                self.assertIn("jsonschema", header)


class Infrastructure(Built):
    def missing_validator(self) -> Any:
        registry = gl._sibling("cad_record_schema_registry", "schema_registry.py")
        return mock.patch.object(registry, "document_validator", side_effect=ImportError("No module named 'jsonschema'"))

    def test_a_missing_validator_is_an_error_and_never_a_refused_file(self) -> None:
        self.write(0.8)
        with self.missing_validator(), self.assertRaises(ImportError):
            gl.discover(self.hw)

    def test_loading_a_record_without_the_validator_fails_instead_of_skipping_staleness(self) -> None:
        self.write(0.8)
        with self.missing_validator(), self.assertRaises(mi.IntentError) as raised:
            mi.load_record(self.hw)
        self.assertIn("jsonschema", str(raised.exception))

    def test_the_impact_script_reports_a_missing_validator_as_an_error_not_as_unchanged(self) -> None:
        self.write(0.8)
        self.build_version()
        out = io.StringIO()
        with self.missing_validator(), contextlib.redirect_stdout(out):
            code = impact.main(["--hw", str(self.hw), "--since-version", "v1"])
        report = json.loads(out.getvalue())
        self.assertEqual((code, report["status"]), (2, "error"))
        self.assertIn("jsonschema", report["message"])

    def test_a_record_with_no_guideline_files_needs_no_validator(self) -> None:
        with self.missing_validator():
            self.assertEqual(dict(mi.load_record(self.hw).guideline_digests), {})


if __name__ == "__main__":
    unittest.main()
