# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The file formats of the record: strict YAML, contract-shaped CSV and decision front matter."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

import yaml


class FormatError(ValueError):
    """Text that is not valid in its record format."""


class _StrictLoader(yaml.SafeLoader):
    """Safe YAML that keeps dates as text (the contracts state dates as strings) and refuses a key given twice
    or a key that is not a string."""


_StrictLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise FormatError(
                f"line {key_node.start_mark.line + 1}: mapping key {str(key)[:40]!r} is not text"
            )
        if key in mapping:
            raise FormatError(f"line {key_node.start_mark.line + 1}: key {key[:40]!r} is given twice")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def parse_yaml(text: str) -> Any:
    try:
        # The loader reads the stream as it is built, so a forbidden character fails here already.
        loader = _StrictLoader(text)
    except yaml.YAMLError as error:
        raise FormatError(str(error)[:300]) from error
    try:
        return loader.get_single_data()
    except FormatError:
        raise
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
        raise FormatError(str(error)[:300]) from error
    finally:
        loader.dispose()


def render_yaml(document: Any) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False, width=110)


# --- CSV ---------------------------------------------------------------------------------------------------

_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?")


@dataclass(frozen=True)
class Column:
    """How one CSV column's cells read, derived from its property schema in the row contract."""

    name: str
    nullable: bool
    numeric: str | None  # "integer", "number" or None for text

    def read(self, cell: str) -> Any:
        if cell == "":
            return None if self.nullable else cell
        if self.numeric is None:
            return cell
        if _INTEGER.fullmatch(cell):
            return int(cell)
        if self.numeric == "number" and _NUMBER.fullmatch(cell):
            return float(cell)
        return cell

    def write(self, value: Any) -> str:
        if value is None:
            return ""
        if self.numeric == "integer" and isinstance(value, float) and value.is_integer():
            return str(int(value))  # JSON Schema counts 1.0 as an integer; the reader wants 1
        return str(value)


def _types(property_schema: dict[str, Any]) -> set[Any]:
    declared = property_schema.get("type", [])
    types = set(declared if isinstance(declared, list) else [declared])
    if None in property_schema.get("enum", []):
        types.add("null")
    for branch in property_schema.get("anyOf", []):
        types |= _types(branch)
    return types


def columns(row_schema: dict[str, Any]) -> tuple[Column, ...]:
    out = []
    for name, property_schema in row_schema["properties"].items():
        types = _types(property_schema)
        numeric = "integer" if "integer" in types else "number" if "number" in types else None
        out.append(Column(name=name, nullable="null" in types, numeric=numeric))
    return tuple(out)


def accepted_headers(row_schema: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    """The column lists a file may have: the required columns, or every column, each in property order."""
    every = tuple(row_schema["properties"])
    required = tuple(name for name in every if name in row_schema.get("required", []))
    return (required,) if required == every else (required, every)


def _csv_rows(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        return list(reader)
    except csv.Error as error:
        raise FormatError(f"line {reader.line_num}: {error}") from error


def parse_csv(text: str, row_schema: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _csv_rows(text)
    headers = accepted_headers(row_schema)
    header = tuple(rows[0]) if rows else ()
    if header not in headers:
        expected = " or ".join(",".join(columns_) for columns_ in headers)
        raise FormatError(f"expected CSV columns in order: {expected}")
    by_name = {column.name: column for column in columns(row_schema)}
    parsed = []
    for number, cells in enumerate(rows[1:], start=2):
        if not cells:
            continue
        if len(cells) != len(header):
            raise FormatError(f"line {number}: {len(cells)} cells, expected {len(header)}")
        parsed.append(_csv_row(number, header, cells, by_name))
    return parsed


def _csv_row(
    number: int, header: tuple[str, ...], cells: list[str], by_name: dict[str, Column]
) -> dict[str, Any]:
    row = {}
    for name, cell in zip(header, cells, strict=True):
        try:
            row[name] = by_name[name].read(cell)
        except ValueError as error:  # such as an integer past Python's digit limit
            raise FormatError(f"line {number}, column {name}: {str(error)[:200]}") from error
    return row


def render_csv(rows: list[dict[str, Any]], row_schema: dict[str, Any]) -> str:
    """The CSV text of `rows`: the required columns, or every column when a row states more. Every row then
    states every column, since a blank cell reads back as null."""
    required, *rest = accepted_headers(row_schema)
    header = rest[0] if rest and any(set(row) - set(required) for row in rows) else required
    for index, row in enumerate(rows):
        missing = [name for name in header if name not in row]
        if missing:
            raise FormatError(
                f"row {index} lacks the columns {', '.join(missing)} that another row states; "
                "every row states the optional columns, or none does"
            )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    by_name = {column.name: column for column in columns(row_schema)}
    for row in rows:
        writer.writerow([by_name[name].write(row.get(name)) for name in header])
    return out.getvalue()


# --- decision files --------------------------------------------------------------------------------------

FRONT_MATTER = re.compile(r"\A---\r?\n(?P<front>.*?\n)?---\r?\n(?P<body>.*)\Z", re.DOTALL)


def split_front_matter(text: str) -> tuple[Any, str]:
    """The parsed YAML front matter and the verbatim Markdown body of a decision file; the delimiter lines
    end in LF or CRLF."""
    match = FRONT_MATTER.match(text)
    if match is None:
        raise FormatError("no YAML front matter between --- lines at the top of the file")
    return parse_yaml(match["front"] or ""), match["body"]


def join_front_matter(front: dict[str, Any], body: str) -> str:
    return f"---\n{render_yaml(front)}---\n{body}"


# --- rewriting -------------------------------------------------------------------------------------------


def same(left: Any, right: Any) -> bool:
    """Whether two parsed documents state the same JSON: 2 and 2.0 are one number, true and 1 are not."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right, strict=True))
    numbers = all(isinstance(value, int | float) and not isinstance(value, bool) for value in (left, right))
    return (numbers or type(left) is type(right)) and left == right


def ordered_like(new: Any, old: Any) -> Any:
    """`new` laid out as `old` was: each mapping's keys in `old`'s order, keys `old` lacks after them in
    `new`'s order, and a value `old` states the same way kept as `old` wrote it (2, not 2.0)."""
    if isinstance(new, dict) and isinstance(old, dict):
        keys = [key for key in old if key in new] + [key for key in new if key not in old]
        return {key: ordered_like(new[key], old.get(key)) for key in keys}
    if isinstance(new, list) and isinstance(old, list):
        olds = [*old, *[None] * (len(new) - len(old))]
        return [ordered_like(item, previous) for item, previous in zip(new, olds, strict=False)]
    return old if not isinstance(new, dict | list) and same(new, old) else new
