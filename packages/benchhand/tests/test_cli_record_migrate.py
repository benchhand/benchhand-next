# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""`benchhand record migrate`: the dry run prints the diff and writes nothing; --apply writes behind a
preimage backup; --undo BACKUP puts the files back. All of it sits behind the record-migration flag; with the
flag off the command refuses with feature.disabled."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand import flags
from benchhand.cli import app
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider
from typer.testing import CliRunner, Result

LAMP_ARM_HW = Path(__file__).resolve().parents[3] / "reference" / "examples" / "lamp-arm" / "hw"


def _tree(hw: Path) -> dict[str, bytes]:
    return {
        path.relative_to(hw).as_posix(): path.read_bytes() for path in sorted(hw.rglob("*")) if path.is_file()
    }


def _invoke(args: list[str], *, record_migration: str = "on") -> Result:
    """Run the CLI with the record-migration flag at the variant ``record_migration``, decided through
    OpenFeature's in-memory provider."""
    flag = InMemoryFlag(record_migration, {"on": True, "off": False})
    decisions = flags.decide(InMemoryProvider({flags.RECORD_MIGRATION.key: flag}))
    return CliRunner().invoke(app, args, obj=decisions)


def test_record_migrate_with_a_relative_hw_path_prints_the_plan_applies_it_and_undoes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(LAMP_ARM_HW, tmp_path / "hw")
    monkeypatch.chdir(tmp_path)
    before = _tree(Path("hw"))
    dry = _invoke(["record", "migrate", "hw"])
    assert dry.exit_code == 0, dry.output
    assert "-record_version: 2\n+record_version: 3\n" in dry.output
    assert dry.output.endswith("ready: 10 files\n")
    assert _tree(Path("hw")) == before
    applied = _invoke(["record", "migrate", "--apply", "hw"])
    assert applied.exit_code == 0, applied.output
    assert applied.output.endswith("applied: 10 of 10 files\n")
    [undo_line] = [line for line in applied.output.splitlines() if line.startswith("to undo: ")]
    command = undo_line.removeprefix("to undo: ")
    backup = command.removeprefix("benchhand record migrate --undo ")
    assert command.startswith("benchhand record migrate --undo ") and Path(backup).is_absolute()
    again = _invoke(["record", "migrate", "hw"])
    assert again.output.endswith("current: 0 files\n")
    undone = _invoke(["record", "migrate", "--undo", backup])
    assert undone.exit_code == 0, undone.output
    assert undone.output.endswith("undone: 10 files\n")
    assert _tree(Path("hw")) == before


def test_record_migrate_exits_1_on_a_refusal_and_2_on_bad_arguments(tmp_path: Path) -> None:
    hw = tmp_path / "hw"
    hw.mkdir()
    (hw / "product.yaml").write_text("record_version: 9\n")
    result = _invoke(["record", "migrate", str(hw)])
    assert result.exit_code == 1
    assert "error record.version_unsupported hw/product.yaml#/record_version" in result.output
    assert _invoke(["record", "migrate", "--resume", str(hw)]).exit_code == 2
    assert _invoke(["record", "migrate", "--undo", str(tmp_path), str(hw)]).exit_code == 2
    assert _invoke(["record", "migrate"]).exit_code == 2


@pytest.mark.parametrize(
    "args",
    [["--apply"], ["--apply", "--resume"], []],
    ids=["apply", "resume", "dry-run"],
)
def test_record_migrate_with_the_flag_off_refuses_with_feature_disabled_and_writes_nothing(
    tmp_path: Path, args: list[str]
) -> None:
    shutil.copytree(LAMP_ARM_HW, tmp_path / "hw")
    before = _tree(tmp_path / "hw")
    result = _invoke(["record", "migrate", *args, str(tmp_path / "hw")], record_migration="off")
    assert result.exit_code == 1
    assert result.output.startswith(
        "error feature.disabled record-migration: benchhand record migrate is not offered in this release"
    )
    assert f'defaultVariant to "on" in {flags.FLAGS_FILE}' in result.output
    assert _tree(tmp_path / "hw") == before
    assert not (tmp_path / ".benchhand").exists()


def test_record_migrate_undo_with_the_flag_off_refuses_with_feature_disabled(tmp_path: Path) -> None:
    result = _invoke(["record", "migrate", "--undo", str(tmp_path)], record_migration="off")
    assert result.exit_code == 1
    assert "error feature.disabled record-migration" in result.output


def test_record_migrate_refuses_with_the_shipped_flags_file(tmp_path: Path) -> None:
    """No injected decision: the CLI reads benchhand/flags.yaml, where the flag is off."""
    shutil.copytree(LAMP_ARM_HW, tmp_path / "hw")
    result = CliRunner().invoke(app, ["record", "migrate", str(tmp_path / "hw")])
    assert result.exit_code == 1
    assert "error feature.disabled record-migration" in result.output


def test_record_migrate_help_marks_it_experimental_behind_the_flag() -> None:
    listing = CliRunner().invoke(app, ["record", "--help"])
    assert "migrate" in listing.output and "Experimental" in listing.output
    help_text = CliRunner().invoke(app, ["record", "migrate", "--help"])
    assert help_text.exit_code == 0
    assert "record-migration feature flag" in " ".join(help_text.output.split())
