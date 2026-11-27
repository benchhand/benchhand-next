# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""bom.csv against the part records: every row names a part or an assembly, states what its part record
states, keeps a level sequence, and counts what assembly.yaml places."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import BomRow, Part, as_json
from benchhand_core.record.rules.assembly import Inventory

BOM = documents.BOM.path
PART_COLUMNS = ("rev", "title", "material", "process", "make_buy", "supplier")


def _error(code: str, message: str, *parts: str | int, subject: str | None = None) -> Finding:
    return error(code, BOM, message, pointer=pointer(*parts), subject=subject)


def procurement_cells(part: dict[str, Any]) -> dict[str, Any]:
    """The procurement columns a BOM row states for `part` (its JSON); `unit` names what qty counts."""
    procurement = part.get("procurement", {})
    specification = procurement.get("specification", {})
    return {
        "unit": "pcs",
        "designation": procurement.get("designation"),
        "manufacturer": procurement.get("manufacturer"),
        "manufacturer_part_number": procurement.get("manufacturer_part_number"),
        "supplier_part_number": procurement.get("supplier_part_number"),
        "specification_reference": specification.get("reference"),
        "specification_revision": specification.get("revision"),
    }


def _stated(part: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """What `row` must state, column by column, for `part` (both as JSON)."""
    stated = {column: part.get(column) for column in PART_COLUMNS}
    stated["mass"] = part["mass_target"]
    if "unit" in row:
        stated.update(procurement_cells(part))
    return stated


def _row(rows: list[BomRow], index: int, parts: Mapping[str, Part]) -> list[Finding]:
    row = rows[index]
    pn = row.pn
    part_path = documents.part(pn).path
    if pn not in parts:
        is_assembly = row.level == 0 or (index + 1 < len(rows) and rows[index + 1].level > row.level)
        if is_assembly:
            return []
        message = f"BOM PN {pn} has no {part_path} and is not an assembly"
        return [_error("bom.unknown_part", message, index, "PN", subject=pn)]
    findings: list[Finding] = []
    cells = as_json(row)
    for column, value in _stated(as_json(parts[pn]), cells).items():
        if cells.get(column) != value:
            message = f"{column} {cells.get(column)!r} does not match {part_path} ({value!r})"
            findings.append(_error("bom.mismatch", message, index, column, subject=pn))
    return findings


def _levels(rows: list[BomRow]) -> list[Finding]:
    findings: list[Finding] = []
    previous: int | None = None
    for index, row in enumerate(rows):
        level = row.level
        if (level not in (0, 1)) if previous is None else (level > previous + 1):
            message = f"level {level} must start at 0 or 1 and cannot skip a parent depth"
            findings.append(_error("bom.level", message, index, "level"))
        previous = level
    return findings


def totals(rows: list[BomRow]) -> dict[str, int]:
    """The assembled quantity of each PN: each row's qty times the qty of every parent row above it."""
    quantities: dict[str, int] = {}
    parents: list[tuple[int, int]] = []  # (level, cumulative quantity)
    for row in rows:
        while parents and parents[-1][0] >= row.level:
            parents.pop()
        quantity = row.qty * (parents[-1][1] if parents else 1)
        quantities[row.pn] = quantities.get(row.pn, 0) + quantity
        parents.append((row.level, quantity))
    return quantities


def _quantities(rows: list[BomRow], placed: Inventory) -> list[Finding]:
    """A PN with explicit occurrences has a BOM quantity equal to its number of occurrences; a PN with no
    BOM row counts zero."""
    findings: list[Finding] = []
    quantities = totals(rows)
    explicit_pns = dict.fromkeys(
        occurrence.pn for occurrence in placed.occurrences.values() if occurrence.explicit
    )
    for pn in explicit_pns:
        occurrences = placed.of(pn)
        quantity = quantities.get(pn, 0)
        if quantity == len(occurrences):
            continue
        refs = ", ".join(occurrence.ref for occurrence in occurrences)
        message = f"BOM quantity of {pn} is {quantity}, but assembly.yaml places it {len(occurrences)} times"
        first = next((index for index, row in enumerate(rows) if row.pn == pn), None)
        at = pointer(first, "qty") if first is not None else None
        findings.append(error("bom.quantity", BOM, f"{message} ({refs})", pointer=at, subject=pn))
    return findings


def check(rows: list[BomRow], parts: Mapping[str, Part], placed: Inventory | None) -> list[Finding]:
    findings = [finding for index in range(len(rows)) for finding in _row(rows, index, parts)]
    findings.extend(_levels(rows))
    if placed is not None:
        findings.extend(_quantities(rows, placed))
    return findings
