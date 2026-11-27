# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""record/part.schema.json's purchase: a bought item named by identity or by a commodity designation. The cases
are prototype PR #331's test_schema_manufacturing.py purchase cases."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from benchhand_contracts import violations

PURCHASE_ID = "https://benchhand.github.io/benchhand/contracts/record/part.schema.json#/$defs/purchase"
UNKNOWN = {"status": "unknown", "reason": "not recorded in this fixture"}
SOURCE = {
    "kind": "standard",
    "reference": "ISO 4762:2004",
    "revision": "2004",
    "url": "https://www.iso.org/standard/34512.html",
    "accessed": "2026-11-27",
}
SCREW = {
    "kind": "standard_designation",
    "standard": "ISO 4762",
    "size": "M4",
    "length": 20,
    "property_class": "8.8",
}
INSERT = {
    "kind": "family_designation",
    "family": "heat_set_insert",
    "thread": "M3",
    "length": 5.7,
    "outside_diameter": 4.6,
    "recommended_hole": 4.0,
}


def purchase(change: Callable[[dict[str, Any]], None] = lambda _: None) -> dict[str, Any]:
    """A purchase named by identity, with `change` applied."""
    document: dict[str, Any] = {
        "identity": {
            "status": "known",
            "value": "ISO 4762 - M4 x 20 - 8.8",
            "basis": "standard",
            "sources": [SOURCE],
        },
        "specification": UNKNOWN,
        "ratings": UNKNOWN,
    }
    change(document)
    return document


def designate(base: dict[str, Any], *, omit: str | None = None, **override: object) -> Callable[[dict], None]:
    """Replace a purchase's identity with `base`, minus `omit` and with `override` applied."""

    def change(document: dict[str, Any]) -> None:
        designation = {key: value for key, value in base.items() if key != omit} | override
        document.pop("identity")
        document["designation"] = designation

    return change


def test_a_purchase_names_its_identity() -> None:
    assert violations(PURCHASE_ID, purchase()) == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(designate(SCREW), id="standard-designation-only"),
        pytest.param(designate({**SCREW, "finish": "A2"}), id="standard-designation-with-finish"),
        pytest.param(designate(SCREW, length="not_applicable"), id="length-not-applicable"),
        pytest.param(designate(SCREW, standard="ISO 4762\n"), id="standard-with-block-scalar-newline"),
        pytest.param(designate(SCREW, standard="ISO 4762\r"), id="standard-with-trailing-carriage-return"),
        pytest.param(
            designate(SCREW, standard="ISO\x1c4762"), id="standard-separated-by-a-python-only-space"
        ),
        pytest.param(
            designate(SCREW, standard="ISO \ufeff4762"), id="standard-number-led-by-a-byte-order-mark"
        ),
        pytest.param(designate(INSERT), id="heat-set-insert-family-designation"),
        pytest.param(lambda document: document.update(designation=SCREW), id="identity-and-designation"),
        pytest.param(
            lambda document: document.update(
                reference_catalogue=[
                    {"vendor": "Accu", "part_number": "SSCI-M4-20-A2", "url": "https://accu.co.uk"}
                ]
            ),
            id="reference-catalogue",
        ),
    ],
)
def test_a_purchase_names_a_commodity_item_by_designation(change: Callable[[dict], None]) -> None:
    assert violations(PURCHASE_ID, purchase(change)) == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda document: document.pop("identity"), id="neither-identity-nor-designation"),
        pytest.param(designate(SCREW, omit="size"), id="designation-without-size"),
        pytest.param(designate(SCREW, omit="length"), id="designation-without-length"),
        pytest.param(designate(SCREW, length=0), id="screw-of-zero-length"),
        pytest.param(designate(SCREW, length=-20), id="screw-of-negative-length"),
        pytest.param(designate(SCREW, standard="ISO4762"), id="standard-without-number"),
        pytest.param(designate(SCREW, standard="ISO 4762\n\n"), id="standard-with-two-trailing-newlines"),
        pytest.param(designate(SCREW, standard="ISO 4762\nM4"), id="standard-over-two-lines"),
        pytest.param(designate(SCREW, standard="ISO \n4762"), id="standard-number-on-the-next-line"),
        pytest.param(
            designate(SCREW, standard="ISO\ufeff4762"), id="standard-separated-by-a-byte-order-mark"
        ),
        pytest.param(designate(INSERT, length=0), id="insert-of-zero-length"),
        pytest.param(designate(INSERT, length=-5.7), id="insert-of-negative-length"),
        pytest.param(designate(INSERT, outside_diameter=0), id="insert-of-zero-outside-diameter"),
        pytest.param(designate(INSERT, outside_diameter=-4.6), id="insert-of-negative-outside-diameter"),
        pytest.param(designate(INSERT, recommended_hole=0), id="insert-of-zero-hole"),
        pytest.param(designate(INSERT, recommended_hole=-4.0), id="insert-of-negative-hole"),
        pytest.param(designate(INSERT, omit="recommended_hole"), id="insert-without-hole"),
        pytest.param(designate(INSERT, kind="standard_designation"), id="insert-fields-under-standard-kind"),
        pytest.param(
            lambda document: document.update(reference_catalogue=[]), id="empty-reference-catalogue"
        ),
        pytest.param(
            lambda document: document.update(
                reference_catalogue=[{"vendor": "Accu", "url": "https://accu.co.uk"}]
            ),
            id="reference-catalogue-without-part-number",
        ),
        pytest.param(
            lambda document: document.update(
                reference_catalogue=[{"vendor": "Accu", "part_number": "SSCI-M4-20-A2", "url": "accu.co.uk"}]
            ),
            id="reference-catalogue-url-without-scheme",
        ),
    ],
)
def test_a_purchase_outside_the_designation_shapes_is_refused(change: Callable[[dict], None]) -> None:
    assert violations(PURCHASE_ID, purchase(change))


PROTOTYPE_STANDARD = re.compile(r"^(ISO|DIN|EN|ASME|ANSI|JIS)\s\S.*$")  # part.schema.json, prototype 3a7542dd
STANDARD_PARTS = ["ISO", "DIN", "ISOX", "iso"]
STANDARD_GAPS = ["", " ", "\t", "\n", "\r", "\x1c", "\x85", "\xa0", "\u2028", "\u3000", "\ufeff", "x", "  "]
STANDARD_ENDS = ["", "4762", "\n", "\r", "\u2028", "4762\n", "4762\n\n", "47\n62", "4762\r\n", "\ufeff", " "]


def _accepts_standard(text: str) -> bool:
    return violations(PURCHASE_ID, purchase(designate(SCREW, standard=text))) == []


def test_the_standard_pattern_accepts_what_the_prototype_regex_accepts() -> None:
    """The prototype's Python regex `\\s\\S.*$` reads a trailing newline and Python's own whitespace; the
    contract's ECMAScript pattern must accept exactly the same strings."""
    candidates = [
        part + gap + end for part in STANDARD_PARTS for gap in STANDARD_GAPS for end in STANDARD_ENDS
    ]
    disagreements = [
        text for text in candidates if bool(PROTOTYPE_STANDARD.search(text)) != _accepts_standard(text)
    ]
    assert disagreements == []
