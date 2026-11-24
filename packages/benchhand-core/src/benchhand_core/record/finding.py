"""Findings: the generated model of contracts/common/finding.schema.json, and JSON Pointers into documents."""

from __future__ import annotations

from benchhand_contracts import Finding
from benchhand_contracts.models.common.finding_schema import Severity

__all__ = ["Finding", "Severity", "error", "pointer"]


def error(
    code: str, path: str, message: str, *, pointer: str | None = None, subject: str | None = None
) -> Finding:
    """A blocking finding; pointer and subject left None are absent, as the contract has no null for them."""
    optional = {"pointer": pointer, "subject": subject}
    present = {name: value for name, value in optional.items() if value is not None}
    return Finding(code=code, severity=Severity.error, path=path, message=message, **present)


def pointer(*parts: str | int) -> str:
    """The JSON Pointer (RFC 6901) of the path `parts` into a document."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)
