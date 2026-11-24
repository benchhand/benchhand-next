"""Read and write a project's hw/ record, validated against the record contracts on every read and write.

`read_record` is lenient: it reads every document it can and keeps each problem as a typed error, so
validation can report them all. `load_record` is strict: it raises the first error. `save_record` and
`save_document` validate every document before any file is touched, then replace each file atomically.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from benchhand_core.record import contracts, documents
from benchhand_core.record.documents import DocumentSpec
from benchhand_core.record.errors import (
    RECORD_VERSION,
    RecordError,
    RecordMissingError,
    RecordReadError,
    RecordSchemaError,
    RecordVersionError,
)
from benchhand_core.record.formats import (
    FormatError,
    join_front_matter,
    parse_csv,
    parse_yaml,
    render_csv,
    render_yaml,
    split_front_matter,
)
from benchhand_core.record.model import MANUFACTURING_DOCUMENTS, Decision, JsonObject, Record

DECISION_FILE = re.compile(r"(?P<id>DR-[0-9]{3})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md")


@dataclass
class RecordRead:
    """What `read_record` could read: each document that passed its contract, and every error met."""

    product: JsonObject | None = None
    requirements: JsonObject | None = None
    interfaces: JsonObject | None = None
    assembly: JsonObject | None = None
    bom: list[JsonObject] | None = None
    verification: list[JsonObject] | None = None
    parts: dict[str, JsonObject] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    manufacturing: dict[str, JsonObject] = field(default_factory=dict)
    guidelines: dict[str, JsonObject] = field(default_factory=dict)
    policy: JsonObject | None = None
    errors: list[RecordError] = field(default_factory=list)

    def record(self) -> Record:
        """The complete record, or the first error (an unsupported record version first)."""
        if self.errors:
            versions = [error for error in self.errors if isinstance(error, RecordVersionError)]
            raise (versions or self.errors)[0]
        assert self.product is not None and self.requirements is not None and self.interfaces is not None
        assert self.assembly is not None and self.bom is not None and self.verification is not None
        return Record(
            product=self.product,
            requirements=self.requirements,
            interfaces=self.interfaces,
            assembly=self.assembly,
            bom=self.bom,
            verification=self.verification,
            parts=self.parts,
            decisions=self.decisions,
            manufacturing=self.manufacturing,
            guidelines=self.guidelines,
            policy=self.policy,
        )


# --- validation -----------------------------------------------------------------------------------------


def check_document(spec: DocumentSpec, document: Any) -> None:
    """Raise RecordSchemaError when `document` (a mapping, or the rows of a CSV file) breaks its contract."""
    if spec.format == "csv":
        found = _row_violations(spec.contract, document)
    else:
        found = contracts.violations(spec.contract, document)
    if found:
        raise RecordSchemaError(spec.path, found)


def _row_violations(contract: str, rows: Any) -> tuple[contracts.SchemaViolation, ...]:
    if not isinstance(rows, list):
        return (contracts.SchemaViolation("", "", "rows must be a list"),)
    found = []
    for index, row in enumerate(rows):
        for violation in contracts.violations(contract, row):
            found.append(replace(violation, pointer=f"/{index}{violation.pointer}"))
    return tuple(found)


def check_version(path: str, product: Any) -> None:
    found = product.get("record_version") if isinstance(product, dict) else None
    if isinstance(found, bool) or found != RECORD_VERSION:
        raise RecordVersionError(path, found)


def check_decision(path: str, decision: Decision) -> None:
    contract_violations = contracts.violations(documents.DECISION_CONTRACT, decision.front)
    if contract_violations:
        raise RecordSchemaError(path, contract_violations)
    match = DECISION_FILE.fullmatch(decision.file_name)
    if match is None:
        raise RecordReadError(
            path, f"slug {decision.slug!r} is not lowercase words joined by -", code="decision.file_name"
        )


# --- reading -----------------------------------------------------------------------------------------


def _text(root: Path, path: str) -> str:
    try:
        return (root / path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RecordMissingError(path) from None
    except (OSError, UnicodeDecodeError) as error:
        raise RecordReadError(path, f"cannot read: {str(error)[:200]}") from error


def _parse(spec: DocumentSpec, text: str) -> Any:
    try:
        if spec.format == "csv":
            return parse_csv(text, contracts.schema(spec.contract))
        return parse_yaml(text)
    except FormatError as error:
        raise RecordReadError(spec.path, str(error)) from error


def read_document(root: Path, spec: DocumentSpec) -> Any:
    """One document, checked against its contract; product.yaml also against the record version."""
    document = _parse(spec, _text(root, spec.path))
    if spec == documents.PRODUCT:
        check_version(spec.path, document)
    check_document(spec, document)
    return document


def read_decision(root: Path, file_name: str) -> Decision:
    path = documents.decision_path(file_name)
    match = DECISION_FILE.fullmatch(file_name)
    if match is None:
        raise RecordReadError(path, "a decision record is named DR-###-<slug>.md", code="decision.file_name")
    try:
        front, body = split_front_matter(_text(root, path))
    except FormatError as error:
        raise RecordReadError(path, str(error)) from error
    decision = Decision(slug=match["slug"], front=front, body=body)
    check_decision(path, decision)
    if decision.id != match["id"]:
        raise RecordReadError(
            path, f"front matter id {decision.id} does not match the file name", code="decision.id_mismatch"
        )
    return decision


def _misnamed_part(name: str, pn: str, names: list[str]) -> RecordReadError:
    """The error for parts/<name>/part.yaml whose PN is not its directory name; a PN another directory also
    holds is a duplicate."""
    path = documents.part(name).path
    others = [documents.part(other).path for other in names if other != name]
    if others:
        return RecordReadError(path, f"PN {pn} is also the PN of {', '.join(others)}", code="part.duplicate")
    return RecordReadError(path, f"directory name does not match PN {pn}", code="part.directory_mismatch")


class _Reader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.read = RecordRead()

    def attempt(self, spec: DocumentSpec) -> Any:
        try:
            return read_document(self.root, spec)
        except RecordError as error:
            self.read.errors.append(error)
            return None

    def optional(self, spec: DocumentSpec) -> Any:
        return self.attempt(spec) if (self.root / spec.path).exists() else None

    def parts(self) -> None:
        directory = self.root / documents.PARTS_DIR
        if not directory.is_dir():
            self.read.errors.append(RecordMissingError(documents.PARTS_DIR, "parts directory is missing"))
            return
        found: dict[str, list[str]] = {}
        for part_file in sorted(directory.glob("*/part.yaml")):
            name = part_file.parent.name
            part = self.attempt(documents.part(name))
            if part is not None:
                found.setdefault(part["PN"], []).append(name)
                if part["PN"] == name:
                    self.read.parts[name] = part
        for pn, names in found.items():
            for name in names:
                if name != pn:
                    self.read.errors.append(_misnamed_part(name, pn, names))

    def decisions(self) -> None:
        directory = self.root / documents.DECISIONS_DIR
        names = sorted(path.name for path in directory.glob("DR-*.md")) if directory.is_dir() else []
        for file_name in names:
            try:
                decision = read_decision(self.root, file_name)
            except RecordError as error:
                self.read.errors.append(error)
                continue
            if decision.id in self.read.decisions:
                other = self.read.decisions[decision.id].file_name
                self.read.errors.append(
                    RecordReadError(
                        documents.decision_path(file_name),
                        f"{decision.id} is also the id of {other}",
                        code="decision.duplicate",
                    )
                )
                continue
            self.read.decisions[decision.id] = decision

    def manufacturing(self) -> None:
        for name in MANUFACTURING_DOCUMENTS:
            document = self.optional(documents.manufacturing(name))
            if document is not None:
                self.read.manufacturing[name] = document
        directory = self.root / documents.GUIDELINES_DIR
        for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
            document = self.attempt(documents.guideline(path.stem))
            if document is not None:
                self.read.guidelines[path.stem] = document


def read_record(root: Path) -> RecordRead:
    """Every record document under `root/hw` that reads and meets its contract, and every error met."""
    reader = _Reader(root)
    read = reader.read
    read.product = reader.attempt(documents.PRODUCT)
    read.requirements = reader.attempt(documents.REQUIREMENTS)
    read.interfaces = reader.attempt(documents.INTERFACES)
    read.assembly = reader.attempt(documents.ASSEMBLY)
    read.bom = reader.attempt(documents.BOM)
    read.verification = reader.attempt(documents.VERIFICATION)
    read.policy = reader.optional(documents.POLICY)
    reader.parts()
    reader.decisions()
    reader.manufacturing()
    return read


def load_record(root: Path) -> Record:
    """The record of the project at `root`; raises the first RecordError (record_version problems first)."""
    if not (root / documents.HW).is_dir():
        raise RecordMissingError(documents.HW, "the project has no hw/ directory")
    return read_record(root).record()


# --- writing -----------------------------------------------------------------------------------------


def _render(spec: DocumentSpec, document: Any) -> str:
    if spec == documents.PRODUCT:
        check_version(spec.path, document)
    check_document(spec, document)
    if spec.format == "csv":
        return render_csv(document, contracts.schema(spec.contract))
    return render_yaml(document)


def _record_files(record: Record) -> list[tuple[str, str]]:
    files = [
        (documents.PRODUCT.path, _render(documents.PRODUCT, record.product)),
        (documents.REQUIREMENTS.path, _render(documents.REQUIREMENTS, record.requirements)),
        (documents.INTERFACES.path, _render(documents.INTERFACES, record.interfaces)),
        (documents.ASSEMBLY.path, _render(documents.ASSEMBLY, record.assembly)),
        (documents.BOM.path, _render(documents.BOM, record.bom)),
        (documents.VERIFICATION.path, _render(documents.VERIFICATION, record.verification)),
    ]
    if record.policy is not None:
        files.append((documents.POLICY.path, _render(documents.POLICY, record.policy)))
    for pn, part in record.parts.items():
        files.append((documents.part(pn).path, _render(documents.part(pn), part)))
    for name, document in record.manufacturing.items():
        files.append((documents.manufacturing(name).path, _render(documents.manufacturing(name), document)))
    for stem, document in record.guidelines.items():
        files.append((documents.guideline(stem).path, _render(documents.guideline(stem), document)))
    for decision in record.decisions.values():
        path = documents.decision_path(decision.file_name)
        check_decision(path, decision)
        files.append((path, join_front_matter(decision.front, decision.body)))
    return files


def _replace(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def save_document(root: Path, spec: DocumentSpec, document: Any) -> None:
    """Write one YAML document or the rows of one CSV file, after checking it against its contract."""
    _replace(root, spec.path, _render(spec, document))


def save_decision(root: Path, decision: Decision) -> None:
    """Write one decision record file, after checking its front matter and file name."""
    path = documents.decision_path(decision.file_name)
    check_decision(path, decision)
    _replace(root, path, join_front_matter(decision.front, decision.body))


def save_record(root: Path, record: Record) -> None:
    """Write every document of `record` under `root/hw`. Every document is checked first, so a violation
    leaves every file as it was. Files the record does not hold are left alone; nothing is deleted."""
    for path, text in _record_files(record):
        _replace(root, path, text)
