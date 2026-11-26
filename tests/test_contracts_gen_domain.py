"""The domain model built from the published schemas: classes, fields, relations, cardinality and unions."""

from __future__ import annotations

from typing import Any

import pytest
from contracts_gen.domain import MAX_ENUM_VALUES, ClassNode, DomainModel, build_model, class_id, ref_counts
from contracts_gen.sources import REPO_ROOT, SCHEMAS_OUT, Contract, load_contracts


def _contract(stem: str, schema: dict[str, Any]) -> Contract:
    return Contract(f"{stem}.schema.json", {"$id": f"https://example.test/{stem}", **schema})


PERSON = _contract(
    "common/person",
    {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
)

WIDGET = _contract(
    "record/widget",
    {
        "type": "object",
        "required": ["id", "status", "lines", "step"],
        "properties": {
            "id": {"$ref": "#/$defs/part_id"},
            "status": {"enum": ["draft", "released"]},
            "size": {"enum": [f"s{n}" for n in range(MAX_ENUM_VALUES + 1)]},
            "notes": {"type": "object", "properties": {"text": {"type": "string"}}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/line"}},
            "owner": {"$ref": "../common/person.schema.json"},
            "step": {"$ref": "#/$defs/step"},
        },
        "$defs": {
            "part_id": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "line": {"type": "object", "required": ["qty"], "properties": {"qty": {"type": "integer"}}},
            "press": {
                "type": "object",
                "required": ["kind", "force"],
                "properties": {"kind": {"const": "press"}, "force": {"type": "number"}},
            },
            "bolt": {
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"const": "bolt"}, "torque": {"type": "number"}},
            },
            "step": {"oneOf": [{"$ref": "#/$defs/press"}, {"$ref": "#/$defs/bolt"}]},
        },
    },
)


def _fields(node: ClassNode) -> list[str]:
    """The fields as ``name: type``, with ``?`` after the name of an optional one."""
    return [f"{held.name}{'' if held.required else '?'}: {held.type}" for held in node.fields]


def _members(model: DomainModel, class_: str) -> list[str]:
    return _fields(model.classes[class_])


def test_a_synthetic_contract_has_nesting_arrays_optionals_refs_and_a_discriminated_union() -> None:
    model = build_model([PERSON, WIDGET])
    assert _members(model, "record_widget") == [
        "id: part_id",
        "status: enum draft|released",
        "size?: enum",
        "notes?: object",
        "tags?: string[]",
        "lines: line[1..*]",
        "owner?: person",
        "step: step",
    ]
    assert _members(model, "record_widget__notes") == ["text?: string"]
    assert model.classes["record_widget__step"].stereotype == "abstract"
    assert _members(model, "record_widget__step") == ["kind: discriminator"]
    assert _members(model, "record_widget__bolt") == ["kind: const bolt", "torque?: number"]
    assert {(rel.source, rel.target, rel.kind) for rel in model.relations} == {
        ("record_widget", "record_widget__notes", "composition"),
        ("record_widget", "record_widget__line", "composition"),
        ("record_widget", "common_person", "association"),
        ("record_widget", "record_widget__step", "composition"),
        ("record_widget__step", "record_widget__press", "inheritance"),
        ("record_widget__step", "record_widget__bolt", "inheritance"),
    }


def test_a_field_carries_its_description_and_the_values_of_an_enum_too_long_to_spell_out() -> None:
    schema = {
        "type": "object",
        "description": "A box.",
        "properties": {
            "size": {"description": "How big.", "enum": [f"s{n}" for n in range(MAX_ENUM_VALUES + 1)]},
            "sizes": {"type": "array", "items": {"enum": ["a", "b"]}},
            "plain": {"type": "string"},
        },
    }
    node = build_model([_contract("record/box", schema)]).classes["record_box"]
    size, sizes, plain = node.fields
    assert node.description == "A box."
    assert (size.description, len(size.values)) == ("How big.", MAX_ENUM_VALUES + 1)
    assert sizes.values == ("a", "b")
    assert (plain.description, plain.values) == ("", ())


def test_cardinality_comes_from_arrays_and_from_required_versus_optional() -> None:
    model = build_model([PERSON, WIDGET])
    held = {rel.label: rel.cardinality for rel in model.relations if rel.source == "record_widget"}
    assert held == {"notes": "0..1", "lines": "1..*", "owner": "0..1", "step": "1"}


