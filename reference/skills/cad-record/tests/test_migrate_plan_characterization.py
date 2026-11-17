#!/usr/bin/env python3
"""migrate.plan characterization: the whole outcome (plan JSON with diffs, or the refusal message) of each variant
that exercises one planning branch, pinned by digest so a refactor cannot change a byte. The record version 1
variants run on the minimal v1 fixture, given one interface where the branch needs it. The refusal digests hash
message text worked out from migrate.py; the pending digests are pinned from a run on that input."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from test_migrate import TODAY, V1_MINIMAL, fx, mi, migrate

# preferences, use_case_kept and blocks_present: regenerated when the input gained an interface (IF-001) so that
# the functional-block branch of plan_interfaces runs, and two drawing.operations so the move branch of plan_assembly
# runs. The refusal digests are unchanged.
GOLDEN = {
    'blocks_present': 'pending:d7fdc21cf2f6aea9206c5158dc4ce8d43a12cd7216d960c620f16e8171528a14',
    'lamp': 'pending:6b36118a2f3afe40d71a075daea512bc03d7cbe0dc44bb989892f377e241d01e',
    'missing_file': 'refused:09b3aedef2fae20db529d5d9e0697c50c74100c2394b1211ee77ecc30c31ede3',
    'missing_question': 'refused:af778ab0eefdbe56a767f2985edc40ceb88da14536441491414f60904d7be225',
    'no_interface_id': 'refused:a4e4f9d8b254e4dade7aac7f9afe12e4b9b56c46ac94b5369b11851d2b32dc78',
    'no_operations': 'pending:0ca25ee48f3a76a06eb6c0bbab223134e2110f4b24f46cdfa0e19da334015bd3',
    'no_product': 'refused:2d8d8cc2b3d3028be4b727a95807fb4807c7df1dd7241c73c8972d6b6b50e0eb',
    'not_mapping': 'refused:d59a63f21132ab76ba29500f332a006266fb27171760be5915a70475e3f0b76d',
    'preferences': 'pending:884a17d8f3f976196758d0941c552f933d051030d1f56afaa10bf9e2186547cb',
    'use_case_kept': 'pending:6399ceaff758d7a99d905eaa5cab4aa6c2a1ee911bfc751d7f2e154efb71a55c',
}


class PlanOutcome(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-migrate-char-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "project" / "hw"
        shutil.copytree(fx.LAMP, self.hw)

    def edit(self, rel: str, change: Any) -> None:
        path = self.hw / rel
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def outcome(self) -> tuple[str, str]:
        try:
            plan = migrate.plan(self.hw, TODAY)
        except migrate.Refused as error:
            return "refused", str(error).replace(str(self.hw), "<hw>")
        report = plan.as_dict()
        report["after"] = {c.path: c.after for c in plan.changes}
        return plan.status, json.dumps(report, indent=2)

    def digest(self) -> str:
        status, text = self.outcome()
        return f"{status}:{hashlib.sha256(text.encode()).hexdigest()}"

    def check(self, name: str) -> None:
        self.assertEqual(self.digest(), GOLDEN[name])


KEPT = "TST: filled in by hand before the run was interrupted"


class Version1Variants(PlanOutcome):
    """The planning branches that need a record version 1, on the minimal v1 fixture (one part, no interfaces)."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-migrate-char-v1-")
        self.addCleanup(temporary.cleanup)
        self.hw = Path(temporary.name) / "project" / "hw"
        shutil.copytree(V1_MINIMAL, self.hw)

    def assert_version_1(self) -> None:
        product = yaml.safe_load((self.hw / "product.yaml").read_text(encoding="utf-8"))
        self.assertEqual(mi.record_version(product), 1, "the input is a record version 1, or the test proves nothing")

    def add_interface(self) -> None:
        fx.add_v1_interface(self.hw)

    def add_operations(self) -> None:
        fx.add_v1_operations(self.hw)

    def migrated_then(self, change: Any) -> None:
        """Migrate a copy that has an interface. Hand-edit the interface's functional block so a rewrite shows.
        Then undo the version bump and more, by `change`. An interrupted run leaves this state."""
        self.add_interface()
        self.add_operations()
        migrate.apply(migrate.plan(self.hw, TODAY))
        self.edit("interfaces.yaml", lambda d: d["interfaces"][0]["functional"]["critical"].update(reason=KEPT))
        self.edit("product.yaml", change)

    def assert_functional_kept(self) -> None:
        """Replanning leaves the interface's existing functional block alone (migrate.py skips it) and on disk."""
        self.assertNotIn("hw/interfaces.yaml", {c.path for c in migrate.plan(self.hw, TODAY).changes})
        interfaces = yaml.safe_load((self.hw / "interfaces.yaml").read_text(encoding="utf-8"))["interfaces"]
        self.assertEqual(interfaces[0]["functional"]["critical"]["reason"], KEPT)

    def test_preferences_already_present(self) -> None:
        self.assert_version_1()
        self.add_interface()
        self.add_operations()
        self.edit("requirements.yaml", lambda d: d.update(preferences=[]))
        changes = {c.path: c for c in migrate.plan(self.hw, TODAY).changes}
        # 11 use-case questions, 1 for the part and 1 for the interface. The operations exist. Preferences are there.
        self.assertEqual(changes["hw/requirements.yaml"].summary, ["adds assumptions, open_questions (13 open questions)"])
        self.assertEqual(changes["hw/assembly.yaml"].summary,
                         ["moves drawing.operations (2 operations) to top-level operations, unchanged"])
        self.assertEqual(changes["hw/interfaces.yaml"].summary, ["adds functional (critical and functions unknown) to IF-001"])
        self.check("preferences")

    def test_interrupted_run_keeps_use_case_and_rewrites_the_dated_note(self) -> None:
        self.migrated_then(lambda d: d.pop("record_version"))
        self.assert_version_1()
        self.assert_functional_kept()
        note = next(c for c in migrate.plan(self.hw, TODAY).changes if c.path.startswith("hw/docs/record-migration-v2-"))
        self.assertEqual(note.action, "modify", "the first run's dated note exists and is rewritten")
        self.check("use_case_kept")

    def test_interrupted_run_with_every_block_present_but_the_use_case(self) -> None:
        self.migrated_then(lambda d: (d.pop("record_version"), d.pop("use_case")))
        self.assert_version_1()
        self.assert_functional_kept()
        self.check("blocks_present")

    def test_existing_open_questions_missing_a_migrated_id(self) -> None:
        self.migrated_then(lambda d: d.pop("record_version"))
        self.assert_version_1()
        self.assertEqual(migrate.plan(self.hw, TODAY).status, "pending", "the interrupted run replans, or the check below is vacuous")
        # The first run asked 13 questions (11 use case, part, interface), and the replan needs the same 13.
        self.edit("requirements.yaml", lambda d: d["open_questions"].pop())
        self.check("missing_question")

    def test_an_interface_without_an_id(self) -> None:
        self.assert_version_1()
        interface = {"from": "base_sub", "to": "base_sub", "type": "motion", "description": "TST interface"}
        self.edit("interfaces.yaml", lambda d: d.update(interfaces=[interface]))
        self.check("no_interface_id")

    def test_a_mapping_check_on_each_document(self) -> None:
        self.assert_version_1()
        (self.hw / "requirements.yaml").write_text("- a\n", encoding="utf-8")
        self.check("not_mapping")

    def test_a_missing_record_file(self) -> None:
        self.assert_version_1()
        (self.hw / "interfaces.yaml").unlink()
        self.check("missing_file")


class Variants(PlanOutcome):
    def test_no_product(self) -> None:
        (self.hw / "product.yaml").unlink()
        self.check("no_product")

    def test_a_current_record(self) -> None:
        migrate.apply(migrate.plan(self.hw, TODAY))
        self.assertEqual(self.outcome()[0], "current")


if __name__ == "__main__":
    unittest.main()
