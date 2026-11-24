"""verification.csv against requirements.yaml: one row per requirement, no row for an unknown one, and no
requirement id given twice, which would let one row stand for two requirements."""

from __future__ import annotations

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import Requirements, VerificationRow

VERIFICATION = documents.VERIFICATION.path
REQUIREMENTS = documents.REQUIREMENTS.path


def _duplicate_requirements(requirements: Requirements) -> list[Finding]:
    findings: list[Finding] = []
    first: dict[str, int] = {}
    for index, requirement in enumerate(requirements.requirements):
        if requirement.id in first:
            message = f"{requirement.id} is also the id of requirements/{first[requirement.id]}"
            at = pointer("requirements", index, "id")
            findings.append(
                error("requirements.duplicate", REQUIREMENTS, message, pointer=at, subject=requirement.id)
            )
        first.setdefault(requirement.id, index)
    return findings


def check(rows: list[VerificationRow], requirements: Requirements) -> list[Finding]:
    known = dict.fromkeys(requirement.id for requirement in requirements.requirements)
    findings = _duplicate_requirements(requirements)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        requirement = row.requirement
        where = pointer(index, "requirement")
        if requirement in seen:
            message = f"{requirement} has more than one verification row"
            findings.append(error("verification.duplicate", VERIFICATION, message, pointer=where))
        elif requirement not in known:
            message = f"{requirement} is not a requirement in {REQUIREMENTS}"
            findings.append(error("verification.unknown_requirement", VERIFICATION, message, pointer=where))
        seen.add(requirement)
    for requirement in known:
        if requirement not in seen:
            message = f"requirement {requirement} has no verification row"
            findings.append(error("verification.missing", VERIFICATION, message, subject=requirement))
    return findings
