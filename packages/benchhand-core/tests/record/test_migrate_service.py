"""migrate(): the dry run, apply in place with a recovery point and a lock, refusals, and interrupted applies,
on copies of the reference records."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from benchhand_core.record.migrate import MigrationStatus, migrate, recovery, service
from benchhand_core.record.migrate.inventory import LOCK_NAME, TEMP_SUFFIX
from benchhand_core.record.store import load_record
from benchhand_core.record.validate import validate

from .conftest import LAMP_ARM_HW, TEMPLATE_HW


def _tree(hw: Path) -> dict[str, bytes]:
    """Every entry under `hw` (files by content, directories as <dir>)."""
    return {
        path.relative_to(hw).as_posix(): (path.read_bytes() if path.is_file() else b"<dir>")
        for path in sorted(hw.rglob("*"))
    }


def _copy(source: Path, root: Path) -> Path:
    shutil.copytree(source, root / "hw")
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _committed(source: Path, root: Path) -> Path:
    _copy(source, root)
    _git(root, "init", "-q")
    _git(root, "add", "hw")
    _git(root, "commit", "-q", "-m", "prototype record")
    return root


def _codes(findings: tuple) -> list[str]:  # type: ignore[type-arg]
    return [finding.code for finding in findings]


@pytest.mark.parametrize("source", [LAMP_ARM_HW, TEMPLATE_HW], ids=["lamp-arm", "template"])
def test_a_reference_record_migrates_and_validates_with_no_findings(source: Path, tmp_path: Path) -> None:
    root = _committed(source, tmp_path)
    plan = migrate(root)
    assert plan.status == MigrationStatus.ready
    assert (plan.findings, plan.remaining) == ((), ())
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied, result.refusals
    assert result.written[-1] == "hw/product.yaml"
    assert result.recovery == f"git -C {root.resolve()} restore -- hw"
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
    root = _committed(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    plan = migrate(root)
    migrate(root, apply=True)
    after = _tree(root / "hw")
    changed = {change.path.removeprefix("hw/"): change.after.encode("utf-8") for change in plan.changes}
    assert after.keys() == before.keys()
    for path, content in after.items():
        assert content == changed.get(path, before[path]), path


def test_the_recovery_command_puts_hw_back(tmp_path: Path) -> None:
    for backup in (False, True):
        root = _committed(LAMP_ARM_HW, tmp_path / f"backup-{backup}")
        before = _tree(root / "hw")
        result = migrate(root, apply=True, backup=backup)
        assert result.status == MigrationStatus.applied
        assert result.recovery is not None
        subprocess.run(shlex.split(result.recovery), check=True, capture_output=True)
        assert _tree(root / "hw") == before


def test_backup_is_a_complete_copy_reported_in_the_result(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root / "hw")
    result = migrate(root, apply=True, backup=True)
    assert result.status == MigrationStatus.applied
    assert (
        result.backup is not None
        and result.backup.parent.parent == (root / ".benchhand" / "backups").resolve()
    )
    assert _tree(result.backup) == before
    assert "migrate.backup_written" in _codes(result.findings)


def test_apply_without_a_recovery_point_is_refused_naming_both_fixes(tmp_path: Path) -> None:
    plain = _copy(LAMP_ARM_HW, tmp_path / "plain")
    dirty = _committed(LAMP_ARM_HW, tmp_path / "dirty")
    (dirty / "hw" / "notes.md").write_text("not committed\n")
    for root in (plain, dirty):
        before = _tree(root / "hw")
        result = migrate(root, apply=True)
        assert result.status == MigrationStatus.refused
        [refusal] = result.refusals
        assert refusal.code == "migrate.no_recovery_point"
        assert "git restore hw" in (refusal.action or "") and "--backup" in (refusal.action or "")
        assert _tree(root / "hw") == before


def test_untracked_junk_does_not_count_against_a_clean_work_tree(tmp_path: Path) -> None:
    root = _committed(LAMP_ARM_HW, tmp_path)
    (root / "hw" / ".DS_Store").write_bytes(b"\x00junk")
    assert migrate(root, apply=True).status == MigrationStatus.applied


def test_migrating_a_record_version_3_record_is_a_no_op(lamp_arm: Path) -> None:
    before = _tree(lamp_arm)
    for apply in (False, True):
        result = migrate(lamp_arm, apply=apply)
        assert result.status == MigrationStatus.current
        assert _codes(result.findings) == ["migrate.current"]
    assert _tree(lamp_arm) == before


def test_prototype_pr_319_record_version_1_migrates_as_version_2(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    product.write_text(product.read_text().replace("record_version: 2", "record_version: 1", 1))
    assert migrate(root, apply=True, backup=True).status == MigrationStatus.applied
    assert validate(root) == []


@pytest.mark.parametrize("value", ["7", "'2'", "true", None])
def test_an_unknown_record_version_is_refused_and_nothing_changes(tmp_path: Path, value: str | None) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    replacement = "" if value is None else f"record_version: {value}\n"
    product.write_text(product.read_text().replace("record_version: 2\n", replacement, 1))
    before = _tree(tmp_path)
    result = migrate(root, apply=True, backup=True)
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
        result = migrate(root, apply=apply, backup=True)
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
    result = migrate(root, apply=True, backup=True)
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
        assert len(plan.changes) == len(migrate(_copy(LAMP_ARM_HW, tmp_path / "clean")).changes)
        result = migrate(root, apply=True, backup=True)
        assert result.status == MigrationStatus.applied, result.refusals
        assert result.backup is not None and not (result.backup / ".DS_Store").exists()
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
            result = migrate(root, apply=apply, backup=True)
            assert result.status == MigrationStatus.refused
            assert _codes(result.refusals) == ["migrate.scan_failed"]
            assert result.refusals[0].path == "hw/renders"
    finally:
        os.chmod(hidden, 0o755)


def test_sealed_history_stays_byte_identical(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    hw = root / "hw"
    sealed = ["versions/v1/hw/product.yaml", "checks/v1/verification.csv", "releases/A/hw/bom.csv"]
    sources = ["product.yaml", "verification.csv", "bom.csv"]
    for path, source in zip(sealed, sources, strict=True):
        (hw / path).parent.mkdir(parents=True)
        shutil.copy(hw / source, hw / path)
    shutil.copytree(hw / "decisions", hw / "versions" / "v1" / "hw" / "decisions")
    before = {
        path: data
        for path, data in _tree(hw).items()
        if path.split("/")[0] in ("versions", "checks", "releases")
    }
    result = migrate(root, apply=True, backup=True)
    assert result.status == MigrationStatus.applied, result.refusals
    assert not [
        change for change in result.changes if change.path.split("/")[1] in ("versions", "checks", "releases")
    ]
    assert {path: data for path, data in _tree(hw).items() if path in before} == before


def test_a_frozen_record_whose_digest_inputs_would_change_is_refused(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    text = product.read_text()
    product.write_text(text.replace("flow:\n", "flow:\n  frozen: {version: v1, evidence_sha256: abc}\n", 1))
    before = _tree(tmp_path)
    for apply in (False, True):
        result = migrate(root, apply=apply, backup=True)
        assert result.status == MigrationStatus.refused
        [refusal] = result.refusals
        assert (refusal.code, refusal.pointer) == ("migrate.frozen_anchor", "/flow/frozen")
        assert "hw/verification.csv" in refusal.message and "Phase 2" in (refusal.action or "")
    assert _tree(tmp_path) == before


def test_a_symlink_leaving_the_project_is_refused_and_one_inside_is_read(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path / "project")
    (tmp_path / "outside.md").write_text("outside\n")
    (root / "README.md").write_text("inside\n")
    (root / "hw" / "inside.md").symlink_to("../README.md")
    assert migrate(root).status == MigrationStatus.ready
    (root / "hw" / "outside.md").symlink_to(tmp_path / "outside.md")
    before = _tree(root / "hw")
    for apply in (False, True):
        result = migrate(root, apply=apply, backup=True)
        assert result.status == MigrationStatus.refused
        [refusal] = result.refusals
        assert (refusal.code, refusal.path) == ("migrate.symlink_outside", "hw/outside.md")
    assert _tree(root / "hw") == before


def test_a_crlf_csv_keeps_its_line_endings_and_data_rows(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    bom = root / "hw" / "bom.csv"
    crlf = bom.read_bytes().replace(b"\n", b"\r\n")
    bom.write_bytes(crlf)
    migrate(root, apply=True, backup=True)
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
    result = migrate(root, apply=True, backup=True)
    assert _codes(result.refusals) == ["migrate.locked"]
    assert f"delete hw/{LOCK_NAME}" in (result.refusals[0].action or "")
    assert _tree(root / "hw") == before
    lock.unlink()

    def stuck(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", stuck)
    result = migrate(root, apply=True, backup=True)
    assert result.status == MigrationStatus.applied
    assert "migrate.cleanup_failed" in _codes(result.findings)


def test_a_file_changed_after_the_plan_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    real_checked = service._checked

    def plan_then_edit(*args: object) -> object:
        planned = real_checked(*args)  # type: ignore[arg-type]
        (root / "hw" / "bom.csv").write_text("edited meanwhile\n")
        return planned

    monkeypatch.setattr(service, "_checked", plan_then_edit)
    result = migrate(root, apply=True, backup=True)
    assert result.status == MigrationStatus.refused
    [refusal] = result.refusals
    assert (refusal.code, refusal.path) == ("migrate.changed_meanwhile", "hw/bom.csv")
    assert result.recovery is not None and result.recovery in (refusal.action or "")
    assert (root / "hw" / "bom.csv").read_text() == "edited meanwhile\n"
    assert result.written == ()


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
    result = migrate(root, apply=True, backup=True)
    assert _codes(result.refusals) == ["migrate.changed_meanwhile"]
    assert _tree(root / "hw") == {**before, "added.md": b"new\n"}


def _clean_run(tmp_path: Path) -> dict[str, bytes]:
    root = _copy(LAMP_ARM_HW, tmp_path / "clean")
    assert migrate(root, apply=True, backup=True).status == MigrationStatus.applied
    return _tree(root / "hw")


class _Crash(BaseException):
    """The process dying mid-apply: nothing in the service catches it."""


@pytest.mark.parametrize("stop_after", [0, 1, 4, 9])
def test_a_rerun_after_an_interrupted_apply_finishes_it_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_after: int
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "crashed")
    real_write = recovery.write_durably
    written: list[Path] = []

    def crash_after(target: Path, data: bytes) -> None:
        if len(written) == stop_after:
            raise _Crash
        real_write(target, data)
        written.append(target)

    monkeypatch.setattr(recovery, "write_durably", crash_after)
    monkeypatch.setattr(recovery, "release_lock", lambda lock: None)  # a killed process leaves its lock
    with pytest.raises(_Crash):
        migrate(root, apply=True, backup=True)
    monkeypatch.undo()
    assert len(written) == stop_after
    assert _codes(migrate(root, apply=True, backup=True).refusals) == ["migrate.locked"]
    (root / "hw" / LOCK_NAME).unlink()
    rerun = migrate(root, apply=True, backup=True)
    assert rerun.status == MigrationStatus.applied, rerun.refusals
    assert len(rerun.written) == 10 - stop_after
    assert _tree(root / "hw") == expected
    assert not list((root / "hw").rglob(f"*{TEMP_SUFFIX}"))


def test_a_write_failure_stops_apply_and_names_the_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _clean_run(tmp_path)
    root = _copy(LAMP_ARM_HW, tmp_path / "failed")
    real_write = recovery.write_durably
    calls: list[Path] = []

    def fail_second(target: Path, data: bytes) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        real_write(target, data)

    monkeypatch.setattr(recovery, "write_durably", fail_second)
    result = migrate(root, apply=True, backup=True)
    assert result.status == MigrationStatus.failed
    assert len(result.written) == 1
    [refusal] = result.refusals
    assert refusal.code == "migrate.write_failed"
    assert result.recovery is not None and result.recovery in (refusal.action or "")
    monkeypatch.undo()
    assert migrate(root, apply=True, backup=True).status == MigrationStatus.applied
    assert _tree(root / "hw") == expected
