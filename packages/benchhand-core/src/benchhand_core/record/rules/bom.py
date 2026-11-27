# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""bom.csv against the part records: every row names a part or an assembly, states what its part record
states, keeps a level sequence, and counts what assembly.yaml places.

A commodity item (screw, nut, washer, dowel, O-ring, heat-set insert) is bought by designation: any supplier of
the standard or family will do. The part record carries it as `purchase.designation` on its purchased route
operation. `designation_problem` decides whether such a designation identifies the item, and `designation_cell`
is the designation column a BOM row states for a part, so the BOM and its validation read one lookup."""

from __future__ import annotations

import re
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


# Families no ISO standard defines, each with the fields an order line needs.
KNOWN_FAMILIES: dict[str, tuple[str, ...]] = {
    "heat_set_insert": ("thread", "length", "outside_diameter", "recommended_hole"),
}
# Standards that define a feature (a thread, a fit, a tolerance), not a part.
FEATURE_STANDARDS = (
    "ISO 965",
    "ISO 261",
    "ISO 262",
    "ISO 68",
    "ISO 286",
    "ISO 2768",
    "ISO 1101",
    "ASME Y14.5",
    "ASME B1.1",
)
# Part standards of items without a length: nuts and washers.
NO_LENGTH_STANDARDS = frozenset(
    {
        *("ISO 4032", "ISO 4033", "ISO 4034", "ISO 4035", "ISO 8673", "ISO 8674", "ISO 8675", "ISO 7040"),
        *("ISO 7041", "ISO 7089", "ISO 7090", "ISO 7091", "ISO 7092", "ISO 7093-1", "ISO 7094"),
        *("DIN 934", "DIN 985", "DIN 125", "DIN 9021", "DIN 127"),
    }
)
NOT_APPLICABLE = "not_applicable"
# Screw, bolt and nut standards whose size is a thread designation (M6, #10-24, 1/4-20). For these a bare number
# such as 8.8 is not a size: it reads as a property class. Every other standard (a washer, a ring, a pin) keeps a
# bare decimal as its size.
THREADED_FASTENERS = {
    "ISO 4762": "hexagon socket head cap screws, M1.6 to M64",
    "ISO 4014": "hexagon head bolts, product grades A and B",
    "ISO 4017": "hexagon head screws, product grades A and B",
    "ISO 7380": "button head screws with hexagon socket",
    "ISO 10642": "countersunk head screws with hexagon socket",
    "ISO 4032": "hexagon regular nuts (style 1), product grades A and B",
    "DIN 912": "hexagon socket head cap screws",
    "DIN 933": "hexagon head screws, fully threaded",
    "DIN 934": "hexagon nuts",
}
_FEATURE = tuple(tuple(entry.split(" ", 1)) for entry in FEATURE_STANDARDS)
_THREADED = tuple(tuple(entry.split(" ", 1)) for entry in THREADED_FASTENERS)
_SUFFIX = re.compile(r"(?:-\d+)+$")
# A thread designation: M6 (metric, coarse pitch by default), or #10-24 and 1/4-20 (threads per inch).
_THREAD_SIZE = re.compile(r"(?:M\d|#\d+-\d|\d+/\d+-\d)")

# The standards bodies a designation may name, alone or combined (DIN EN ISO 4017, ISO/EN/DIN 898-1).
_BODY = "DIN|ISO|EN|ASME|ANSI"
_NUMBER = r"[A-Z]?\d+(?:\.\d+)*(?:-\d+)*"
_TIMES = r"\s*[x\u00d7]\s*\d+(?:\.\d+)?"
# A size is a metric or unified designator (M5, #10-24), or a number pair (5x0.6), with an optional tolerance class
# after the diameter (ISO 2338 - 5 m6 x 20). The standard's own number alone (DIN 471) is not one.
_FIT = r"(?:\s*[a-zA-Z]{1,2}\d{1,2})?"
_SIZE = rf"(?:[M#]\d+(?:\.\d+)?(?:-\d+)?(?:{_TIMES})?|\d+(?:[./]\d+)*(?:-\d+)?{_FIT}{_TIMES})(?!\d)"
# A bare nominal size (ISO 7089 - 5, ASME B18.2.2 1/4-20) is a whole token after the standard number: a number, a
# fraction or a thread, an optional series (UNC, UNF, UNEF), then a space, a delimiter or the end. A number before a
# hardness unit (200 HV) is a grade, and a stainless class (A2-70) starts with a letter, so neither is a size.
_HARDNESS_UNIT = r"HV|HB[WS]?|HR[ABC]"
_BARE = (
    r"\d{1,4}(?:\.\d+)?(?:/\d{1,3})?(?:-\d{1,3})?(?:UNEF|UNC|UNF)?(?=\s|$|[,;)\"])"
    rf"(?!\s*(?:{_HARDNESS_UNIT})\b)"
)
STANDARD_DESIGNATION = re.compile(
    rf"(?<![A-Za-z])(?P<bodies>(?:{_BODY})(?:[ /]+(?:{_BODY}))*)\s+(?P<number>{_NUMBER})"
    rf"(?:(?:\s*[-\u2013\u2014]\s*|\s+)(?P<size>{_SIZE})|\s+(?:[-\u2013\u2014]\s+)?(?P<bare>{_BARE}))"
)


def _listed(standard_bodies: str, number: str, entries: tuple[tuple[str, ...], ...]) -> bool:
    """Whether the standard (bodies such as DIN EN ISO, a number such as 965-1) is one of `entries` by body and
    number: ISO 965 covers ISO 965-1, DIN ISO 965-1 and DIN EN ISO 965-1, not DIN 965 (a screw)."""
    bodies = set(re.split(r"[ /]+", standard_bodies))
    root = _SUFFIX.sub("", number)
    return any(body in bodies and root == entry for body, entry in entries)


def is_feature_standard(standard: str) -> bool:
    """Whether `standard` (ISO 965-1, DIN EN ISO 286-2) names a feature standard, which identifies no part."""
    *bodies, number = standard.split()
    return _listed(" ".join(bodies), number, _FEATURE)


def _part_standard(match: re.Match[str]) -> bool:
    """A part standard with a size that fits it: a thread designation for a threaded fastener, any size otherwise."""
    bodies, number = match["bodies"], match["number"]
    if _listed(bodies, number, _FEATURE):
        return False
    size = match["size"] or match["bare"]
    return not _listed(bodies, number, _THREADED) or _THREAD_SIZE.match(size) is not None


def size_problem(standard: str, size: str) -> str | None:
    """Why `size` does not complete `standard` as a whole size, or None: M4 fits ISO 4762, 8.8 (a property class)
    does not."""
    text = f"{standard} {size}"
    for match in STANDARD_DESIGNATION.finditer(text):
        if match.start() == 0 and match.end() == len(text) and _part_standard(match):
            return None
    return f"size {size!r} does not fit {standard}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _missing(designation: Mapping[str, Any], fields: tuple[str, ...]) -> str | None:
    absent = [field for field in fields if designation.get(field) in (None, "")]
    return f"missing {', '.join(absent)}" if absent else None


def _standard_problem(designation: Mapping[str, Any]) -> str | None:
    problem = _missing(designation, ("standard", "size", "length", "property_class"))
    if problem:
        return problem
    standard = str(designation["standard"])
    if is_feature_standard(standard):
        return f"{standard} is a feature standard, not a part standard"
    size = str(designation["size"])
    # The length has its own field: M4 with length 20, never M4x20. This also refuses a fine pitch such as M8x1.
    if re.search(r"[x\u00d7]", size):
        return f"size {size!r} embeds a length; record the length in the length field"
    problem = size_problem(standard, size)
    if problem:
        return problem
    length = designation["length"]
    if length == NOT_APPLICABLE:
        if standard not in NO_LENGTH_STANDARDS:
            return f"{standard} needs a length; not_applicable is for nuts and washers"
    elif not _is_number(length):
        return "length must be a positive number"
    return None


def _family_problem(designation: Mapping[str, Any]) -> str | None:
    family = designation.get("family")
    if family not in KNOWN_FAMILIES:
        return f"family {family!r} is not a known commodity family ({', '.join(sorted(KNOWN_FAMILIES))})"
    fields = KNOWN_FAMILIES[family]
    problem = _missing(designation, fields)
    if problem:
        return problem
    bad = [field for field in fields[1:] if not _is_number(designation[field])]
    return f"{', '.join(bad)} must be a positive number" if bad else None


def designation_problem(designation: Any) -> str | None:
    """Why `designation` (a `purchase.designation`) does not identify a commodity item, or None when it does."""
    if not isinstance(designation, Mapping):
        return "kind: no structured designation"
    kind = designation.get("kind")
    if kind == "standard_designation":
        return _standard_problem(designation)
    if kind == "family_designation":
        return _family_problem(designation)
    return f"kind {kind!r} is not a commodity designation"


def _number(value: Any) -> str:
    return f"{value:g}"


def designation_text(designation: Mapping[str, Any]) -> str:
    """One order line: `ISO 4762 M4x20, 8.8, A2` or `heat_set_insert M3x5.7, OD 4.6, hole 4`."""
    if designation.get("kind") == "family_designation":
        parts = [
            f"{designation['family']} {designation['thread']}x{_number(designation['length'])}",
            f"OD {_number(designation['outside_diameter'])}",
            f"hole {_number(designation['recommended_hole'])}",
        ]
        parts += [str(designation[key]) for key in ("material", "finish") if designation.get(key)]
        return ", ".join(parts)
    length = designation["length"]
    head = f"{designation['standard']} {designation['size']}"
    if length != NOT_APPLICABLE:
        head += f"x{_number(length)}"
    finish = [str(designation["finish"])] if designation.get("finish") else []
    return ", ".join([head, str(designation["property_class"]), *finish])


def _purchase(part: Mapping[str, Any]) -> Mapping[str, Any]:
    """The `purchase` of the part's first purchased route operation, or an empty mapping."""
    intent = part.get("intent")
    route = intent.get("route") if isinstance(intent, Mapping) else None
    for operation in route if isinstance(route, list) else ():
        if not isinstance(operation, Mapping) or operation.get("kind") != "purchased":
            continue
        purchase = operation.get("purchase")
        if isinstance(purchase, Mapping):
            return purchase
    return {}


def commodity_label(part: Mapping[str, Any]) -> str | None:
    """The order line of a part (its JSON) bought by commodity designation, or None when it is not one: its first
    purchased operation has no eligible designation, or the record leaves an identity field open
    (`procurement.open`), so the item is not settled."""
    designation = _purchase(part).get("designation")
    procurement = part.get("procurement")
    opened = procurement.get("open") if isinstance(procurement, Mapping) else None
    if not isinstance(designation, Mapping) or designation_problem(designation) is not None or opened:
        return None
    return designation_text(designation)


def designation_cell(part: Mapping[str, Any]) -> str | None:
    """The designation column of a BOM row for `part` (its JSON): the text the record states in
    `procurement.designation`, else the order line of an eligible commodity designation, else None."""
    procurement = part.get("procurement")
    text = procurement.get("designation") if isinstance(procurement, Mapping) else None
    return text or commodity_label(part)


def procurement_cells(part: dict[str, Any]) -> dict[str, Any]:
    """The procurement columns a BOM row states for `part` (its JSON); `unit` names what qty counts."""
    procurement = part.get("procurement", {})
    specification = procurement.get("specification", {})
    return {
        "unit": "pcs",
        "designation": designation_cell(part),
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
