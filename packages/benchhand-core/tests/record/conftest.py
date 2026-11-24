"""Fixtures: the reference lamp-arm record and the project template, converted to record_version 3."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from . import prototype_v2


@pytest.fixture
def lamp_arm(tmp_path: Path) -> Path:
    """A project root whose hw/ is the reference lamp-arm record, converted."""
    root = tmp_path / "lamp-arm"
    prototype_v2.convert_tree(prototype_v2.LAMP_ARM_HW, root / "hw")
    return root


@pytest.fixture
def template(tmp_path: Path) -> Path:
    """A project root whose hw/ is the empty project template, converted."""
    root = tmp_path / "template"
    prototype_v2.convert_tree(prototype_v2.TEMPLATE_HW, root / "hw")
    return root


@pytest.fixture
def prototype_lamp_arm(tmp_path: Path) -> Path:
    """A project root whose hw/ is the lamp-arm record as the prototype wrote it (record_version 2)."""
    root = tmp_path / "prototype"
    shutil.copytree(prototype_v2.LAMP_ARM_HW, root / "hw")
    return root
