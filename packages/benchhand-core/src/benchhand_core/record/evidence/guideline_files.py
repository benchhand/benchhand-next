"""Discover guideline sets on disk and hash their bytes: the observation half of the prototype's guideline
discovery (guidelines.py:251-341 `_read`, `_scan`, `_refuse_key_collisions`, `discover`, at release.toml
reference_commit 412b5d9). Only the reader calls this.

A set is valid when its file parses, meets the manufacturing-guideline contract and passes the quantity rules
the contract cannot state (guidelines.guideline_problems, the prototype's guidelines.py:186 `validate`). A
refused file never enters resolution: the id it declares resolves to nothing, and the catalog lists it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from benchhand_core.record import contracts
from benchhand_core.record.evidence.guidelines import (
    SHIPPED_COPY,
    GuidelineCatalog,
    GuidelineSet,
    Refusal,
    guideline_problems,
)
from benchhand_core.record.formats import FormatError, parse_yaml


@dataclass(frozen=True)
class Layer:
    """One directory of guideline files, shown in refusals as `shown`/<file name>; `copies` when it is a
    version's snapshot, which alone may hold the shipped--* copies a build writes; `shipped` when it is the
    shipped catalog."""

    directory: Path
    shown: str = ""
    copies: bool = False
    shipped: bool = False


def _read(path: Path) -> tuple[GuidelineSet | None, str | None, tuple[str, ...]]:
    """The set in one file, or None, the id it declares (when it declares one) and why it is refused
    (guidelines.py:251)."""
    raw = path.read_bytes()
    try:
        data = parse_yaml(raw.decode("utf-8"))
    except (UnicodeDecodeError, FormatError) as error:
        return None, None, (f"cannot read the file: {error}",)
    ident = data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), str) else None
    found = contracts.violations("manufacturing-guideline", data)
    if found:
        return None, ident, tuple(f"{v.pointer or '/'}: {v.message}" for v in found)
    problems = guideline_problems(data)
    if problems:
        return None, ident, tuple(problems)
    guideline = GuidelineSet(
        id=data["id"],
        revision=data["revision"],
        extends=tuple(data.get("extends", ())),
        abstract=bool(data.get("abstract", False)),
        scope=data["scope"],
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return guideline, ident, ()


@dataclass
class _Scan:
    found: dict[str, GuidelineSet] = field(default_factory=dict)
    blocked: set[str] = field(default_factory=set)
    refused: list[Refusal] = field(default_factory=list)
    shipped: bool = False


def _scan(layer: Layer) -> _Scan:
    """The valid sets of one directory by id, the ids its refused files declare, the refusals, and whether it
    holds a shipped set or a copy of one (guidelines.py:278)."""
    scan = _Scan()
    directory = layer.directory
    paths = sorted(directory.glob("*.yaml")) if directory.is_dir() and not directory.is_symlink() else []
    for path in paths:
        shown = f"{layer.shown}/{path.name}" if layer.shown else path.name
        copy = path.name.startswith(SHIPPED_COPY)
        if path.is_symlink() or (copy and not layer.copies):
            reason = (
                "is a symbolic link"
                if path.is_symlink()
                else f"{SHIPPED_COPY}* names are reserved for build copies"
            )
            scan.refused.append(Refusal(shown, (reason,)))
            continue
        guideline, ident, problems = _read(path)
        if guideline is not None and guideline.id in scan.found:
            problems = (f"{guideline.id} is already defined in this directory",)
        if guideline is None or problems:
            scan.blocked.update({ident} if ident else set())
            scan.refused.append(Refusal(shown, problems))
            continue
        scan.found[guideline.id] = guideline
        scan.shipped = scan.shipped or layer.shipped or copy
    return scan


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
    """The catalog of the layers, the first holding an id winning (guidelines.py:312). A shipped layer that
    holds a valid set counts as read even when other layers win all its ids; a version's copy counts only
    when it wins."""
    winners: dict[str, GuidelineSet] = {}
    blocked: set[str] = set()
    refused: list[Refusal] = []
    has_shipped = False
    for layer in layers:
        scan = _scan(layer)
        blocked |= scan.blocked
        refused += scan.refused
        has_shipped = has_shipped or (layer.shipped and scan.shipped)
        for ident, guideline in scan.found.items():
            if ident not in winners and ident not in blocked:
                winners[ident] = guideline
                has_shipped = has_shipped or scan.shipped
    collisions = _refuse_key_collisions(winners)
    refused += [
        Refusal(ident, (f"{ident} has the packet key of another set",)) for ident in sorted(collisions)
    ]
    return GuidelineCatalog(winners, frozenset(blocked | collisions), has_shipped, tuple(refused))


def holds_shipped_copies(directory: Path) -> bool:
    """Whether a version's snapshot copied shipped sets."""
    return directory.is_dir() and any(directory.glob(f"{SHIPPED_COPY}*.yaml"))
