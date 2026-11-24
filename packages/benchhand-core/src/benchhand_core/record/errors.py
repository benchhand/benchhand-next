"""Typed record errors. Each names the project-relative file and turns into findings with stable codes."""

from __future__ import annotations

from benchhand_core.record.contracts import SchemaViolation
from benchhand_core.record.finding import Finding

RECORD_VERSION = 3


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
        return [Finding(code=self.code, path=self.path, message=self.message)]


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
        action = "Use the benchhand release that wrote this record, or migrate it; nothing was changed."
        return [
            Finding(
                code=self.code, path=self.path, pointer="/record_version", message=self.message, action=action
            )
        ]


class RecordSchemaError(RecordError):
    """A document that breaks its contract; each violation carries its document and schema pointers."""

    code = "record.schema"

    def __init__(self, path: str, violations: tuple[SchemaViolation, ...]) -> None:
        first = violations[0]
        super().__init__(path, f"{first.pointer or '/'}: {first.message} ({first.schema_path})")
        self.violations = violations

    def findings(self) -> list[Finding]:
        return [
            Finding(
                code=self.code,
                path=self.path,
                pointer=violation.pointer,
                message=f"{violation.message} ({violation.schema_path})",
            )
            for violation in self.violations
        ]
