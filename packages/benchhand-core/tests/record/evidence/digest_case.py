"""A real, non-empty acceptance-inventory case: the lamp-arm record with a ledger entry, its cited artifact,
bundle, source and criterion-source artifacts, files under hw/manufacturing/sources/, a built v1 and a sealed
check packet bound to it whose outcomes contradict its result (the assessment refuses it; the inventory
still holds it).

`write_case` writes the same bytes into a v2 (prototype) or v3 hw/ tree; nothing it writes depends on the
record version. Run as a module to lay out both trees for the prototype capture (see test_digest.py):

    PYTHONPATH=packages/benchhand-core/tests uv run python -m record.evidence.digest_case <dir>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

READBACK = {
    "id": "cad.readback@LMP-0001",
    "family": "cad.readback",
    "subject": {"PN": "LMP-0001"},
    "level": "cad_valid",
    "stage": "layout",
    "basis": "LMP-0001: B-rep validity, readback, manufacturing state and component identity",
}
VERIFICATION = "requirement,method,criteria,result,evidence\nREQ-001,T,Measure head travel,planned,\n"
DATASHEET = "manufacturing/sources/datasheet.txt"
COUPON = "parts/LMP-0001/sources/coupon.txt"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return _sha(path)


def _seal(directory: Path, **fields: Any) -> str:
    paths = [p for p in sorted(directory.rglob("*")) if p.is_file()]
    files = {p.relative_to(directory).as_posix(): _sha(p) for p in paths}
    manifest = json.dumps({"files": files, **fields}, indent=1, sort_keys=True)
    return _write(directory / "manifest.json", manifest)


def _packet(record_version: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_version": record_version,
        "producer": "TST producer 1.0",
        "scope": [{"PN": "LMP-0001"}],
        "expected": [READBACK],
        "outcomes": [
            {"obligation": READBACK["id"], "outcome": "fail", "method": "TST", "coverage": "the sealed STEP"}
        ],
        "findings": [],
        "dependencies": {"geometry": "a" * 64},
        "complete": True,
        "result": "pass",
    }


BUILT_LEDGER_SHA = "e" * 64  # the manifest a ledger entry cites when the case builds a version in some form


def _build_version(hw: Path, record_version: int) -> None:
    """Seal hw/versions/v1 with a snapshot of the record at `hw` and its parts' model sources, as a build
    does, and bind a packet at `record_version` to it."""
    from .conftest import snapshot  # not at import: this module also runs outside pytest

    snapshot(hw, "v1")
    models = sorted((hw / "parts").glob("*/model.py"))
    parts = {path.parent.name: {"source_sha256": _sha(path)} for path in models}
    version_sha = _seal(hw / "versions/v1", version="v1", parts=parts)
    _write(hw / "checks/v1/cad/result.json", json.dumps(_packet(record_version), indent=1, sort_keys=True))
    _seal(hw / "checks/v1/cad", version_manifest_sha256=version_sha)


def write_case(hw: Path, *, built_as: int | None = None) -> None:
    """Add the case's files to the record at `hw`. A v3 tree also gets a fixed verification.csv, so the
    inventory does not depend on the converter's output.

    `built_as` None keeps the golden case: a version with one note file and a packet at record_version 3.
    2 or 3 builds v1 as a build at that record version does: a snapshot of the record documents at `hw`
    (v2 documents in a prototype tree) and a packet at that record_version, both sealed. The ledger then
    cites a fixed manifest digest, so the inventory of the two forms differs by the packet's manifest only."""
    if (hw / "verification.csv").read_text(encoding="utf-8").startswith("requirement,") and built_as is None:
        _write(hw / "verification.csv", VERIFICATION)
    datasheet = _write(hw / DATASHEET, "PETG datasheet\n")
    _write(hw / "manufacturing/sources/curves/creep.csv", "hours,strain\n0,0\n")
    coupon = _write(hw / COUPON, "coupon report\n")
    report = _write(hw / "docs/readback.txt", "readback ok\n")
    _write(hw / "captures/v1/bench/photo.txt", "bench photo\n")
    bench = _seal(hw / "captures/v1/bench")
    if built_as is None:
        _write(hw / "versions/v1/note.txt", "v1\n")
        version_sha = _seal(hw / "versions/v1", version="v1")
        _write(hw / "checks/v1/cad/result.json", json.dumps(_packet(3), indent=1, sort_keys=True))
        _seal(hw / "checks/v1/cad", version_manifest_sha256=version_sha)
    else:
        _build_version(hw, built_as)
        version_sha = BUILT_LEDGER_SHA
    entry = {
        "id": "EV-001",
        "requirement": "REQ-001",
        "subject": {"product": True},
        "level": "cad_valid",
        "result": "pass",
        "method": "TST readback",
        "source": {"kind": "datasheet", "reference": "PETG", "artifact": DATASHEET},
        "criterion": {
            "property": "readback",
            "operator": "equals",
            "value": True,
            "source": {"kind": "test", "reference": "coupon", "artifact": COUPON},
        },
        "configuration": {"version": "v1", "manifest_sha256": version_sha},
        "artifacts": [{"path": "hw/docs/readback.txt", "sha256": report}],
        "bundle": {"path": "hw/captures/v1/bench", "manifest_sha256": bench},
    }
    entry["source"]["sha256"] = datasheet
    entry["criterion"]["source"]["sha256"] = coupon
    ledger = yaml.safe_dump({"entries": [entry]}, sort_keys=False, allow_unicode=True)
    _write(hw / "manufacturing/evidence.yaml", ledger)


def main(target: Path) -> None:
    """Lay out <target>/v2/hw (the prototype's lamp-arm) and <target>/v3/hw (converted), each with the
    case."""
    from record.conftest import LAMP_ARM_HW, migrated

    shutil.copytree(LAMP_ARM_HW, target / "v2" / "hw")
    write_case(target / "v2" / "hw")
    migrated(LAMP_ARM_HW, target / "v3")
    write_case(target / "v3" / "hw")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
