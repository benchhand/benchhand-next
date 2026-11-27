# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The record store: typed reads and writes of hw/, validated against the contracts on read and on write."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml
from benchhand_contracts.models.record.part_schema import FormClass, ModelFrame
from benchhand_core.record import contracts, documents, store
from benchhand_core.record.errors import (
    RecordError,
    RecordMissingError,
    RecordReadError,
    RecordSchemaError,
    RecordVersionError,
)
from benchhand_core.record.model import BomRow, Policy


def tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def write_yaml(path: Path, document: object) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_the_lamp_arm_record_round_trips_through_save_and_load(lamp_arm: Path, tmp_path: Path) -> None:
    record = store.load_record(lamp_arm)
    assert sorted(record.parts) == [f"LMP-{n:04d}" for n in range(1, 12)]
    assert sorted(record.decisions) == ["DR-001", "DR-002", "DR-003", "DR-004", "DR-005", "DR-010"]
    assert sorted(record.manufacturing) == ["capabilities", "materials", "selection"]
    assert record.product.record_version == 3
    assert record.verification[0].requirement == "REQ-001"

    copy = tmp_path / "copy"
    store.save_record(copy, record)
    assert store.load_record(copy) == record

    first = tree(copy)
    store.save_record(copy, store.load_record(copy))
    assert tree(copy) == first  # saving what was read rewrites the same bytes


def test_saving_what_was_loaded_leaves_every_file_as_it_was(lamp_arm: Path) -> None:
    before = tree(lamp_arm)
    store.save_record(lamp_arm, store.load_record(lamp_arm))
    assert tree(lamp_arm) == before


def test_a_saved_change_keeps_the_file_key_order_and_adds_new_keys_after_it(lamp_arm: Path) -> None:
    path = lamp_arm / "hw/parts/LMP-0001/part.yaml"
    keys = list(yaml.safe_load(path.read_text(encoding="utf-8")))
    record = store.load_record(lamp_arm)
    part = record.parts["LMP-0001"]
    part.title = "Base plate, revised"
    part.form_class = FormClass.plate
    part.model_frame = ModelFrame.assembly_zero
    store.save_record(lamp_arm, record)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "model_frame" not in keys and "form_class" not in keys
    assert list(saved) == [*keys, "model_frame", "form_class"]  # new keys in the contract's order
    assert saved["title"] == "Base plate, revised"


