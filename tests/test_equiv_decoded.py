"""The decoded comparison of the published schemas with the hand-written ones (``tools/equiv/decoded.py``)."""

from __future__ import annotations

from typing import Any

from decoded import ALLOWED, Difference, differences, reason
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

PROTOCOL = "provider/protocol.schema.json"
PARAMS = "/$defs/Request/properties/params"


def _found(old: Any, new: Any) -> list[Difference]:
    return list(differences(old, new))


def test_an_allowlisted_path_is_allowed_only_its_exact_change() -> None:
    """``params`` went from ``{}`` to ``true`` on purpose; ``{}`` to ``false`` would refuse every request."""

    def with_params(new: Any) -> dict[str, Any]:
        return {"$defs": {"Request": {"properties": {"params": new}}}}

    old = with_params({})
    intended, refusing = (_found(old, with_params(new)) for new in (True, False))
    assert intended == [Difference(PARAMS, "changed", {}, True)]
    assert reason(PROTOCOL, intended[0]) is not None
    assert refusing == [Difference(PARAMS, "changed", {}, False)]
    assert reason(PROTOCOL, refusing[0]) is None
    assert reason("record/part.schema.json", intended[0]) is None


def test_literal_data_keeps_booleans_apart_from_numbers() -> None:
    """Python's ``True == 1``; a const of 1 accepts a different instance than a const of true."""
    assert _found({"const": True}, {"const": 1}) == [Difference("/const", "changed", True, 1)]
    assert _found({"enum": [{"on": True}]}, {"enum": [{"on": 1}]}) == [
        Difference("/enum/0/on", "changed", True, 1)
    ]
    assert _found({"default": 1}, {"default": 1.0}) == [Difference("/default", "changed", 1, 1.0)]
    assert _found({"const": True}, {"const": True}) == []
    assert all(isinstance(entry.old, float) is not isinstance(entry.new, float) for entry in ALLOWED[-7:])


def test_sibling_properties_and_allof_that_both_refuse_a_property_must_keep_their_order() -> None:
    properties = {"a": {"type": "string"}}
    all_of = [{"properties": {"a": {"const": "x"}}}]
    old = {"type": "object", "properties": properties, "allOf": all_of}
    new = {"type": "object", "allOf": all_of, "properties": properties}
    reversed_order = Difference("/", "keyword order", ["properties", "allOf"], ["allOf", "properties"])
    assert _found(old, new) == [reversed_order]
    # The reversal is a real change: the first violation at /a comes from the other keyword.
    first = [best_match(Draft202012Validator(schema).iter_errors({"a": 1})) for schema in (old, new)]
    assert [error.validator for error in first if error] == ["type", "const"]


def test_the_order_of_if_counts_and_keywords_that_judge_other_paths_are_not_compared() -> None:
    """jsonschema reports then and else under if; properties a and an allOf about b never share a path."""
    condition = {"if": {"required": ["a"]}, "then": {"properties": {"a": {"const": 1}}}}
    old = {"properties": {"a": {"type": "string"}}, **condition}
    new = {**condition, "properties": {"a": {"type": "string"}}}
    assert _found(old, new) == [Difference("/", "keyword order", ["properties", "if"], ["if", "properties"])]
    apart = {"properties": {"a": {"type": "string"}}, "allOf": [{"properties": {"b": {"const": 1}}}]}
    assert _found(apart, {"allOf": apart["allOf"], "properties": apart["properties"]}) == []
