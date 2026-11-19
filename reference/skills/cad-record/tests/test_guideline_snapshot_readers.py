#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The snapshot readers of the motion and analysis producers run the real loader on a version's record/ (benchhand-lch).
Each test freezes a version with a shipped guideline set, changes the live shipped bytes, and calls the reader's own
`assess`. A spy wraps the real `load_record`, keeps its result and stops the reader there, so the test sees what the
reader's call gave: no guideline refusals, and the digests of the frozen copies, not those of the live install."""

from __future__ import annotations

import argparse
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_module as load  # noqa: E402

fx = load("cad_record_mi_fixtures", HERE / "fixtures" / "manufacturing_intent.py")
mi = fx.intent_module()
gl = load("cad_record_guidelines", SKILLS / "cad-record" / "scripts" / "guidelines.py")
build = load("cad_model_record_for_lch", SKILLS / "cad-model" / "scripts" / "cadmodel" / "record.py")
sys.path.insert(0, str(SKILLS / "cad-analysis" / "scripts"))
READERS = {  # an ImportError here is a failure of the test, never a silently dropped reader
    "play": load("cad_lch_snapshot_play", SKILLS / "cad-motion" / "scripts" / "play.py"),
    "access": load("cad_lch_snapshot_access", SKILLS / "cad-motion" / "scripts" / "access.py"),
    "stop_reaction": load("cad_lch_snapshot_stop_reaction", SKILLS / "cad-analysis" / "scripts" / "stop_reaction.py"),
}


class Stop(Exception):
    """Raised by the spy once the reader has asked for the record."""


def shipped_set(minimum: float) -> str:
    return yaml.safe_dump({
        "schema_version": 1, "id": "fdm.material.pa", "revision": 1, "title": "TST", "scope": {"process": "fdm"},
        "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": fx.quantity(minimum),
                    "citations": [fx.source("datasheet", "TST guide")]}]}, sort_keys=False)


class FrozenVersion(unittest.TestCase):
    """A project whose version v1 was built while a shipped guideline set held the bytes of `shipped_set(1.5)`."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.shipped = root / "shipped"
        patch = mock.patch.object(gl, "SHIPPED", self.shipped)
        patch.start()
        self.addCleanup(patch.stop)
        self.shipped.mkdir()
        (self.shipped / "pa.yaml").write_text(shipped_set(1.5), encoding="utf-8")
        documents = {rel: data for rel, data in fx.tst_record().items() if not rel.startswith("_")}
        self.hw = fx.write_record(root / "hw", copy.deepcopy(documents))
        pns = sorted(path.parent.name for path in (self.hw / "parts").glob("*/part.yaml"))
        self.record_dir = self.hw / "versions" / "v1" / "record"
        build.write_snapshot(self.record_dir, build.snapshot(self.hw, pns))
        self.frozen = dict(mi.load_record(self.hw).guideline_digests.get("tst_printer", {}))
        self.assertEqual(sorted(self.frozen), ["fdm.material.pa@1"], "the frozen version holds the shipped set")
        (self.shipped / "pa.yaml").write_text(shipped_set(2.5), encoding="utf-8")  # the live install changes
        live = gl.discover(self.hw).guidelines["fdm.material.pa"].sha256
        self.assertNotEqual(live, self.frozen["fdm.material.pa@1"], "the live bytes differ from the frozen ones")

    def loaded(self, run: Any) -> Any:
        """The Record the reader's own call to load_record gave, after the real loader ran."""
        seen: list[Any] = []
        real = mi.load_record

        def spy(hw: Path, **kwargs: Any) -> Any:
            seen.append(real(hw, **kwargs))
            raise Stop

        with mock.patch.object(mi, "load_record", spy), self.assertRaises(Stop):
            run()
        return seen[0]

    def assert_frozen(self, record: Any) -> None:
        self.assertEqual([p.message for p in record.problems if p.code == "intent.guideline"], [], "a shipped copy is accepted")
        self.assertEqual(dict(record.guideline_digests.get("tst_printer", {})), self.frozen, "the digests are those of the snapshot")


class SnapshotReaders(FrozenVersion):
    def test_each_producer_reads_the_frozen_guideline_copies_not_the_live_install(self) -> None:
        for name, module in READERS.items():
            with self.subTest(reader=name):
                args = argparse.Namespace(version="v1", hw=self.hw, version_dir=self.record_dir.parent, record_hw=self.record_dir)
                self.assert_frozen(self.loaded(lambda: module.assess(args, "v1", self.record_dir)))

    def test_a_producer_run_without_a_version_reads_the_live_record(self) -> None:
        for name, module in READERS.items():
            with self.subTest(reader=name):
                args = argparse.Namespace(version=None, hw=self.hw, version_dir=None, record_hw=self.hw)
                record = self.loaded(lambda: module.assess(args, None, self.hw))
                live = gl.discover(self.hw).guidelines["fdm.material.pa"].sha256
                self.assertEqual(dict(record.guideline_digests["tst_printer"]), {"fdm.material.pa@1": live})


if __name__ == "__main__":
    unittest.main()
