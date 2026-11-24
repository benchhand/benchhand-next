"""The assembly's occurrence inventory, and the joints whose parent and child reference it.

An occurrence is one placement of one part. `assembly.yaml` lists explicit occurrences under `occurrences`
and joins them to subassemblies by `@id`. A PN in a subassembly's `parts` list is one implicit occurrence
at the identity placement, whose id is the PN. A reference is `@id`, or a bare PN that has exactly one
occurrence.
"""

from __future__ import annotations

import graphlib
import math
from collections.abc import Mapping
from dataclasses import dataclass

from benchhand_contracts.models.record import assembly_schema
from benchhand_contracts.models.record.part_schema import ModelFrame

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import Assembly, Part

ASSEMBLY = documents.ASSEMBLY.path

Joint = assembly_schema.Joints | assembly_schema.Joints1
Subassembly = assembly_schema.Subassemblies | assembly_schema.Subassemblies1


@dataclass(frozen=True)
class Occurrence:
    id: str
    pn: str
    explicit: bool  # listed under occurrences; False for a PN in a subassembly's parts list (id == PN)
    identity: bool = True  # placed with no translation and no rotation

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
    return error(code, ASSEMBLY, message, pointer=pointer(*parts), subject=subject)


def _is_identity(placement: assembly_schema.Placement | None) -> bool:
    if placement is None:
        return True
    still = placement.translation_mm is None or all(value == 0 for value in placement.translation_mm)
    turned = placement.rotation is not None and math.remainder(placement.rotation.angle_deg, 360.0) != 0
    return still and not turned


def _explicit(
    assembly: Assembly, part_numbers: frozenset[str], findings: list[Finding]
) -> dict[str, Occurrence]:
    explicit: dict[str, Occurrence] = {}
    for index, raw in enumerate(assembly.occurrences or []):
        occurrence = Occurrence(raw.id, raw.pn, explicit=True, identity=_is_identity(raw.placement))
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


def _members(subassembly: Subassembly, index: int, explicit: dict[str, Occurrence]) -> Members:
    """The occurrences a subassembly holds. A PN in its parts list needs no part record yet: the project
    template's placeholder has none until the parts stage."""
    members: list[Occurrence] = []
    findings: list[Finding] = []
    explicit_pns = {occurrence.pn for occurrence in explicit.values()}
    for position, pn in enumerate(subassembly.parts or []):
        where = ("subassemblies", index, "parts", position)
        if pn in explicit_pns:
            message = f"{pn} has explicit occurrences; list them under occurrences instead of parts"
            findings.append(_error("assembly.occurrence", message, *where, subject=pn))
        else:
            members.append(Occurrence(pn, pn, explicit=False))
    for position, ref in enumerate(subassembly.occurrences or []):
        if ref[1:] in explicit:
            members.append(explicit[ref[1:]])
        else:
            where = ("subassemblies", index, "occurrences", position)
            findings.append(_error("assembly.occurrence", f"{ref} names no occurrence", *where))
    return members, findings


def _frames(placed: Inventory, parts: Mapping[str, Part]) -> list[Finding]:
    """A part modelled in assembly_zero (the default) is already in assembly coordinates, so it is placed
    once, at the identity placement; a placed or repeated part is modelled part_local."""
    findings: list[Finding] = []
    for pn, part in parts.items():
        occurrences = placed.of(pn)
        if part.model_frame is ModelFrame.part_local or not occurrences:
            continue
        path = documents.part(pn).path
        if len(occurrences) > 1:
            message = (
                f"{pn} is placed {len(occurrences)} times but its model_frame is assembly_zero; "
                "a repeated part is modelled part_local"
            )
            findings.append(error("assembly.model_frame", path, message, subject=pn))
        elif not occurrences[0].identity:
            message = (
                f"{occurrences[0].ref} has a non-identity placement but {pn}'s model_frame is assembly_zero; "
                "a placed part is modelled part_local"
            )
            findings.append(error("assembly.model_frame", path, message, subject=pn))
    return findings


def inventory(assembly: Assembly, parts: Mapping[str, Part]) -> tuple[Inventory, list[Finding]]:
    """The inventory of a contract-valid assembly.yaml, and each problem that leaves a reference open or
    places a part its model frame does not allow."""
    findings: list[Finding] = []
    explicit = _explicit(assembly, frozenset(parts), findings)
    occurrences: dict[str, Occurrence] = {}
    group_of: dict[str, str] = {}
    for index, subassembly in enumerate(assembly.subassemblies):
        members, problems = _members(subassembly, index, explicit)
        findings.extend(problems)
        for occurrence in members:
            if occurrence.explicit and occurrence.id in group_of:
                message = f"{occurrence.ref} belongs to both {group_of[occurrence.id]} and {subassembly.id}"
                findings.append(_error("assembly.occurrence", message, "subassemblies", index, "occurrences"))
            group_of.setdefault(occurrence.id, subassembly.id)
            occurrences.setdefault(occurrence.id, occurrence)
    for index, raw in enumerate(assembly.occurrences or []):
        if raw.id not in group_of:
            message = f"@{raw.id} belongs to no subassembly"
            findings.append(_error("assembly.occurrence", message, "occurrences", index))
    placed = Inventory(occurrences, frozenset(parts))
    return placed, findings + _frames(placed, parts)