def test_reading_keeps_decision_bodies_and_csv_cells_as_written(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    source = next((lamp_arm / "hw/decisions").glob("DR-004-*.md"))
    assert source.read_text(encoding="utf-8").endswith(record.decisions["DR-004"].body)
    assert record.decisions["DR-003"].front.status.value == "superseded"
    bushing = next(row for row in record.bom if row.pn == "LMP-0008")
    assert bushing.mass == 2.0 and bushing.qty == 1 and bushing.supplier is None
    assert bushing.specification_revision == "01/24"


def test_a_crlf_decision_body_round_trips_byte_for_byte(lamp_arm: Path, tmp_path: Path) -> None:
    source = next((lamp_arm / "hw/decisions").glob("DR-004-*.md"))
    text = source.read_bytes().replace(b"\n", b"\r\n")
    source.write_bytes(text)
    body = text.split(b"---\r\n", 2)[2]

    record = store.load_record(lamp_arm)
    assert record.decisions["DR-004"].body.encode() == body
    copy = tmp_path / "copy"
    store.save_record(copy, record)
    assert (copy / source.relative_to(lamp_arm)).read_bytes().endswith(b"---\n" + body)
    assert store.load_record(copy).decisions["DR-004"] == record.decisions["DR-004"]


@pytest.mark.parametrize("version", [2, 4, "3", True, None])
def test_any_record_version_but_3_is_refused_and_nothing_changes(lamp_arm: Path, version: object) -> None:
    product_path = lamp_arm / "hw/product.yaml"
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    if version is None:
        del product["record_version"]
    else:
        product["record_version"] = version
    write_yaml(product_path, product)
    before = tree(lamp_arm)

    with pytest.raises(RecordVersionError) as raised:
        store.load_record(lamp_arm)

    assert raised.value.code == "record.version_unsupported"
    assert raised.value.path == "hw/product.yaml"
    assert tree(lamp_arm) == before


def test_the_prototype_record_is_refused_by_its_version_first(prototype_lamp_arm: Path) -> None:
    with pytest.raises(RecordVersionError):
        store.load_record(prototype_lamp_arm)
    read = store.read_record(prototype_lamp_arm)
    # the old verification.csv header is reported too; reading reports every problem it meets
    assert {error.code for error in read.errors} >= {"record.version_unsupported", "record.unreadable"}


def test_a_schema_violation_names_the_document_pointer_and_the_schema_path(lamp_arm: Path) -> None:
    part_path = lamp_arm / "hw/parts/LMP-0001/part.yaml"
    part = yaml.safe_load(part_path.read_text(encoding="utf-8"))
    part["rev"] = "O"  # a reserved revision letter
    write_yaml(part_path, part)

    with pytest.raises(RecordSchemaError) as raised:
        store.load_record(lamp_arm)

    assert raised.value.path == "hw/parts/LMP-0001/part.yaml"
    [violation] = raised.value.violations
    assert violation.pointer == "/rev"
    # The location is the keyword that failed, past the $ref that led there, and it resolves.
    resource, _, keyword = violation.schema_path.partition("#")
    assert resource == contracts.schema_id("common")
    assert keyword == "/$defs/revision/pattern"
    assert isinstance(contracts.schema("common")["$defs"]["revision"]["pattern"], str)


def test_a_bad_csv_row_is_pointed_to_by_its_row_index_and_column(lamp_arm: Path) -> None:
    bom_path = lamp_arm / "hw/bom.csv"
    lines = bom_path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace(",cnc,make,", ",laser-sintering,make,")
    bom_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(RecordSchemaError) as raised:
        store.load_record(lamp_arm)

    assert raised.value.path == "hw/bom.csv"
    assert [violation.pointer for violation in raised.value.violations] == ["/1/process"]


def test_a_csv_with_columns_out_of_order_is_unreadable(lamp_arm: Path) -> None:
    (lamp_arm / "hw/verification.csv").write_text(
        "method,requirement,criteria,result,evidence\nT,REQ-001,x,planned,\n", encoding="utf-8"
    )
    with pytest.raises(RecordReadError, match="expected CSV columns in order"):
        store.load_record(lamp_arm)


def test_a_yaml_key_given_twice_is_unreadable(lamp_arm: Path) -> None:
    path = lamp_arm / "hw/interfaces.yaml"
    path.write_text("interfaces: []\ninterfaces: []\n", encoding="utf-8")
    with pytest.raises(RecordReadError, match="given twice") as raised:
        store.load_record(lamp_arm)
    assert raised.value.path == "hw/interfaces.yaml"


def test_a_missing_required_document_is_named(lamp_arm: Path) -> None:
    (lamp_arm / "hw/assembly.yaml").unlink()
    with pytest.raises(RecordMissingError) as raised:
        store.load_record(lamp_arm)
    assert raised.value.path == "hw/assembly.yaml"


def test_a_part_directory_must_be_named_after_its_pn(lamp_arm: Path) -> None:
    parts = lamp_arm / "hw/parts"
    (parts / "LMP-0011").rename(parts / "LMP-0099")
    (parts / "LMP-0012").mkdir()
    (parts / "LMP-0012/part.yaml").write_bytes((parts / "LMP-0001/part.yaml").read_bytes())

    read = store.read_record(lamp_arm)

    by_path = {error.path: error.code for error in read.errors}
    assert by_path == {
        "hw/parts/LMP-0099/part.yaml": "part.directory_mismatch",
        "hw/parts/LMP-0012/part.yaml": "part.duplicate",
    }
    assert "LMP-0001" in read.parts and "LMP-0012" not in read.parts


def test_a_decision_file_needs_the_id_and_slug_name_and_its_own_id(lamp_arm: Path) -> None:
    decisions = lamp_arm / "hw/decisions"
    dr_001 = next(decisions.glob("DR-001-*.md"))
    (decisions / "DR-006.md").write_bytes(dr_001.read_bytes())
    (decisions / "DR-007-copy.md").write_bytes(dr_001.read_bytes())
    (decisions / "DR-001-again.md").write_bytes(dr_001.read_bytes())

    read = store.read_record(lamp_arm)

    assert {error.path: error.code for error in read.errors} == {
        "hw/decisions/DR-006.md": "decision.file_name",
        "hw/decisions/DR-007-copy.md": "decision.id_mismatch",
        dr_001.relative_to(lamp_arm).as_posix(): "decision.duplicate",
    }


def test_a_decision_without_front_matter_is_unreadable(lamp_arm: Path) -> None:
    path = next((lamp_arm / "hw/decisions").glob("DR-005-*.md"))
    path.write_text("# A decision\n\nStatus: APPROVED\n", encoding="utf-8")
    with pytest.raises(RecordReadError, match="no YAML front matter"):
        store.load_record(lamp_arm)


def test_saving_an_invalid_record_touches_no_file(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    record.product = record.product.model_copy(update={"id": "Not A Slug"})
    record.requirements.requirements[0] = record.requirements.requirements[0].model_copy(update={"id": "R1"})

    with pytest.raises(RecordSchemaError) as raised:
        store.save_record(lamp_arm, record)

    assert raised.value.path == "hw/product.yaml"
    assert tree(lamp_arm) == before


def test_saving_refuses_a_record_version_other_than_3(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    product = record.product.model_copy(update={"record_version": 2})
    with pytest.raises(RecordVersionError):
        store.save_document(lamp_arm, documents.PRODUCT, product)


def test_save_document_writes_one_validated_document(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    policy = Policy.model_validate(
        {"policy_version": 1, "default": "ask", "gates": {"layout_freeze": {"mode": "chat"}}}
    )
    with pytest.raises(RecordSchemaError, match="decision"):
        store.save_document(lamp_arm, documents.POLICY, policy)
    assert not (lamp_arm / "hw/policy.yaml").exists()

    assert policy.gates is not None
    policy.gates["layout_freeze"].decision = "DR-010"
    store.save_document(lamp_arm, documents.POLICY, policy)
    assert store.load_record(lamp_arm).policy == policy
    assert store.load_record(lamp_arm).parts == record.parts


def test_the_converted_template_loads_with_no_parts(template: Path) -> None:
    record = store.load_record(template)
    assert record.parts == {} and record.decisions == {}
    assert record.product.flow.stage == "ground"


def test_the_empty_template_saves_into_a_new_root_that_loads(template: Path, tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    record = store.load_record(template)
    store.save_record(fresh, record)
    assert store.load_record(fresh) == record


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_a_csv_integer_given_as_a_float_is_written_as_an_integer(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    record.bom[1].qty = 1.0  # type: ignore[assignment]  # JSON Schema counts 1.0 as an integer
    store.save_record(lamp_arm, record)
    assert store.load_record(lamp_arm).bom[1].qty == 1


def test_an_empty_text_cell_is_refused_because_a_blank_cell_reads_as_null(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    record.bom[1].title = ""
    with pytest.raises(RecordSchemaError) as raised:
        store.save_record(lamp_arm, record)
    assert [violation.pointer for violation in raised.value.violations] == ["/1/title"]
    assert tree(lamp_arm) == before


def test_a_part_saved_under_another_pn_or_a_bad_decision_id_touches_no_file(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    record.parts["LMP-0012"] = record.parts.pop("LMP-0011")
    with pytest.raises(RecordError) as raised:
        store.save_record(lamp_arm, record)
    assert raised.value.code == "part.directory_mismatch"
    assert raised.value.path == "hw/parts/LMP-0012/part.yaml"
    assert tree(lamp_arm) == before

    record = store.load_record(lamp_arm)
    record.decisions["DR-001"].front.id = "DR-1"
    with pytest.raises(RecordSchemaError) as raised:
        store.save_record(lamp_arm, record)
    assert "/id" in [violation.pointer for violation in raised.value.violations]
    assert tree(lamp_arm) == before


def test_a_non_finite_number_is_refused_with_its_pointer(lamp_arm: Path) -> None:
    path = lamp_arm / "hw/assembly.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("[0, 0, 21.495]", "[0, 0, .nan]"))
    with pytest.raises(RecordSchemaError) as raised:
        store.load_record(lamp_arm)
    [violation] = raised.value.violations
    assert violation.pointer.startswith("/occurrences/") and violation.pointer.endswith("/translation_mm/2")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("interfaces.yaml", "interfaces: []\x07\n"),  # a control character YAML forbids
        ("verification.csv", 'requirement,method,criteria,result,evidence\nREQ-001,T,"unterminated\n'),
    ],
)
def test_malformed_text_is_an_unreadable_finding_not_a_crash(lamp_arm: Path, name: str, text: str) -> None:
    (lamp_arm / "hw" / name).write_text(text, encoding="utf-8")
    read = store.read_record(lamp_arm)
    assert [(error.code, error.path) for error in read.errors] == [("record.unreadable", f"hw/{name}")]


def test_an_integer_cell_past_the_digit_limit_is_unreadable_at_its_line_and_column(lamp_arm: Path) -> None:
    bom_path = lamp_arm / "hw/bom.csv"
    lines = bom_path.read_text(encoding="utf-8").splitlines()
    cells = lines[2].split(",")
    cells[3] = "1" * 5000  # qty; int() refuses more than 4300 digits
    lines[2] = ",".join(cells)
    bom_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RecordReadError, match="line 3, column qty"):
        store.load_record(lamp_arm)


def test_a_bom_where_only_some_rows_state_the_procurement_columns_touches_no_file(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    plain = {"level": 1, "PN": "LMP-0001", "rev": "A", "qty": 1, "title": "Base", "material": None}
    plain |= {"process": None, "make_buy": "make", "supplier": None, "mass": None}
    record.bom.append(BomRow.model_validate(plain))
    with pytest.raises(RecordError) as raised:
        store.save_record(lamp_arm, record)
    assert (raised.value.code, raised.value.path) == ("record.csv_columns", "hw/bom.csv")
    assert tree(lamp_arm) == before


def test_a_decision_saved_under_a_new_slug_beside_its_old_file_touches_no_file(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    renamed = dataclasses.replace(record.decisions["DR-001"], slug="renamed")
    with pytest.raises(RecordError) as raised:
        store.save_decision(lamp_arm, renamed)
    assert (raised.value.code, raised.value.path) == ("decision.duplicate", "hw/decisions/DR-001-renamed.md")
    record.decisions["DR-001"] = renamed
    with pytest.raises(RecordError, match="DR-001 is also the id of DR-001-"):
        store.save_record(lamp_arm, record)
    assert tree(lamp_arm) == before


def test_save_document_and_save_decision_check_the_file_identity_first(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    before = tree(lamp_arm)
    with pytest.raises(RecordError) as raised:
        store.save_document(lamp_arm, documents.part("LMP-0012"), record.parts["LMP-0011"])
    assert raised.value.code == "part.directory_mismatch"
    assert raised.value.path == "hw/parts/LMP-0012/part.yaml"

    decision = record.decisions["DR-001"]
    fields = decision.front.model_dump(exclude={"id"}, exclude_unset=True)
    without_id = dataclasses.replace(decision, front=type(decision.front).model_construct(**fields))
    with pytest.raises(RecordSchemaError, match="'id' is a required property"):
        store.save_decision(lamp_arm, without_id)
    assert tree(lamp_arm) == before


@pytest.mark.parametrize("stem", ["../escape", "nested/inner", "..", ""])
def test_a_guideline_key_is_one_file_name(stem: str) -> None:
    with pytest.raises(ValueError, match="not a guideline file stem"):
        documents.guideline(stem)


def test_a_gate_title_that_is_one_line_with_a_visible_character_loads(lamp_arm: Path) -> None:
    # U+0085 is whitespace to Python's re but not to ECMAScript; the contract's class is ECMAScript's.
    gate = 'kind: gate\nstatus: provisional\ngate: layout_freeze\nstage: layout\ntitle: "\\N"\n'
    (lamp_arm / "hw/decisions/DR-021-nel.md").write_text(
        f"---\nid: DR-021\ndate: '2026-11-21'\n{gate}---\n", encoding="utf-8"
    )
    assert store.load_record(lamp_arm).decisions["DR-021"].front.title == "\x85"
