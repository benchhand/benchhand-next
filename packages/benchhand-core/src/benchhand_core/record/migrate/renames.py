"""Rules that rename YAML keys at a path, or CSV header cells, and strip white space around v2 numbers."""

from __future__ import annotations

from benchhand_core.record import contracts
from benchhand_core.record.finding import Finding, error, info, pointer
from benchhand_core.record.formats import columns
from benchhand_core.record.migrate import csv_edit
from benchhand_core.record.migrate.rule import Rewrite, Transform
from benchhand_core.record.migrate.yaml_edit import Document, entry

YamlPath = tuple[str, ...]


def _conflict(path: str, at: str | None, old: str, new: str) -> Finding:
    return error(
        "migrate.key_conflict",
        path,
        f"{old} and {new} are both present; record version 3 keeps only {new}",
        pointer=at,
        action=f"Remove one of {old} and {new}, keeping the value that is right, then migrate again.",
    )


def yaml_keys(paths: tuple[YamlPath, ...], renames: dict[str, str]) -> Transform:
    """Rename the keys `renames` names in every mapping at each of `paths`."""

    def transform(path: str, text: str) -> Rewrite:
        document = Document.parse(text)
        conflicts: list[Finding] = []
        for yaml_path in paths:
            for target in document.mappings_at(yaml_path):
                for old, new in renames.items():
                    if entry(target.mapping, old) is None:
                        continue
                    if entry(target.mapping, new) is not None:
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
    """Strip the white space around a number in a numeric column, which the prototype's int() and float()
    accepted and the record version 3 reader does not; every other byte is left as it is."""

    def transform(path: str, text: str) -> Rewrite:
        numeric = {column.name: column for column in columns(contracts.schema(contract)) if column.numeric}
        stripped = csv_edit.strip_numbers(text, numeric)
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
