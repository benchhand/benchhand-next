"""BOM numeric cells: ASCII white space around a number is stripped; a number the prototype read that record
version 3 cannot read is refused, naming the row, column and value."""

from __future__ import annotations

import pytest
from benchhand_core.record.migrate.renames import csv_numbers

HEADER = "level,PN,rev,qty,title,mass\n"
BOM_NUMBERS = csv_numbers("bom-row")


def test_ascii_white_space_around_a_number_is_stripped_and_nothing_else_changes() -> None:
    text = HEADER + "1,LMP-0001,X1,\t2 , padded title ,0.25\n"
    rewrite = BOM_NUMBERS("hw/bom.csv", text)
    assert rewrite.text == HEADER + "1,LMP-0001,X1,2, padded title ,0.25\n"
    assert [(f.code, f.pointer) for f in rewrite.findings] == [("migrate.csv_number_spacing", "/0/qty")]


@pytest.mark.parametrize(
    ("cell", "column"),
    [
        ("\uff10", "level"),  # a full-width digit zero, which int() reads
        (" \u0662 ", "qty"),  # an Arabic-Indic digit two, padded
        ("1_000", "qty"),  # int() reads digit grouping
        ("\u00a01", "qty"),  # a no-break space, which str.strip() removes and ASCII stripping does not
        ("inf", "mass"),  # float() reads inf
    ],
)
def test_a_number_the_prototype_read_but_version_3_cannot_is_refused_with_its_cell(
    cell: str, column: str
) -> None:
    cells = {"level": "1", "qty": "2", "mass": "0.25"} | {column: cell}
    text = HEADER + f"{cells['level']},LMP-0001,X1,{cells['qty']},Base,{cells['mass']}\n"
    rewrite = BOM_NUMBERS("hw/bom.csv", text)
    assert rewrite.text == text
    [refusal] = rewrite.findings
    assert (refusal.severity.value, refusal.code, refusal.path, refusal.pointer) == (
        "error",
        "migrate.csv_number_unreadable",
        "hw/bom.csv",
        f"/0/{column}",
    )
    assert repr(cell) in refusal.message and f"row 0, column {column}" in refusal.message


def test_a_cell_the_prototype_also_rejected_is_left_to_the_validator() -> None:
    text = HEADER + "1,LMP-0001,X1,two,Base,\n"
    assert BOM_NUMBERS("hw/bom.csv", text).findings == ()
