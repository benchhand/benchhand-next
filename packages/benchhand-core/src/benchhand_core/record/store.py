"""Read and write a project's hw/ record, validated against the record contracts on every read and write.

`read_record` is lenient: it reads every document it can and keeps each problem as a typed error, so
validation can report them all. `load_record` is strict: it raises the first error. `save_record` and
`save_document` validate every document before any file is touched, then replace each changed file
atomically. A saved file keeps the key order it had, and a file whose content is unchanged is not rewritten.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchhand_contracts import ContractViolation
from benchhand_contracts.base import ContractModel

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
    ordered_like,
    parse_csv,
    parse_yaml,
    render_csv,
    render_yaml,
    same,
    split_front_matter,
)
from benchhand_core.record.model import (
    MANUFACTURING_DOCUMENTS,
    Assembly,
    BomRow,
    Decision,
    DecisionFrontMatter,
    Guideline,
    Interfaces,
    Part,
    Policy,
    Product,
    Record,
    Requirements,
    VerificationRow,
    as_json,
)

DECISION_FILE = re.compile(r"(?P<id>DR-[0-9]{3})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md")

Document = ContractModel | list[ContractModel]


@dataclass
class RecordRead:
    """What `read_record` could read: each document that passed its contract, and every error met."""

    product: Product | None = None
    requirements: Requirements | None = None
    interfaces: Interfaces | None = None
    assembly: Assembly | None = None
    bom: list[BomRow] | None = None
    verification: list[VerificationRow] | None = None
    parts: dict[str, Part] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    manufacturing: dict[str, ContractModel] = field(default_factory=dict)
    guidelines: dict[str, Guideline] = field(default_factory=dict)
    policy: Policy | None = None
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


def check_document(spec: DocumentSpec, data: Any) -> None:
    """Raise RecordSchemaError when `data` (a document's JSON, or the rows of a CSV file) breaks its
    contract; for product.yaml, RecordVersionError first when its record_version is not this release's."""
    if spec == documents.PRODUCT:
        check_version(spec.path, data)
    if spec.format == "csv":
        found = _row_violations(spec.contract, data)
    else:
        found = contracts.violations(spec.contract, data)
    if found:
        raise RecordSchemaError(spec.path, found)


def _row_violations(contract: str, rows: Any) -> list[ContractViolation]:
    if not isinstance(rows, list):
        return [ContractViolation(contracts.schema_id(contract), "", "", "rows must be a list")]
    found = []
    for index, row in enumerate(rows):
        for violation in contracts.violations(contract, row):
            found.append(
                ContractViolation(
                    violation.schema_id,
                    f"/{index}{violation.pointer}",
                    violation.schema_path,
                    violation.message,
                )
            )
    return found


def check_version(path: str, product: Any) -> None:
    found = product.get("record_version") if isinstance(product, dict) else None
    if isinstance(found, bool) or found != RECORD_VERSION:
        raise RecordVersionError(path, found)


def _check_decision_name(path: str, slug: str) -> None:
    if DECISION_FILE.fullmatch(f"DR-000-{slug}.md") is None:
        raise RecordReadError(
            path, f"slug {slug!r} is not lowercase words joined by -", code="decision.file_name"
        )


def _decision_front(path: str, data: Any) -> Any:
    found = contracts.violations(documents.DECISION_CONTRACT, data)
    if found:
        raise RecordSchemaError(path, found)
    return DecisionFrontMatter.model_validate(data).root


# --- reading -----------------------------------------------------------------------------------------


def _text(root: Path, path: str) -> str:
    """The file's text with its line endings as written."""
    try:
        return (root / path).read_bytes().decode("utf-8")
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
    """One document as its model (a CSV file as a list of row models), checked against its contract;
    product.yaml also against the record version."""
    data = _parse(spec, _text(root, spec.path))
    check_document(spec, data)
    if spec.format == "csv":
        return [spec.model.model_validate(row) for row in data]
    return spec.model.model_validate(data)


def read_decision(root: Path, file_name: str) -> Decision:
    path = documents.decision_path(file_name)
    match = DECISION_FILE.fullmatch(file_name)
    if match is None:
        raise RecordReadError(path, "a decision record is named DR-###-<slug>.md", code="decision.file_name")
    try:
        front, body = split_front_matter(_text(root, path))
    except FormatError as error:
        raise RecordReadError(path, str(error)) from error
    decision = Decision(slug=match["slug"], front=_decision_front(path, front), body=body)
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
                found.setdefault(part.pn, []).append(name)
                if part.pn == name:
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


def _as_data(spec: DocumentSpec, document: Document) -> Any:
    if isinstance(document, list):
        return [as_json(row) for row in document]
    return as_json(document)


def _on_disk(root: Path, spec: DocumentSpec) -> Any:
    """What the file at `spec` states now, or None if it is absent or unreadable."""
    try:
        return _parse(spec, _text(root, spec.path))
    except RecordError:
        return None


def _render(root: Path, spec: DocumentSpec, document: Document) -> str | None:
    """The new text of `spec`'s file, after checking `document`; None when the file already states it."""
    data = _as_data(spec, document)
    check_document(spec, data)
    current = _on_disk(root, spec)
    if current is not None and same(data, current):
        return None
    if spec.format == "csv":
        return render_csv(data, contracts.schema(spec.contract))
    return render_yaml(ordered_like(data, current))


def _render_part(root: Path, pn: str, part: Part) -> str | None:
    spec = documents.part(pn)
    text = _render(root, spec, part)
    if part.pn != pn:
        message = f"PN {part.pn} is saved under {pn}; a part directory is named after its PN"
        raise RecordError(spec.path, message, code="part.directory_mismatch")
    return text


def _render_decision(root: Path, key: str, decision: Decision) -> tuple[str, str | None]:
    """The decision file's path and new text (None when unchanged), after checking its front matter and
    that its id is `key`, the id the record holds it under."""
    path = documents.decision_path(f"{key}-{decision.slug}.md")
    _check_decision_name(path, decision.slug)
    front = as_json(decision.front)
    _decision_front(path, front)
    if decision.id != key:
        raise RecordError(
            path, f"front matter id {decision.id} is saved as {key}", code="decision.id_mismatch"
        )
    try:
        current_front, current_body = split_front_matter(_text(root, path))
    except (RecordError, FormatError):
        current_front, current_body = None, None
    if current_body == decision.body and same(front, current_front):
        return path, None
    return path, join_front_matter(ordered_like(front, current_front), decision.body)


def _record_documents(record: Record) -> list[tuple[DocumentSpec, Document]]:
    found: list[tuple[DocumentSpec, Document]] = [
        (documents.PRODUCT, record.product),
        (documents.REQUIREMENTS, record.requirements),
        (documents.INTERFACES, record.interfaces),
        (documents.ASSEMBLY, record.assembly),
        (documents.BOM, list(record.bom)),
        (documents.VERIFICATION, list(record.verification)),
    ]
    if record.policy is not None:
        found.append((documents.POLICY, record.policy))
    found.extend((documents.manufacturing(name), document) for name, document in record.manufacturing.items())
    found.extend((documents.guideline(stem), document) for stem, document in record.guidelines.items())
    return found


def _record_files(root: Path, record: Record) -> list[tuple[str, str | None]]:
    files = [(spec.path, _render(root, spec, document)) for spec, document in _record_documents(record)]
    files.extend((documents.part(pn).path, _render_part(root, pn, part)) for pn, part in record.parts.items())
    files.extend(_render_decision(root, key, decision) for key, decision in record.decisions.items())
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


def save_document(root: Path, spec: DocumentSpec, document: Document) -> None:
    """Write one YAML document or the rows of one CSV file, after checking it against its contract."""
    text = _render(root, spec, document)
    if text is not None:
        _replace(root, spec.path, text)


def save_decision(root: Path, decision: Decision) -> None:
    """Write one decision record file, after checking its front matter and file name."""
    path, text = _render_decision(root, decision.id, decision)
    if text is not None:
        _replace(root, path, text)


def save_record(root: Path, record: Record) -> None:
    """Write every document of `record` under `root/hw`. Every document is checked first, so a violation
    leaves every file as it was. Files the record does not hold are left alone; nothing is deleted."""
    files = _record_files(root, record)
    (root / documents.PARTS_DIR).mkdir(parents=True, exist_ok=True)
    for path, text in files:
        if text is not None:
            _replace(root, path, text)
