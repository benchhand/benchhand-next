"""The domain model generated from the published schemas: classes, relations, cardinality and unions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from contracts_gen.docs import write_docs
from contracts_gen.domain import MAX_ENUM_VALUES, build_model, class_id
from contracts_gen.domain_render import DOMAIN_MODEL_FILE, MAX_DIAGRAM_CLASSES, render_domain_model
from contracts_gen.sources import DOCS_OUT, REPO_ROOT, SCHEMAS_OUT, Contract, load_contracts
from mermaid_render import MERMAID_READY, MERMAID_SKIP_REASON, mermaid_blocks, render_markdown

needs_mermaid = pytest.mark.skipif(not MERMAID_READY, reason=MERMAID_SKIP_REASON)


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

EXPECTED_RECORD_DIAGRAM = """\
classDiagram
    class record_widget["widget"] {
        id: part_id
        status: enum draft|released
        size?: enum
        notes?: object
        tags?: string[]
        lines: line[]
        owner?: person
        step: step
    }
    class record_widget__notes["widget.notes"] {
        text?: string
    }
    class record_widget__line["line"] {
        qty: integer
    }
    class record_widget__step["step"] {
        <<abstract>>
        kind: discriminator
    }
    class record_widget__press["press"] {
        kind: const press
        force: number
    }
    class record_widget__bolt["bolt"] {
        kind: const bolt
        torque?: number
    }
    class common_person["common/person.person"] {
        <<external>>
    }
    record_widget "1" *-- "0..1" record_widget__notes : notes
    record_widget "1" *-- "1..*" record_widget__line : lines
    record_widget --> "0..1" common_person : owner
    record_widget__step <|-- record_widget__press
    record_widget__step <|-- record_widget__bolt
    record_widget "1" *-- "1" record_widget__step : step"""


def _blocks(markdown: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)\n```", markdown, flags=re.DOTALL)


def test_a_synthetic_contract_renders_nesting_arrays_optionals_refs_and_a_discriminated_union() -> None:
    blocks = _blocks(render_domain_model([PERSON, WIDGET]))
    assert blocks[-1] == EXPECTED_RECORD_DIAGRAM


def test_the_overview_shows_the_record_documents_and_nothing_else() -> None:
    overview = _blocks(render_domain_model([PERSON, WIDGET]))[0]
    assert 'class record_widget["widget"]' in overview
    assert "<<document>>" in overview
    assert "common_person" not in overview


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
    assert model.classes["record_inherit__child"].members == ["extra?: string"]


def test_a_group_over_the_class_limit_is_split_by_document_without_dropping_a_class() -> None:
    def crowded(stem: str) -> Contract:
        defs = {f"item_{n}": {"type": "object", "properties": {"n": {"type": "integer"}}} for n in range(30)}
        return _contract(stem, {"$defs": defs})

    text = render_domain_model([crowded("record/first"), crowded("record/second")])
    assert f"more than {MAX_DIAGRAM_CLASSES}, so there is one diagram per document" in text
    assert "### `record/first`" in text
    assert "### `record/second`" in text
    for stem in ("record/first", "record/second"):
        assert all(f"class {class_id(stem, f'item_{n}')}[" in text for n in range(30))


def test_every_object_definition_of_the_published_contracts_is_a_class() -> None:
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    text = render_domain_model(contracts)
    missing = [
        f"{contract.stem}#{name}"
        for contract in contracts
        for name, schema in contract.schema.get("$defs", {}).items()
        if "properties" in schema and f"class {class_id(contract.stem, name)}[" not in text
    ]
    assert missing == []


def test_the_docs_include_the_domain_model_and_link_it_from_the_index(tmp_path: Path) -> None:
    write_docs([PERSON, WIDGET], tmp_path)
    assert (tmp_path / DOMAIN_MODEL_FILE).read_text().startswith("# Domain model\n")
    assert f"]({DOMAIN_MODEL_FILE})" in (tmp_path / "README.md").read_text()


def test_the_committed_domain_model_is_what_the_generator_writes() -> None:
    """The drift check covers every generated file; this one names the file a reader opens."""
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    committed = (REPO_ROOT / DOCS_OUT / DOMAIN_MODEL_FILE).read_text(encoding="utf-8")
    assert committed == render_domain_model(contracts)


@needs_mermaid
def test_every_synthetic_block_renders(tmp_path: Path) -> None:
    text = render_domain_model([PERSON, WIDGET])
    assert len(render_markdown(text, tmp_path)) == mermaid_blocks(text)


@needs_mermaid
def test_every_block_of_the_domain_model_renders(tmp_path: Path) -> None:
    text = (REPO_ROOT / DOCS_OUT / DOMAIN_MODEL_FILE).read_text(encoding="utf-8")
    assert len(render_markdown(text, tmp_path)) == mermaid_blocks(text)
