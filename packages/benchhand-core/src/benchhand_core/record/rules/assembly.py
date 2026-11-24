"""The assembly's occurrence inventory, and the joints whose parent and child reference it.

An occurrence is one placement of one part. `assembly.yaml` lists explicit occurrences under `occurrences`
and joins them to subassemblies by `@id`. A PN in a subassembly's `parts` list is one implicit occurrence
whose id is the PN. A reference is `@id`, or a bare PN that has exactly one occurrence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, pointer

ASSEMBLY = documents.ASSEMBLY.path


@dataclass(frozen=True)
class Occurrence:
    id: str
    pn: str
    explicit: bool  # listed under occurrences; False for a PN in a subassembly's parts list (id == PN)

    @property
    def ref(self) -> str:
        return f"@{self.id}" if self.explicit else self.pn


@dataclass(frozen=True)
class Inventory:
    """Every occurrence in the assembly, by id, and the PNs that have a part record."""

    occurrences: Mapping[str, Occurrence]
    part_numbers: frozenset[str]

    def of(self, pn: str) -> list[Occurrence]:
        return [occurrence for occurrence in self.occurrences.values() if occurrence.pn == pn]

    def resolve(self, ref: str) -> Occurrence | str:
        """The occurrence `ref` names, or why it names none."""
        if ref.startswith("@"):
            occurrence = self.occurrences.get(ref[1:])
            return (
                occurrence if occurrence is not None and occurrence.explicit else f"{ref} names no occurrence"
            )
        found = self.of(ref)
        if len(found) == 1:
            return found[0]
        if found:
            refs = ", ".join(occurrence.ref for occurrence in found)
            return f"{ref} is placed {len(found)} times; name one of {refs}"
        if ref not in self.part_numbers:
            return f"part {ref} does not exist"
        return f"{ref} is not placed in any subassembly"

    def endpoint(self, pn: str, occurrence_ref: str | None) -> Occurrence | str:
        """A feature endpoint's occurrence: `occurrence_ref` if given, which must be an occurrence of `pn`."""
        found = self.resolve(occurrence_ref or pn)
        if isinstance(found, Occurrence) and found.pn != pn:
            return f"{occurrence_ref} is an occurrence of {found.pn}, not {pn}"
        return found


def _error(code: str, message: str, *parts: str | int, subject: str | None = None) -> Finding:
    return Finding(code=code, path=ASSEMBLY, pointer=pointer(*parts), message=message, subject=subject)


def _explicit(assembly: Any, part_numbers: frozenset[str], findings: list[Finding]) -> dict[str, Occurrence]:
    explicit: dict[str, Occurrence] = {}
    for index, raw in enumerate(assembly.get("occurrences", [])):
        occurrence = Occurrence(raw["id"], raw["PN"], explicit=True)
        if occurrence.id in explicit:
            message = f"occurrence id {occurrence.id} is used twice"
            findings.append(_error("assembly.occurrence", message, "occurrences", index, "id"))
            continue
        if occurrence.pn not in part_numbers:
            message = f"occurrence {occurrence.ref}: part {occurrence.pn} does not exist"
            findings.append(
                _error("assembly.unknown_part", message, "occurrences", index, "PN", subject=occurrence.pn)
            )
        explicit[occurrence.id] = occurrence
    return explicit


Members = tuple[list[Occurrence], list[Finding]]


def _members(subassembly: Any, index: int, explicit: dict[str, Occurrence]) -> Members:
    """The occurrences a subassembly holds. A PN in its parts list needs no part record yet: the project
    template's placeholder has none until the parts stage."""
    members: list[Occurrence] = []
    findings: list[Finding] = []
    explicit_pns = {occurrence.pn for occurrence in explicit.values()}
    for position, pn in enumerate(subassembly.get("parts", [])):
        where = ("subassemblies", index, "parts", position)
        if pn in explicit_pns:
            message = f"{pn} has explicit occurrences; list them under occurrences instead of parts"
            findings.append(_error("assembly.occurrence", message, *where, subject=pn))
        else:
            members.append(Occurrence(pn, pn, explicit=False))
    for position, ref in enumerate(subassembly.get("occurrences", [])):
        if ref[1:] in explicit:
            members.append(explicit[ref[1:]])
        else:
            where = ("subassemblies", index, "occurrences", position)
            findings.append(_error("assembly.occurrence", f"{ref} names no occurrence", *where))
    return members, findings


def inventory(assembly: Any, part_numbers: frozenset[str]) -> tuple[Inventory, list[Finding]]:
    """The inventory of a contract-valid assembly.yaml, and each problem that leaves a reference open."""
    findings: list[Finding] = []
    explicit = _explicit(assembly, part_numbers, findings)
    occurrences: dict[str, Occurrence] = {}
    group_of: dict[str, str] = {}
    for index, subassembly in enumerate(assembly["subassemblies"]):
        members, problems = _members(subassembly, index, explicit)
        findings.extend(problems)
        for occurrence in members:
            if occurrence.explicit and occurrence.id in group_of:
                message = (
                    f"{occurrence.ref} belongs to both {group_of[occurrence.id]} and {subassembly['id']}"
                )
                findings.append(_error("assembly.occurrence", message, "subassemblies", index, "occurrences"))
            group_of.setdefault(occurrence.id, subassembly["id"])
            occurrences.setdefault(occurrence.id, occurrence)
    for index, raw in enumerate(assembly.get("occurrences", [])):
        if raw["id"] not in group_of:
            message = f"@{raw['id']} belongs to no subassembly"
            findings.append(_error("assembly.occurrence", message, "occurrences", index))
    return Inventory(occurrences, part_numbers), findings


def _joint(joint: Any, index: int, placed: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    ends: list[Occurrence] = []
    for end in ("parent", "child"):
        found = placed.resolve(joint[end])
        if isinstance(found, str):
            findings.append(
                _error("assembly.joint_reference", f"{joint['id']} {end}: {found}", "joints", index, end)
            )
        else:
            ends.append(found)
    if len(ends) == 2 and ends[0] == ends[1]:
        message = f"{joint['id']}: parent and child are both {ends[0].ref}"
        findings.append(_error("assembly.joint_reference", message, "joints", index, "child"))
    if joint["min"] > joint["max"]:
        message = f"{joint['id']}: minimum {joint['min']} exceeds maximum {joint['max']}"
        findings.append(_error("assembly.joint_limits", message, "joints", index, "min"))
    elif "nominal" in joint and not joint["min"] <= joint["nominal"] <= joint["max"]:
        message = f"{joint['id']}: nominal {joint['nominal']} is outside [{joint['min']}, {joint['max']}]"
        findings.append(_error("assembly.joint_limits", message, "joints", index, "nominal"))
    return findings


def joints(assembly: Any, placed: Inventory) -> list[Finding]:
    """Each joint's parent and child resolve to two occurrences, and its nominal lies within its limits."""
    return [
        finding for index, joint in enumerate(assembly["joints"]) for finding in _joint(joint, index, placed)
    ]
