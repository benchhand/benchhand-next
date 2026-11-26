"""Sealed history read through an in-memory upgrade.

Migrate never rewrites `hw/versions/**` or `hw/checks/**` (docs/contract/record-migration.md), so a migrated
project keeps the packets and snapshots of its built versions at the prototype's record_version. The evidence
reader upgrades what it reads here, after it has checked the seal on the bytes on disk, and never writes the
result back: a digest states the bytes on disk.

A snapshot document is upgraded by migrate's own rules (`rules.rewrite`), run on the document under the
`hw/` path it had in the project it was copied from. A packet differs from its record version 3 form in
`record_version` only: no rule names a packet, because a rule edits a file in the project, so the one change
is made here, on the parsed document.
"""

from __future__ import annotations

from typing import Any

from benchhand_core.record.errors import RECORD_VERSION, SOURCE_VERSIONS
from benchhand_core.record.finding import Severity
from benchhand_core.record.formats import FormatError, parse_yaml
from benchhand_core.record.migrate.rules import rewrite


class UpgradeError(Exception):
    """A sealed document the migrate rules cannot upgrade."""


def source_version(data: Any) -> int | None:
    """The record_version of a document when it is one the migration converts (the prototype's), else None."""
    found = data.get("record_version") if isinstance(data, dict) else None
    if isinstance(found, bool) or found not in SOURCE_VERSIONS:
        return None
    return found


def snapshot_is_source_form(product_text: str) -> bool:
    """Whether a snapshot's product.yaml says the snapshot was built at a record version the migration converts."""
    try:
        return source_version(parse_yaml(product_text)) is not None
    except FormatError:
        return False


def upgrade_snapshot_document(relative: str, text: str) -> str:
    """The text of the snapshot document at `relative` (a path inside the snapshot, such as `product.yaml`),
    upgraded by every migrate rule that names `hw/<relative>`. UpgradeError when a rule cannot read it or
    refuses it."""
    path = f"hw/{relative}"
    rewritten = rewrite(path, text)
    if rewritten.unreadable is not None:
        raise UpgradeError(f"cannot upgrade {relative}: {rewritten.unreadable}")
    for finding in rewritten.findings:
        if finding.severity == Severity.error:
            where = finding.pointer or "/"
            raise UpgradeError(f"cannot upgrade {relative} at {where}: {finding.code}: {finding.message}")
    return rewritten.text


def upgrade_packet(data: Any) -> Any:
    """A packet at a record version the migration converts, as record version 3: a copy with the new
    record_version. Any other document is returned as it is."""
    if source_version(data) is None:
        return data
    return {**data, "record_version": RECORD_VERSION}
