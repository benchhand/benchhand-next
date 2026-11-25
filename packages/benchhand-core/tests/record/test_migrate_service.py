"""migrate(): the dry run, apply, refusals and the failure path, on copies of the reference records."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand_core.record.migrate import MigrationStatus, migrate, service
from benchhand_core.record.store import load_record
from benchhand_core.record.validate import validate

from .conftest import LAMP_ARM_HW, TEMPLATE_HW


def _tree(root: Path) -> dict[str, bytes]:
    """Every entry under root (files by content, directories as None), stage leftovers included."""
    return {
        path.relative_to(root).as_posix(): (path.read_bytes() if path.is_file() else b"<dir>")
        for path in sorted(root.rglob("*"))
    }


def _copy(source: Path, root: Path) -> Path:
    shutil.copytree(source, root / "hw")
    return root


@pytest.mark.parametrize("source", [LAMP_ARM_HW, TEMPLATE_HW], ids=["lamp-arm", "template"])
def test_a_reference_record_migrates_and_validates_with_no_findings(source: Path, tmp_path: Path) -> None:
    root = _copy(source, tmp_path)
    plan = migrate(root)
    assert plan.status == MigrationStatus.ready
    assert (plan.findings, plan.remaining) == ((), ())
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied
    assert validate(root) == []
    load_record(root)


def test_the_dry_run_writes_nothing_and_states_each_change_as_a_diff(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root)
    plan = migrate(root)
    assert _tree(root) == before
    product = next(change for change in plan.changes if change.path == "hw/product.yaml")
    assert product.rules == ("record-version", "human-approval")
    diff = product.diff()
    assert diff.startswith("--- a/hw/product.yaml\n+++ b/hw/product.yaml\n")
    assert "-record_version: 2\n+record_version: 3\n" in diff


def test_apply_writes_exactly_the_planned_text_and_leaves_every_other_file_byte_identical(
    tmp_path: Path,
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root)
    plan = migrate(root)
    migrate(root, apply=True)
    after = _tree(root)
    changed = {change.path: change.after.encode("utf-8") for change in plan.changes}
    assert after.keys() == before.keys()
    for path, content in after.items():
        assert content == changed.get(path, before[path]), path


def test_migrating_a_record_version_3_record_is_a_no_op(lamp_arm: Path) -> None:
    before = _tree(lamp_arm)
    for apply in (False, True):
        result = migrate(lamp_arm, apply=apply)
        assert result.status == MigrationStatus.current
        assert [finding.code for finding in result.findings] == ["migrate.current"]
    assert _tree(lamp_arm) == before


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
    text = product.read_text()
    replacement = "" if value is None else f"record_version: {value}\n"
    product.write_text(text.replace("record_version: 2\n", replacement, 1))
    before = _tree(root)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.refused
    [refusal] = result.refusals
    assert (refusal.code, refusal.path, refusal.pointer) == (
        "record.version_unsupported",
        "hw/product.yaml",
        "/record_version",
    )
    assert refusal.action
    assert _tree(root) == before


def test_a_deprecated_decision_is_refused_in_the_dry_run_and_apply_writes_nothing(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    decision = next((root / "hw" / "decisions").glob("DR-001-*.md"))
    decision.write_text(decision.read_text().replace("status: accepted", "status: deprecated", 1))
    before = _tree(root)
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
    assert _tree(root) == before


def test_human_approval_key_is_reported_because_those_gates_now_ask(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    product = root / "hw" / "product.yaml"
    text = product.read_text()
    assert 'human_approval: "all"' in text
    product.write_text(text.replace('human_approval: "all"', 'human_approval: "key"', 1))
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied
    [note] = result.findings
    assert (note.code, note.severity.value, note.pointer) == (
        "migrate.gates_now_ask",
        "info",
        "/flow/profile/human_approval",
    )
    assert "hw/policy.yaml" in (note.action or "")
    assert not (root / "hw" / "policy.yaml").exists()
    assert "human_approval" not in product.read_text()


def test_os_and_tool_junk_is_never_read_rewritten_or_counted(tmp_path: Path) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    decisions = root / "hw" / "decisions"
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
    plan = migrate(root)
    assert plan.status == MigrationStatus.ready
    assert not any(change.path in junk for change in plan.changes)
    assert len(plan.changes) == len(migrate(_copy(LAMP_ARM_HW, tmp_path / "clean")).changes)
    assert migrate(root, apply=True).status == MigrationStatus.applied
    assert {path: (root / path).read_bytes() for path in junk} == junk
    assert validate(root) == []
    assert len(list(decisions.glob("DR-*.md"))) == 6


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


@pytest.mark.parametrize("fail_at", ["stage", "swap", "re-read"])
def test_a_failure_during_apply_leaves_the_tree_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: str
) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    before = _tree(root)

    def broken(*_: object, **__: object) -> None:
        raise OSError("injected failure")

    if fail_at == "stage":
        monkeypatch.setattr(service, "_write", broken)
    elif fail_at == "swap":
        real_rename = service.os.rename
        calls = []

        def rename(source: Path, target: Path) -> None:
            calls.append(source)
            if len(calls) == 2:  # the staged hw/ into place, after the original moved aside
                raise OSError("injected failure")
            real_rename(source, target)

        monkeypatch.setattr(service.os, "rename", rename)
    else:
        real_validated = service._validated
        seen = []

        def validated(stage: Path) -> object:
            seen.append(stage)
            if len(seen) == 2:  # the re-read of the swapped-in record
                raise OSError("injected failure")
            return real_validated(stage)

        monkeypatch.setattr(service, "_validated", validated)
    with pytest.raises(OSError, match="injected failure"):
        migrate(root, apply=True)
    assert _tree(root) == before


def test_a_file_changed_after_the_plan_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _copy(LAMP_ARM_HW, tmp_path)
    real_plan = service._plan

    def plan_then_edit(*args: object) -> service.Migration:
        planned = real_plan(*args)  # type: ignore[arg-type]
        (root / "hw" / "bom.csv").write_text("edited meanwhile\n")
        return planned

    monkeypatch.setattr(service, "_plan", plan_then_edit)
    before = _tree(root)
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.refused
    assert [finding.code for finding in result.refusals] == ["migrate.changed_meanwhile"]
    assert _tree(root) == {**before, "hw/bom.csv": b"edited meanwhile\n"}
