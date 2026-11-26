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


def migrated(source_hw: Path, work: Path) -> Path:
    """The hw/ of a copy of `source_hw` under `work`, migrated with --backup (the backup stays in `work`)."""
    shutil.copytree(source_hw, work / "hw")
    result = migrate(work, apply=True, backup=True)
    assert result.status == MigrationStatus.applied, result.refusals
    return work / "hw"


@pytest.fixture(scope="session")
def migrated_trees(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Each reference record migrated once per session; tests take a copy."""
    base = tmp_path_factory.mktemp("migrated")
    return {
        "lamp-arm": migrated(LAMP_ARM_HW, base / "lamp-arm"),
        "template": migrated(TEMPLATE_HW, base / "template"),
    }


@pytest.fixture
def lamp_arm(tmp_path: Path, migrated_trees: dict[str, Path]) -> Path:
    """A project root whose hw/ is the reference lamp-arm record, migrated."""
    root = tmp_path / "lamp-arm"
    shutil.copytree(migrated_trees["lamp-arm"], root / "hw")
    return root


@pytest.fixture
def template(tmp_path: Path, migrated_trees: dict[str, Path]) -> Path:
    """A project root whose hw/ is the empty project template, migrated."""
    root = tmp_path / "template"
    shutil.copytree(migrated_trees["template"], root / "hw")
    return root


@pytest.fixture
def prototype_lamp_arm(tmp_path: Path) -> Path:
    """A project root whose hw/ is the lamp-arm record as the prototype wrote it (record_version 2)."""
    root = tmp_path / "prototype"
    shutil.copytree(LAMP_ARM_HW, root / "hw")
    return root
