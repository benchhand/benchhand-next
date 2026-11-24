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
    loader = _StrictLoader(text)
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

    @staticmethod
    def write(value: Any) -> str:
        return "" if value is None else str(value)


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


def parse_csv(text: str, row_schema: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(csv.reader(io.StringIO(text, newline="")))
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
        parsed.append({name: by_name[name].read(cell) for name, cell in zip(header, cells, strict=True)})
    return parsed


def render_csv(rows: list[dict[str, Any]], row_schema: dict[str, Any]) -> str:
    required, *rest = accepted_headers(row_schema)
    header = rest[0] if rest and any(set(row) - set(required) for row in rows) else required
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([Column.write(row.get(name)) for name in header])
    return out.getvalue()


# --- decision files --------------------------------------------------------------------------------------

FRONT_MATTER = re.compile(r"\A---\n(?P<front>.*?\n)?---\n(?P<body>.*)\Z", re.DOTALL)


def split_front_matter(text: str) -> tuple[Any, str]:
    """The parsed YAML front matter and the verbatim Markdown body of a decision file."""
    match = FRONT_MATTER.match(text)
    if match is None:
        raise FormatError("no YAML front matter between --- lines at the top of the file")
    return parse_yaml(match["front"] or ""), match["body"]


def join_front_matter(front: dict[str, Any], body: str) -> str:
    return f"---\n{render_yaml(front)}---\n{body}"
