# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""record/rules/bom.py: which structured designations name a commodity item, and the designation column a BOM
row states for it. Ported from prototype PR #331's test_commodity_identity.py; the expected texts are worked out
from the designation fields (the issue's own example is `ISO 4762 M4x20, 8.8, A2`)."""

from __future__ import annotations

from typing import Any

import pytest
from benchhand_core.record.rules.bom import (
    FEATURE_STANDARDS,
    commodity_label,
    designation_cell,
    designation_problem,
    designation_text,
)

SCREW = {
    "kind": "standard_designation",
    "standard": "ISO 4762",
    "size": "M4",
    "length": 20,
    "property_class": "8.8",
    "finish": "A2",
}
NUT = {
    "kind": "standard_designation",
    "standard": "ISO 4032",
    "size": "M4",
    "length": "not_applicable",
    "property_class": "8",
}
INSERT = {
    "kind": "family_designation",
    "family": "heat_set_insert",
    "thread": "M3",
    "length": 5.7,
    "outside_diameter": 4.6,
    "recommended_hole": 4.0,
}


def without(designation: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in designation.items() if key != field}


def part(designation: Any = None, *, opened: dict[str, str] | None = None) -> dict[str, Any]:
    """A bought part's JSON whose purchased operation carries `designation`; `opened` is procurement.open."""
    purchase: dict[str, Any] = {"identity": {"status": "unknown", "reason": "x"}}
    if designation is not None:
        purchase["designation"] = designation
    record: dict[str, Any] = {
        "PN": "TST-0001",
        "intent": {"route": [{"id": "buy", "kind": "purchased", "purchase": purchase}]},
    }
    if opened:
        record["procurement"] = {"mode": "catalog", "open": opened}
    return record


# --- eligibility ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("designation", [SCREW, NUT, INSERT], ids=["screw", "nut-without-length", "insert"])
def test_an_eligible_designation_has_no_problem(designation: dict[str, Any]) -> None:
    assert designation_problem(designation) is None


@pytest.mark.parametrize(
    ("designation", "word"),
    [
        pytest.param({**INSERT, "family": "mystery_widget"}, "family", id="unknown-family"),
        pytest.param({**SCREW, "standard": "ISO 965-1"}, "feature", id="feature-only-standard"),
        pytest.param({**SCREW, "length": "not_applicable"}, "length", id="screw-without-length"),
        pytest.param(without(INSERT, "recommended_hole"), "recommended_hole", id="insert-without-hole"),
        pytest.param(without(SCREW, "size"), "size", id="standard-without-size"),
        pytest.param({**SCREW, "kind": "manufacturer_pn"}, "kind", id="unknown-kind"),
    ],
)
def test_an_ineligible_designation_names_its_problem(designation: dict[str, Any], word: str) -> None:
    assert word in (designation_problem(designation) or "")


def test_a_nut_may_omit_its_length_and_a_dowel_may_not() -> None:
    dowel = {**NUT, "standard": "ISO 8734", "size": "6"}
    assert designation_problem(NUT) is None
    assert "length" in (designation_problem(dowel) or "")


# --- size -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["8.8", "20", "M4 8.8", "M4x", "M4x20", "M4\u00d720"])
def test_a_property_class_or_a_length_is_not_the_size_of_a_threaded_standard(size: str) -> None:
    assert "size" in (designation_problem({**SCREW, "size": size}) or "")


def test_a_size_that_embeds_the_length_is_refused() -> None:
    assert "embeds a length" in (designation_problem({**SCREW, "size": "M4x20"}) or "")
    assert designation_problem({**SCREW, "size": "M4", "length": 20}) is None


def test_a_fine_pitch_size_is_refused_too() -> None:
    # The known limit of the whole-size rule (prototype bead c7q.32): M8x1 reads as a size with a length.
    assert "embeds a length" in (designation_problem({**SCREW, "size": "M8x1"}) or "")


@pytest.mark.parametrize(
    "designation",
    [
        pytest.param({**SCREW, "size": "M4"}, id="metric-screw"),
        pytest.param({**SCREW, "standard": "ISO 7380-1", "size": "M5"}, id="button-head-screw"),
        pytest.param({**NUT, "standard": "ISO 7089", "size": "M4"}, id="washer"),
        pytest.param({**SCREW, "standard": "ISO 8734", "size": "6"}, id="dowel"),
    ],
)
def test_each_family_of_standard_takes_its_own_size(designation: dict[str, Any]) -> None:
    assert designation_problem(designation) is None


@pytest.mark.parametrize("standard", ["ISO 965-1", "DIN ISO 965-1", "DIN EN ISO 965-1", "ASME B1.1"])
def test_a_feature_standard_alone_or_combined_names_no_part(standard: str) -> None:
    assert "feature" in (designation_problem({**SCREW, "standard": standard}) or "")


def test_din_965_is_a_screw_not_the_iso_965_thread() -> None:
    assert "ISO 965" in FEATURE_STANDARDS
    assert designation_problem({**SCREW, "standard": "DIN 965", "size": "M4"}) is None


# --- order line and BOM column --------------------------------------------------------------------------


def test_a_standard_designation_reads_like_an_order_line() -> None:
    assert designation_text(SCREW) == "ISO 4762 M4x20, 8.8, A2"
    assert designation_text(NUT) == "ISO 4032 M4, 8"


def test_a_family_designation_lists_its_dimensions() -> None:
    assert designation_text(INSERT) == "heat_set_insert M3x5.7, OD 4.6, hole 4"


def test_a_part_with_an_eligible_designation_has_a_commodity_label() -> None:
    assert commodity_label(part(SCREW)) == "ISO 4762 M4x20, 8.8, A2"
    assert commodity_label(part(INSERT)) == "heat_set_insert M3x5.7, OD 4.6, hole 4"


def test_no_label_without_a_structured_designation_or_with_an_ineligible_one() -> None:
    assert commodity_label(part()) is None
    assert commodity_label(part({**SCREW, "length": "not_applicable"})) is None


def test_an_open_identity_field_withholds_the_label() -> None:
    assert commodity_label(part(SCREW, opened={"manufacturer_part_number": "not chosen"})) is None


def test_the_designation_is_read_from_the_purchased_route_operation_only() -> None:
    record = part(SCREW)
    record["intent"]["route"][0]["kind"] = "inspection"
    assert commodity_label(record) is None
    assert commodity_label({"PN": "TST-0001", "intent": {"route": {"status": "unknown"}}}) is None


def test_the_designation_text_of_the_record_wins_the_bom_column() -> None:
    record = part(SCREW)
    record["procurement"] = {"mode": "catalog", "designation": "ISO 4762 - M4 x 20"}
    assert designation_cell(record) == "ISO 4762 - M4 x 20"


def test_an_eligible_structured_designation_fills_a_blank_bom_column() -> None:
    assert designation_cell(part(SCREW)) == "ISO 4762 M4x20, 8.8, A2"


def test_the_bom_column_is_empty_when_the_designation_is_ineligible_or_unresolved() -> None:
    assert designation_cell(part({**SCREW, "length": "not_applicable"})) is None
    assert designation_cell(part(SCREW, opened={"manufacturer_part_number": "x"})) is None
