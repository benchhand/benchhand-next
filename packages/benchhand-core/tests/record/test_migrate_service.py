"""migrate() and undo(): the dry run, apply in place behind a preimage backup and a lock, refusals, stopped
applies and their --resume or --undo, on copies of the reference records."""

from __future__ import annotations

import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from benchhand_core.record.migrate import MigrationStatus, migrate, recovery, service, undo
from benchhand_core.record.migrate.inventory import LOCK_NAME, OWNER_NAME, TEMP_SUFFIX
from benchhand_core.record.store import load_record
from benchhand_core.record.validate import validate

from .conftest import LAMP_ARM_HW, TEMPLATE_HW

LAMP_ARM_CHANGES = 10  # the files a lamp-arm migration changes
OWN = (LOCK_NAME, OWNER_NAME)  # the service's files under hw/


def _tree(hw: Path) -> dict[str, bytes]:
    """Every entry under `hw` (files by content, directories as <dir>)."""
    return {
        path.relative_to(hw).as_posix(): (path.read_bytes() if path.is_file() else b"<dir>")
        for path in sorted(hw.rglob("*"))
    }


def _copy(source: Path, root: Path) -> Path:
    shutil.copytree(source, root / "hw")
    return root


def _codes(findings: tuple) -> list[str]:  # type: ignore[type-arg]
    return [finding.code for finding in findings]


def _backups(root: Path) -> list[Path]:
    return sorted((root / recovery.BACKUPS).iterdir()) if (root / recovery.BACKUPS).exists() else []


@pytest.mark.parametrize("source", [LAMP_ARM_HW, TEMPLATE_HW], ids=["lamp-arm", "template"])
def test_a_reference_record_migrates_and_validates_with_no_findings(source: Path, tmp_path: Path) -> None:
    root = _copy(source, tmp_path)
    plan = migrate(root)
    assert plan.status == MigrationStatus.ready
    assert (plan.findings, plan.remaining) == ((), ())
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied, result.refusals
    assert result.written[-1] == "hw/product.yaml"
    assert result.backup is not None and result.recovery == f"benchhand record migrate --undo {result.backup}"
    assert _codes(result.findings) == ["migrate.backup_written"]
    assert validate(root) == []
    load_record(root)
    assert not (root / "hw" / LOCK_NAME).exists()


