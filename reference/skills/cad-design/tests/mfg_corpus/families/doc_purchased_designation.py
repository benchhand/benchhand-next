"""Build documentation: a purchased part with no designation, or no manufacturer part number.

A buyer orders a standard part (DIN, ISO, EN, ASME) by the designation of its standard, with its size. A buyer orders a
non-standard catalog part by its manufacturer part number. Supplier order codes are not required for either, so this family
does not test them.

The record is a small synthetic one: a single purchased part, one interface, a BOM and the generic fixture requirement. It has
no decision text, notes or free-text requirement that could repeat an identifier. Each mutant differs from its twin only by
the defect. A release judges the `purchase.identity` obligation: the process checks assess the record into a packet, and the
evidence assessment of cad-record concludes from it.

Two pairs cover the title fallback of the purchase handler. With an empty designation field, a title that states a standard
designation with its size passes (the handler adds an advisory, which the unit tests assert). A title that names the standard
without a size fails. Both pairs share one mutant, and their twins differ: one has the designation in the field, one in the
title. test_mfg_corpus.py reads every file of each variant's tree and checks that the identifier is absent from the mutant and
present in the twin.
"""

from collections.abc import Callable
from typing import Any

import doc_support
from corpus import Family, Outcome, Pair

PREFIXES = ("purchase.identity@",)
PN = "TST-0003"
SIZE = "5\u00d70.6"
STANDARD_DESIGNATION = f"DIN 471 \u2013 {SIZE}"
MPN = "TST-CL8000-M4X8"
RING = "Retaining ring"
RING_NAMING_STANDARD = "Retaining ring DIN 471"
# Pair id to the token that the twin holds and the mutant lacks, anywhere in its tree.
TOKENS = {
    "designation_standard": STANDARD_DESIGNATION,
    "mpn_non_standard": MPN,
    "title_without_size": SIZE,
    "title_with_size": SIZE,
}


def bought(title: str, procurement: dict[str, Any]) -> dict[str, Any]:
    """The one part of the record: a catalog item whose identity, specification, ratings and availability are all known,
    so only the designation fields differ between the variants."""
    fx = doc_support.fixtures()
    datasheet = [fx.source("datasheet", "TST item datasheet")]
    facts = {
        "identity": fx.known("TST item"),
        "specification": fx.known("TST specification", "supplier_typical", datasheet),
        "ratings": fx.known("TST rating", "supplier_typical", datasheet),
        "availability": fx.known("TST stock item"),
    }
    part = doc_support.made_part(PN, [fx.operation("buy", "purchased", purchase=facts)], "purchased", None)
    part.update(make_buy="buy", title=title, procurement={"mode": "catalog", **procurement})
    part["intent"]["material_profile"] = fx.not_applicable("catalogue item")
    return part


def record_run(case: Callable[[bool], tuple[str, dict[str, Any]]]) -> Callable[[bool], Outcome]:
    """A pair's `run`: `case(mutant)` gives the part's title and procurement block, and a release judges the record."""

    def run(mutant: bool) -> Outcome:
        title, procurement = case(mutant)
        fx = doc_support.fixtures()
        with doc_support.workspace() as root:
            # The one interface joins the part to itself: it is the part's mounting.
            hw = fx.write_record(root / "hw", fx.record(parts=[bought(title, procurement)], decisions=(),
                                                        interfaces=[fx.interface("IF-001", PN, PN)]))
            return doc_support.record_verdict(hw, *PREFIXES)

    return run


def designation_standard(mutant: bool) -> tuple[str, dict[str, Any]]:
    return RING, {} if mutant else {"designation": STANDARD_DESIGNATION}


def mpn_non_standard(mutant: bool) -> tuple[str, dict[str, Any]]:
    procurement = {"designation": "Compression limiter, M4 x 8"}
    if not mutant:
        procurement["manufacturer_part_number"] = MPN
    return "Compression limiter", procurement


def title_without_size(mutant: bool) -> tuple[str, dict[str, Any]]:
    return RING_NAMING_STANDARD, {} if mutant else {"designation": STANDARD_DESIGNATION}


def title_with_size(mutant: bool) -> tuple[str, dict[str, Any]]:
    return (RING_NAMING_STANDARD if mutant else f"{RING_NAMING_STANDARD} \u2013 {SIZE}"), {}


FAMILY = Family(
    id="doc_purchased_designation", check="cad-design/scripts/process_checks/purchased.py (+ validate.py, build_guide.py)",
    owner="cad-design",
    pairs=(
        Pair("designation_standard", "the retaining ring has no designation of its standard", record_run(designation_standard)),
        Pair("mpn_non_standard", "the compression limiter has no manufacturer part number", record_run(mpn_non_standard)),
        Pair("title_without_size", "the designation field is empty and the title names DIN 471 without a size; the twin "
             "has the designation in the field", record_run(title_without_size)),
        Pair("title_with_size", "the designation field is empty and the title names DIN 471 without a size; the twin's "
             "title states the designation with its size", record_run(title_with_size)),
    ))
