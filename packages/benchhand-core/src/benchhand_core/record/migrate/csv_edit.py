"""Rename CSV header cells in place: every other byte, the data rows and line endings included, stays."""

from __future__ import annotations

from dataclasses import dataclass

from benchhand_core.record.formats import FormatError


@dataclass(frozen=True)
class HeaderCell:
    start: int
    end: int
    name: str  # the cell's value, unquoted
    quoted: bool


def header_cells(text: str) -> list[HeaderCell]:
    """The cells of the first CSV record, with where each sits in `text`."""
    cells: list[HeaderCell] = []
    start, index, quoted = 0, 0, False
    while True:
        if index < len(text) and text[index] == '"' and index == start:
            close = _closing_quote(text, index)
            quoted, index = True, close + 1
            continue
        if index >= len(text) or text[index] in ",\r\n":
            cells.append(_cell(text, start, index, quoted))
            if index >= len(text) or text[index] != ",":
                return cells
            start, index, quoted = index + 1, index + 1, False
            continue
        if quoted:
            raise FormatError(f"header cell at {start}: text after its closing quote")
        index += 1


def _closing_quote(text: str, opening: int) -> int:
    index = opening + 1
    while True:
        close = text.find('"', index)
        if close < 0:
            raise FormatError("header cell: a quote is never closed")
        if text.startswith('""', close):
            index = close + 2
            continue
        return close


def _cell(text: str, start: int, end: int, quoted: bool) -> HeaderCell:
    raw = text[start:end]
    name = raw[1:-1].replace('""', '"') if quoted else raw
    return HeaderCell(start, end, name, quoted)


def rename_header(text: str, renames: dict[str, str]) -> str:
    """`text` with each header cell named in `renames` renamed, quoted as it was."""
    for cell in reversed(header_cells(text)):
        new = renames.get(cell.name)
        if new is not None:
            shown = f'"{new}"' if cell.quoted else new
            text = text[: cell.start] + shown + text[cell.end :]
    return text