def _ends(joint: Joint, index: int, placed: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    ends: list[Occurrence] = []
    for end in ("parent", "child"):
        found = placed.resolve(getattr(joint, end))
        if isinstance(found, str):
            findings.append(
                _error("assembly.joint_reference", f"{joint.id} {end}: {found}", "joints", index, end)
            )
        else:
            ends.append(found)
    if len(ends) == 2 and ends[0] == ends[1]:
        message = f"{joint.id}: parent and child are both {ends[0].ref}"
        findings.append(_error("assembly.joint_reference", message, "joints", index, "child"))
    return findings


def _limits(joint: Joint, index: int) -> list[Finding]:
    if joint.min > joint.max:
        message = f"{joint.id}: minimum {joint.min} exceeds maximum {joint.max}"
        return [_error("assembly.joint_limits", message, "joints", index, "min")]
    if joint.nominal is not None and not joint.min <= joint.nominal <= joint.max:
        message = f"{joint.id}: nominal {joint.nominal} is outside [{joint.min}, {joint.max}]"
        return [_error("assembly.joint_limits", message, "joints", index, "nominal")]
    return []


def _coupling(joint: Joint, index: int, assembly: Assembly) -> list[Finding]:
    """A coupled joint's driver is another joint, and the profile or mechanism it names exists."""
    coupling = joint.coupling
    where = ("joints", index, "coupling")
    problems: list[tuple[str, str]] = []
    if isinstance(coupling, assembly_schema.Coupling1 | assembly_schema.Coupling2):
        if coupling.driver == joint.id:
            problems.append(("driver", f"{joint.id} is coupled to itself"))
        elif coupling.driver not in {other.id for other in assembly.joints}:
            problems.append(("driver", f"driver {coupling.driver} is not a joint of this assembly"))
    if isinstance(coupling, assembly_schema.Coupling2) and coupling.profile not in (assembly.profiles or {}):
        problems.append(("profile", f"profile {coupling.profile!r} is not in `profiles`"))
    if isinstance(coupling, assembly_schema.Coupling3) and coupling.mechanism not in {
        mechanism.id for mechanism in assembly.mechanisms or []
    }:
        problems.append(("mechanism", f"mechanism {coupling.mechanism!r} is not in `mechanisms`"))
    return [
        _error("assembly.coupling", f"{joint.id} coupling: {message}", *where, key)
        for key, message in problems
    ]


def _coupling_cycle(assembly: Assembly) -> list[Finding]:
    """A coupling cycle: following each joint's driver leads back to it. A self-coupling is reported by
    `_coupling` instead."""
    mechanisms = {mechanism.id: mechanism.driver for mechanism in assembly.mechanisms or []}
    joint_ids = {joint.id for joint in assembly.joints}
    drivers: dict[str, set[str]] = {}
    for joint in assembly.joints:
        coupling = joint.coupling
        if isinstance(coupling, assembly_schema.Coupling1 | assembly_schema.Coupling2):
            driver = coupling.driver
        elif isinstance(coupling, assembly_schema.Coupling3):
            driver = mechanisms.get(coupling.mechanism)
        else:
            continue
        if driver in joint_ids and driver != joint.id:
            drivers[joint.id] = {driver}
    try:
        tuple(graphlib.TopologicalSorter(drivers).static_order())
    except graphlib.CycleError as error:
        cycle = error.args[1]
        index = next(index for index, joint in enumerate(assembly.joints) if joint.id == cycle[0])
        message = f"coupling cycle: {' -> '.join(cycle)} (each joint drives the next)"
        return [_error("assembly.coupling", message, "joints", index, "coupling")]
    return []


def joints(assembly: Assembly, placed: Inventory) -> list[Finding]:
    """Each joint's parent and child resolve to two occurrences, its nominal lies within its limits, and a
    coupling names a driver, profile or mechanism the assembly has, in no cycle of drivers."""
    findings: list[Finding] = []
    for index, joint in enumerate(assembly.joints):
        findings.extend(
            [*_ends(joint, index, placed), *_limits(joint, index), *_coupling(joint, index, assembly)]
        )
    return findings + _coupling_cycle(assembly)
