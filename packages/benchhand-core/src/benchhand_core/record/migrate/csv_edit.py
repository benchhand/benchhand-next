"""Edit CSV cells in place: rename header cells, or strip white space around numbers. Every other byte, the
line endings included, stays as written."""

from __future__ import annotations

from dataclasses import dataclass

from benchhand_core.record.formats import Column, FormatError


@dataclass(frozen=True)
class Cell:
    start: int
    end: int
    value: str  # the cell's value, unquoted
    quoted: bool

    def shown(self, value: str) -> str:
        return f'"{value}"' if self.quoted else value


def _closing_quote(text: str, opening: int) -> int:
    index = opening + 1
    while True:
        close = text.find('"', index)
        if close < 0:
            raise FormatError("a quoted CSV cell is never closed")
        if text.startswith('""', close):
            index = close + 2
            continue
        return close


def _cell(text: str, start: int, end: int, quoted: bool) -> Cell:
    raw = text[start:end]
    value = raw[1:-1].replace('""', '"') if quoted else raw
    return Cell(start, end, value, quoted)


def _record(text: str, start: int) -> tuple[list[Cell], int]:
    """The cells of the record that starts at `start`, and where the next record starts."""
    cells: list[Cell] = []
    index, quoted = start, False
    while True:
        if index < len(text) and text[index] == '"' and index == start:
            quoted, index = True, _closing_quote(text, index) + 1
            continue
        if index >= len(text) or text[index] in ",\r\n":
            cells.append(_cell(text, start, index, quoted))
            if index < len(text) and text[index] == ",":
                start, index, quoted = index + 1, index + 1, False
                continue
            following = index + (2 if text.startswith("\r\n", index) else 1)
            return cells, min(following, len(text) + 1)
        if quoted:
            raise FormatError(f"CSV cell at {start}: text after its closing quote")
        index += 1


def records(text: str) -> list[list[Cell]]:
    """Every record of `text`, each cell with where it sits."""
    found, start = [], 0
    while start < len(text):
        cells, start = _record(text, start)
        found.append(cells)
    return found


def header_cells(text: str) -> list[Cell]:
    return _record(text, 0)[0]


def _replace(text: str, changes: list[tuple[Cell, str]]) -> str:
    for cell, shown in sorted(changes, key=lambda change: change[0].start, reverse=True):
        text = text[: cell.start] + shown + text[cell.end :]
    return text


def rename_header(text: str, renames: dict[str, str]) -> str:
    """`text` with each header cell named in `renames` renamed, quoted as it was."""
    cells = [cell for cell in header_cells(text) if cell.value in renames]
    return _replace(text, [(cell, cell.shown(renames[cell.value])) for cell in cells])


@dataclass(frozen=True)
class Stripped:
    text: str
    count: int
    first: tuple[int, str]  # the data row index and column of the first cell stripped


def _is_number(column: Column, value: str) -> bool:
    return value != "" and not isinstance(column.read(value), str)


def strip_numbers(text: str, numeric: dict[str, Column]) -> Stripped:
    """`text` with the white space around each number in a column of `numeric` removed."""
    header, *rows = records(text) or [[]]
    names = [cell.value for cell in header]
    changes: list[tuple[Cell, str]] = []
    first: tuple[int, str] = (0, "")
    index = 0
    for row in rows:
        if len(row) == 1 and row[0].value == "" and not row[0].quoted:
            continue  # a blank line, which the reader skips
        for name, cell in zip(names, row, strict=False):
            value = cell.value.strip()
            if name in numeric and value != cell.value and _is_number(numeric[name], value):
                if not changes:
                    first = (index, name)
                changes.append((cell, cell.shown(value)))
        index += 1
    return Stripped(_replace(text, changes), len(changes), first)
