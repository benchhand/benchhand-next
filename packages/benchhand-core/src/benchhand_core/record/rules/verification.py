"""verification.csv against requirements.yaml: one row per requirement, and no row for an unknown one."""

from __future__ import annotations

from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, pointer

VERIFICATION = documents.VERIFICATION.path


def check(rows: list[dict[str, Any]], requirements: dict[str, Any]) -> list[Finding]:
    known = [requirement["id"] for requirement in requirements["requirements"]]
    findings: list[Finding] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        requirement = row["requirement"]
        where = pointer(index, "requirement")
        if requirement in seen:
            message = f"{requirement} has more than one verification row"
            findings.append(Finding("verification.duplicate", VERIFICATION, message, pointer=where))
        elif requirement not in known:
            message = f"{requirement} is not a requirement in {documents.REQUIREMENTS.path}"
            findings.append(Finding("verification.unknown_requirement", VERIFICATION, message, pointer=where))
        seen.add(requirement)
    for requirement in known:
        if requirement not in seen:
            message = f"requirement {requirement} has no verification row"
            findings.append(Finding("verification.missing", VERIFICATION, message, subject=requirement))
    return findings
