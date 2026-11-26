"""Fixtures: a built version of the reference lamp-arm record (converted to record_version 3), sealed the way
the prototype seals one (layout.py `seal`, 412b5d9): a manifest.json listing the sha256 of every file."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

SNAPSHOT_DOCUMENTS = (
    "product.yaml",
    "requirements.yaml",
    "interfaces.yaml",
    "assembly.yaml",
    "manufacturing/capabilities.yaml",
    "manufacturing/materials.yaml",
    "manufacturing/selection.yaml",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(directory: Path, **fields: Any) -> str:
    """Write directory/manifest.json listing every file below it; returns the manifest's sha256."""
    files = {
        path.relative_to(directory).as_posix(): sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"files": files, **fields}, indent=1, sort_keys=True), encoding="utf-8")
    return sha256(manifest)


def snapshot(hw: Path, version: str, shipped: Path | None = None) -> Path:
    """Copy the record documents to hw/versions/<V>/record/, as a build does: the project's guideline sets
    as they are, and each shipped set in `shipped` the project does not override as shipped--<file name>
    (guidelines.py:343 snapshot_files)."""
    record = hw / "versions" / version / "record"
    for rel in SNAPSHOT_DOCUMENTS:
        if (hw / rel).is_file():
            (record / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hw / rel, record / rel)
    for part in sorted((hw / "parts").glob("*/part.yaml")):
        target = record / "parts" / part.parent.name / "part.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(part, target)
    guidelines = record / "manufacturing" / "guidelines"
    own = sorted((hw / "manufacturing" / "guidelines").glob("*.yaml"))
    ids = {yaml.safe_load(path.read_text(encoding="utf-8")).get("id") for path in own}
    copies = [(path, path.name) for path in own]
    for path in sorted(shipped.glob("*.yaml")) if shipped is not None else []:
        if yaml.safe_load(path.read_text(encoding="utf-8")).get("id") not in ids:
            copies.append((path, f"shipped--{path.name}"))
    for path, name in copies:
        guidelines.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, guidelines / name)
    return record


def build(root: Path, version: str = "v1", shipped: Path | None = None) -> str:
    """Snapshot and seal `version` of the project at `root`; returns the version manifest's sha256."""
    hw = root / "hw"
    snapshot(hw, version, shipped)
    models = sorted((hw / "parts").glob("*/model.py"))
    parts = {path.parent.name: {"source_sha256": sha256(path)} for path in models}
    return seal(hw / "versions" / version, version=version, parts=parts)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def built(lamp_arm: Path) -> tuple[Path, str]:
    """The lamp-arm project with v1 built and sealed: (root, version manifest sha256)."""
    return lamp_arm, build(lamp_arm)


WritePacket = Callable[..., Path]


@pytest.fixture
def write_packet() -> WritePacket:
    def write(root: Path, name: str, data: dict[str, Any], version_sha: str, version: str = "v1") -> Path:
        bundle = root / "hw" / "checks" / version / name
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "result.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        seal(bundle, version_manifest_sha256=version_sha)
        return bundle

    return write
