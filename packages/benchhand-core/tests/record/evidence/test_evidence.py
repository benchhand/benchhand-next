"""The evidence service on a built lamp-arm version (record_version 3, converted from the prototype).

Each test cites the prototype rule it ports: skills/cad-record/scripts/evidence.py, impact.py,
manufacturing_intent.py or assembly_operations.py at release.toml reference_commit 412b5d9, and the
prototype test (reference/skills/cad-record/tests/test_evidence.py) it is ported from.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.assess import assess
from benchhand_core.record.evidence.built import NotComputed
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


def run(root: Path, today: date = TODAY) -> dict[str, Any]:
    record = load_record(root)
    built = read_built_version(root, record, "v1")
    return assess(record, built, today).model_dump(mode="json", by_alias=True, exclude_none=True)


def statuses(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {status["obligation"]["id"]: status for status in result["statuses"]}


def codes(result: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in result["findings"]}


def expected(root: Path) -> dict[str, dict[str, Any]]:
    return {o.id: as_json(o) for o in required_checks(view(load_record(root)))}


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


def current_fingerprints(root: Path, subject: dict[str, Any]) -> dict[str, str]:
    record = load_record(root)
    built = read_built_version(root, record, "v1")
    placed, _ = inventory(record.assembly, record.parts)
    return fp.fingerprints(view(record), placed, subject, built.current_geometry)


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
    ours = [as_json(o) for o in required_checks(view(load_record(lamp_arm)))]
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
        read_built_version(root, load_record(root), "v1")


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
    built_version = replace(read_built_version(root, record, "v1"), staleness=NotComputed("TST"))
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
    built_version = read_built_version(root, load_record(root), "v1")
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
        read_built_version(root, load_record(root), "v1")


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
    expected_by_id = {o.id: o for o in required_checks(view(record))}
    placed, _ = inventory(record.assembly, record.parts)
    ctx = EntryContext(view(record), placed, expected_by_id, read_built_version(root, record, "v1"), TODAY)
    entry = {"id": "EV-001", "obligation": TRIAL, "subject": {"PN": "LMP-0001", "operation": "print"}}
    entry |= {"level": "physically_validated", "result": "pass", "physical": {"specimen": "coupon 1"}}
    given = credit(entry, 0, EntryJudgement("pass", ("EV-001 pass",)), expected_by_id[TRIAL], ctx)
    assert given.result == "unknown"
    assert [f.code for f in given.findings] == ["evidence.physical_fields"]


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
