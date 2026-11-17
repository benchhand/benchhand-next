#!/usr/bin/env python3
"""migrate.plan characterization: the whole outcome (plan JSON with diffs, or the refusal message) of the lamp-arm
record and of each variant that exercises one planning branch, pinned by digest so a refactor cannot change a byte."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from test_migrate import TODAY, fx, migrate

GOLDEN = {
    'blocks_present': 'pending:28981c62082707083f7d70599b36e11d4dc0b23e45662954fcba86924e6139b3',
    'lamp': 'pending:6b36118a2f3afe40d71a075daea512bc03d7cbe0dc44bb989892f377e241d01e',
    'missing_file': 'refused:09b3aedef2fae20db529d5d9e0697c50c74100c2394b1211ee77ecc30c31ede3',
    'missing_question': 'refused:5a4b00b06fe5db33a42593aadfdf92979fc4dea7b926a94401de624fb78a7e36',
    'no_interface_id': 'refused:a4e4f9d8b254e4dade7aac7f9afe12e4b9b56c46ac94b5369b11851d2b32dc78',
    'no_operations': 'pending:0ca25ee48f3a76a06eb6c0bbab223134e2110f4b24f46cdfa0e19da334015bd3',
    'no_product': 'refused:2d8d8cc2b3d3028be4b727a95807fb4807c7df1dd7241c73c8972d6b6b50e0eb',
    'not_mapping': 'refused:d59a63f21132ab76ba29500f332a006266fb27171760be5915a70475e3f0b76d',
    'preferences': 'pending:5bffbc6f321a0ccf9cd8626b8445fc0dc587281e9e4e63831c999f043fc001db',
    'use_case_kept': 'pending:85d8bd8af519b028bd2a13e9fe9f686fef40426d7b6331882be5115f188ffcec',
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


class Variants(PlanOutcome):
    def migrated_then(self, change: Any) -> None:
        migrate.apply(migrate.plan(self.hw, TODAY))
        self.edit("product.yaml", change)

    def test_existing_open_questions_missing_a_migrated_id(self) -> None:
        self.migrated_then(lambda d: d.pop("record_version"))
        self.edit("requirements.yaml", lambda d: d["open_questions"].pop())
        self.check("missing_question")

    def test_no_product(self) -> None:
        (self.hw / "product.yaml").unlink()
        self.check("no_product")

    def test_a_current_record(self) -> None:
        migrate.apply(migrate.plan(self.hw, TODAY))
        self.assertEqual(self.outcome()[0], "current")


if __name__ == "__main__":
    unittest.main()
