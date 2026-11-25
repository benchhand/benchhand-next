"""The normaliser that splits TypeSpec's JSON Schema bundle into the published contracts (ADR-0017).

Each rewrite must accept and reject the same instances as the emitted form, so the cases validate both.
"""

from __future__ import annotations

from typing import Any

import pytest
from contracts_gen.normalise import BASE_URI, NormaliseError, normalise
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

DIALECT = "https://json-schema.org/draft/2020-12/schema"
ROOT_ID = f"{BASE_URI}demo/widget.schema.json"
LIB_ID = f"{BASE_URI}demo/library.schema.json"
CLOSED = {"not": {}}


def _decl(schema_id: str, **schema: Any) -> dict[str, Any]:
    return {"$schema": DIALECT, "$id": schema_id, **schema}


def _def(contract: str, name: str) -> str:
    return f"{BASE_URI}demo/{contract}/{name}.json"


def _bundle(*declarations: dict[str, Any]) -> dict[str, Any]:
    return {"$schema": DIALECT, "$id": "contracts.schema.json", "$defs": {d["$id"]: d for d in declarations}}


LIBRARY_ROOT = _decl(LIB_ID, anyOf=[{}])
PART_NUMBER = _decl(_def("library", "PartNumber"), type="string", pattern="^[A-Z]{3}-[0-9]{4}$")
COLOUR = _decl(_def("widget", "WidgetColour"), type="string", enum=["red", "blue"], **{"x-inline": True})
WIDGET = _decl(
    ROOT_ID,
    type="object",
    properties={
        "part": {"$ref": PART_NUMBER["$id"], "description": "the part"},
        "colour": {"$ref": COLOUR["$id"]},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "minLength": 1},
        "kind": {"anyOf": [{"type": "string", "const": "a"}, {"type": "string", "const": "b"}]},
        "tags": {"$ref": "#/$defs/RecordString"},
        "extra": {},
    },
    required=["part"],
    unevaluatedProperties=CLOSED,
    allOf=[{"if": {"properties": {"kind": {"const": "a"}}}, "then": {"required": ["colour"]}}],
    **{"$defs": {"RecordString": {"type": "object", "unevaluatedProperties": {"type": "string"}}}},
)
ORDER = [WIDGET["$id"], COLOUR["$id"], LIBRARY_ROOT["$id"], PART_NUMBER["$id"]]


def _published() -> dict[str, dict[str, Any]]:
    return normalise(_bundle(WIDGET, COLOUR, LIBRARY_ROOT, PART_NUMBER), ORDER)


def test_the_bundle_splits_into_files_with_relative_refs() -> None:
    published = _published()
    assert set(published) == {"demo/widget.schema.json", "demo/library.schema.json"}
    widget = published["demo/widget.schema.json"]
    assert widget["$id"] == ROOT_ID
    part_ref = "library.schema.json#/$defs/PartNumber"
    assert widget["properties"]["part"] == {"description": "the part", "$ref": part_ref}
    # WidgetColour is x-inline, so it is written in place and isn't a $defs entry.
    assert widget["properties"]["colour"] == {"type": "string", "enum": ["red", "blue"]}
    assert widget["properties"]["note"] == {"minLength": 1, "type": ["string", "null"]}
    assert widget["properties"]["kind"] == {"enum": ["a", "b"]}
    assert widget["properties"]["tags"] == {"type": "object", "additionalProperties": {"type": "string"}}
    assert widget["properties"]["extra"] is True
    assert widget["additionalProperties"] is False and "unevaluatedProperties" not in widget
    assert "$defs" not in widget
    assert published["demo/library.schema.json"] == {
        "$schema": DIALECT,
        "$id": LIB_ID,
        "$defs": {"PartNumber": {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$"}},
    }


def _registry(schemas: Any) -> Registry:
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)


@pytest.mark.parametrize(
    "instance",
    [
        {"part": "LMP-0001"},
        {"part": "LMP-0001", "kind": "a", "colour": "red", "note": None, "tags": {"x": "y"}, "extra": [1]},
        {"part": "lmp"},
        {"part": "LMP-0001", "unknown": 1},
        {"part": "LMP-0001", "kind": "a"},
        {"part": "LMP-0001", "kind": "c"},
        {"part": "LMP-0001", "note": ""},
        {"part": "LMP-0001", "tags": {"x": 1}},
        {"part": "LMP-0001", "colour": "green"},
    ],
)
def test_the_published_form_accepts_what_the_bundle_accepts(instance: Any) -> None:
    bundle = _bundle(WIDGET, COLOUR, LIBRARY_ROOT, PART_NUMBER)
    emitted = Draft202012Validator({"$ref": ROOT_ID}, registry=_registry(bundle["$defs"].values()))
    published = Draft202012Validator({"$ref": ROOT_ID}, registry=_registry(_published().values()))
    assert published.is_valid(instance) == emitted.is_valid(instance)


def test_inlining_a_local_def_leaves_instance_data_alone() -> None:
    # A const, an example or a default that looks like a $ref to a local $defs entry is data, not a schema.
    literal = {"$ref": "#/$defs/RecordString"}
    widget = _decl(
        ROOT_ID,
        type="object",
        properties={
            "tags": {"$ref": "#/$defs/RecordString"},
            "pointer": {"const": literal, "default": literal, "examples": [literal]},
            "choice": {"enum": [literal]},
        },
        unevaluatedProperties=CLOSED,
        **{"$defs": {"RecordString": {"type": "object", "unevaluatedProperties": {"type": "string"}}}},
    )
    properties = normalise(_bundle(widget), [ROOT_ID])["demo/widget.schema.json"]["properties"]
    assert properties["tags"] == {"type": "object", "additionalProperties": {"type": "string"}}
    assert properties["pointer"] == {"const": literal, "default": literal, "examples": [literal]}
    assert properties["choice"] == {"enum": [literal]}


def test_a_closed_object_beside_an_applicator_that_names_an_unlisted_property_is_refused() -> None:
    # unevaluatedProperties sees `colour` evaluated by the then branch; additionalProperties would refuse it.
    widget = _decl(
        ROOT_ID,
        type="object",
        properties={"kind": {"type": "string"}},
        unevaluatedProperties=CLOSED,
        allOf=[{"if": {"required": ["kind"]}, "then": {"properties": {"colour": {"type": "string"}}}}],
    )
    with pytest.raises(NormaliseError, match="names the property 'colour'"):
        normalise(_bundle(widget), [ROOT_ID])


def test_a_contract_without_a_root_is_refused() -> None:
    with pytest.raises(NormaliseError, match="demo/library.schema.json has no root type"):
        normalise(_bundle(PART_NUMBER), [PART_NUMBER["$id"]])


def test_a_declaration_the_emitter_dropped_is_reported() -> None:
    # The emitter keeps one of two declarations with the same name, even in different namespaces.
    with pytest.raises(NormaliseError, match="missing from the bundle: .*widget/Lost.json"):
        normalise(_bundle(LIBRARY_ROOT, PART_NUMBER), [*ORDER[2:], _def("widget", "Lost")])


def test_a_ref_written_in_an_extension_must_resolve() -> None:
    missing = {"$ref": "library.schema.json#/$defs/Nope"}
    widget = _decl(ROOT_ID, type="object", unevaluatedProperties=CLOSED, **{"not": missing})
    with pytest.raises(NormaliseError, match="doesn't resolve"):
        normalise(_bundle(widget, LIBRARY_ROOT, PART_NUMBER), [ROOT_ID, *ORDER[2:]])
