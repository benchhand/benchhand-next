"""interfaces.yaml references to parts and occurrences: clearance pairs, fits, heat-set inserts, `@` ends."""

from __future__ import annotations

from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, pointer
from benchhand_core.record.rules.assembly import Inventory, Occurrence

INTERFACES = documents.INTERFACES.path
FITS = ("press_fit", "running_fit", "locating_fit")


Pair = frozenset[str]


def _error(code: str, message: str, *parts: str | int) -> Finding:
    return Finding(code=code, path=INTERFACES, pointer=pointer(*parts), message=message)


def _pair(refs: list[str], placed: Inventory, *where: str | int) -> tuple[list[Finding], Pair | None]:
    """The findings on a two-reference pair, and the ids of its two occurrences when both resolve apart."""
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


def _fit(fit: Any, placed: Inventory, *where: str | int) -> list[Finding]:
    if "pair" in fit:
        return _pair(fit["pair"], placed, *where, "pair")[0]
    findings: list[Finding] = []
    ends: list[Occurrence] = []
    for role in ("hole", "shaft"):
        endpoint = fit[role]
        found = placed.endpoint(endpoint["PN"], endpoint.get("occurrence"))
        if isinstance(found, str):
            findings.append(_error("interface.reference", found, *where, role))
        else:
            ends.append(found)
    if len(ends) == 2 and ends[0] == ends[1]:
        message = f"hole and shaft are both on {ends[0].ref}"
        findings.append(_error("interface.pair", message, *where))
    return findings


def _limits(limits: Any, placed: Inventory, index: int) -> list[Finding]:
    findings: list[Finding] = []
    for kind in FITS:
        if kind in limits:
            findings.extend(_fit(limits[kind], placed, "interfaces", index, "limits", kind))
    for position, insert in enumerate(limits.get("heat_set", [])):
        where = ("interfaces", index, "limits", "heat_set", position, "pair")
        findings.extend(_pair(insert["pair"], placed, *where)[0])
    return findings


def _ends(interface: Any, placed: Inventory, index: int) -> list[Finding]:
    """`from` and `to` are descriptive unless they start with @, which must name an occurrence."""
    findings: list[Finding] = []
    for end in ("from", "to"):
        ref = interface[end]
        if ref.startswith("@") and isinstance(found := placed.resolve(ref), str):
            findings.append(_error("interface.reference", found, "interfaces", index, end))
    return findings


def check(interfaces: Any, placed: Inventory) -> list[Finding]:
    """Every part and occurrence reference in interfaces.yaml resolves, and an occurrence pair has at most
    one clearance requirement."""
    findings: list[Finding] = []
    clearances: dict[Pair, int] = {}
    for index, interface in enumerate(interfaces["interfaces"]):
        findings.extend(_ends(interface, placed, index))
        if "pair" in interface:
            problems, pair = _pair(interface["pair"], placed, "interfaces", index, "pair")
            findings.extend(problems)
            if pair is not None and pair in clearances:
                earlier = clearances[pair]
                message = f"{interface['id']}: the pair already has a clearance at interfaces/{earlier}"
                findings.append(_error("interface.pair", message, "interfaces", index, "pair"))
            elif pair is not None:
                clearances[pair] = index
        findings.extend(_limits(interface.get("limits", {}), placed, index))
    return findings
