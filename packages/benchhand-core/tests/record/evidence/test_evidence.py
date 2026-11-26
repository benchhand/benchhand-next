"""The evidence service on a built lamp-arm version (record_version 3, converted from the prototype).

Each test cites the prototype rule it ports: skills/cad-record/scripts/evidence.py, impact.py,
manufacturing_intent.py or assembly_operations.py at release.toml reference_commit 412b5d9, and the
prototype test (reference/skills/cad-record/tests/test_evidence.py) it is ported from.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_core.record.errors import RecordSchemaError
from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.assess import assess
from benchhand_core.record.evidence.built import NotComputed
from benchhand_core.record.evidence.guidelines import with_guideline_digests
from benchhand_core.record.evidence.obligations import required_checks
from benchhand_core.record.evidence.reader import BuiltVersionError, read_built_version
from benchhand_core.record.evidence.view import view
from benchhand_core.record.model import as_json
from benchhand_core.record.rules.assembly import inventory
from benchhand_core.record.store import load_record

from .conftest import WritePacket, build, seal, sha256, write_yaml

TODAY = date(2026, 6, 1)
READBACK = "cad.readback@LMP-0001"
ROUTE = "route.consistency@LMP-0001"
TRIAL = "process.fdm.trial@LMP-0001/print"
EXPORT_3MF = "export.3mf@LMP-0001"
JOINT = "assembly.joint@op:heat_set_base_bushing"
APPROVED = "DR-005"
EVIDENCE = Path("hw/manufacturing/evidence.yaml")


def run(root: Path, today: date = TODAY, shipped: Path | None = None) -> dict[str, Any]:
    record = load_record(root)
    built = read_built_version(root, record, "v1", shipped_guidelines=shipped)
    return assess(record, built, today).model_dump(mode="json", by_alias=True, exclude_none=True)


def statuses(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {status["obligation"]["id"]: status for status in result["statuses"]}


def codes(result: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def expected(root: Path) -> dict[str, dict[str, Any]]:
    return {o.id: as_json(o) for o in required_checks(view(load_record(root))).obligations}


def packet(
    root: Path, outcomes: dict[str, str], *, level: str | None = None, **fields: Any
) -> dict[str, Any]:
    """A manufacturing-check-result for `outcomes` (obligation -> outcome) of the record at `root`."""
    known = expected(root)
    rows = []
    for ident, outcome in outcomes.items():
        row = {"obligation": ident, "outcome": outcome, "method": "TST", "coverage": "the sealed STEP only"}
        if level is not None:
            row["level"] = level
        if outcome == "not_assessed":
            row["reason"] = "calibration_off"
        rows.append(row)
    shown = {row["outcome"] for row in rows}
    result = next((r for r in ("fail", "unknown", "not_assessed") if r in shown), "pass")
    data = {
        "schema_version": 1,
        "record_version": 3,
        "producer": "TST producer 1.0",
        "scope": [{"PN": "LMP-0001"}],
        "expected": [known[ident] for ident in outcomes],
        "outcomes": rows,
        "findings": [],
        "dependencies": {"geometry": "a" * 64},
        "complete": True,
        "result": result,
    }
    return {**data, **fields}


def current_fingerprints(root: Path, subject: dict[str, Any], shipped: Path | None = None) -> dict[str, str]:
    record = load_record(root)
    built = read_built_version(root, record, "v1", shipped_guidelines=shipped)
    placed, _ = inventory(record.assembly, record.parts)
    return fp.fingerprints(
        with_guideline_digests(view(record), built.guidelines), placed, subject, built.current_geometry
    )


def ledger_entry(root: Path, manifest_sha: str, **fields: Any) -> dict[str, Any]:
    """A qualified pass of cad.readback@LMP-0001 on v1, citing hw/docs/readback.txt, with every
    fingerprint of its subject as it stands now."""
    report = root / "hw" / "docs" / "readback.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    if not report.exists():
        report.write_text("readback ok\n", encoding="utf-8")
    subject = {"PN": "LMP-0001"}
    entry = {
        "id": "EV-001",
        "obligation": READBACK,
        "subject": subject,
        "level": "cad_valid",
        "result": "pass",
        "method": "TST readback",
        "criterion": {
            "property": "readback",
            "operator": "equals",
            "value": True,
            "source": {
                "kind": "test",
                "reference": "TST",
                "url": "https://example.org/tst",
                "accessed": "2026-05-01",
            },
        },
        "configuration": {"version": "v1", "manifest_sha256": manifest_sha, "rev": "X1"},
        "fingerprints": current_fingerprints(root, subject),
        "artifacts": [{"path": "hw/docs/readback.txt", "sha256": sha256(report)}],
    }
    return {**entry, **fields}


def write_ledger(root: Path, *entries: dict[str, Any]) -> None:
    write_yaml(root / EVIDENCE, {"entries": list(entries)})


def waiver(**fields: Any) -> dict[str, Any]:
    data = {
        "decision": APPROVED,
        "subject": {"PN": "LMP-0001"},
        "criterion": "TST",
        "operating_envelope": "TST",
        "valid_until": "2026-12-31",
        "reason": "TST",
        "consequence": "TST",
        "authority": "the owner",
    }
    return {**data, **fields}


def waived_entry(root: Path, manifest_sha: str, target: str, **waiver_fields: Any) -> dict[str, Any]:
    return {
        "id": "EV-002",
        "obligation": target,
        "subject": {"PN": "LMP-0001", **({"operation": "print"} if "/print" in target else {})},
        "level": expected(root)[target]["level"],
        "result": "waived",
        "method": "TST",
        "waiver": waiver(**waiver_fields),
    }


# Obligations and the three sources


def test_lamp_arm_obligations_match_the_prototype(lamp_arm: Path) -> None:
    """manufacturing_intent.py:2642 required_checks, on the same record before and after conversion. The
    one difference is v3's heat-set key rename (hole_d -> hole_diameter_mm) in the basis text."""
    golden = json.loads((Path(__file__).parent / "lamp_arm_obligations.412b5d9.json").read_text())
    ours = [as_json(o) for o in required_checks(view(load_record(lamp_arm))).obligations]
    theirs = [
        {**o, "basis": o["basis"].replace("declared hole_d ", "declared hole_diameter_mm ")}
        for o in golden["obligations"]
    ]
    assert ours == theirs


def test_every_obligation_gets_exactly_one_status(built: tuple[Path, str]) -> None:
    """evidence.py:835: one status per expected obligation, none invented."""
    root, _ = built
    result = run(root)
    ids = [status["obligation"]["id"] for status in result["statuses"]]
    assert ids == sorted(expected(root))
    assert len(ids) == len(set(ids))


