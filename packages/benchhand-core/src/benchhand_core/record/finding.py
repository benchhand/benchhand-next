"""Findings: the generated model of contracts/common/finding.schema.json, and JSON Pointers into documents."""

from __future__ import annotations

from typing import TypedDict, Unpack

from benchhand_contracts import Finding
from benchhand_contracts.models.common.finding_schema import Severity

__all__ = ["Finding", "Severity", "error", "info", "pointer"]


class FindingFields(TypedDict, total=False):
    """The optional fields of a finding; a field left out (or None) is absent, as the contract has no null."""

    pointer: str | None
    subject: str | None
    action: str | None


def _finding(severity: Severity, code: str, path: str, message: str, optional: FindingFields) -> Finding:
    present: dict[str, str] = {name: value for name, value in optional.items() if isinstance(value, str)}
    return Finding(code=code, severity=severity, path=path, message=message, **present)


def error(code: str, path: str, message: str, **optional: Unpack[FindingFields]) -> Finding:
    """A blocking finding."""
    return _finding(Severity.error, code, path, message, optional)


def info(code: str, path: str, message: str, **optional: Unpack[FindingFields]) -> Finding:
    """A finding that never blocks."""
    return _finding(Severity.info, code, path, message, optional)


def pointer(*parts: str | int) -> str:
    """The JSON Pointer (RFC 6901) of the path `parts` into a document."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)
