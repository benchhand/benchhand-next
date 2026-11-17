#!/usr/bin/env python3
"""The shared schema validators: a schema edited or deleted in the running process is read again, and
each schema directory (another checkout's cad-record) keeps its own registry and validators."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
EXAMPLE = SKILL.parent.parent / "examples" / "lamp-arm" / "hw"
MANUFACTURING_ID = "https://srobroek.com/cad/schemas/manufacturing.schema.json"


def load(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


validate = load("cad_record_validate", SCRIPTS / "validate.py")
intent = validate.intent
registry = validate.schema_registry
ROW = {"requirement_id": "REQ-001", "method": "I", "criteria": "fits", "result": "pass", "evidence": "hw/docs/x.md"}


def edit_json(path: Path, change: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class SchemaRoots(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-schema-registry-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def schemas(self, name: str) -> Path:
        """A copy of cad-record's schemas/, as another checkout of the skill holds it."""
        copy = self.root / name / "schemas"
        shutil.copytree(SKILL / "schemas", copy)
        probe = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                 "$id": "https://srobroek.com/cad/schemas/probe.schema.json",
                 "type": "object", "properties": {"title": {"$ref": f"{MANUFACTURING_ID}#/$defs/text"}}}
        (copy / "probe.schema.json").write_text(json.dumps(probe), encoding="utf-8")
        return copy

    def check(self, schemas: Path, document: Any, name: str) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        with mock.patch.object(validate, "SCHEMAS", schemas):
            validate.validate_document(document, name, "doc", findings)
        return findings

    @contextlib.contextmanager
    def coarse_clock(self) -> Iterator[list[int]]:
        """Stat every path as it was when first seen, as a filesystem with a coarse clock (Linux at
        HZ=100 stamps files from a 10 ms tick) records several writes in one tick: an in-place edit of
        the same length then changes no stat field. `time.time_ns` reads the yielded clock, which
        starts 1 ms after the last schema directory was made; a test moves it on."""
        real = registry._stamp
        seen: dict[str, Any] = {}
        clock = [os.stat(self.root).st_ctime_ns + 1_000_000]
        with mock.patch.object(registry, "_stamp", lambda path: seen.setdefault(str(path), real(path))), \
                mock.patch("time.time_ns", lambda: clock[0]):
            yield clock


