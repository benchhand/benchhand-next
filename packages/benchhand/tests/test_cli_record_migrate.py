# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""`benchhand record migrate`: the dry run prints the diff and writes nothing; --apply writes behind a
preimage backup; --undo BACKUP puts the files back."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand.cli import app
from typer.testing import CliRunner

LAMP_ARM_HW = Path(__file__).resolve().parents[3] / "reference" / "examples" / "lamp-arm" / "hw"


def _tree(hw: Path) -> dict[str, bytes]:
    return {
        path.relative_to(hw).as_posix(): path.read_bytes() for path in sorted(hw.rglob("*")) if path.is_file()
    }


def test_record_migrate_with_a_relative_hw_path_prints_the_plan_applies_it_and_undoes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(LAMP_ARM_HW, tmp_path / "hw")
    monkeypatch.chdir(tmp_path)
    before = _tree(Path("hw"))
    dry = CliRunner().invoke(app, ["record", "migrate", "hw"])
    assert dry.exit_code == 0, dry.output
    assert "-record_version: 2\n+record_version: 3\n" in dry.output
    assert dry.output.endswith("ready: 10 files\n")
    assert _tree(Path("hw")) == before
    applied = CliRunner().invoke(app, ["record", "migrate", "--apply", "hw"])
    assert applied.exit_code == 0, applied.output
    assert applied.output.endswith("applied: 10 of 10 files\n")
    [undo_line] = [line for line in applied.output.splitlines() if line.startswith("to undo: ")]
    command = undo_line.removeprefix("to undo: ")
    backup = command.removeprefix("benchhand record migrate --undo ")
    assert command.startswith("benchhand record migrate --undo ") and Path(backup).is_absolute()
    again = CliRunner().invoke(app, ["record", "migrate", "hw"])
    assert again.output.endswith("current: 0 files\n")
    undone = CliRunner().invoke(app, ["record", "migrate", "--undo", backup])
    assert undone.exit_code == 0, undone.output
    assert undone.output.endswith("undone: 10 files\n")
    assert _tree(Path("hw")) == before


def test_record_migrate_exits_1_on_a_refusal_and_2_on_bad_arguments(tmp_path: Path) -> None:
    hw = tmp_path / "hw"
    hw.mkdir()
    (hw / "product.yaml").write_text("record_version: 9\n")
    result = CliRunner().invoke(app, ["record", "migrate", str(hw)])
    assert result.exit_code == 1
    assert "error record.version_unsupported hw/product.yaml#/record_version" in result.output
    assert CliRunner().invoke(app, ["record", "migrate", "--resume", str(hw)]).exit_code == 2
    assert CliRunner().invoke(app, ["record", "migrate", "--undo", str(tmp_path), str(hw)]).exit_code == 2
    assert CliRunner().invoke(app, ["record", "migrate"]).exit_code == 2
