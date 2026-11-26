"""What the evidence rules read about a built version, beside the record: the evidence service's only inputs.

The reader (benchhand_core.record.evidence.reader) forms a BuiltVersion from the files of hw/versions/<V>/,
hw/checks/<V>/ and the files the record cites. Phase 2's snapshot service can replace that reader; the rules
read only these types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from benchhand_core.record.evidence.paths import PathQuery, Verdict
from benchhand_core.record.finding import Finding


@dataclass(frozen=True)
class Packet:
    """A sealed required-check packet: its bundle (hw/checks/<V>/<S>), the sha256 of the bundle's
    manifest.json (what a finding disposition cites) and its result.json, which met the
    manufacturing-check-result contract."""

    bundle: str
    manifest_sha256: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class ChangedSinceBuild:
    """The dependency domains that changed per subject key between the built record and the current one."""

    changed: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class NotComputed:
    """Build staleness could not be computed: no producer outcome that it would decide counts."""

    reason: str


@dataclass(frozen=True)
class FileState:
    """One file below hw/: its sha256, or why it cannot be read (missing, a link, not normalized)."""

    sha256: str | None = None
    problem: str | None = None


@dataclass(frozen=True)
class BuiltVersion:
    """A built version and what was read about it. `current_geometry` maps each PN to the sha256 of its
    current hw/parts/<PN>/model.py; `files` maps an hw/ path to its state, for every file the acceptance
    inventory and the ledger entries cite; `bundle_seals` maps each bundle a ledger entry cites to why it
    fails its seal (empty when every payload file verifies); `path_verdicts` judges every path the ledgers
    cite against the project's filesystem and git; `packet_findings` are the bundles the reader refused."""

    label: str
    manifest_sha256: str
    staleness: ChangedSinceBuild | NotComputed
    packets: tuple[Packet, ...] = ()
    packet_findings: tuple[Finding, ...] = ()
    current_geometry: Mapping[str, str | None] = field(default_factory=dict)
    files: Mapping[str, FileState] = field(default_factory=dict)
    bundle_seals: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    path_verdicts: Mapping[PathQuery, Verdict] = field(default_factory=dict)
