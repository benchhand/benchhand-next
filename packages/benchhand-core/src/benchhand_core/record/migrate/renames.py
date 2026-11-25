"""Rules that rename YAML keys at a path, or CSV header cells."""

from __future__ import annotations

from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.migrate import csv_edit, yaml_edit
from benchhand_core.record.migrate.rule import Rewrite, Transform

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
        root = yaml_edit.compose(text)
        splices: list[yaml_edit.Splice | None] = []
        conflicts: list[Finding] = []
        for yaml_path in paths:
            for steps, mapping in yaml_edit.mappings_at(root, yaml_path):
                for old, new in renames.items():
                    if yaml_edit.entry(mapping, old) is None:
                        continue
                    if yaml_edit.entry(mapping, new) is not None:
                        conflicts.append(_conflict(path, pointer(*steps, old), old, new))
                        continue
                    splices.append(yaml_edit.rename_key(mapping, old, new))
        if conflicts:
            return Rewrite(text, tuple(conflicts))
        return Rewrite(yaml_edit.apply(text, splices))

    return transform


def csv_columns(renames: dict[str, str]) -> Transform:
    """Rename the header cells `renames` names; the data rows are left byte for byte."""

    def transform(path: str, text: str) -> Rewrite:
        names = [cell.name for cell in csv_edit.header_cells(text)]
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
