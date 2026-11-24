"""validate(): every finding on a project's record, without changing a file.

It reports what reading met (presence, readability, record_version, contracts, part directory names,
decision file names) and the core cross-references between documents that each contract alone cannot state.
"""

from __future__ import annotations

from pathlib import Path

from benchhand_core.record import contracts, documents
from benchhand_core.record.errors import RecordMissingError
from benchhand_core.record.finding import Finding
from benchhand_core.record.rules import bom, decisions, drawing, interfaces, verification
from benchhand_core.record.rules.assembly import Inventory, inventory, joints
from benchhand_core.record.store import RecordRead, read_record

PARTS_FROM_STAGE = "layout"


def _no_parts(read: RecordRead) -> list[Finding]:
    """From the layout stage on, or at a stage the record does not name, the record has parts."""
    parts_unread = any(error.path.startswith(documents.PARTS_DIR) for error in read.errors)
    if read.parts or read.product is None or parts_unread:
        return []
    stages = contracts.schema("common")["$defs"]["stage"]["enum"]
    stage = read.product["flow"]["stage"]
    if stages.index(stage) < stages.index(PARTS_FROM_STAGE):
        return []
    message = f"no part records found; the {stage} stage needs {documents.PARTS_DIR}/<PN>/part.yaml"
    return [Finding("record.no_parts", documents.PARTS_DIR, message)]


def _placement(read: RecordRead) -> tuple[Inventory | None, list[Finding]]:
    if read.assembly is None:
        return None, []
    placed, findings = inventory(read.assembly, frozenset(read.parts))
    return placed, findings + joints(read.assembly, placed)


def validate(root: Path) -> list[Finding]:
    """Every finding on the record of the project at `root`; an error blocks, a warning or info never does."""
    if not (root / documents.HW).is_dir():
        return RecordMissingError(documents.HW, "the project has no hw/ directory").findings()
    read = read_record(root)
    findings = [finding for error in read.errors for finding in error.findings()]
    findings.extend(_no_parts(read))
    findings.extend(decisions.check(read))
    placed, placement_findings = _placement(read)
    findings.extend(placement_findings)
    if read.interfaces is not None and placed is not None:
        findings.extend(interfaces.check(read.interfaces, placed))
    if read.bom is not None:
        findings.extend(bom.check(read.bom, read.parts, placed))
    if read.verification is not None and read.requirements is not None:
        findings.extend(verification.check(read.verification, read.requirements))
    if read.product is not None:
        findings.extend(drawing.check(read.product, read.parts))
    return findings
