"""The record store: typed reads and writes of hw/, validated against the contracts on read and on write."""

from __future__ import annotations

from pathlib import Path

import prototype_v2
import pytest
import yaml
from benchhand_core.record import documents, store
from benchhand_core.record.errors import (
    RecordMissingError,
    RecordReadError,
    RecordSchemaError,
    RecordVersionError,
)


def tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def write_yaml(path: Path, document: object) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_the_lamp_arm_record_round_trips_through_save_and_load(lamp_arm: Path, tmp_path: Path) -> None:
    record = store.load_record(lamp_arm)
    assert sorted(record.parts) == [f"LMP-{n:04d}" for n in range(1, 12)]
    assert sorted(record.decisions) == ["DR-001", "DR-002", "DR-003", "DR-004", "DR-005", "DR-010"]
    assert sorted(record.manufacturing) == ["capabilities", "materials", "selection"]
    assert record.product["record_version"] == 3
    assert record.verification[0]["requirement"] == "REQ-001"

    copy = tmp_path / "copy"
    store.save_record(copy, record)
    assert store.load_record(copy) == record

    first = tree(copy)
    store.save_record(copy, store.load_record(copy))
    assert tree(copy) == first  # saving what was read rewrites the same bytes


def test_reading_keeps_decision_bodies_and_csv_cells_as_written(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    source = next((lamp_arm / "hw/decisions").glob("DR-004-*.md"))
    assert source.read_text(encoding="utf-8").endswith(record.decisions["DR-004"].body)
    assert record.decisions["DR-003"].front["status"] == "superseded"
    bushing = next(row for row in record.bom if row["PN"] == "LMP-0008")
    assert bushing["mass"] == 2.0 and bushing["qty"] == 1 and bushing["supplier"] is None
    assert bushing["specification_revision"] == "01/24"


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
    assert violation.schema_path == "part.schema.json#/properties/rev/pattern"


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
    record.product["flow"]["stage"] = "finished"
    record.requirements["requirements"][0]["priority"] = "maybe"

    with pytest.raises(RecordSchemaError) as raised:
        store.save_record(lamp_arm, record)

    assert raised.value.path == "hw/product.yaml"
    assert tree(lamp_arm) == before


def test_saving_refuses_a_record_version_other_than_3(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    record.product["record_version"] = 2
    with pytest.raises(RecordVersionError):
        store.save_document(lamp_arm, documents.PRODUCT, record.product)


def test_save_document_writes_one_validated_document(lamp_arm: Path) -> None:
    record = store.load_record(lamp_arm)
    policy = {"policy_version": 1, "default": "ask", "gates": {"layout_freeze": {"mode": "chat"}}}
    with pytest.raises(RecordSchemaError, match="decision"):
        store.save_document(lamp_arm, documents.POLICY, policy)
    assert not (lamp_arm / "hw/policy.yaml").exists()

    policy["gates"]["layout_freeze"]["decision"] = "DR-010"
    store.save_document(lamp_arm, documents.POLICY, policy)
    assert store.load_record(lamp_arm).policy == policy
    assert store.load_record(lamp_arm).parts == record.parts


def test_the_converted_template_loads_with_no_parts(template: Path) -> None:
    record = store.load_record(template)
    assert record.parts == {} and record.decisions == {}
    assert record.product["flow"]["stage"] == "ground"


def test_the_fixture_converter_only_renames_what_the_migration_page_lists() -> None:
    migration = (Path(__file__).resolve().parents[4] / "docs/contract/record-migration.md").read_text()
    renames = {
        **prototype_v2.HEAT_SET_RENAMES,
        **prototype_v2.BOM_COLUMN_RENAMES,
        **prototype_v2.VERIFICATION_COLUMN_RENAMES,
    }
    for old, new in renames.items():
        assert f"| `{old}` | `{new}` |" in migration
