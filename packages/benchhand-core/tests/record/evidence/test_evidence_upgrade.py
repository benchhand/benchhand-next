"""The evidence reader upgrades a prototype (record_version 2) packet and snapshot of a built version in memory.

Migrate leaves sealed history alone (docs/contract/record-migration.md), so a migrated project keeps its built
versions at record_version 2. The reader checks the seal on the bytes on disk, then upgrades what it reads with
migrate's own rules, never writes, and the digests keep covering the bytes on disk.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.assess import assess
from benchhand_core.record.evidence.built import BuiltVersion, ChangedSinceBuild, NotComputed
from benchhand_core.record.evidence.reader import BuiltVersionError, read_built_version, read_snapshot
from benchhand_core.record.evidence.view import view
from benchhand_core.record.migrate import MigrationStatus, migrate
from benchhand_core.record.model import Record
from benchhand_core.record.rules.assembly import inventory
from benchhand_core.record.store import load_record

from ..conftest import LAMP_ARM_HW
from .conftest import seal, sha256
from .digest_case import build_version, write_case

TODAY = date(2026, 6, 1)
PACKET = "hw/checks/v1/cad"
VERSION = "hw/versions/v1"

# evidence_sha256 of the migrated v2 fixture (`migrated_v2`), computed with the reader before it upgraded
# anything: a digest recorded for a v2 built version stays valid, because it states the bytes on disk.
V2_EVIDENCE_SHA256 = "140f1ff9c288f14cbaaa1e9b0f5b7f5fd143cc40b6dba81ea06964cc31c0070d"


def hashes(directory: Path) -> dict[str, str]:
    """Every file below `directory` with its sha256."""
    return {
        path.relative_to(directory).as_posix(): sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _version_sha(root: Path) -> str:
    return sha256(root / VERSION / "manifest.json")


@pytest.fixture
def migrated_v2(tmp_path: Path) -> Path:
    """A prototype lamp-arm project with v1 built at record_version 2 (a v2 snapshot, a v2 packet, both
    sealed), migrated: its live record is v3, its sealed history is as the prototype wrote it."""
    source = tmp_path / "source"
    shutil.copytree(LAMP_ARM_HW, source / "hw")
    write_case(source / "hw", built_as=2)
    root = tmp_path / "migrated"
    shutil.copytree(source / "hw", root / "hw")
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied, result.refusals
    for sealed in ("versions", "checks"):
        assert hashes(root / "hw" / sealed) == hashes(source / "hw" / sealed), (
            "migrate rewrote sealed history"
        )
    return root


def read(root: Path) -> tuple[Record, BuiltVersion]:
    record = load_record(root)
    return record, read_built_version(root, record, "v1", shipped_guidelines=None)


def dumped(root: Path) -> dict[str, Any]:
    record, built = read(root)
    return assess(record, built, TODAY).model_dump(mode="json", by_alias=True, exclude_none=True)


def codes(result: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def test_a_v2_packet_upgrades_in_memory_and_counts(migrated_v2: Path) -> None:
    on_disk = (migrated_v2 / PACKET / "result.json").read_bytes()
    assert json.loads(on_disk)["record_version"] == 2
    _, built = read(migrated_v2)
    assert built.packet_findings == ()
    [packet] = built.packets
    assert packet.data["record_version"] == 3
    assert packet.bundle == PACKET
    assert (migrated_v2 / PACKET / "result.json").read_bytes() == on_disk  # nothing is written back


def test_a_v2_snapshot_upgrades_in_memory_and_staleness_is_computed(migrated_v2: Path) -> None:
    on_disk = hashes(migrated_v2 / VERSION)
    _, built = read(migrated_v2)
    assert built.staleness == ChangedSinceBuild({})
    assert "record_version: 2" in (migrated_v2 / VERSION / "record/product.yaml").read_text(encoding="utf-8")
    assert hashes(migrated_v2 / VERSION) == on_disk


def test_a_v2_snapshot_that_cannot_be_upgraded_leaves_staleness_not_computed(migrated_v2: Path) -> None:
    """hole_d beside hole_diameter_mm is a conflict the heat-set-keys rule refuses (migrate.key_conflict)."""
    interfaces = migrated_v2 / VERSION / "record/interfaces.yaml"
    text = interfaces.read_text(encoding="utf-8")
    assert "hole_d:" in text
    interfaces.write_text(text.replace("hole_d:", "hole_diameter_mm: 1\n      hole_d:", 1), encoding="utf-8")
    seal(migrated_v2 / VERSION, version="v1")
    _, built = read(migrated_v2)
    assert isinstance(built.staleness, NotComputed)
    assert "interfaces.yaml" in built.staleness.reason


def test_a_v2_packet_that_cannot_be_upgraded_is_a_finding_and_counts_as_nothing(migrated_v2: Path) -> None:
    result_json = migrated_v2 / PACKET / "result.json"
    data = json.loads(result_json.read_text(encoding="utf-8"))
    data["producer"] = 7  # a v2 form that breaks the v3 contract, which upgrading cannot repair
    result_json.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    seal(migrated_v2 / PACKET, version_manifest_sha256=_version_sha(migrated_v2))
    _, built = read(migrated_v2)
    assert built.packets == ()
    [finding] = built.packet_findings
    assert finding.code == "packet.unupgradable"
    assert finding.path == f"{PACKET}/result.json"
    assert "record_version 2" in finding.message
    assert "/producer" in finding.message
    assert PACKET in built.bound_bundles  # sealed and bound, so the inventory holds it


def test_a_v3_packet_is_unchanged(migrated_v2: Path, tmp_path: Path) -> None:
    twin = rebuilt_in_v3(migrated_v2, tmp_path)
    on_disk = json.loads((twin / PACKET / "result.json").read_text(encoding="utf-8"))
    assert on_disk["record_version"] == 3
    _, built = read(twin)
    [packet] = built.packets
    assert dict(packet.data) == on_disk
    assert built.packet_findings == ()


def test_a_v3_packet_that_breaks_its_contract_stays_packet_invalid(migrated_v2: Path, tmp_path: Path) -> None:
    twin = rebuilt_in_v3(migrated_v2, tmp_path)
    result_json = twin / PACKET / "result.json"
    data = json.loads(result_json.read_text(encoding="utf-8"))
    data["producer"] = 7
    result_json.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    seal(twin / PACKET, version_manifest_sha256=_version_sha(twin))
    _, built = read(twin)
    assert [finding.code for finding in built.packet_findings] == ["packet.invalid"]


def test_the_seal_is_verified_on_the_bytes_before_the_upgrade(migrated_v2: Path) -> None:
    """A v2 packet changed after it was sealed is stale, however well it would upgrade."""
    result_json = migrated_v2 / PACKET / "result.json"
    result_json.write_text(result_json.read_text(encoding="utf-8") + " ", encoding="utf-8")
    _, built = read(migrated_v2)
    assert built.packets == ()
    [finding] = built.packet_findings
    assert finding.code == "packet.invalid"
    assert "result.json changed after it was sealed" in finding.message
    assert PACKET not in built.bound_bundles


def test_a_v2_snapshot_changed_after_sealing_is_no_build(migrated_v2: Path) -> None:
    product = migrated_v2 / VERSION / "record/product.yaml"
    product.write_text(product.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    with pytest.raises(BuiltVersionError, match="changed after it was sealed"):
        read(migrated_v2)


def rebuilt_in_v3(migrated_v2: Path, tmp_path: Path) -> Path:
    """The twin: the migrated project with v1 built again in v3 forms, from its migrated documents."""
    twin = tmp_path / "twin"
    shutil.copytree(migrated_v2 / "hw", twin / "hw")
    shutil.rmtree(twin / "hw/versions")
    shutil.rmtree(twin / "hw/checks")
    build_version(twin / "hw", 3)
    return twin


def test_a_v2_built_version_and_its_v3_twin_agree(migrated_v2: Path, tmp_path: Path) -> None:
    """Everything the upgrade feeds agrees with a version built in v3 forms from the same record: the
    packet's data, the built snapshot's fingerprints, staleness and the expected digest. The inventory agrees
    on every key but the packet's manifest, which states the sealed bytes and so differs."""
    twin = rebuilt_in_v3(migrated_v2, tmp_path)
    record, built = read(migrated_v2)
    twin_record, twin_built = read(twin)
    assert [dict(p.data) for p in built.packets] == [dict(p.data) for p in twin_built.packets]
    assert built.staleness == twin_built.staleness == ChangedSinceBuild({})
    snapshot = read_snapshot(migrated_v2 / VERSION / "record", record)
    twin_snapshot = read_snapshot(twin / VERSION / "record", twin_record)
    placed = inventory(snapshot.assembly, snapshot.parts)[0]
    twin_placed = inventory(twin_snapshot.assembly, twin_snapshot.parts)[0]
    assert fp.subject_fingerprints(view(snapshot), placed, built.current_geometry) == fp.subject_fingerprints(
        view(twin_snapshot), twin_placed, twin_built.current_geometry
    )
    result, twin_result = dumped(migrated_v2), dumped(twin)
    assert result["expected_sha256"] == twin_result["expected_sha256"]
    manifest = f"{PACKET}/manifest.json"
    ours, theirs = result["acceptance"]["inventory"], twin_result["acceptance"]["inventory"]
    assert ours[manifest] != theirs[manifest]
    assert {k: v for k, v in ours.items() if k != manifest} == {
        k: v for k, v in theirs.items() if k != manifest
    }
    assert result["statuses"] == twin_result["statuses"]
    assert codes(result) == codes(twin_result)


def test_a_v2_built_versions_evidence_digest_is_the_one_of_its_bytes(migrated_v2: Path) -> None:
    """Pin: the digest of a v2 built version, computed before the reader upgraded anything, is unchanged,
    so a digest already recorded for one stays valid."""
    assert dumped(migrated_v2)["acceptance"]["evidence_sha256"] == V2_EVIDENCE_SHA256