def test_record_obligations_come_from_the_record(built: tuple[Path, str]) -> None:
    """evidence.py:739-750: intent.* stays unknown and assembly.joint is judged from declared joint facts
    (evidence.py:859, assembly_operations.py:633), as the prototype judges the same record."""
    root, _ = built
    golden = json.loads((Path(__file__).parent / "lamp_arm_joints.412b5d9.json").read_text())["joints"]
    found = statuses(run(root))
    assert found["intent.use_case@product"]["sources"] == ["record"]
    assert found["intent.use_case@product"]["result"] == "unknown"
    joints = {i: [s["result"], s["reasons"][0]] for i, s in found.items() if i.startswith("assembly.joint")}
    assert joints == golden
    assert found[JOINT]["sources"] == ["record"]


def test_nothing_shown_is_unknown(built: tuple[Path, str]) -> None:
    """test_evidence.py:228 nothing_shown_is_unknown: no evidence at all is unknown, never pass."""
    root, _ = built
    found = statuses(run(root))
    assert found[READBACK] == {
        "obligation": expected(root)[READBACK],
        "result": "unknown",
        "sources": [],
        "reasons": [],
    }


# Producer packets


def test_a_sealed_packet_pass_counts(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """evidence.py:752-790: a sealed packet bound to the build shows its outcome."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    found = statuses(run(root))
    assert found[READBACK]["result"] == "pass"
    assert found[READBACK]["sources"] == ["hw/checks/v1/cad"]


def test_a_producer_cannot_physically_validate(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """test_evidence.py:238: software evidence never shows physical validation (evidence.py:775)."""
    root, version_sha = built
    write_packet(root, "process", packet(root, {TRIAL: "pass"}), version_sha)
    result = run(root)
    assert statuses(result)[TRIAL]["result"] == "unknown"
    assert "evidence.physical_claim" in codes(result)


def test_an_outcome_at_another_level_does_not_count(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """test_evidence.py:255 (evidence.py:770)."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}, level="process_planned"), version_sha)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "packet.unexpected" in codes(result)


def test_a_packet_contradicting_itself_is_refused(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """test_evidence.py:554 (evidence.py:876): a result its outcomes do not show voids the packet."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "fail"}, result="pass"), version_sha)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "packet.invalid" in codes(result)
    assert result["complete"] is False


def test_a_changed_file_breaks_the_packet_seal(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """test_evidence.py:591 (layout.py:837, evidence.py:1185): bytes that differ from the manifest count as
    nothing."""
    root, version_sha = built
    bundle = write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    (bundle / "result.json").write_text((bundle / "result.json").read_text() + " ", encoding="utf-8")
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    [finding] = [f for f in result["findings"] if f["code"] == "packet.invalid"]
    assert "result.json changed after it was sealed" in finding["message"]


def test_a_packet_bound_to_another_build_counts_as_nothing(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """test_evidence.py:547 (evidence.py:1200): the version_manifest_sha256 binding."""
    root, _ = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}), "f" * 64)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert any("bound to another build" in f["message"] for f in result["findings"])


def test_an_unsealed_version_is_refused(built: tuple[Path, str]) -> None:
    """layout.py:942 built_version: a version whose files changed after sealing is no build."""
    root, _ = built
    (root / "hw/versions/v1/record/product.yaml").write_text("changed\n", encoding="utf-8")
    with pytest.raises(BuiltVersionError, match="changed after it was sealed"):
        read_built_version(root, load_record(root), "v1", shipped_guidelines=None)


def test_an_outcome_whose_inputs_changed_since_the_build_is_stale(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """test_evidence.py:430 (evidence.py:782, impact.py:535): a changed model source makes cad.* stale."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    model = root / "hw/parts/LMP-0001/model.py"
    model.write_text(model.read_text() + "\n# changed\n", encoding="utf-8")
    result = run(root)
    assert result["build_staleness"] == "computed"
    assert statuses(result)[READBACK]["result"] == "stale"
    assert "geometry" in statuses(result)[READBACK]["reasons"][0]


def test_uncomputed_build_staleness_never_counts_as_pass(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """Supervisor condition 2: without build staleness a producer outcome counts as not_computed, never pass,
    and the result says staleness was not computed."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    record = load_record(root)
    built_version = replace(
        read_built_version(root, record, "v1", shipped_guidelines=None), staleness=NotComputed("TST")
    )
    result = assess(record, built_version, TODAY).model_dump(mode="json", exclude_none=True)
    assert result["build_staleness"] == "not_computed"
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert statuses(result)[READBACK]["reasons"][0].startswith("not_computed:")
    assert "evidence.staleness_not_computed" in codes(result)


def test_a_snapshot_that_does_not_read_leaves_staleness_not_computed(built: tuple[Path, str]) -> None:
    """evidence.py:1695: staleness compares the built snapshot; one that does not read is not computed."""
    root, _ = built
    (root / "hw/versions/v1/record/product.yaml").write_text("record_version: 2\n", encoding="utf-8")
    seal(root / "hw/versions/v1", version="v1")
    built_version = read_built_version(root, load_record(root), "v1", shipped_guidelines=None)
    assert isinstance(built_version.staleness, NotComputed)


# Seals


def test_a_linked_check_bundle_counts_as_nothing(
    built: tuple[Path, str], write_packet: WritePacket, tmp_path: Path
) -> None:
    """A seal read through a link proves nothing: a check bundle that is a link is packet.invalid."""
    root, version_sha = built
    bundle = write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    elsewhere = tmp_path / "elsewhere"
    bundle.rename(elsewhere)
    bundle.symlink_to(elsewhere, target_is_directory=True)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert any(
        "is a symbolic link" in f["message"] for f in result["findings"] if f["code"] == "packet.invalid"
    )
    assert result["complete"] is False


def test_a_linked_version_root_is_refused(built: tuple[Path, str], tmp_path: Path) -> None:
    """A version directory reached through a link is no build."""
    root, _ = built
    versions = root / "hw/versions"
    elsewhere = tmp_path / "versions-elsewhere"
    versions.rename(elsewhere)
    versions.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(BuiltVersionError, match="hw/versions is a symbolic link"):
        read_built_version(root, load_record(root), "v1", shipped_guidelines=None)


def test_a_bundle_without_its_result_is_packet_invalid(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """A damaged packet cannot disappear: a check bundle without result.json is packet.invalid and the
    assessment is incomplete (the prototype skips it, evidence.py:1219)."""
    root, version_sha = built
    bundle = write_packet(root, "cad", packet(root, {READBACK: "pass"}), version_sha)
    (bundle / "result.json").unlink()
    result = run(root)
    assert any(
        "has no result.json" in f["message"] for f in result["findings"] if f["code"] == "packet.invalid"
    )
    assert result["complete"] is False


def test_a_cited_bundle_is_verified_in_full(built: tuple[Path, str]) -> None:
    """A ledger entry citing a bundle relies on every payload file: an edited, added or removed file fails
    the seal even though the manifest's own sha256 is unchanged."""
    root, version_sha = built
    bundle = root / "hw/captures/v1/bench"
    bundle.mkdir(parents=True)
    (bundle / "photo.txt").write_text("bench photo\n", encoding="utf-8")
    manifest_sha = seal(bundle)
    entry = ledger_entry(
        root, version_sha, bundle={"path": "hw/captures/v1/bench", "manifest_sha256": manifest_sha}
    )
    write_ledger(root, entry)
    assert statuses(run(root))[READBACK]["result"] == "pass"
    for change in ("edit", "add", "remove"):
        if change == "edit":
            (bundle / "photo.txt").write_text("another photo\n", encoding="utf-8")
        elif change == "add":
            (bundle / "photo.txt").write_text("bench photo\n", encoding="utf-8")
            (bundle / "extra.txt").write_text("extra\n", encoding="utf-8")
        else:
            (bundle / "extra.txt").unlink()
            (bundle / "photo.txt").unlink()
        result = run(root)
        assert statuses(result)[READBACK]["result"] == "stale", change
        assert "evidence.bundle_seal" in codes(result), change


# Fingerprints: guideline sets and the model frame

SHIPPED = Path(__file__).parents[5] / "reference/skills/cad-record/assets/manufacturing/guidelines"
MOUNTING = "purchase.mounting@LMP-0011/buy"


def shipped_copy(tmp_path: Path) -> Path:
    shipped = tmp_path / "shipped"
    shutil.copytree(SHIPPED, shipped)
    return shipped


def test_a_changed_guideline_set_makes_the_evidence_stale(
    lamp_arm: Path, write_packet: WritePacket, tmp_path: Path
) -> None:
    """impact.py:343-351: the `source` fingerprint holds every guideline set a part's capability profile
    resolves through. With the build otherwise unchanged, a changed set makes the route outcome stale."""
    shipped = shipped_copy(tmp_path)
    version_sha = build(lamp_arm, shipped=shipped)
    write_packet(lamp_arm, "process", packet(lamp_arm, {ROUTE: "pass"}), version_sha)
    assert statuses(run(lamp_arm, shipped=shipped))[ROUTE]["result"] == "pass"
    generic = shipped / "fdm.generic.yaml"
    generic.write_text(generic.read_text(encoding="utf-8") + "\n# revised\n", encoding="utf-8")
    found = statuses(run(lamp_arm, shipped=shipped))[ROUTE]
    assert found["result"] == "stale"
    assert "source" in found["reasons"][0]


def test_a_build_whose_shipped_sets_are_not_read_now_is_stale(
    lamp_arm: Path, write_packet: WritePacket, tmp_path: Path
) -> None:
    """A build that copied shipped sets, read without a shipped catalog, is stale with
    guideline.catalog_missing, never unchanged."""
    version_sha = build(lamp_arm, shipped=shipped_copy(tmp_path))
    write_packet(lamp_arm, "process", packet(lamp_arm, {ROUTE: "pass"}), version_sha)
    found = statuses(run(lamp_arm, shipped=None))[ROUTE]
    assert found["result"] == "stale"
    assert found["reasons"][0].startswith("guideline.catalog_missing:")


def test_a_missing_shipped_catalog_is_stale_even_when_project_copies_match(
    lamp_arm: Path, write_packet: WritePacket, tmp_path: Path
) -> None:
    """The shipped sets copied byte for byte into the project after the build give the same digests, but
    without the shipped catalog the build's sets cannot be shown: packet and ledger evidence of the part are
    stale with guideline.catalog_missing."""
    shipped = shipped_copy(tmp_path)
    version_sha = build(lamp_arm, shipped=shipped)
    write_packet(lamp_arm, "process", packet(lamp_arm, {ROUTE: "pass"}), version_sha)
    entry = ledger_entry(lamp_arm, version_sha, id="EV-002", obligation=ROUTE, level="process_planned")
    entry["fingerprints"] = current_fingerprints(lamp_arm, entry["subject"], shipped=shipped)
    write_ledger(lamp_arm, entry)
    assert statuses(run(lamp_arm, shipped=shipped))[ROUTE]["result"] == "pass"
    shutil.copytree(shipped, lamp_arm / "hw/manufacturing/guidelines")
    found = statuses(run(lamp_arm, shipped=None))[ROUTE]
    assert found["result"] == "stale"
    assert len(found["reasons"]) == 2
    assert all("guideline.catalog_missing" in reason for reason in found["reasons"])


def test_a_guideline_with_an_unreadable_quantity_is_refused(
    lamp_arm: Path, write_packet: WritePacket, tmp_path: Path
) -> None:
    """guidelines.py:186-200, 242-246: a set whose nozzle interval is reversed passes the schema but is
    refused at discovery. It never enters resolution, so it stales nothing, and it gets a finding."""
    shipped = shipped_copy(tmp_path)
    version_sha = build(lamp_arm, shipped=shipped)
    write_packet(lamp_arm, "process", packet(lamp_arm, {ROUTE: "pass"}), version_sha)
    bad = yaml.safe_load((shipped / "fdm.nozzle.d0_4.yaml").read_text(encoding="utf-8"))
    bad["id"] = "fdm.nozzle.reversed"
    bad["scope"]["nozzle_diameter"] = {"lower": 0.6, "upper": 0.4, "units": "mm"}
    bad.pop("extends", None)
    write_yaml(lamp_arm / "hw/manufacturing/guidelines/fdm.nozzle.reversed.yaml", bad)
    record = load_record(lamp_arm)
    built_version = read_built_version(lamp_arm, record, "v1", shipped_guidelines=shipped)
    assert "fdm.nozzle.reversed" not in built_version.guidelines.sets
    assert "fdm.nozzle.reversed" in built_version.guidelines.blocked
    result = assess(record, built_version, TODAY).model_dump(mode="json", exclude_none=True)
    assert statuses(result)[ROUTE]["result"] == "pass"
    [finding] = [f for f in result["findings"] if f["code"] == "intent.guideline"]
    assert finding["path"] == "hw/manufacturing/guidelines/fdm.nozzle.reversed.yaml"
    assert "reversed" in finding["message"]


def test_a_changed_model_frame_of_a_bought_part_makes_the_evidence_stale(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """impact.py:240-267, 357-369: a bought part's `occurrences` domain holds its model_frame, which
    purchase.* reads. With the build otherwise unchanged, a changed frame makes the outcome stale."""
    root, version_sha = built
    write_packet(root, "purchase", packet(root, {MOUNTING: "pass"}), version_sha)
    assert statuses(run(root))[MOUNTING]["result"] == "pass"
    part = root / "hw/parts/LMP-0011/part.yaml"
    text = part.read_text(encoding="utf-8")
    part.write_text(text.replace("model_frame: part_local", "model_frame: assembly_zero"), encoding="utf-8")
    found = statuses(run(root))[MOUNTING]
    assert found["result"] == "stale"
    assert found["reasons"][0] == "its inputs changed since the version was built: occurrences"


# The ledger


def test_a_bound_packet_refused_for_its_contract_stays_in_the_inventory(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """evidence.py:1207, 1302-1303: the inventory holds every sealed packet bound to the build, also one the
    assessment refuses; here its result.json is at record_version 2."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass"}, record_version=2), version_sha)
    result = run(root)
    assert "packet.invalid" in codes(result)
    assert "hw/checks/v1/cad/manifest.json" in result["acceptance"]["inventory"]


def test_a_sealed_bundle_that_is_no_packet_stays_out_of_the_inventory(
    built: tuple[Path, str], write_packet: WritePacket
) -> None:
    """evidence.py:1185-1228: a sealed, bound result.json without expected and outcomes is never collected,
    so it is packet.invalid and the inventory does not hold it."""
    root, version_sha = built
    write_packet(root, "cad", {}, version_sha)
    result = run(root)
    [finding] = [f for f in result["findings"] if f["code"] == "packet.invalid"]
    assert "no expected and outcomes" in finding["message"]
    assert "hw/checks/v1/cad/manifest.json" not in result["acceptance"]["inventory"]


def test_an_artifact_a_project_guideline_cites_is_in_the_inventory(built: tuple[Path, str]) -> None:
    """manufacturing-guideline.tsp citations: a project guideline citing a file under the part's sources
    holds that file in the inventory, so changing it changes the digest."""
    root, _ = built
    cited = root / "hw/parts/LMP-0001/sources/coupon.txt"
    cited.parent.mkdir(parents=True, exist_ok=True)
    cited.write_text("coupon run 1\n", encoding="utf-8")
    guideline = yaml.safe_load((SHIPPED / "fdm.nozzle.d0_4.yaml").read_text(encoding="utf-8"))
    guideline["id"] = "fdm.project.coupon"
    guideline.pop("extends", None)
    citation = {"kind": "test", "reference": "coupon", "artifact": "parts/LMP-0001/sources/coupon.txt"}
    guideline["limits"][0]["citations"] = [{**citation, "sha256": sha256(cited)}]
    write_yaml(root / "hw/manufacturing/guidelines/fdm.project.coupon.yaml", guideline)
    before = run(root)["acceptance"]
    assert "hw/parts/LMP-0001/sources/coupon.txt" in before["inventory"]
    cited.write_text("coupon run 2\n", encoding="utf-8")
    assert run(root)["acceptance"]["evidence_sha256"] != before["evidence_sha256"]


# The ledger


def test_current_qualified_evidence_passes(built: tuple[Path, str]) -> None:
    """test_evidence.py:324 (evidence.py:941)."""
    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    found = statuses(run(root))
    assert found[READBACK]["result"] == "pass"
    assert found[READBACK]["sources"] == ["EV-001"]


@pytest.mark.parametrize("result", ["planned", "unknown"])
def test_planned_and_unknown_evidence_never_pass(built: tuple[Path, str], result: str) -> None:
    """test_evidence.py:271 (evidence.py:964)."""
    root, _ = built
    write_ledger(
        root,
        {
            "id": "EV-001",
            "obligation": READBACK,
            "subject": {"PN": "LMP-0001"},
            "level": "cad_valid",
            "result": result,
            "method": "TST",
        },
    )
    assert statuses(run(root))[READBACK]["result"] == result


def test_evidence_of_another_version_is_stale(built: tuple[Path, str]) -> None:
    """test_evidence.py:329 (evidence.py:971)."""
    root, _ = built
    write_ledger(root, ledger_entry(root, "e" * 64))
    assert statuses(run(root))[READBACK]["result"] == "stale"


def test_a_changed_dependency_fingerprint_makes_the_evidence_stale(built: tuple[Path, str]) -> None:
    """test_evidence.py:334 (evidence.py:985, impact.py:568)."""
    root, version_sha = built
    entry = ledger_entry(root, version_sha)
    entry["fingerprints"]["geometry"] = "0" * 64
    write_ledger(root, entry)
    found = statuses(run(root))[READBACK]
    assert found["result"] == "stale"
    assert "geometry" in found["reasons"][0]


def test_evidence_without_its_required_fingerprints_is_unqualified(built: tuple[Path, str]) -> None:
    """test_evidence.py:400 (evidence.py:979, _REQUIRED_DOMAINS)."""
    root, version_sha = built
    entry = ledger_entry(root, version_sha)
    entry["fingerprints"] = {"route": entry["fingerprints"]["route"]}
    write_ledger(root, entry)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "evidence.unqualified" in codes(result)


def test_cited_bytes_that_changed_make_the_evidence_stale(built: tuple[Path, str]) -> None:
    """test_evidence.py:413 (evidence.py:991)."""
    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    (root / "hw/docs/readback.txt").write_text("edited\n", encoding="utf-8")
    assert statuses(run(root))[READBACK]["result"] == "stale"


def test_physical_evidence_covers_its_own_subject_only(built: tuple[Path, str]) -> None:
    """test_evidence.py:420 (evidence.py:947)."""
    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha, subject={"PN": "LMP-0004"}))
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "evidence.subject" in codes(result)


# Path rules


def scratch_entry(root: Path, manifest_sha: str) -> dict[str, Any]:
    scratch = root / "hw/.cad/objects/readback"
    scratch.parent.mkdir(parents=True)
    scratch.write_text("readback ok\n", encoding="utf-8")
    artifacts = [{"path": "hw/.cad/objects/readback", "sha256": sha256(scratch)}]
    return ledger_entry(root, manifest_sha, artifacts=artifacts)


def test_a_scratch_artifact_earns_no_credit_and_refuses_the_digest(built: tuple[Path, str]) -> None:
    """evidence.py:947-949, evidence_paths.py:135: a correctly hashed file under hw/.cad/ is scratch, not the
    record; the entry is unknown and the acceptance inventory refuses (evidence.py:1292)."""
    root, version_sha = built
    write_ledger(root, scratch_entry(root, version_sha))
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "evidence.scratch_path" in codes(result)
    assert result["acceptance"]["status"] == "refused"


def test_a_managed_artifact_named_only_in_prose_earns_no_credit(built: tuple[Path, str]) -> None:
    """evidence_paths.py:202: prose citing a record result the entry's artifacts do not list."""
    root, version_sha = built
    photo = root / "hw/captures/v1/bench/photo.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"png")
    write_ledger(root, ledger_entry(root, version_sha, note="see hw/captures/v1/bench/photo.png"))
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert "evidence.uncited_artifact" in codes(result)
    assert result["acceptance"]["status"] == "refused"


def test_an_entry_resting_on_a_refused_entry_earns_no_credit(built: tuple[Path, str]) -> None:
    """evidence.py:801-806, evidence_paths.py:238: an entry whose prose names a refused entry is unknown."""
    root, version_sha = built
    refused = scratch_entry(root, version_sha)
    reliant = ledger_entry(root, version_sha, id="EV-002", obligation=ROUTE, note="as EV-001 measured")
    reliant["level"] = "process_planned"
    write_ledger(root, refused, reliant)
    result = run(root)
    assert statuses(result)[ROUTE]["result"] == "unknown"
    assert "EV-002 rests on refused evidence EV-001" in statuses(result)[ROUTE]["reasons"]
    assert "evidence.refused_dependency" in codes(result)


def test_an_untracked_file_of_a_git_project_earns_no_credit(built: tuple[Path, str]) -> None:
    """evidence_paths.py:157: in a git work tree a cited file outside the managed locations must be
    tracked."""
    import subprocess

    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "hw/product.yaml"], check=True)
    assert statuses(run(root))[READBACK]["result"] == "unknown"
    subprocess.run(["git", "-C", str(root), "add", "hw/docs/readback.txt"], check=True)
    assert statuses(run(root))[READBACK]["result"] == "pass"


def test_a_work_tree_with_no_tracked_files_refuses_unmanaged_citations(built: tuple[Path, str]) -> None:
    """evidence_paths.py:119-159: an empty index is still a work tree, so an existing cited file outside
    the managed locations is refused, and the inventory with it."""
    import subprocess

    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert any("is not tracked by git" in f["message"] for f in result["findings"])
    assert result["acceptance"]["status"] == "refused"


def test_a_project_outside_git_applies_only_the_layout_rules(tmp_path: Path) -> None:
    """A root git confirms is no work tree checks no tracking (evidence_paths.py:117)."""
    from benchhand_core.record.evidence.path_judge import git_view

    assert git_view(tmp_path).not_worktree is True


@pytest.mark.parametrize("failure", ["unreadable index", "no git"])
def test_git_that_cannot_be_read_refuses_unmanaged_citations(
    built: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    """A git read failure is not proof of "no work tree" (the prototype reads it so, evidence_paths.py:
    123-127): an unmanaged citation is refused with its own reason, never let through."""
    import subprocess

    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "hw"], check=True)
    if failure == "unreadable index":
        (root / ".git/index").write_bytes(b"not an index")
    else:
        monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "unknown"
    assert any("cannot be checked against git" in f["message"] for f in result["findings"])


# Ledger credit: level and subject per target


def require_cad_valid(root: Path) -> str:
    """Give REQ-001 a cad_valid evidence requirement and an approved policy asking cad_valid evidence of it
    for LMP-0001, then rebuild v1; returns the new version manifest sha256."""
    requirements = yaml.safe_load((root / "hw/requirements.yaml").read_text(encoding="utf-8"))
    requirements["requirements"][0]["evidence_required"] = ["cad_valid"]
    write_yaml(root / "hw/requirements.yaml", requirements)
    product = yaml.safe_load((root / "hw/product.yaml").read_text(encoding="utf-8"))
    product["use_case"]["evidence_policy"] = {
        "obligations": [{"requirement": "REQ-001", "subject": {"PN": "LMP-0001"}, "level": "cad_valid"}],
        "decision": APPROVED,
    }
    write_yaml(root / "hw/product.yaml", product)
    return build(root)


def requirement_entry(root: Path, manifest_sha: str, subject: dict[str, Any]) -> dict[str, Any]:
    entry = ledger_entry(root, manifest_sha, subject=subject, requirement="REQ-001")
    entry.pop("obligation")
    entry["fingerprints"] = current_fingerprints(root, subject)
    return entry


@pytest.mark.parametrize(
    ("asked", "shown"),
    [
        ({"PN": "LMP-0011", "occurrence": "@ring-base"}, {"PN": "LMP-0011", "occurrence": "@ring-elbow"}),
        (
            {"PN": "LMP-0001", "feature": "seat", "region": "upper"},
            {"PN": "LMP-0001", "feature": "seat", "region": "lower"},
        ),
    ],
)
def test_evidence_of_another_occurrence_or_region_credits_nothing(
    built: tuple[Path, str], asked: dict[str, Any], shown: dict[str, Any]
) -> None:
    """An occurrence or a region is part of where a subject is: evidence of one ring placement, or of one
    region of a feature, never passes the policy obligation of another of the same part."""
    root, _ = built
    product = yaml.safe_load((root / "hw/product.yaml").read_text(encoding="utf-8"))
    product["use_case"]["evidence_policy"] = {
        "obligations": [{"subject": asked, "level": "cad_valid"}],
        "decision": APPROVED,
    }
    write_yaml(root / "hw/product.yaml", product)
    version_sha = build(root)
    [target] = [i for i in expected(root) if i.startswith("policy.cad_valid@")]
    for subject, result in ((asked, "pass"), (shown, "unknown")):
        entry = ledger_entry(root, version_sha, obligation=target, subject=subject)
        entry["fingerprints"] = current_fingerprints(root, subject)
        write_ledger(root, entry)
        found = run(root)
        assert statuses(found)[target]["result"] == result, subject
    assert "evidence.subject" in codes(found)


def write_policy(root: Path, *subjects: dict[str, Any]) -> str:
    """An approved evidence policy asking cad_valid evidence of each subject; returns the rebuilt v1's
    manifest sha256."""
    product = yaml.safe_load((root / "hw/product.yaml").read_text(encoding="utf-8"))
    rows = [{"subject": subject, "level": "cad_valid"} for subject in subjects]
    product["use_case"]["evidence_policy"] = {"obligations": rows, "decision": APPROVED}
    write_yaml(root / "hw/product.yaml", product)
    return build(root)


@pytest.mark.parametrize(
    ("first", "second", "ids"),
    [
        (
            {"PN": "LMP-0011", "occurrence": "@ring-base"},
            {"PN": "LMP-0011", "occurrence": "@ring-elbow"},
            ("policy.cad_valid@LMP-0011@ring-base", "policy.cad_valid@LMP-0011@ring-elbow"),
        ),
        (
            {"PN": "LMP-0001", "feature": "seat", "region": "upper"},
            {"PN": "LMP-0001", "feature": "seat", "region": "lower"},
            ("policy.cad_valid@LMP-0001#seat:upper", "policy.cad_valid@LMP-0001#seat:lower"),
        ),
    ],
)
def test_policy_rows_at_two_occurrences_or_regions_are_two_obligations(
    built: tuple[Path, str], first: dict[str, Any], second: dict[str, Any], ids: tuple[str, str]
) -> None:
    """Two policy rows on one part at different occurrences or regions are two obligations: evidence of
    the first passes it and leaves the second unknown. The prototype's anchor leaves both out
    (manufacturing_intent.py:2621), so it keeps the first row and drops the second."""
    root, _ = built
    version_sha = write_policy(root, first, second)
    assert {i for i in expected(root) if i.startswith("policy.cad_valid@")} == set(ids)
    entry = ledger_entry(root, version_sha, obligation=ids[0], subject=first)
    entry["fingerprints"] = current_fingerprints(root, first)
    write_ledger(root, entry)
    found = statuses(run(root))
    assert found[ids[0]]["result"] == "pass"
    assert found[ids[1]]["result"] == "unknown"


def test_an_obligation_id_naming_two_checks_credits_neither(built: tuple[Path, str]) -> None:
    """Policy rows whose subjects differ only in the requirements they serve share one id. Each check under
    it stays unknown with no credit, and a finding names the collision."""
    root, _ = built
    first = {"PN": "LMP-0001", "requirements": ["REQ-001"]}
    second = {"PN": "LMP-0001", "requirements": ["REQ-002"]}
    version_sha = write_policy(root, first, second)
    target = "policy.cad_valid@LMP-0001"
    entry = ledger_entry(root, version_sha, obligation=target, subject=first)
    entry["fingerprints"] = current_fingerprints(root, first)
    write_ledger(root, entry)
    result = run(root)
    colliding = [s for s in result["statuses"] if s["obligation"]["id"] == target]
    assert [s["obligation"]["subject"] for s in colliding] == [first, second]
    assert [s["result"] for s in colliding] == ["unknown", "unknown"]
    [finding] = [f for f in result["findings"] if f["code"] == "obligation.id_collision"]
    assert finding["subject"] == target


# A part anchor, read back by the grammar of common.tsp obligation_id.
PART_ANCHOR = re.compile(
    r"^(?P<PN>[A-Z]{2,5}-[0-9]{4})(?P<occurrence>@[a-z][a-z0-9_-]*)?(?:\.(?P<component>[a-z][a-z0-9_]*))?"
    r"(?:/(?P<operation>[a-z][a-z0-9_]*))?(?:#(?P<feature>[a-z][a-z0-9_]*)(?::(?P<region>[a-z][a-z0-9_]*))?)?$"
)


def part_subjects() -> list[dict[str, str]]:
    """Every combination of a part subject's optional segments, a region only with its feature."""
    values = {"occurrence": "@ring-base_2", "component": "hub", "operation": "print", "feature": "seat"}
    found = []
    for present in itertools.product((False, True), repeat=len(values)):
        chosen = {k: v for (k, v), on in zip(values.items(), present, strict=True) if on}
        subject = {"PN": "LMP-0011"} | chosen
        found.append(subject)
        if "feature" in subject:
            found.append(subject | {"region": "upper"})
    return found


@pytest.mark.parametrize("subject", part_subjects(), ids=lambda s: "+".join(s))
def test_a_part_anchor_reads_back_as_its_subject(subject: dict[str, str]) -> None:
    """No anchor segment's characters include a later delimiter, so the obligation id of each combination
    of a part's occurrence, component, operation, feature and region reads back as its subject."""
    from benchhand_contracts.models.record.common_schema import Obligation
    from benchhand_core.record.evidence.obligations import obligation_anchor

    anchor = obligation_anchor(subject)
    parsed = PART_ANCHOR.match(anchor)
    assert parsed is not None, anchor
    assert {k: v for k, v in parsed.groupdict().items() if v} == subject
    data = {"family": "policy.cad_valid", "subject": subject, "level": "cad_valid", "stage": "layout"}
    Obligation.model_validate(data | {"id": f"policy.cad_valid@{anchor}", "basis": "TST"})


@pytest.mark.parametrize("key", ["occurrence", "component", "operation", "feature", "region"])
def test_a_subject_name_holding_an_anchor_delimiter_is_refused(key: str) -> None:
    """A name holding a later delimiter would read back as another subject; the subject refuses it."""
    from benchhand_contracts.models.record.common_schema import Obligation
    from benchhand_core.record.evidence.obligations import obligation_anchor
    from pydantic import ValidationError

    subject = {"PN": "LMP-0011", "feature": "seat"} | {key: "@ring.base" if key == "occurrence" else "a:b"}
    data = {"family": "policy.cad_valid", "subject": subject, "level": "cad_valid", "stage": "layout"}
    ident = f"policy.cad_valid@{obligation_anchor(subject)}"
    with pytest.raises(ValidationError):
        Obligation.model_validate(data | {"id": ident, "basis": "TST"})


def test_a_policy_row_with_a_region_but_no_feature_is_refused(built: tuple[Path, str]) -> None:
    """The anchor writes a region only after its feature, so a region without one would vanish from the id.
    The record refuses such a subject (common.tsp subject dependentRequired) before any id is made."""
    root, _ = built
    write_policy(root, {"PN": "LMP-0001", "region": "upper"})
    with pytest.raises(RecordSchemaError, match="'feature' is a dependency of 'region'"):
        load_record(root)


def test_an_entry_at_another_level_credits_nothing(built: tuple[Path, str]) -> None:
    """Levels are independent facets: a cad_valid entry never passes a physically_validated obligation (a
    prototype gap, evidence.py:932-951)."""
    root, version_sha = built
    subject = {"PN": "LMP-0001", "operation": "print"}
    entry = ledger_entry(root, version_sha, obligation=TRIAL, subject=subject)
    entry["fingerprints"] = current_fingerprints(root, subject)
    write_ledger(root, entry)
    result = run(root)
    assert statuses(result)[TRIAL]["result"] == "unknown"
    assert "evidence.level" in codes(result)


def test_an_inferred_target_is_credited_only_at_its_own_location(built: tuple[Path, str]) -> None:
    """An entry for a requirement credits the requirement and policy obligations at its level only where its
    subject is the target's subject (a prototype gap, evidence.py:932-939)."""
    root, _ = built
    version_sha = require_cad_valid(root)
    write_ledger(root, requirement_entry(root, version_sha, {"PN": "LMP-0001"}))
    found = statuses(run(root))
    assert found["policy.cad_valid@LMP-0001"]["result"] == "pass"
    assert found["requirement.cad_valid@REQ-001"]["result"] == "unknown"
    write_ledger(root, requirement_entry(root, version_sha, {"PN": "LMP-0004"}))
    assert statuses(run(root))["policy.cad_valid@LMP-0001"]["result"] == "unknown"
    write_ledger(root, requirement_entry(root, version_sha, {"product": True}))
    assert statuses(run(root))["requirement.cad_valid@REQ-001"]["result"] == "pass"


def test_physical_evidence_without_its_test_credits_nothing(built: tuple[Path, str]) -> None:
    """A physically_validated pass needs the physical test fields the contract requires
    (manufacturing-evidence.tsp `physical`); an entry read leniently without them credits nothing."""
    from benchhand_core.record.evidence.ledger import EntryContext, EntryJudgement, credit

    root, _ = built
    record = load_record(root)
    expected_by_id = {o.id: o for o in required_checks(view(record)).obligations}
    placed, _ = inventory(record.assembly, record.parts)
    ctx = EntryContext(
        view(record),
        placed,
        expected_by_id,
        read_built_version(root, record, "v1", shipped_guidelines=None),
        TODAY,
    )
    entry = {"id": "EV-001", "obligation": TRIAL, "subject": {"PN": "LMP-0001", "operation": "print"}}
    entry |= {"level": "physically_validated", "result": "pass", "physical": {"specimen": "coupon 1"}}
    given = credit(entry, 0, EntryJudgement("pass", ("EV-001 pass",)), expected_by_id[TRIAL], ctx)
    assert given.result == "unknown"
    assert [f.code for f in given.findings] == ["evidence.physical_fields"]


# Route coverage


def test_an_unrecognised_route_kind_stays_unknown(lamp_arm: Path, write_packet: WritePacket) -> None:
    """contracts/record/common.tsp route_kind: a kind with no check contract reports its coverage as
    unknown, whatever a sealed packet or the ledger shows (the prototype accepts either pass)."""
    part = lamp_arm / "hw/parts/LMP-0001/part.yaml"
    text = part.read_text(encoding="utf-8")
    part.write_text(text.replace("kind: drilling", "kind: boring"), encoding="utf-8")
    version_sha = build(lamp_arm)
    coverage = "process.boring.coverage@LMP-0001/finish_holes"
    write_packet(lamp_arm, "process", packet(lamp_arm, {coverage: "pass"}), version_sha)
    entry = ledger_entry(lamp_arm, version_sha, obligation=coverage, level="process_planned")
    entry["subject"] = {"PN": "LMP-0001", "operation": "finish_holes"}
    entry["fingerprints"] = current_fingerprints(lamp_arm, entry["subject"])
    write_ledger(lamp_arm, entry)
    result = run(lamp_arm)
    assert statuses(result)[coverage]["result"] == "unknown"
    assert "evidence.uncovered_route" in codes(result)
    unexpected = [f["message"] for f in result["findings"] if f["code"] == "packet.unexpected"]
    assert any("no check contract" in message for message in unexpected)


@pytest.mark.parametrize("result", ["waived", "planned"])
def test_an_unrecognised_route_kind_is_neither_waived_nor_planned(lamp_arm: Path, result: str) -> None:
    """common.tsp route_kind: the final status of a coverage obligation with no check contract is unknown,
    whatever the evidence, also an approved waiver or a planned entry."""
    part = lamp_arm / "hw/parts/LMP-0001/part.yaml"
    part.write_text(
        part.read_text(encoding="utf-8").replace("kind: drilling", "kind: boring"), encoding="utf-8"
    )
    version_sha = build(lamp_arm)
    coverage = "process.boring.coverage@LMP-0001/finish_holes"
    subject = {"PN": "LMP-0001", "operation": "finish_holes"}
    if result == "waived":
        entry = waived_entry(lamp_arm, version_sha, coverage, subject=subject)
        entry["subject"] = subject
    else:
        entry = ledger_entry(
            lamp_arm, version_sha, obligation=coverage, level="process_planned", subject=subject
        )
        entry["result"] = "planned"
        entry["fingerprints"] = current_fingerprints(lamp_arm, subject)
    write_ledger(lamp_arm, entry)
    found = statuses(run(lamp_arm))[coverage]
    assert found["result"] == "unknown"
    assert "waiver" not in found
    assert any("no check contract" in reason for reason in found["reasons"])


# Joint temperatures


DATASHEET = {
    "kind": "datasheet",
    "reference": "TST",
    "url": "https://example.org/tst",
    "accessed": "2026-05-01",
}


def heat_set_temperature_reason(lamp_arm: Path, temperature: dict[str, Any], limit: dict[str, Any]) -> str:
    """The reason assembly.joint@op:heat_set_base_bushing shows with this use-case temperature and a
    sourced PETG service temperature limit."""
    from benchhand_core.record.evidence.assess import _part_of as part_of
    from benchhand_core.record.evidence.joints import joint_results

    record = view(load_record(lamp_arm))
    use_case = record.use_case
    environment = {**use_case["environment"], "temperature": {"status": "known", "value": temperature}}
    known = {"status": "known", "value": limit, "basis": "measured", "sources": [DATASHEET]}
    petg = {**record.materials["petg"], "properties": [{"name": "max_service_temperature", "value": known}]}
    record = replace(
        record,
        product={**record.product, "use_case": {**use_case, "environment": environment}},
        materials={**record.materials, "petg": petg},
    )
    placed, _ = inventory(load_record(lamp_arm).assembly, load_record(lamp_arm).parts)
    return joint_results(record, part_of(placed))[JOINT][1]


@pytest.mark.parametrize(
    ("temperature", "limit", "shown"),
    [
        ({"value": 40, "units": "deg_C"}, {"value": 60, "units": "deg_C"}, None),
        ({"value": 70, "units": "deg_C"}, {"value": 60, "units": "deg_C"}, "above petg"),
        ({"value": 40, "units": "mm"}, {"value": 60, "units": "deg_C"}, "use-case temperature is unknown"),
        ({"lower": 50, "upper": 10, "units": "deg_C"}, {"value": 60, "units": "deg_C"}, "is unknown"),
        ({"value": 40, "units": "deg_C"}, {"value": 60, "units": "mm"}, "is no valid temperature"),
    ],
)
def test_a_joint_temperature_needs_a_valid_temperature(
    lamp_arm: Path, temperature: dict[str, Any], limit: dict[str, Any], shown: str | None
) -> None:
    """assembly_operations.py:752, with manufacturing_intent.py:1326-1355 and 1549-1557: a use-case
    temperature or host limit whose unit is not a temperature, or an interval with reversed ends, makes the
    joint unknown; it never judges the joint."""
    reason = heat_set_temperature_reason(lamp_arm, temperature, limit)
    if shown is None:
        assert "temperature" not in reason
    else:
        assert shown in reason


# Waivers


def test_a_valid_waiver_stays_waived_never_pass(built: tuple[Path, str]) -> None:
    """test_evidence.py:446 (evidence.py:351, 262)."""
    root, version_sha = built
    write_ledger(root, waived_entry(root, version_sha, ROUTE))
    found = statuses(run(root))[ROUTE]
    assert found["result"] == "waived"
    assert found["waiver"]["decision"] == APPROVED


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"decision": "DR-999"}, "waiver.unapproved"),
        ({"decision": "DR-003"}, "waiver.unapproved"),
        ({"valid_until": "2026-05-31"}, "waiver.expired"),
        ({"subject": {"PN": "LMP-0004"}}, "waiver.scope"),
        ({"obligation": READBACK}, "waiver.scope"),
    ],
)
def test_an_unapproved_expired_or_misscoped_waiver_counts_as_nothing(
    built: tuple[Path, str], fields: dict[str, Any], code: str
) -> None:
    """test_evidence.py:453 (evidence.py:351-372): DR-003 exists but does not approve."""
    root, version_sha = built
    write_ledger(root, waived_entry(root, version_sha, ROUTE, **fields))
    result = run(root)
    assert statuses(result)[ROUTE]["result"] == "unknown"
    assert code in codes(result)


