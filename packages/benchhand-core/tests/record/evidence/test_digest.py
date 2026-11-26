"""The acceptance digest pinned to the prototype's (evidence.py:1320 acceptance_digest and :306
expected_digest at release.toml reference_commit 412b5d9). The golden values are the prototype functions'
output on these inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from benchhand_core.record.evidence.assess import assess
from benchhand_core.record.evidence.digest import acceptance_digest, expected_digest
from benchhand_core.record.evidence.reader import read_built_version
from benchhand_core.record.store import load_record

from ..conftest import LAMP_ARM_HW, migrated
from .digest_case import write_case

# Files the v3 inventory holds beyond the prototype's, each with its reason.
EXTRAS = {
    # part.yaml procurement.specification.artifact: the prototype reads the specification as a fact and
    # never collects its artifact (manufacturing_intent.py:1839), so its bytes fall outside its digest
    "hw/parts/LMP-0010/sources/lampholder-insert-requirement.md": (
        "c113b676a25cda537635651373807ca2bc142acc76625e07945a4c08183e008d"
    ),
}

INVENTORY = {
    "hw/verification.csv": "a" * 64,
    "hw/manufacturing/evidence.yaml": "b" * 64,
    "hw/manufacturing/sources/datasheet \u00e9.pdf": "c" * 64,
    "hw/checks/v1/cad/manifest.json": "d" * 64,
}


def test_acceptance_digest_matches_the_prototype() -> None:
    assert acceptance_digest(INVENTORY) == "4303385450ac7a64c6e8ebb3201881e3ee2ba7d1d873cb401a7d66313d472e9c"


def test_acceptance_digest_ignores_inventory_order() -> None:
    assert acceptance_digest(dict(reversed(INVENTORY.items()))) == acceptance_digest(INVENTORY)


def test_expected_digest_of_no_obligations_matches_the_prototype() -> None:
    assert expected_digest([]) == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def test_lamp_arm_acceptance_inventory_matches_the_prototype(tmp_path: Path) -> None:
    """The exact inventory and evidence_sha256 of a real, non-empty case (evidence.py:1283-1323): the
    lamp-arm record with a ledger entry citing an artifact, a sealed bundle, a source and a criterion-source
    artifact; files under manufacturing/sources/; and a sealed check packet the assessment refuses (its
    outcome contradicts its result) but the inventory holds. The expected digest is pinned too.

    The v3 inventory is the prototype's plus EXTRAS: it covers every artifact the record names, where the
    prototype covers only those its `source()` call sites read (manufacturing_intent.py:1345), so v3 and
    prototype evidence_sha256 differ on such a record. Any other difference fails.

    lamp_arm_acceptance.412b5d9.json was captured from the prototype at 412b5d9, against a copy of the
    read-only snapshot. In a `mktemp -d` directory D:

        cp -R <snapshot of benchhand/benchhand at 412b5d9> D/proto
        find D/proto -exec chmod u+w {} +
        PYTHONPATH=packages/benchhand-core/tests uv run python -m record.evidence.digest_case D/case
        cd D/proto/skills/cad-record/scripts
        uv run --script <this directory>/capture_412b5d9.py D/case > lamp_arm_acceptance.412b5d9.json
    """
    golden = json.loads((Path(__file__).parent / "lamp_arm_acceptance.412b5d9.json").read_text())
    root = tmp_path / "case"
    migrated(LAMP_ARM_HW, root)
    write_case(root / "hw")
    record = load_record(root)
    result = assess(record, read_built_version(root, record, "v1", shipped_guidelines=None), date(2026, 6, 1))
    dumped = result.model_dump(mode="json", exclude_none=True)
    acceptance = dumped["acceptance"]
    assert any(f["code"] == "packet.invalid" for f in dumped["findings"])
    assert acceptance["inventory"] == {**golden["inventory"], **EXTRAS}
    assert acceptance["evidence_sha256"] == acceptance_digest({**golden["inventory"], **EXTRAS})
    assert acceptance_digest(golden["inventory"]) == golden["evidence_sha256"]
    # the expected obligations differ only by v3's heat-set key rename in the basis text (see
    # test_lamp_arm_obligations_match_the_prototype)
    theirs = json.loads((Path(__file__).parent / "lamp_arm_obligations.412b5d9.json").read_text())
    assert expected_digest(theirs["obligations"]) == golden["expected_sha256"]
    renamed = [
        {**o, "basis": o["basis"].replace("declared hole_d ", "declared hole_diameter_mm ")}
        for o in theirs["obligations"]
    ]
    assert dumped["expected_sha256"] == expected_digest(renamed)
