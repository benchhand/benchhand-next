"""A finding: one problem a service reports (contracts/common/finding.schema.json)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# Hand-written until the codegen lane lands; its generated model replaces this class at merge.

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    severity: Severity = "error"
    pointer: str | None = None
    action: str | None = None
    subject: str | None = None

    @property
    def blocking(self) -> bool:
        return self.severity == "error"

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "severity": self.severity, "path": self.path}
        if self.pointer is not None:
            data["pointer"] = self.pointer
        data["message"] = self.message
        if self.action is not None:
            data["action"] = self.action
        if self.subject is not None:
            data["subject"] = self.subject
        return data
