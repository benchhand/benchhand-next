"""Fixtures: the reference lamp-arm record and the project template, migrated to record_version 3 by the
migrate service."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand_core.record.migrate import MigrationStatus, migrate

REFERENCE_ROOT = Path(__file__).resolve().parents[4] / "reference"
LAMP_ARM_HW = REFERENCE_ROOT / "examples" / "lamp-arm" / "hw"
TEMPLATE_HW = REFERENCE_ROOT / "skills" / "cad-record" / "assets" / "project-template" / "hw"


def migrated(source_hw: Path, root: Path) -> Path:
    """`root` with a copy of `source_hw` as its hw/, migrated; returns `root`."""
    shutil.copytree(source_hw, root / "hw")
    result = migrate(root, apply=True)
    assert result.status == MigrationStatus.applied, result.refusals
    return root


@pytest.fixture
def lamp_arm(tmp_path: Path) -> Path:
    """A project root whose hw/ is the reference lamp-arm record, migrated."""
    return migrated(LAMP_ARM_HW, tmp_path / "lamp-arm")


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A project root whose hw/ is the empty project template, migrated."""
    return migrated(TEMPLATE_HW, tmp_path / "template")


@pytest.fixture
def prototype_lamp_arm(tmp_path: Path) -> Path:
    """A project root whose hw/ is the lamp-arm record as the prototype wrote it (record_version 2)."""
    root = tmp_path / "prototype"
    shutil.copytree(LAMP_ARM_HW, root / "hw")
    return root