def test_an_array_that_may_be_empty_or_absent_is_zero_to_many() -> None:
    schema = {
        "type": "object",
        "required": ["rows"],
        "properties": {
            "rows": {"type": "array", "items": {"$ref": "#/$defs/row"}},
            "maybe": {"oneOf": [{"$ref": "#/$defs/row"}, {"type": "null"}]},
        },
        "$defs": {"row": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    model = build_model([_contract("record/rows", schema)])
    held = {rel.label: rel.cardinality for rel in model.relations if rel.source == "record_rows"}
    assert held == {"rows": "0..*", "maybe": "0..1"}


def test_a_union_without_a_common_const_is_a_union_not_an_abstract_class() -> None:
    plain = {"type": "object", "properties": {"x": {"type": "number"}}}
    union = {"oneOf": [{"$ref": "#/$defs/a"}, {"$ref": "#/$defs/b"}]}
    schema = {"$defs": {"pair": union, "a": plain, "b": plain}}
    model = build_model([_contract("record/pairs", schema)])
    assert model.classes["record_pairs__pair"].stereotype == "union"


def test_allof_with_a_ref_is_inheritance() -> None:
    base = {"type": "object", "properties": {"id": {"type": "string"}}}
    child = {"allOf": [{"$ref": "#/$defs/base"}, {"properties": {"extra": {"type": "string"}}}]}
    model = build_model([_contract("record/inherit", {"$defs": {"base": base, "child": child}})])
    assert [(rel.source, rel.target, rel.kind) for rel in model.relations] == [
        ("record_inherit__base", "record_inherit__child", "inheritance")
    ]
    assert _members(model, "record_inherit__child") == ["extra?: string"]


def _union_branches(schema: Any) -> list[Any]:
    branches = [b for keyword in ("oneOf", "anyOf") for b in schema.get(keyword, []) if isinstance(b, dict)]
    return [b for b in branches if b != {"type": "null"}]


def _is_object(contracts: dict[str, Contract], stem: str, branch: Any) -> bool:
    """A branch with properties, or a ``$ref`` to a ``$defs`` entry with properties."""
    if "properties" in branch:
        return True
    ref = branch.get("$ref", "")
    target, _, fragment = ref.partition("#/$defs/")
    if not fragment:
        return False
    folder = stem.rsplit("/", 1)[0]
    other = f"{folder}/{target.removesuffix('.schema.json')}" if target else stem
    return "properties" in contracts[other].schema.get("$defs", {}).get(fragment, {})


def test_every_object_definition_of_the_published_contracts_is_a_class() -> None:
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    classes = build_model(contracts).classes
    missing = [
        f"{contract.stem}#{name}"
        for contract in contracts
        for name, schema in contract.schema.get("$defs", {}).items()
        if "properties" in schema and class_id(contract.stem, name) not in classes
    ]
    assert missing == []


def test_every_document_root_and_every_union_of_objects_is_a_class() -> None:
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    by_stem = {contract.stem: contract for contract in contracts}
    classes = build_model(contracts).classes
    roots = [
        c.stem
        for c in contracts
        if "properties" in c.schema
        or (
            len(branches := _union_branches(c.schema)) > 1
            and all(_is_object(by_stem, c.stem, b) for b in branches)
        )
    ]
    assert {"jobs/job", "provider/protocol"} <= set(roots)
    unions = [
        class_id(contract.stem, name)
        for contract in contracts
        for name, schema in contract.schema.get("$defs", {}).items()
        if len(branches := _union_branches(schema)) > 1
        and all(_is_object(by_stem, contract.stem, b) for b in branches)
    ]
    assert unions
    assert [stem for stem in roots if class_id(stem, None) not in classes] == []
    assert [union for union in unions if union not in classes] == []


@pytest.fixture(scope="module")
def published() -> DomainModel:
    return build_model(load_contracts(REPO_ROOT / SCHEMAS_OUT))


def _relation(model: DomainModel, source: str, label: str) -> tuple[str, str, str]:
    (found,) = [rel for rel in model.relations if rel.source == source and rel.label == label]
    return found.target, found.kind, found.cardinality


def test_a_nullable_job_process_is_zero_or_one_process_identity(published: DomainModel) -> None:
    assert _relation(published, "jobs_job__JobRecord", "process") == (
        "jobs_job__ProcessIdentity",
        "composition",
        "0..1",
    )
    assert "jobs_job__JobRecord__process" not in published.classes
    assert "process: ProcessIdentity or null" in _members(published, "jobs_job__JobRecord")


def test_map_values_are_typed_and_related(published: DomainModel) -> None:
    assert "facets: facets by key" in _members(published, "record_evidence_assessment")
    assert _relation(published, "record_evidence_assessment", "facets") == (
        "record_evidence_assessment__facets",
        "composition",
        "0..*",
    )
    assert "parts?: version_part by key" in _members(published, "record_bundle_manifest")
    assert _relation(published, "record_bundle_manifest", "parts") == (
        "record_bundle_manifest__version_part",
        "composition",
        "0..*",
    )


def test_tuples_and_nested_arrays_keep_their_shape_and_bounds(published: DomainModel) -> None:
    assert "samples: [number, number][2..*]" in _members(published, "record_assembly__profile")
    holder = "record_interfaces__functional__print_in_place"
    assert "gap_features: face[2][1..*]" in _members(published, holder)
    assert _relation(published, holder, "gap_features") == ("record_interfaces__face", "composition", "2..*")


def test_literals_are_json(published: DomainModel) -> None:
    assert "make_buy: enum make|buy|null" in _members(published, "record_bom_row")
    assert not [held for node in published.classes.values() for held in node.fields if "None" in held.type]


def test_ref_counts_count_refs_anywhere_but_not_inside_the_same_contract() -> None:
    counts = ref_counts([PERSON, WIDGET])
    assert counts == {("record/widget", "common/person"): 1}


def test_a_ref_into_another_contracts_definition_names_the_helper_it_points_at() -> None:
    # A ref to an x-inline helper of another contract points at its place inside a definition there.
    holder = _contract(
        "record/holder",
        {"$defs": {"approval": {"type": "object", "properties": {"channel": {"enum": ["app", "chat"]}}}}},
    )
    request = _contract(
        "flow/request",
        {
            "type": "object",
            "required": ["channel"],
            "properties": {
                "channel": {"$ref": "../record/holder.schema.json#/$defs/approval/properties/channel"}
            },
        },
    )
    model = build_model([holder, request])
    assert model.classes["flow_request"].members == ["channel: channel = app|chat"]


def test_a_tuple_of_classes_holds_one_per_position() -> None:
    schema = {
        "type": "object",
        "required": ["pair"],
        "properties": {
            "pair": {
                "type": "array",
                "prefixItems": [{"$ref": "#/$defs/row"}, {"$ref": "#/$defs/row"}],
                "minItems": 2,
                "maxItems": 2,
            }
        },
        "$defs": {"row": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    model = build_model([_contract("record/pair", schema)])
    assert _members(model, "record_pair") == ["pair: [row, row]"]
    assert {rel.cardinality for rel in model.relations if rel.label == "pair"} == {"1"}


def test_a_branch_that_redeclares_an_inherited_property_keeps_it_required() -> None:
    base = {
        "type": "object",
        "required": ["value", "status"],
        "properties": {"status": {"type": "string"}, "value": True, "note": {"type": "string"}},
    }
    narrowed = {"allOf": [{"$ref": "#/$defs/base"}, {"properties": {"value": {"$ref": "#/$defs/row"}}}]}
    row = {"type": "object", "properties": {"n": {"type": "integer"}}}
    schema = {"$defs": {"base": base, "narrowed": narrowed, "row": row}}
    model = build_model([_contract("record/narrow", schema)])
    assert _members(model, "record_narrow__narrowed") == [
        "value: row"
    ]  # not status or note: they stay inherited
    (held,) = [
        rel for rel in model.relations if rel.source == "record_narrow__narrowed" and rel.label == "value"
    ]
    assert held.cardinality == "1"


def test_a_property_the_parent_does_not_require_stays_optional_when_redeclared() -> None:
    base = {"type": "object", "properties": {"value": True}}
    narrowed = {"allOf": [{"$ref": "#/$defs/base"}, {"properties": {"value": {"type": "number"}}}]}
    model = build_model([_contract("record/narrow", {"$defs": {"base": base, "narrowed": narrowed}})])
    assert _members(model, "record_narrow__narrowed") == ["value?: number"]


def test_a_redeclared_property_is_required_through_two_levels_of_parents(published: DomainModel) -> None:
    value = [
        held
        for held in published.classes["record_common__quantity_fact__known"].fields
        if held.name == "value"
    ]
    assert [held.required for held in value] == [True]
