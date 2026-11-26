"""Discover guideline sets on disk and hash their bytes: the observation half of the prototype's guideline
discovery (guidelines.py:251-341 `_read`, `_scan`, `_refuse_key_collisions`, `discover`, at release.toml
reference_commit 412b5d9). Only the reader calls this.

A set is valid when its file parses and meets the manufacturing-guideline contract. The prototype also
checks its quantities (guidelines.py:186 `validate`); the contract carries what the digests read.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from benchhand_core.record import contracts
from benchhand_core.record.evidence.guidelines import SHIPPED_COPY, GuidelineCatalog, GuidelineSet
from benchhand_core.record.formats import FormatError, parse_yaml


@dataclass(frozen=True)
class Layer:
    """One directory of guideline files; `copies` when it is a version's snapshot, which alone may hold the
    shipped--* copies a build writes; `shipped` when it is the shipped catalog."""

    directory: Path
    copies: bool = False
    shipped: bool = False


def _read(path: Path) -> tuple[GuidelineSet | None, str | None]:
    """The set in one file, or None and the id it declares (when it declares one) for a refused file."""
    raw = path.read_bytes()
    try:
        data = parse_yaml(raw.decode("utf-8"))
    except (UnicodeDecodeError, FormatError):
        return None, None
    ident = data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), str) else None
    if contracts.violations("manufacturing-guideline", data):
        return None, ident
    found = GuidelineSet(
        id=data["id"],
        revision=data["revision"],
        extends=tuple(data.get("extends", ())),
        abstract=bool(data.get("abstract", False)),
        scope=data["scope"],
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return found, ident


def _scan(layer: Layer) -> tuple[dict[str, GuidelineSet], set[str], bool]:
    """The valid sets of one directory by id, the ids its refused files declare, and whether it holds a
    shipped set or a copy of one (guidelines.py:278)."""
    found: dict[str, GuidelineSet] = {}
    blocked: set[str] = set()
    shipped = False
    directory = layer.directory
    paths = sorted(directory.glob("*.yaml")) if directory.is_dir() and not directory.is_symlink() else []
    for path in paths:
        copy = path.name.startswith(SHIPPED_COPY)
        if path.is_symlink() or (copy and not layer.copies):
            continue
        guideline, ident = _read(path)
        if guideline is None or guideline.id in found:
            blocked.update({ident} if ident else set())
            continue
        found[guideline.id] = guideline
        shipped = shipped or layer.shipped or copy
    return found, blocked, shipped


def _refuse_key_collisions(winners: dict[str, GuidelineSet]) -> set[str]:
    """Remove each set whose packet key (fdm.a.b and fdm.a_b) an earlier id already has
    (guidelines.py:298)."""
    seen: set[str] = set()
    refused: set[str] = set()
    for ident in sorted(winners):
        stem = ident.replace(".", "_")
        if stem in seen:
            winners.pop(ident)
            refused.add(ident)
        seen.add(stem)
    return refused


def discover(layers: Iterable[Layer]) -> GuidelineCatalog:
    """The catalog of the layers, the first holding an id winning (guidelines.py:312)."""
    winners: dict[str, GuidelineSet] = {}
    blocked: set[str] = set()
    has_shipped = False
    for layer in layers:
        found, refused, shipped = _scan(layer)
        blocked |= refused
        for ident, guideline in found.items():
            if ident not in winners and ident not in blocked:
                winners[ident] = guideline
                has_shipped = has_shipped or shipped
    blocked |= _refuse_key_collisions(winners)
    return GuidelineCatalog(winners, frozenset(blocked), has_shipped)


def holds_shipped_copies(directory: Path) -> bool:
    """Whether a version's snapshot copied shipped sets."""
    return directory.is_dir() and any(directory.glob(f"{SHIPPED_COPY}*.yaml"))
