# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Rules that rename YAML keys at a path, or CSV header cells, and strip white space around v2 numbers."""

from __future__ import annotations

from benchhand_core.record import contracts
from benchhand_core.record.finding import Finding, error, info, pointer
from benchhand_core.record.formats import columns
from benchhand_core.record.migrate import csv_edit
from benchhand_core.record.migrate.rule import Rewrite, Transform
from benchhand_core.record.migrate.yaml_edit import Document

YamlPath = tuple[str, ...]


def _conflict(path: str, at: str | None, old: str, new: str) -> Finding:
    return error(
        "migrate.key_conflict",
        path,
        f"{old} and {new} are both present; record version 3 keeps only {new}",
        pointer=at,
        action=f"Remove one of {old} and {new}, keeping the value that is right, then migrate again.",
    )


def _unreadable_number(path: str, cell: csv_edit.Unreadable) -> Finding:
    return error(
        "migrate.csv_number_unreadable",
        path,
        f"row {cell.row}, column {cell.column}: {cell.value!r} was a number to the prototype, but record "
        "version 3 reads only ASCII digits, sign, decimal point and exponent",
        pointer=pointer(cell.row, cell.column),
        action=f"Write the {cell.column} of row {cell.row} with ASCII digits, then migrate again.",
    )


def yaml_keys(paths: tuple[YamlPath, ...], renames: dict[str, str]) -> Transform:
    """Rename the keys `renames` names in every mapping at each of `paths`."""

    def transform(path: str, text: str) -> Rewrite:
        document = Document.parse(text)
        conflicts: list[Finding] = []
        for yaml_path in paths:
            for target in document.mappings_at(yaml_path):
                for old, new in renames.items():
                    if not document.has(target, old):
                        continue
                    if document.has(target, new):
                        conflicts.append(_conflict(path, pointer(*target.steps, old), old, new))
                        continue
                    document.rename_key(target, old, new)
        if conflicts:
            return Rewrite(text, tuple(conflicts))
        return Rewrite(document.result())

    return transform


def csv_columns(renames: dict[str, str]) -> Transform:
    """Rename the header cells `renames` names; the data rows are left byte for byte."""

    def transform(path: str, text: str) -> Rewrite:
        names = [cell.value for cell in csv_edit.header_cells(text)]
        # A header cell has no JSON Pointer: the contract points into CSV data rows only.
        conflicts = tuple(
            _conflict(path, None, f"column {old}", f"column {new}")
            for old, new in renames.items()
            if old in names and new in names
        )
        if conflicts:
            return Rewrite(text, conflicts)
        return Rewrite(csv_edit.rename_header(text, renames))

    return transform


def csv_numbers(contract: str) -> Transform:
    """Strip the ASCII white space around a number in a numeric column, which the prototype's int() and
    float() accepted and the record version 3 reader does not; every other byte is left as it is. A cell the
    prototype read that record version 3 cannot, even stripped (non-ASCII digits, say), refuses the file."""

    def transform(path: str, text: str) -> Rewrite:
        numeric = {column.name: column for column in columns(contracts.schema(contract)) if column.numeric}
        stripped = csv_edit.strip_numbers(text, numeric)
        if stripped.unreadable:
            return Rewrite(text, tuple(_unreadable_number(path, cell) for cell in stripped.unreadable))
        if stripped.count == 0:
            return Rewrite(text)
        note = info(
            "migrate.csv_number_spacing",
            path,
            f"white space around {stripped.count} numeric cells removed (first at /{stripped.first[0]}/"
            f"{stripped.first[1]}); record version 3 reads a number without it",
            pointer=pointer(*stripped.first),
        )
        return Rewrite(stripped.text, (note,))

    return transform
