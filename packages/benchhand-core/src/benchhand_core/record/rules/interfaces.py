# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""interfaces.yaml references to parts and occurrences: clearance pairs, fits, heat-set inserts, `@` ends."""

from __future__ import annotations

from collections.abc import Sequence

from benchhand_contracts.models.record import common_schema, drawing_schema, interfaces_schema

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import Interfaces
from benchhand_core.record.rules.assembly import Inventory, Occurrence

INTERFACES = documents.INTERFACES.path
FITS = ("press_fit", "running_fit", "locating_fit")


Pair = frozenset[str]
PartRef = common_schema.Pn | common_schema.OccurrenceRef
Fit = drawing_schema.Fit1 | drawing_schema.Fit2


def _error(code: str, message: str, *parts: str | int) -> Finding:
    return error(code, INTERFACES, message, pointer=pointer(*parts))


def _pair(pair: Sequence[PartRef], placed: Inventory, *where: str | int) -> tuple[list[Finding], Pair | None]:
    """The findings on a two-reference pair, and the ids of its two occurrences when both resolve apart."""
    refs = [ref.root for ref in pair]
    findings: list[Finding] = []
    ends: list[Occurrence] = []
    for position, ref in enumerate(refs):
        found = placed.resolve(ref)
        if isinstance(found, str):
            findings.append(_error("interface.reference", found, *where, position))
        else:
            ends.append(found)
    if len(ends) == 2 and ends[0] == ends[1]:
        message = f"{refs[0]} and {refs[1]} are the same occurrence {ends[0].ref}"
        findings.append(_error("interface.pair", message, *where))
        return findings, None
    return findings, frozenset(end.id for end in ends) if len(ends) == 2 else None


def _fit(fit: Fit, placed: Inventory, *where: str | int) -> list[Finding]:
    if fit.pair is not None:
        return _pair(fit.pair, placed, *where, "pair")[0]
    findings: list[Finding] = []
    ends: list[Occurrence] = []
    for role in ("hole", "shaft"):
        endpoint: drawing_schema.FitEndpoint = getattr(fit, role)
        found = placed.endpoint(endpoint.pn, endpoint.occurrence)
        if isinstance(found, str):
            findings.append(_error("interface.reference", found, *where, role))
        else:
            ends.append(found)
    if len(ends) == 2 and ends[0] == ends[1]:
        message = f"hole and shaft are both on {ends[0].ref}"
        findings.append(_error("interface.pair", message, *where))
    return findings


def _limits(limits: interfaces_schema.Limits | None, placed: Inventory, index: int) -> list[Finding]:
    findings: list[Finding] = []
    if limits is None:
        return findings
    for kind in FITS:
        if (fit := getattr(limits, kind)) is not None:
            findings.extend(_fit(fit, placed, "interfaces", index, "limits", kind))
    for position, insert in enumerate(limits.heat_set or []):
        where = ("interfaces", index, "limits", "heat_set", position, "pair")
        findings.extend(_pair(insert.pair, placed, *where)[0])
    return findings


def _ends(interface: interfaces_schema.Interface, placed: Inventory, index: int) -> list[Finding]:
    """`from` and `to` are descriptive unless they start with @, which must name an occurrence."""
    findings: list[Finding] = []
    for end, ref in (("from", interface.from_), ("to", interface.to)):
        if ref.startswith("@") and isinstance(found := placed.resolve(ref), str):
            findings.append(_error("interface.reference", found, "interfaces", index, end))
    return findings


def check(interfaces: Interfaces, placed: Inventory) -> list[Finding]:
    """Every part and occurrence reference in interfaces.yaml resolves, and an occurrence pair has at most
    one clearance requirement."""
    findings: list[Finding] = []
    clearances: dict[Pair, int] = {}
    for index, interface in enumerate(interfaces.interfaces):
        findings.extend(_ends(interface, placed, index))
        if interface.pair is not None:
            problems, pair = _pair(interface.pair, placed, "interfaces", index, "pair")
            findings.extend(problems)
            if pair is not None and pair in clearances:
                earlier = clearances[pair]
                message = f"{interface.id}: the pair already has a clearance at interfaces/{earlier}"
                findings.append(_error("interface.pair", message, "interfaces", index, "pair"))
            elif pair is not None:
                clearances[pair] = index
        findings.extend(_limits(interface.limits, placed, index))
    return findings