def test_the_dry_run_writes_nothing_and_states_each_change_as_a_diff(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(tmp_path)
    plan = migrate(root)
    assert _tree(tmp_path) == before
    product = next(change for change in plan.changes if change.path == "hw/product.yaml")
    assert product.rules == ("record-version", "human-approval")
    diff = product.diff()
    assert diff.startswith("--- a/hw/product.yaml\n+++ b/hw/product.yaml\n")
    assert "-record_version: 2\n+record_version: 3\n" in diff


def test_apply_writes_exactly_the_planned_text_and_leaves_every_other_file_byte_identical(
    tmp_path: Path,
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    plan = migrate(root)
    migrate(root, apply=True)
    after = _tree(root / "hw")
    changed = {change.path.removeprefix("hw/"): change.after.encode("utf-8") for change in plan.changes}
    assert after.keys() == before.keys()
    for path, content in after.items():
        assert content == changed.get(path, before[path]), path


def test_the_backup_holds_the_preimages_of_the_changed_files_with_a_manifest(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    plan = migrate(root)
    result = migrate(root, apply=True)
    assert result.backup is not None and result.backup.parent == root / recovery.BACKUPS
    assert (result.backup / recovery.COMPLETE).is_file()
    preimages = _tree(result.backup / "hw")
    changed = {change.path.removeprefix("hw/") for change in plan.changes}
    assert {path for path, data in preimages.items() if data != b"<dir>"} == changed
    assert all(preimages[path] == before[path] for path in changed)
    manifest = json.loads((result.backup / recovery.MANIFEST).read_text())
    assert {entry["path"]: entry["sha256"] for entry in manifest["files"]} == {
        path: recovery.sha256(before[path]) for path in changed
    }


def test_undo_puts_back_exactly_the_record_as_it_was_junk_and_all(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    (root / "hw" / ".DS_Store").write_bytes(b"\x00junk")
    (root / "hw" / "notes.md").write_text("never committed anywhere\n")
    before = _tree(root / "hw")
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied and result.backup is not None
    undone = undo(result.backup)
    assert undone.status == MigrationStatus.undone, undone.refusals
    assert undone.written[0] == "hw/product.yaml" and len(undone.written) == LAMP_ARM_CHANGES
    assert _tree(root / "hw") == before
    assert undo(result.backup).written == ()  # a second undo has nothing left to put back


def test_undo_leaves_a_file_something_else_changed_and_reports_it(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    result = migrate(root, apply=True)
    assert result.backup is not None
    (root / "hw" / "bom.csv").write_text("edited after the migration\n")
    undone = undo(result.backup)
    assert undone.status == MigrationStatus.undone
    [skipped] = undone.findings
    assert (skipped.code, skipped.path) == ("migrate.undo_skipped", "hw/bom.csv")
    assert str(result.backup / "hw" / "bom.csv") in (skipped.action or "")
    assert (root / "hw" / "bom.csv").read_text() == "edited after the migration\n"
    assert {path: data for path, data in _tree(root / "hw").items() if path != "bom.csv"} == {
        path: data for path, data in before.items() if path != "bom.csv"
    }


def test_undo_refuses_a_backup_that_is_incomplete_or_does_not_match_its_manifest(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    result = migrate(root, apply=True)
    assert result.backup is not None
    after = _tree(root / "hw")
    (result.backup / "hw" / "bom.csv").write_text("damaged\n")
    assert _codes(undo(result.backup).refusals) == ["migrate.backup_unusable"]
    (result.backup / recovery.COMPLETE).unlink()
    assert _codes(undo(result.backup).refusals) == ["migrate.backup_incomplete"]
    assert _codes(undo(tmp_path / "elsewhere").refusals) == ["migrate.backup_unusable"]
    assert _tree(root / "hw") == after


def test_migrating_a_record_version_3_record_is_a_no_op_that_still_validates(lamp_arm: Path) -> None:
    before = _tree(lamp_arm)
    for apply in (False, True):
        result = migrate(lamp_arm, apply=apply)
        assert result.status == MigrationStatus.current
        assert _codes(result.findings) == ["migrate.current"]
        assert result.remaining == ()
    assert _tree(lamp_arm) == before
    (lamp_arm / "hw" / "bom.csv").write_text("level,PN\n")
    assert migrate(lamp_arm).refusals  # a broken record_version 3 record is reported, not called fine


def test_prototype_pr_319_record_version_1_migrates_as_version_2(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    product.write_text(product.read_text().replace("record_version: 2", "record_version: 1", 1))
    assert migrate(root, apply=True).status == MigrationStatus.applied
    assert validate(root) == []


@pytest.mark.parametrize("value", ["7", "'2'", "true", None])
def test_an_unknown_record_version_is_refused_and_nothing_changes(tmp_path: Path, value: str | None) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    replacement = "" if value is None else f"record_version: {value}\n"
    product.write_text(product.read_text().replace("record_version: 2\n", replacement, 1))
    before = _tree(tmp_path)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.refused
    [refusal] = result.refusals
    assert (refusal.code, refusal.path, refusal.pointer) == (
        "record.version_unsupported",
        "hw/product.yaml",
        "/record_version",
    )
    assert refusal.action
    assert _tree(tmp_path) == before


def test_a_deprecated_decision_is_refused_in_the_dry_run_and_apply_writes_nothing(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    decision = next((root / "hw" / "decisions").glob("DR-001-*.md"))
    decision.write_text(decision.read_text().replace("status: accepted", "status: deprecated", 1))
    before = _tree(tmp_path)
    for apply in (False, True):
        result = migrate(root, apply=apply)
        assert result.status == MigrationStatus.refused
        [refusal] = result.refusals
        assert (refusal.code, refusal.path, refusal.pointer) == (
            "migrate.deprecated_status",
            f"hw/decisions/{decision.name}",
            "/status",
        )
        assert "accepted, rejected, or superseded" in (refusal.action or "")
    assert _tree(tmp_path) == before


def test_human_approval_key_is_reported_because_those_gates_now_ask(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    text = product.read_text()
    assert 'human_approval: "all"' in text
    product.write_text(text.replace('human_approval: "all"', 'human_approval: "key"', 1))
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied
    [note] = [finding for finding in result.findings if finding.code == "migrate.gates_now_ask"]
    assert (note.severity.value, note.pointer) == ("info", "/flow/profile/human_approval")
    assert "hw/policy.yaml" in (note.action or "")
    assert not (root / "hw" / "policy.yaml").exists()
    assert "human_approval" not in product.read_text()


def test_os_and_tool_junk_is_never_read_or_rewritten(tmp_path: Path) -> None:
    """Junk made unreadable would fail the run if anything read it or listed its directory."""
    root = _copy(LAMP_ARM_HW, tmp_path)
    junk = {
        "hw/.DS_Store": b"\x00\x01binary",
        "hw/decisions/._DR-001-three-link-revolute-lamp-arm-layout.md": b"\x00\x05\x16\x07AppleDouble",
        "hw/decisions/.DR-003-press-fit-pivot-pins.md.swp": b"b0VIM",
        "hw/__pycache__/x.cpython-312.pyc": b"\x00\xff",
        "hw/Thumbs.db": b"\xd0\xcf",
    }
    for path, content in junk.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
    for path in junk:
        os.chmod(root / path, 0)
    os.chmod(root / "hw" / "__pycache__", 0)
    try:
        plan = migrate(root)
        assert plan.status == MigrationStatus.ready, plan.refusals
        assert len(plan.changes) == LAMP_ARM_CHANGES
        result = migrate(root, apply=True)
        assert result.status == MigrationStatus.applied, result.refusals
    finally:
        os.chmod(root / "hw" / "__pycache__", 0o755)
        for path in junk:
            os.chmod(root / path, 0o644)
    assert {path: (root / path).read_bytes() for path in junk} == junk
    assert validate(root) == []


def test_a_directory_that_cannot_be_listed_refuses_the_record(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    hidden = root / "hw" / "renders"
    hidden.mkdir()
    os.chmod(hidden, 0)
    try:
        for apply in (False, True):
            result = migrate(root, apply=apply)
            assert result.status == MigrationStatus.refused
            assert _codes(result.refusals) == ["migrate.scan_failed"]
            assert result.refusals[0].path == "hw/renders"
    finally:
        os.chmod(hidden, 0o755)
    assert _backups(root) == [] and not (root / "hw" / LOCK_NAME).exists()


def test_sealed_history_stays_byte_identical(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    hw = root / "hw"
    sealed = ["versions/v1/hw/product.yaml", "checks/v1/verification.csv", "releases/A/hw/bom.csv"]
    sources = ["product.yaml", "verification.csv", "bom.csv"]
    for path, source in zip(sealed, sources, strict=True):
        (hw / path).parent.mkdir(parents=True)
        shutil.copy(hw / source, hw / path)
    shutil.copytree(hw / "decisions", hw / "versions" / "v1" / "hw" / "decisions")
    history = ("versions", "checks", "releases")
    before = {path: data for path, data in _tree(hw).items() if path.split("/")[0] in history}
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied, result.refusals
    assert not [change for change in result.changes if change.path.split("/")[1] in history]
    assert {path: data for path, data in _tree(hw).items() if path in before} == before


@pytest.mark.parametrize("ledger_converted", [False, True], ids=["ledger-changes", "no-ledger-change"])
def test_a_frozen_prototype_record_is_always_refused(tmp_path: Path, ledger_converted: bool) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    if ledger_converted:  # the verification ledger already in its version 3 form: no rule changes a ledger
        planned = next(change for change in migrate(root).changes if change.path == "hw/verification.csv")
        (root / planned.path).write_text(planned.after)
        assert "hw/verification.csv" not in [change.path for change in migrate(root).changes]
    product = root / "hw" / "product.yaml"
    text = product.read_text()
    product.write_text(text.replace("flow:\n", "flow:\n  frozen: {version: v1, evidence_sha256: abc}\n", 1))
    before = _tree(tmp_path)
    for apply in (False, True):
        result = migrate(root, apply=apply)
        assert result.status == MigrationStatus.refused
        [refusal] = result.refusals
        assert (refusal.code, refusal.pointer) == ("migrate.frozen_anchor", "/flow/frozen")
        assert "Phase 2" in (refusal.action or "")
    assert _tree(tmp_path) == before


def test_a_symlink_leaving_the_project_refuses_before_any_file_is_read(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    (tmp_path / "outside.md").write_text("outside\n")
    (root / "README.md").write_text("inside\n")
    (root / "hw" / "inside.md").symlink_to("../README.md")
    assert migrate(root).status == MigrationStatus.ready
    (root / "hw" / "outside.md").symlink_to(tmp_path / "outside.md")
    os.chmod(root / "hw" / "bom.csv", 0)  # a rule target that would fail the run if it were read
    try:
        for apply in (False, True):
            result = migrate(root, apply=apply)
            assert result.status == MigrationStatus.refused
            [refusal] = result.refusals
            assert (refusal.code, refusal.path) == ("migrate.symlink_outside", "hw/outside.md")
    finally:
        os.chmod(root / "hw" / "bom.csv", 0o644)
    assert _backups(root) == []


def test_a_symbolic_link_to_a_directory_is_refused(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    (root / "docs").mkdir()
    (root / "docs" / "escape.md").symlink_to(tmp_path)  # a nested link a walk through it would meet
    (root / "hw" / "linked-docs").symlink_to("../docs")
    for apply in (False, True):
        result = migrate(root, apply=apply)
        assert [(finding.code, finding.path) for finding in result.refusals] == [
            ("migrate.unsupported_layout", "hw/linked-docs")
        ]


def test_a_symlinked_hw_is_refused_before_anything_is_read_or_locked(tmp_path: Path) -> None:
    other = _copy(LAMP_ARM_HW, tmp_path / "other")
    root = tmp_path / "project"
    root.mkdir()
    (root / "hw").symlink_to(other / "hw")
    before = _tree(other / "hw")
    for apply in (False, True):
        result = migrate(root, apply=apply)
        assert _codes(result.refusals) == ["migrate.symlink_hw"]
    assert _tree(other / "hw") == before
    assert not (root / ".benchhand").exists()


def test_a_crlf_csv_keeps_its_line_endings_and_data_rows(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    bom = root / "hw" / "bom.csv"
    crlf = bom.read_bytes().replace(b"\n", b"\r\n")
    bom.write_bytes(crlf)
    migrate(root, apply=True)
    header, rest = crlf.split(b"\r\n", 1)
    migrated_header, migrated_rest = bom.read_bytes().split(b"\r\n", 1)
    assert migrated_rest == rest
    assert migrated_header == header.replace(b"specification_ref", b"specification_reference").replace(
        b"specification_rev", b"specification_revision"
    )


def test_a_held_lock_refuses_and_a_lock_that_cannot_be_removed_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    lock = root / "hw" / LOCK_NAME
    lock.write_text("pid 1\n")
    before = _tree(root / "hw")
    for apply in (False, True):
        result = migrate(root, apply=apply)
        assert _codes(result.refusals) == ["migrate.locked"]
        assert f"delete hw/{LOCK_NAME}" in (result.refusals[0].action or "")
    assert _tree(root / "hw") == before
    lock.unlink()

    def stuck(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", stuck)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied
    assert "migrate.cleanup_failed" in _codes(result.findings)


def test_resume_without_a_stopped_migration_is_refused(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    assert _codes(migrate(root, apply=True, resume=True).refusals) == ["migrate.not_interrupted"]


def test_a_file_changed_after_the_plan_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    real_checked = service._checked

    def plan_then_edit(*args: object) -> object:
        planned = real_checked(*args)  # type: ignore[arg-type]
        (root / "hw" / "bom.csv").write_text("edited meanwhile\n")
        return planned

    monkeypatch.setattr(service, "_checked", plan_then_edit)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.failed
    [refusal] = result.refusals
    assert (refusal.code, refusal.path) == ("migrate.changed_meanwhile", "hw/bom.csv")
    assert result.recovery is not None and result.recovery in (refusal.action or "")
    assert "--resume" in (refusal.action or "")
    assert (root / "hw" / "bom.csv").read_text() == "edited meanwhile\n"
    assert result.written == ()
    monkeypatch.undo()
    assert result.backup is not None
    undone = undo(result.backup)
    assert _codes(undone.findings) == ["migrate.undo_skipped"]
    assert _tree(root / "hw") == {**before, "bom.csv": b"edited meanwhile\n"}


def test_a_target_changed_after_its_temp_file_is_synced_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-hash sits after the temp file's sync, just before the rename."""
    root = _copy(LAMP_ARM_HW, tmp_path)
    real_chmod = os.chmod

    def edit_on_temp_chmod(path: str | Path, mode: int, **kwargs: object) -> None:
        real_chmod(path, mode, **kwargs)  # type: ignore[arg-type]
        if str(path).endswith(TEMP_SUFFIX) and ".bom.csv." in str(path):
            (root / "hw" / "bom.csv").write_text("edited during the write\n")

    monkeypatch.setattr(recovery.os, "chmod", edit_on_temp_chmod)
    result = migrate(root, apply=True)
    monkeypatch.undo()
    assert _codes(result.refusals) == ["migrate.changed_meanwhile"]
    assert (root / "hw" / "bom.csv").read_text() == "edited during the write\n"
    assert not list((root / "hw").rglob(f"*{TEMP_SUFFIX}"))


def test_a_file_added_after_the_plan_refuses_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    real_checked = service._checked

    def plan_then_add(*args: object) -> object:
        planned = real_checked(*args)  # type: ignore[arg-type]
        (root / "hw" / "added.md").write_text("new\n")
        return planned

    monkeypatch.setattr(service, "_checked", plan_then_add)
    before = _tree(root / "hw")
    result = migrate(root, apply=True)
    assert _codes(result.refusals) == ["migrate.changed_meanwhile"]
    assert result.written == ()
    assert {path: data for path, data in _tree(root / "hw").items() if path != LOCK_NAME} == {
        **before,
        "added.md": b"new\n",
    }


def _clean_run(tmp_path: Path) -> dict[str, bytes]:
    root = _copy(LAMP_ARM_HW, tmp_path / "clean")
    assert migrate(root, apply=True).status == MigrationStatus.applied
    return _tree(root / "hw")


class _Crash(BaseException):
    """The process dying mid-apply: nothing in the service catches it."""


def _crash_after(root: Path, monkeypatch: pytest.MonkeyPatch, stop_after: int) -> None:
    """Run an apply that dies after writing `stop_after` files, leaving its lock."""
    real_write = recovery.write_durably
    written: list[Path] = []

    def crash_after(target: Path, data: bytes, expected: str) -> None:
        if len(written) == stop_after:
            raise _Crash
        real_write(target, data, expected)
        written.append(target)

    monkeypatch.setattr(recovery, "write_durably", crash_after)
    with pytest.raises(_Crash):
        migrate(root, apply=True)
    monkeypatch.undo()
    assert len(written) == stop_after


@pytest.mark.parametrize("stop_after", [0, 1, 4, 9])
def test_resume_after_a_stopped_apply_finishes_it_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_after: int
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "crashed")
    _crash_after(root, monkeypatch, stop_after)
    [refusal] = migrate(root, apply=True).refusals
    assert refusal.code == "migrate.locked"
    assert "--resume" in (refusal.action or "") and "--undo" in (refusal.action or "")
    rerun = migrate(root, apply=True, resume=True)
    assert rerun.status == MigrationStatus.applied, rerun.refusals
    assert len(rerun.written) == LAMP_ARM_CHANGES - stop_after
    assert _tree(root / "hw") == expected
    assert len(_backups(root)) == 1  # no second backup of a partly migrated tree
    assert not list((root / "hw").rglob(f"*{TEMP_SUFFIX}"))


@pytest.mark.parametrize("stop_after", [0, 1, 4, 9])
def test_undo_after_a_stopped_apply_puts_the_record_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_after: int
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    before = _tree(root / "hw")
    _crash_after(root, monkeypatch, stop_after)
    [backup] = _backups(root)
    (tmp_path / "alias").symlink_to(root)  # the backup named through another spelling of the project's path
    undone = undo(tmp_path / "alias" / backup.relative_to(root))
    assert undone.status == MigrationStatus.undone, undone.refusals
    assert len(undone.written) == stop_after
    assert _tree(root / "hw") == before  # the lock is gone too


def test_a_stop_after_the_last_write_is_resumed_or_undone_from_record_version_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _clean_run(tmp_path)
    before = _tree(_copy(LAMP_ARM_HW, tmp_path / "original") / "hw")
    real_validate = service.validate
    for finish in ("resume", "undo"):
        root = _copy(LAMP_ARM_HW, tmp_path / finish)

        def crash_on_final_validation(where: Path, root: Path = root) -> object:
            if where == root:
                raise _Crash
            return real_validate(where)

        monkeypatch.setattr(service, "validate", crash_on_final_validation)
        with pytest.raises(_Crash):
            migrate(root, apply=True)
        monkeypatch.undo()
        assert _codes(migrate(root).refusals) == ["migrate.locked"]  # not `current` while a lock is held
        if finish == "resume":
            result = migrate(root, apply=True, resume=True)
            assert (result.status, result.written) == (MigrationStatus.applied, ())
            assert _tree(root / "hw") == expected
        else:
            [backup] = _backups(root)
            assert undo(backup).status == MigrationStatus.undone
            assert _tree(root / "hw") == before


def _crash_publishing_complete(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run an apply killed while it publishes COMPLETE: after the marker's temp file is synced, before its
    rename. A killed process removes neither its lock nor its owner file."""
    real_replace = os.replace

    def crash_on_complete(source: str | Path, target: str | Path) -> None:
        if Path(target).name == recovery.COMPLETE:
            raise _Crash
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", crash_on_complete)
    monkeypatch.setattr(recovery, "clear_lock", lambda root: None)
    monkeypatch.setattr(recovery, "release_owner", lambda owner: None)
    with pytest.raises(_Crash):
        migrate(root, apply=True)
    monkeypatch.undo()


def test_a_stop_while_publishing_complete_wrote_nothing_and_resume_backs_up_again_beside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "crashed")
    before = _tree(root / "hw")
    _crash_publishing_complete(root, monkeypatch)
    assert {path: data for path, data in _tree(root / "hw").items() if path not in OWN} == before
    [unfinished] = _backups(root)
    kept = _tree(unfinished)
    assert not recovery.is_complete(unfinished)
    # the killed process still owns the record until its owner file is removed by hand
    [owned] = migrate(root, apply=True, resume=True).refusals
    assert (owned.code, owned.path) == ("migrate.locked", f"hw/{OWNER_NAME}")
    assert f"delete hw/{OWNER_NAME}" in (owned.action or "")
    (root / "hw" / OWNER_NAME).unlink()
    assert _codes(undo(unfinished).refusals) == ["migrate.backup_incomplete"]
    assert "wrote nothing" in (migrate(root, apply=True).refusals[0].action or "")
    resumed = migrate(root, apply=True, resume=True)
    assert resumed.status == MigrationStatus.applied, resumed.refusals
    assert _codes(resumed.findings)[0] == "migrate.backup_abandoned"
    assert _tree(root / "hw") == expected
    first, second = _backups(root)
    assert first == unfinished and resumed.backup == second and recovery.is_complete(second)
    assert _tree(unfinished) == {**kept, recovery.ABANDONED: _tree(unfinished)[recovery.ABANDONED]}


def test_a_resume_of_an_unfinished_backup_on_a_record_already_at_version_3_marks_it_abandoned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    _crash_publishing_complete(root, monkeypatch)
    (root / "hw" / OWNER_NAME).unlink()
    [unfinished] = _backups(root)
    product = root / "hw" / "product.yaml"
    assert "record_version: 2\n" in product.read_text()
    product.write_text(product.read_text().replace("record_version: 2\n", "record_version: 3\n"))
    result = migrate(root, apply=True, resume=True)
    assert result.status == MigrationStatus.current
    assert _codes(result.findings)[:2] == ["migrate.backup_abandoned", "migrate.current"]
    assert (unfinished / recovery.ABANDONED).is_file()
    assert recovery.read_lock(root) is None and _backups(root) == [unfinished]  # none deleted, none new


def test_a_complete_marker_that_does_not_hold_the_manifest_hash_is_not_complete(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    result = migrate(root, apply=True)
    assert result.backup is not None
    marker = result.backup / recovery.COMPLETE
    assert marker.read_text().strip() == recovery.sha256((result.backup / recovery.MANIFEST).read_bytes())
    for text in ("", "complete\n"):
        marker.write_text(text)
        assert not recovery.is_complete(result.backup)
        assert _codes(undo(result.backup).refusals) == ["migrate.backup_incomplete"]


def test_two_resumes_race_and_exactly_one_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "crashed")
    _crash_after(root, monkeypatch, 1)
    real_acquire = recovery.acquire_owner
    both_ready = threading.Barrier(2)
    loser_tried = threading.Event()

    def acquire_together(where: Path) -> object:
        both_ready.wait(timeout=30)  # both have checked the stale lock; now both try to own the record
        owner = real_acquire(where)
        if isinstance(owner, Path):
            assert loser_tried.wait(timeout=30)  # the winner owns the record while the loser tries
        else:
            loser_tried.set()
        return owner

    monkeypatch.setattr(recovery, "acquire_owner", acquire_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: migrate(root, apply=True, resume=True), range(2)))
    monkeypatch.undo()
    statuses = sorted(result.status.value for result in results)
    assert statuses == ["applied", "refused"]
    [loser] = [result for result in results if result.status == MigrationStatus.refused]
    assert [(f.code, f.path) for f in loser.refusals] == [("migrate.locked", f"hw/{OWNER_NAME}")]
    assert loser.written == ()
    assert _tree(root / "hw") == expected
    assert len(_backups(root)) == 1


@pytest.mark.parametrize("stop", ["after-complete", "before-complete"])
def test_a_linked_backup_directory_is_refused_by_resume_and_undo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    if stop == "after-complete":
        _crash_after(root, monkeypatch, 1)
    else:
        _crash_publishing_complete(root, monkeypatch)
        (root / "hw" / OWNER_NAME).unlink()
    [backup] = _backups(root)
    moved = tmp_path / "elsewhere"
    shutil.move(root / recovery.BACKUPS, moved)
    (root / recovery.BACKUPS).symlink_to(moved)
    hw, elsewhere = _tree(root / "hw"), _tree(moved)
    for result in (migrate(root, apply=True, resume=True), undo(backup)):
        assert [(f.code, f.path) for f in result.refusals] == [
            ("migrate.unsupported_layout", recovery.BACKUPS)
        ]
    assert (_tree(root / "hw"), _tree(moved)) == (hw, elsewhere)  # nothing abandoned, restored or written


def test_a_fresh_apply_refuses_a_linked_benchhand_directory_before_it_writes_a_backup(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    (tmp_path / "elsewhere").mkdir()
    (root / ".benchhand").symlink_to(tmp_path / "elsewhere")
    before = _tree(root / "hw")
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.refused
    assert _codes(result.refusals) == ["migrate.backup_failed"]
    assert list((tmp_path / "elsewhere").iterdir()) == []
    assert _tree(root / "hw") == before


def test_undo_refuses_a_linked_hw_target_or_target_directory_before_it_writes(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    cases = {
        "hw/decisions": lambda root: _relink(root / "hw" / "decisions", outside / "decisions"),
        "hw/bom.csv": lambda root: _relink(root / "hw" / "bom.csv", outside / "bom.csv"),
        "hw": lambda root: _relink(root / "hw", outside / "hw"),
    }
    for path, relink in cases.items():
        root = _copy(LAMP_ARM_HW, tmp_path / path.replace("/", "-"))
        result = migrate(root, apply=True)
        assert result.backup is not None
        relink(root)
        moved = _tree(outside)
        refusals = undo(result.backup).refusals
        code = "migrate.symlink_hw" if path == "hw" else "migrate.unsupported_layout"
        assert [(f.code, f.path) for f in refusals] == [(code, path)]
        assert _tree(outside) == moved  # the record the link points to is left as it is
        shutil.rmtree(outside)
        outside.mkdir()


def _relink(path: Path, moved: Path) -> None:
    """Move `path` to `moved` and leave a symbolic link to it in its place."""
    shutil.move(path, moved)
    path.symlink_to(moved)


def test_a_linked_product_yaml_is_refused_before_it_is_read(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    _relink(root / "hw" / "product.yaml", tmp_path / "product.yaml")
    os.chmod(tmp_path / "product.yaml", 0)  # reading it would refuse with record.unreadable instead
    try:
        for apply in (False, True):
            result = migrate(root, apply=apply)
            assert [(f.code, f.path) for f in result.refusals] == [
                ("migrate.unsupported_layout", "hw/product.yaml")
            ]
    finally:
        os.chmod(tmp_path / "product.yaml", 0o644)
    assert not (root / ".benchhand").exists()


def _crash_on_directory_sync(monkeypatch: pytest.MonkeyPatch, directory: Path, nth: int) -> None:
    """Kill the process at the `nth` sync of `directory`: after a rename into it, before that sync."""
    real_sync = recovery.fsync_directory
    seen = [0]

    def crash_on_nth(path: Path) -> None:
        if path == directory:
            seen[0] += 1
            if seen[0] == nth:
                raise _Crash
        real_sync(path)

    monkeypatch.setattr(recovery, "fsync_directory", crash_on_nth)


def _recording_syncs(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    real_sync = recovery.fsync_directory
    synced: list[Path] = []

    def record(path: Path) -> None:
        synced.append(path)
        real_sync(path)

    monkeypatch.setattr(recovery, "fsync_directory", record)
    return synced


def test_a_retry_after_a_rename_before_its_directory_sync_syncs_that_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "crashed")
    decisions = root / "hw" / "decisions"
    renamed = [change for change in migrate(root).changes if change.path.startswith("hw/decisions/")]
    _crash_on_directory_sync(monkeypatch, decisions, len(renamed))  # the last decision is renamed, unsynced
    with pytest.raises(_Crash):
        migrate(root, apply=True)
    monkeypatch.undo()
    synced = _recording_syncs(monkeypatch)
    resumed = migrate(root, apply=True, resume=True)
    monkeypatch.undo()
    assert resumed.status == MigrationStatus.applied, resumed.refusals
    assert not [path for path in resumed.written if path.startswith("hw/decisions/")]  # nothing left to write
    assert decisions in synced  # yet its directory is synced before the lock goes
    assert _tree(root / "hw") == expected


def test_a_stop_inside_undo_keeps_the_record_locked_and_undo_again_finishes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    result = migrate(root, apply=True)
    assert result.backup is not None
    decisions = root / "hw" / "decisions"
    restored = [change for change in result.changes if change.path.startswith("hw/decisions/")]
    _crash_on_directory_sync(monkeypatch, decisions, len(restored))  # the last decision restored, unsynced
    with pytest.raises(_Crash):
        undo(result.backup)
    monkeypatch.undo()
    assert recovery.read_lock(root) == result.backup
    for dry_or_apply in (False, True):  # no new backup of a half-restored record
        assert _codes(migrate(root, apply=dry_or_apply).refusals) == ["migrate.locked"]
    synced = _recording_syncs(monkeypatch)
    again = undo(result.backup)
    monkeypatch.undo()
    assert again.status == MigrationStatus.undone, again.refusals
    assert not [path for path in again.written if path.startswith("hw/decisions/")]  # nothing left to write
    assert decisions in synced
    assert _tree(root / "hw") == before
    assert len(_backups(root)) == 1


def test_a_write_failure_stops_apply_and_resume_finishes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "failed")
    real_write = recovery.write_durably
    calls: list[Path] = []

    def fail_second(target: Path, data: bytes, expected_sha256: str) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        real_write(target, data, expected_sha256)

    monkeypatch.setattr(recovery, "write_durably", fail_second)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.failed
    assert len(result.written) == 1
    [refusal] = result.refusals
    assert refusal.code == "migrate.write_failed"
    assert result.recovery is not None and result.recovery in (refusal.action or "")
    monkeypatch.undo()
    assert (root / "hw" / LOCK_NAME).exists()
    assert migrate(root, apply=True, resume=True).status == MigrationStatus.applied
    assert _tree(root / "hw") == expected


def test_a_failed_directory_sync_after_a_rename_counts_the_file_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    bom = root / "hw" / "bom.csv"
    original = bom.read_bytes()
    real_sync = recovery.fsync_directory

    def failing_once_bom_is_replaced(path: Path) -> None:
        if path == bom.parent and bom.read_bytes() != original:
            raise OSError(5, "Input/output error")
        real_sync(path)

    monkeypatch.setattr(recovery, "fsync_directory", failing_once_bom_is_replaced)
    result = migrate(root, apply=True)
    monkeypatch.undo()
    assert (result.status, result.written) == (MigrationStatus.failed, ("hw/bom.csv",))
    [refusal] = result.refusals
    assert refusal.code == "migrate.not_durable" and "power loss" in refusal.message
    assert result.recovery is not None and result.recovery in (refusal.action or "")