class EditedSchemas(SchemaRoots):
    def test_validate_document_reads_a_schema_edited_in_the_process(self) -> None:
        schemas = self.schemas("a")
        self.assertEqual(self.check(schemas, ROW, "verification-row.schema.json"), [])
        edit_json(schemas / "verification-row.schema.json", lambda s: s["properties"]["method"].update(enum=["T"]))
        self.assertEqual([f["message"] for f in self.check(schemas, ROW, "verification-row.schema.json")],
                         ["method: 'I' is not one of ['T']"])

    def test_validate_document_reads_a_same_length_edit_that_keeps_the_file_times(self) -> None:
        schemas = self.schemas("a")
        path = schemas / "verification-row.schema.json"
        self.assertEqual(self.check(schemas, ROW, "verification-row.schema.json"), [])
        before = path.stat()
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count('"I"'), 1)
        path.write_text(text.replace('"I"', '"X"'), encoding="utf-8")  # in place: same inode, same size
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = path.stat()
        self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns), (before.st_ino, before.st_size, before.st_mtime_ns))
        self.assertEqual([f["message"] for f in self.check(schemas, ROW, "verification-row.schema.json")],
                         ["method: 'I' is not one of ['X', 'A', 'D', 'T']"])

    def test_validate_document_reads_an_edit_made_in_the_clock_tick_the_schema_was_read(self) -> None:
        for later_ns in (1_000_000, 60_000_000_000):  # checked again in the same tick, and a minute on
            with self.subTest(later_ns=later_ns):
                schemas = self.schemas(f"edit-{later_ns}")
                path = schemas / "verification-row.schema.json"
                with self.coarse_clock() as clock:
                    self.assertEqual(self.check(schemas, ROW, "verification-row.schema.json"), [])
                    path.write_text(path.read_text(encoding="utf-8").replace('"I"', '"X"'), encoding="utf-8")
                    clock[0] += later_ns
                    self.assertEqual([f["message"] for f in self.check(schemas, ROW, "verification-row.schema.json")],
                                     ["method: 'I' is not one of ['X', 'A', 'D', 'T']"])

    def test_validate_document_resolves_a_schema_added_in_the_clock_tick_the_directory_was_listed(self) -> None:
        title = "https://srobroek.com/cad/schemas/title.schema.json"
        for later_ns in (1_000_000, 60_000_000_000):  # checked again in the same tick, and a minute on
            with self.subTest(later_ns=later_ns):
                schemas = self.schemas(f"add-{later_ns}")
                with self.coarse_clock() as clock:
                    self.assertEqual(self.check(schemas, {"title": "Lamp"}, "probe.schema.json"), [])
                    (schemas / "title.schema.json").write_text(json.dumps(
                        {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": title,
                         "type": "string", "maxLength": 2}), encoding="utf-8")
                    (schemas / "titled.schema.json").write_text(json.dumps(
                        {"$schema": "https://json-schema.org/draft/2020-12/schema",
                         "$id": "https://srobroek.com/cad/schemas/titled.schema.json",
                         "type": "object", "properties": {"title": {"$ref": title}}}), encoding="utf-8")
                    clock[0] += later_ns
                    self.assertEqual([f["message"] for f in self.check(schemas, {"title": "Lamp"}, "titled.schema.json")],
                                     ["title: 'Lamp' is too long"])

    def test_validate_document_reads_a_referenced_schema_edited_in_the_process(self) -> None:
        schemas = self.schemas("a")
        self.assertEqual(self.check(schemas, {"title": "Lamp"}, "probe.schema.json"), [])
        edit_json(schemas / "manufacturing.schema.json", lambda s: s["$defs"]["text"].update(maxLength=2))
        self.assertEqual([f["message"] for f in self.check(schemas, {"title": "Lamp"}, "probe.schema.json")],
                         ["title: 'Lamp' is too long"])

    def test_validate_document_reports_a_schema_deleted_in_the_process(self) -> None:
        schemas = self.schemas("a")
        self.assertEqual(self.check(schemas, ROW, "verification-row.schema.json"), [])
        (schemas / "verification-row.schema.json").unlink()
        path = schemas / "verification-row.schema.json"
        self.assertEqual(self.check(schemas, ROW, "verification-row.schema.json"),
                         [{"path": str(path), "severity": "error",
                           "message": f"cannot load schema: [Errno 2] No such file or directory: '{path}'"}])

    def test_schema_problems_reads_a_schema_edited_in_the_process(self) -> None:
        schemas = self.schemas("a")
        documents = {"requirements.yaml": yaml.safe_load((EXAMPLE / "requirements.yaml").read_text(encoding="utf-8"))}
        with mock.patch.object(intent, "SCHEMAS", schemas):
            self.assertEqual(intent.schema_problems(documents), [])
            edit_json(schemas / "requirements.schema.json", lambda s: s["required"].append("signed_off"))
            self.assertEqual([p.message for p in intent.schema_problems(documents)],
                             ["'signed_off' is a required property"])


class SeparateRoots(SchemaRoots):
    def test_each_schema_directory_has_its_own_validators(self) -> None:
        first, second = self.schemas("a"), self.schemas("b")
        edit_json(second / "verification-row.schema.json", lambda s: s["properties"]["method"].update(enum=["T"]))
        self.assertEqual(self.check(first, ROW, "verification-row.schema.json"), [])
        self.assertEqual(len(self.check(second, ROW, "verification-row.schema.json")), 1)
        self.assertEqual(self.check(first, ROW, "verification-row.schema.json"), [])

    def test_each_schema_directory_resolves_references_in_its_own_registry(self) -> None:
        first, second = self.schemas("a"), self.schemas("b")
        edit_json(second / "manufacturing.schema.json", lambda s: s["$defs"]["text"].update(maxLength=2))
        self.assertEqual(self.check(first, {"title": "Lamp"}, "probe.schema.json"), [])
        self.assertEqual([f["message"] for f in self.check(second, {"title": "Lamp"}, "probe.schema.json")],
                         ["title: 'Lamp' is too long"])
        self.assertEqual(self.check(first, {"title": "Lamp"}, "probe.schema.json"), [])


if __name__ == "__main__":
    unittest.main()
