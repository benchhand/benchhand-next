"""The acceptance inventory and its digest: what a freeze records and a release checks.

A port of the prototype's evidence.py (skills/cad-record/scripts/evidence.py at release.toml reference_commit
412b5d9): `acceptance_inventory` (lines 1283-1317), `acceptance_digest` (1320-1323), `expected_digest`
(306-308) and the canonical JSON of layout.py:767. The inventory maps hw/<path> to sha256 for the
verification table, the evidence ledger and finding dispositions, every relied-on bundle manifest (cited
evidence bundles, dispositioned producer bundles and the version's packets), every cited evidence artifact,
every source artifact the record names and every file under hw/manufacturing/sources/. Workflow state,
decision records, timestamps and the release itself are never part of it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from benchhand_core.record.evidence.built import FileState
from benchhand_core.record.evidence.fingerprints import record_artifacts
from benchhand_core.record.evidence.view import RecordView, items, mapping

INVENTORY_SCHEMA = "cad-acceptance-inventory/1"
LEDGER_FILES = ("hw/verification.csv", "hw/manufacturing/evidence.yaml", "hw/manufacturing/findings.yaml")
SOURCES_DIR = "hw/manufacturing/sources"
MANIFEST = "manifest.json"


def canonical_sha(value: Any) -> str:
    """sha256 of canonical JSON: sorted keys, no whitespace, UTF-8, no NaN (layout.py:767)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def expected_digest(expected: Iterable[Mapping[str, Any]]) -> str:
    """sha256 of the expected obligations in their contract form (evidence.py:306)."""
    return canonical_sha(list(expected))


def acceptance_digest(inventory: Mapping[str, str]) -> str:
    """evidence_sha256: sha256 of the sorted [path, sha256] pairs, framed by the inventory schema name
    (evidence.py:1320)."""
    pairs = sorted([path, sha] for path, sha in inventory.items())
    return canonical_sha({"schema": INVENTORY_SCHEMA, "files": pairs})


def cited_bundles(record: RecordView) -> set[str]:
    """The sealed bundles (hw/<kind>/<V>/<S>) the ledger entries cite, which must verify in full."""
    found = {mapping(entry.get("bundle")).get("path") for entry in record.evidence}
    return {path for path in found if isinstance(path, str)}


def cited_paths(record: RecordView, bundles: Iterable[str]) -> set[str]:
    """The hw/ paths the inventory needs beside the ledger files and the sources directory: cited
    artifacts and bundle manifests, dispositioned and packet bundle manifests, and named source artifacts."""
    found: set[object] = set()
    for entry in record.evidence:
        found.update(mapping(a).get("path") for a in items(entry.get("artifacts")))
        if isinstance(entry.get("bundle"), Mapping):
            found.add(f"{entry['bundle'].get('path')}/{MANIFEST}")
    for disposition in record.dispositions:
        found.add(f"{mapping(disposition.get('producer')).get('bundle')}/{MANIFEST}")
    found.update(f"{bundle}/{MANIFEST}" for bundle in bundles)
    found.update(f"hw/{rel}" for rel in record_artifacts(record))
    return {path for path in found if isinstance(path, str)}


def inventory_paths(record: RecordView, bundles: Iterable[str], files: Mapping[str, FileState]) -> set[str]:
    """Every hw/ path of the acceptance inventory, given the files the reader found (it lists the ledger
    files that exist and every file below the sources directory)."""
    present = {path for path in LEDGER_FILES if path in files}
    sources = {path for path in files if path == SOURCES_DIR or path.startswith(f"{SOURCES_DIR}/")}
    return cited_paths(record, bundles) | present | sources


def acceptance_inventory(
    record: RecordView, bundles: Iterable[str], files: Mapping[str, FileState]
) -> tuple[dict[str, str] | None, str | None]:
    """(inventory, None), or (None, why it cannot be formed): a path the reader could not read."""
    inventory, problems = {}, []
    for path in sorted(inventory_paths(record, bundles, files)):
        state = files.get(path)
        if state is None or state.sha256 is None:
            problems.append(f"{path} {state.problem if state is not None else 'was not read'}")
        else:
            inventory[path] = state.sha256
    return (None, "; ".join(problems)) if problems else (inventory, None)
