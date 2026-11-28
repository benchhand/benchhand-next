# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Typed record errors. Each names the project-relative file and turns into findings with stable codes."""

from __future__ import annotations

from benchhand_contracts import ContractViolation

from benchhand_core.record.contracts import shown_location
from benchhand_core.record.finding import Finding, Severity, error

RECORD_VERSION = 3
SOURCE_VERSIONS = (1, 2)  # the prototype's record_version 2, and PR #319's record version 1 (the same format)
MESSAGE_LIMIT = 300


class RecordError(Exception):
    """A record document that cannot be read or written as its contract requires."""

    code = "record.error"

    def __init__(self, path: str, message: str, *, code: str | None = None) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message
        if code is not None:
            self.code = code

    def findings(self) -> list[Finding]:
        return [error(self.code, self.path, self.message)]


class RecordMissingError(RecordError):
    code = "record.missing"

    def __init__(self, path: str, message: str = "required record file is missing") -> None:
        super().__init__(path, message)


class RecordReadError(RecordError):
    """A file that is not readable as its format: YAML, CSV columns, decision front matter or file name."""

    code = "record.unreadable"


class RecordVersionError(RecordError):
    code = "record.version_unsupported"

    def __init__(self, path: str, found: object) -> None:
        shown = "missing" if found is None else repr(found)[:40]
        super().__init__(
            path,
            f"record_version {shown} is not supported; this release reads record_version {RECORD_VERSION}",
        )
        self.found = found

    def findings(self) -> list[Finding]:
        action = "Use the benchhand release that wrote this record; nothing was changed."
        return [
            Finding(
                code=self.code,
                severity=Severity.error,
                path=self.path,
                pointer="/record_version",
                message=self.message,
                action=action,
            )
        ]


class RecordSchemaError(RecordError):
    """A document that breaks its contract; each violation carries its document pointer and the location of
    the failing keyword in the contracts."""

    code = "record.schema"

    def __init__(self, path: str, violations: list[ContractViolation]) -> None:
        first = violations[0]
        super().__init__(path, f"{first.pointer or '/'}: {_described(first)}")
        self.violations = violations

    def findings(self) -> list[Finding]:
        return [
            error(self.code, self.path, _described(violation), pointer=violation.pointer)
            for violation in self.violations
        ]


def _described(violation: ContractViolation) -> str:
    message = violation.message
    if len(message) > MESSAGE_LIMIT:
        message = message[: MESSAGE_LIMIT - 1] + "…"
    where = f" ({shown_location(violation.schema_path)})" if violation.schema_path else ""
    return f"{message}{where}"
