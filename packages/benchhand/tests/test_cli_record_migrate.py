"""`benchhand record migrate`: the dry run prints the diff and writes nothing; --apply writes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand.cli import app
from typer.testing import CliRunner

LAMP_ARM_HW = Path(__file__).resolve().parents[3] / "reference" / "examples" / "lamp-arm" / "hw"


def test_record_migrate_with_a_relative_hw_path_prints_the_plan_then_applies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(LAMP_ARM_HW, tmp_path / "hw")
    monkeypatch.chdir(tmp_path)
    product = Path("hw/product.yaml").read_bytes()
    dry = CliRunner().invoke(app, ["record", "migrate", "hw"])
    assert dry.exit_code == 0, dry.output
    assert "-record_version: 2\n+record_version: 3\n" in dry.output
    assert dry.output.endswith("ready: 10 files\n")
    assert Path("hw/product.yaml").read_bytes() == product
    refused = CliRunner().invoke(app, ["record", "migrate", "--apply", "hw"])
    assert refused.exit_code == 1
    assert "migrate.no_recovery_point" in refused.output
    applied = CliRunner().invoke(app, ["record", "migrate", "--apply", "--backup", "hw"])
    assert applied.exit_code == 0, applied.output
    assert "to undo: cp -Rp " in applied.output
    assert applied.output.endswith("applied: 10 of 10 files\n")
    again = CliRunner().invoke(app, ["record", "migrate", "hw"])
    assert again.output.endswith("current: 0 files\n")


def test_record_migrate_exits_1_on_a_refusal(tmp_path: Path) -> None:
    hw = tmp_path / "hw"
    hw.mkdir()
    (hw / "product.yaml").write_text("record_version: 9\n")
    result = CliRunner().invoke(app, ["record", "migrate", str(hw)])
    assert result.exit_code == 1
    assert "error record.version_unsupported hw/product.yaml#/record_version" in result.output