def test_a_waiver_is_judged_against_the_injected_today(built: tuple[Path, str]) -> None:
    """evidence.py:357: valid_until against `today`, never the clock."""
    root, version_sha = built
    write_ledger(root, waived_entry(root, version_sha, ROUTE, valid_until="2026-06-01"))
    assert statuses(run(root, today=date(2026, 6, 1)))[ROUTE]["result"] == "waived"
    assert statuses(run(root, today=date(2026, 6, 2)))[ROUTE]["result"] == "unknown"


def test_geometry_integrity_cannot_be_waived(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """test_evidence.py:470 (evidence.py:362): a cad.* failure stands under any waiver."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "fail"}), version_sha)
    write_ledger(root, waived_entry(root, version_sha, READBACK))
    result = run(root)
    assert statuses(result)[READBACK]["result"] == "fail"
    assert "waiver.forbidden" in codes(result)


@pytest.mark.parametrize(
    "requirement",
    [
        {"waiver_policy": "forbidden"},
        {"risk": {"severity": "critical", "consequence": "TST"}},
    ],
)
def test_a_governing_requirement_cannot_be_waived(lamp_arm: Path, requirement: dict[str, Any]) -> None:
    """test_evidence.py:470 (evidence.py:340-372, `_requirement_problem`)."""
    from benchhand_core.record.evidence.waivers import WaiverScope, waiver_problem

    record = view(load_record(lamp_arm))
    governing = {"id": "REQ-901", "priority": "must", **requirement}
    record = replace(record, requirements={**record.requirements, "REQ-901": governing})
    scope = WaiverScope(
        subject={"PN": "LMP-0001"},
        obligation=ROUTE,
        family="route.consistency",
        obligation_requirements=("REQ-901",),
    )
    problem = waiver_problem(waiver(), scope, record, TODAY)
    assert problem is not None and problem.code == "waiver.forbidden"


def test_a_mandatory_requirement_of_a_safety_critical_use_case_cannot_be_waived(lamp_arm: Path) -> None:
    """evidence.py:369: under a safety_critical service class a must requirement governs."""
    from benchhand_core.record.evidence.waivers import WaiverScope, waiver_problem

    record = view(load_record(lamp_arm))
    use_case = {**record.use_case, "service_class": {"status": "known", "value": "safety_critical"}}
    record = replace(
        record,
        product={**record.product, "use_case": use_case},
        requirements={**record.requirements, "REQ-901": {"id": "REQ-901", "priority": "must"}},
    )
    scope = WaiverScope(
        subject={"PN": "LMP-0001"},
        obligation=ROUTE,
        family="route.consistency",
        obligation_requirements=("REQ-901",),
    )
    assert waiver_problem(waiver(), scope, record, TODAY).code == "waiver.forbidden"  # type: ignore[union-attr]
    critical = WaiverScope(subject={"PN": "LMP-0001"}, critical=True)
    assert waiver_problem(waiver(), critical, record, TODAY).code == "waiver.forbidden"  # type: ignore[union-attr]


def test_a_waiver_checks_the_requirements_of_its_target(built: tuple[Path, str]) -> None:
    """evidence.py:340-348: the requirements that govern a waived target come from the obligation's subject,
    not the entry's. A policy obligation for LMP-0001 under REQ-002, which forbids waivers, stays unwaived
    when the waiving entry names the part alone."""
    root, _ = built
    requirements = yaml.safe_load((root / "hw/requirements.yaml").read_text(encoding="utf-8"))
    requirements["requirements"][1]["waiver_policy"] = "forbidden"
    write_yaml(root / "hw/requirements.yaml", requirements)
    product = yaml.safe_load((root / "hw/product.yaml").read_text(encoding="utf-8"))
    policy_subject = {"PN": "LMP-0001", "requirements": ["REQ-002"]}
    product["use_case"]["evidence_policy"] = {
        "obligations": [{"subject": policy_subject, "level": "process_planned"}],
        "decision": APPROVED,
    }
    write_yaml(root / "hw/product.yaml", product)
    version_sha = build(root)
    target = "policy.process_planned@LMP-0001"
    write_ledger(root, waived_entry(root, version_sha, target))
    result = run(root)
    assert statuses(result)[target]["result"] == "unknown"
    assert "waiver.forbidden" in codes(result)


# Facets and the acceptance digest


def test_levels_are_independent_facets(built: tuple[Path, str], write_packet: WritePacket) -> None:
    """evidence.py:1047: each level is its own facet; a cad_valid pass shows nothing at another level."""
    root, version_sha = built
    write_packet(root, "cad", packet(root, {READBACK: "pass", ROUTE: "fail"}), version_sha)
    facet = run(root)["facets"]["LMP-0001"]
    assert facet["process_planned"] == "fail"
    assert facet["simulation_supported"] == "not_required"
    assert facet["physically_validated"] == "unknown"


def test_a_verification_csv_pass_is_not_evidence(built: tuple[Path, str]) -> None:
    """test_evidence.py:285 (evidence.py:1069): REQ-001 stated pass with no evidence behind it."""
    root, _ = built
    csv = root / "hw/verification.csv"
    rows = csv.read_text(encoding="utf-8").splitlines()
    rows[1] = rows[1].replace(",planned,", ",pass,")
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert "evidence.csv_unsupported" in codes(run(root))


def test_the_acceptance_digest_covers_the_ledger_and_its_citations(built: tuple[Path, str]) -> None:
    """evidence.py:1283-1323: the ledger, cited artifacts and sources are inventoried; a byte change of any
    changes evidence_sha256."""
    root, version_sha = built
    write_ledger(root, ledger_entry(root, version_sha))
    first = run(root)["acceptance"]
    assert first["status"] == "formed"
    assert {"hw/manufacturing/evidence.yaml", "hw/docs/readback.txt"} <= set(first["inventory"])
    (root / "hw/docs/readback.txt").write_text("edited\n", encoding="utf-8")
    assert run(root)["acceptance"]["evidence_sha256"] != first["evidence_sha256"]


def test_a_link_in_the_sources_refuses_the_digest(built: tuple[Path, str]) -> None:
    """evidence.py:1261: the inventory refuses a symbolic link."""
    root, _ = built
    sources = root / "hw/manufacturing/sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "datasheet.pdf").symlink_to(root / "hw/product.yaml")
    acceptance = run(root)["acceptance"]
    assert acceptance["status"] == "refused"
    assert "symbolic link" in acceptance["reason"]


@pytest.mark.parametrize("linked", ["hw/manufacturing/sources", "hw/manufacturing/findings.yaml"])
def test_a_linked_ledger_file_or_empty_sources_root_refuses_the_digest(
    built: tuple[Path, str], tmp_path: Path, linked: str
) -> None:
    """evidence.py:1306-1307, 1261: a linked sources root, even an empty one, and a linked ledger file refuse
    the inventory; neither may silently drop out of it."""
    root, _ = built
    target = tmp_path / "elsewhere"
    if linked.endswith(".yaml"):
        target.write_text("dispositions: []\n", encoding="utf-8")
    else:
        target.mkdir()
    (root / linked).parent.mkdir(parents=True, exist_ok=True)
    (root / linked).symlink_to(target)
    acceptance = run(root)["acceptance"]
    assert acceptance["status"] == "refused"
    assert f"{linked} lies behind or is a symbolic link" in acceptance["reason"]
