"""bom.csv against the part records: every row names a part or an assembly, states what its part record
states, keeps a level sequence, and counts what assembly.yaml places."""

from __future__ import annotations

from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, pointer
from benchhand_core.record.rules.assembly import Inventory

BOM = documents.BOM.path
PART_COLUMNS = ("rev", "title", "material", "process", "make_buy", "supplier")


def _error(code: str, message: str, *parts: str | int, subject: str | None = None) -> Finding:
    return Finding(code=code, path=BOM, pointer=pointer(*parts), message=message, subject=subject)


def procurement_cells(part: dict[str, Any]) -> dict[str, Any]:
    """The procurement columns a BOM row states for `part`; `unit` names what qty counts."""
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
    """What `row` must state, column by column, for `part`."""
    stated = {column: part.get(column) for column in PART_COLUMNS}
    stated["mass"] = part["mass_target"]
    if "unit" in row:
        stated.update(procurement_cells(part))
    return stated


def _row(rows: list[dict[str, Any]], index: int, parts: dict[str, Any]) -> list[Finding]:
    row = rows[index]
    pn = row["PN"]
    part_path = documents.part(pn).path
    if pn not in parts:
        is_assembly = row["level"] == 0 or (index + 1 < len(rows) and rows[index + 1]["level"] > row["level"])
        if is_assembly:
            return []
        message = f"BOM PN {pn} has no {part_path} and is not an assembly"
        return [_error("bom.unknown_part", message, index, "PN", subject=pn)]
    findings: list[Finding] = []
    for column, value in _stated(parts[pn], row).items():
        if row.get(column) != value:
            message = f"{column} {row.get(column)!r} does not match {part_path} ({value!r})"
            findings.append(_error("bom.mismatch", message, index, column, subject=pn))
    return findings


def _levels(rows: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    previous: int | None = None
    for index, row in enumerate(rows):
        level = row["level"]
        if (level not in (0, 1)) if previous is None else (level > previous + 1):
            message = f"level {level} must start at 0 or 1 and cannot skip a parent depth"
            findings.append(_error("bom.level", message, index, "level"))
        previous = level
    return findings


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """The assembled quantity of each PN: each row's qty times the qty of every parent row above it."""
    quantities: dict[str, int] = {}
    parents: list[tuple[int, int]] = []  # (level, cumulative quantity)
    for row in rows:
        while parents and parents[-1][0] >= row["level"]:
            parents.pop()
        quantity = row["qty"] * (parents[-1][1] if parents else 1)
        quantities[row["PN"]] = quantities.get(row["PN"], 0) + quantity
        parents.append((row["level"], quantity))
    return quantities


def _quantities(rows: list[dict[str, Any]], placed: Inventory) -> list[Finding]:
    """A PN with explicit occurrences has a BOM quantity equal to its number of occurrences."""
    findings: list[Finding] = []
    for pn, quantity in totals(rows).items():
        occurrences = placed.of(pn)
        if occurrences and occurrences[0].explicit and quantity != len(occurrences):
            refs = ", ".join(occurrence.ref for occurrence in occurrences)
            count = len(occurrences)
            message = f"BOM quantity of {pn} is {quantity}, but assembly.yaml places it {count} times"
            first = next(index for index, row in enumerate(rows) if row["PN"] == pn)
            findings.append(_error("bom.quantity", f"{message} ({refs})", first, "qty", subject=pn))
    return findings


def check(rows: list[dict[str, Any]], parts: dict[str, Any], placed: Inventory | None) -> list[Finding]:
    findings = [finding for index in range(len(rows)) for finding in _row(rows, index, parts)]
    findings.extend(_levels(rows))
    if placed is not None:
        findings.extend(_quantities(rows, placed))
    return findings
