# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""validate(): the findings on a record, ported from the prototype's validator cases that still hold."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import validate as validate_contract
from benchhand_core.record.finding import Finding, Severity
from benchhand_core.record.validate import validate

FINDING_ID = "https://benchhand.github.io/benchhand/contracts/common/finding.schema.json"


def edit(root: Path, path: str, change: Callable[[Any], None]) -> None:
    """Load hw/<path> as YAML, apply `change` in place, and write it back."""
    file = root / "hw" / path
    document = yaml.safe_load(file.read_text(encoding="utf-8"))
    change(document)
    file.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def edit_csv(root: Path, name: str, change: Callable[[list[str]], None]) -> None:
    file = root / "hw" / name
    lines = file.read_text(encoding="utf-8").splitlines()
    change(lines)
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_decision(root: Path, front: dict[str, Any], slug: str = "test") -> None:
    text = f"---\n{yaml.safe_dump(front, sort_keys=False)}---\n\n# {front['title']}\n"
    (root / "hw/decisions" / f"{front['id']}-{slug}.md").write_text(text, encoding="utf-8")


def found(findings: list[Finding]) -> set[tuple[str, str, str | None]]:
    return {(finding.code, finding.path, finding.pointer) for finding in findings}


def test_the_lamp_arm_record_validates_with_no_findings(lamp_arm: Path) -> None:
    assert validate(lamp_arm) == []


def test_the_empty_template_validates_at_ground_but_needs_parts_from_layout(template: Path) -> None:
    assert validate(template) == []
    edit(template, "product.yaml", lambda product: product["flow"].update(stage="layout"))
    assert found(validate(template)) == {("record.no_parts", "hw/parts", None)}


def test_a_project_without_hw_is_one_missing_finding(tmp_path: Path) -> None:
    assert found(validate(tmp_path)) == {("record.missing", "hw", None)}


@pytest.mark.parametrize("version", [1, 2, 4, None])
def test_an_unsupported_record_version_is_named_with_the_other_findings_and_nothing_changes(
    lamp_arm: Path, version: int | None
) -> None:
    def set_version(product: dict[str, Any]) -> None:
        product.pop("record_version")
        if version is not None:
            product["record_version"] = version

    edit(lamp_arm, "product.yaml", set_version)
    edit_csv(lamp_arm, "verification.csv", lambda lines: lines.append("REQ-099,T,x,planned,"))
    before = {path: path.read_bytes() for path in lamp_arm.rglob("*") if path.is_file()}

    findings = validate(lamp_arm)

    assert ("record.version_unsupported", "hw/product.yaml", "/record_version") in found(findings)
    assert ("verification.unknown_requirement", "hw/verification.csv", "/7/requirement") in found(findings)
    version_finding = next(f for f in findings if f.code == "record.version_unsupported")
    assert version_finding.action is not None and "nothing was changed" in version_finding.action
    assert {path: path.read_bytes() for path in lamp_arm.rglob("*") if path.is_file()} == before


def test_every_finding_meets_the_finding_contract(prototype_lamp_arm: Path, lamp_arm: Path) -> None:
    (lamp_arm / "hw/parts/LMP-0011").rename(lamp_arm / "hw/parts/LMP-0099")
    edit_csv(lamp_arm, "bom.csv", lambda lines: lines.append(lines[1].replace("LMP-0001", "LMP-0098")))
    edit(lamp_arm, "parts/LMP-0001/part.yaml", lambda part: part["decisions"].append("DR-099"))
    edit(lamp_arm, "assembly.yaml", lambda assembly: assembly["joints"][0].update(parent="LMP-0097"))
    findings = validate(prototype_lamp_arm) + validate(lamp_arm)
    codes = {finding.code for finding in findings}
    assert {
        "record.version_unsupported",
        "record.schema",
        "record.unreadable",
        "part.directory_mismatch",
    } <= codes
    assert {
        "bom.unknown_part",
        "assembly.unknown_part",
        "assembly.joint_reference",
        "decision.reference",
    } <= codes
    for finding in findings:
        validate_contract(FINDING_ID, finding.model_dump(mode="json", exclude_unset=True))
        assert finding.severity is Severity.error


# --- decisions -----------------------------------------------------------------------------------------


def test_a_part_citing_a_decision_without_a_record_is_rejected(lamp_arm: Path) -> None:
    edit(lamp_arm, "parts/LMP-0001/part.yaml", lambda part: part["decisions"].append("DR-099"))
    assert found(validate(lamp_arm)) == {
        ("decision.reference", "hw/parts/LMP-0001/part.yaml", "/decisions/2")
    }


def test_citing_a_decision_the_reader_refuses_names_the_file_and_the_citation(lamp_arm: Path) -> None:
    dr_010 = next((lamp_arm / "hw/decisions").glob("DR-010-*.md"))
    dr_010.write_text(dr_010.read_text(encoding="utf-8").replace("status: accepted", "status: APPROVED"))
    assert {(code, path) for code, path, _ in found(validate(lamp_arm))} == {
        ("record.schema", dr_010.relative_to(lamp_arm).as_posix()),
        ("decision.reference", "hw/product.yaml"),
    }


@pytest.mark.parametrize(
    ("front", "approves"),
    [
        ({"kind": "design", "status": "accepted"}, True),
        ({"kind": "design", "status": "proposed"}, False),
        ({"kind": "design", "status": "rejected"}, False),
        ({"kind": "gate", "status": "provisional", "gate": "design_freeze", "stage": "design_freeze"}, False),
        ({"kind": "gate", "status": "void", "gate": "design_freeze", "stage": "design_freeze"}, False),
        (
            {
                "kind": "gate",
                "status": "approved",
                "gate": "design_freeze",
                "stage": "design_freeze",
                "approval": {"channel": "chat", "by": "the user", "quote": "Freeze v1."},
            },
            True,
        ),
    ],
)
def test_only_a_gate_approved_or_a_design_accepted_freezes_a_version(
    lamp_arm: Path, front: dict[str, Any], approves: bool
) -> None:
    write_decision(lamp_arm, {"id": "DR-020", "title": "Freeze v1", "date": "2026-11-20", **front})
    frozen = {"version": "v1", "manifest_sha256": "a" * 64, "decision": "DR-020"}
    edit(lamp_arm, "product.yaml", lambda product: product["flow"].update(frozen=frozen))

    expected = set() if approves else {("decision.not_approving", "hw/product.yaml", "/flow/frozen/decision")}
    assert found(validate(lamp_arm)) == expected


def test_a_superseded_decision_no_longer_approves_the_flow_profile(lamp_arm: Path) -> None:
    edit(lamp_arm, "product.yaml", lambda product: product["flow"]["profile"].update(decision="DR-003"))
    assert found(validate(lamp_arm)) == {
        ("decision.not_approving", "hw/product.yaml", "/flow/profile/decision")
    }


@pytest.mark.parametrize(
    ("policy", "blocks"),
    [
        (None, True),
        ({"policy_version": 1, "default": "chat", "decision": "DR-010"}, True),
        ({"policy_version": 1, "gates": {"layout_freeze": {"mode": "auto", "decision": "DR-010"}}}, False),
        ({"policy_version": 1, "default": "auto", "decision": "DR-010"}, False),
        (
            {
                "policy_version": 1,
                "default": "auto",
                "decision": "DR-010",
                "gates": {"layout_freeze": {"mode": "ask"}},
            },
            True,
        ),
    ],
)
def test_an_approved_gate_records_its_approval_unless_its_policy_mode_is_auto(
    lamp_arm: Path, policy: dict[str, Any] | None, blocks: bool
) -> None:
    if policy is not None:
        (lamp_arm / "hw/policy.yaml").write_text(yaml.safe_dump(policy), encoding="utf-8")
    gate = {"kind": "gate", "status": "approved", "gate": "layout_freeze", "stage": "layout"}
    write_decision(lamp_arm, {"id": "DR-021", "title": "Layout freeze", "date": "2026-11-21", **gate})

    expected = (
        {("decision.approval_missing", "hw/decisions/DR-021-test.md", "/approval")} if blocks else set()
    )
    assert found(validate(lamp_arm)) == expected


@pytest.mark.parametrize("policy", [None, {"policy_version": 1, "default": "chat", "decision": "DR-010"}])
def test_an_automatic_approval_does_not_pass_a_gate_that_asks(
    lamp_arm: Path, policy: dict[str, Any] | None
) -> None:
    if policy is not None:
        (lamp_arm / "hw/policy.yaml").write_text(yaml.safe_dump(policy), encoding="utf-8")
    gate = {"kind": "gate", "status": "approved", "gate": "layout_freeze", "stage": "layout"}
    approval = {"approval": {"channel": "auto"}}
    write_decision(
        lamp_arm, {"id": "DR-021", "title": "Layout freeze", "date": "2026-11-21", **gate, **approval}
    )
    assert found(validate(lamp_arm)) == {
        ("decision.approval_channel", "hw/decisions/DR-021-test.md", "/approval/channel")
    }


def test_supersedes_must_name_another_existing_decision(lamp_arm: Path) -> None:
    gate = {"kind": "gate", "status": "void", "gate": "layout_freeze", "stage": "layout"}
    write_decision(
        lamp_arm,
        {
            "id": "DR-022",
            "title": "Void layout freeze",
            "date": "2026-11-22",
            **gate,
            "supersedes": ["DR-022", "DR-098"],
        },
    )
    assert found(validate(lamp_arm)) == {
        ("decision.reference", "hw/decisions/DR-022-test.md", "/supersedes/0"),
        ("decision.reference", "hw/decisions/DR-022-test.md", "/supersedes/1"),
    }


# --- parts ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("render", ["shown", "ghost", "hidden"])
def test_a_part_names_how_a_render_draws_it(lamp_arm: Path, render: str) -> None:
    edit(lamp_arm, "parts/LMP-0003/part.yaml", lambda part: part.update(render=render))
    assert validate(lamp_arm) == []


def test_a_render_default_other_than_shown_ghost_or_hidden_is_refused(lamp_arm: Path) -> None:
    edit(lamp_arm, "parts/LMP-0003/part.yaml", lambda part: part.update(render="transparent"))
    part_findings = {item for item in found(validate(lamp_arm)) if item[1] == "hw/parts/LMP-0003/part.yaml"}
    assert part_findings == {("record.schema", "hw/parts/LMP-0003/part.yaml", "/render")}


# --- BOM ------------------------------------------------------------------------------------------------


def test_a_bom_row_must_name_a_part_record_unless_it_is_an_assembly(lamp_arm: Path) -> None:
    def add_rows(lines: list[str]) -> None:
        lines.insert(1, "0,LMP-0100,X1,1,Lamp arm,,,,,,pcs,,,,,,")
        lines.append("1,LMP-0098,X1,1,Ghost,PETG,fdm,make,,1,pcs,,,,,,")

    edit_csv(lamp_arm, "bom.csv", add_rows)
    assert found(validate(lamp_arm)) == {("bom.unknown_part", "hw/bom.csv", "/12/PN")}


def test_a_bom_row_states_what_its_part_record_states(lamp_arm: Path) -> None:
    edit(lamp_arm, "parts/LMP-0002/part.yaml", lambda part: part.update(title="Lower arm", mass_target=150))
    assert found(validate(lamp_arm)) == {
        ("bom.mismatch", "hw/bom.csv", "/1/title"),
        ("bom.mismatch", "hw/bom.csv", "/1/mass"),
    }


def test_bom_procurement_columns_follow_the_part_procurement(lamp_arm: Path) -> None:
    edit(lamp_arm, "parts/LMP-0008/part.yaml", lambda part: part["procurement"].update(designation="other"))
    assert found(validate(lamp_arm)) == {("bom.mismatch", "hw/bom.csv", "/2/designation")}


def test_bom_levels_start_at_0_or_1_and_never_skip_a_depth(lamp_arm: Path) -> None:
    edit_csv(lamp_arm, "bom.csv", lambda lines: lines.__setitem__(2, "3" + lines[2][1:]))
    assert found(validate(lamp_arm)) == {("bom.level", "hw/bom.csv", "/1/level")}


def test_the_bom_quantity_matches_the_number_of_occurrences(lamp_arm: Path) -> None:
    edit_csv(lamp_arm, "bom.csv", lambda lines: lines.__setitem__(9, lines[9].replace(",X1,3,", ",X1,2,")))
    [finding] = validate(lamp_arm)
    assert (finding.code, finding.pointer, finding.subject) == ("bom.quantity", "/8/qty", "LMP-0011")
    assert "@ring-base, @ring-elbow, @ring-head" in finding.message


def test_deleting_the_only_bom_row_of_a_placed_part_counts_zero(lamp_arm: Path) -> None:
    edit_csv(lamp_arm, "bom.csv", lambda lines: lines.__delitem__(9))  # LMP-0011, placed three times
    [finding] = validate(lamp_arm)
    assert (finding.code, finding.pointer, finding.subject) == ("bom.quantity", None, "LMP-0011")
    assert "BOM quantity of LMP-0011 is 0" in finding.message


# --- verification ---------------------------------------------------------------------------------------


def test_each_requirement_has_one_verification_row_and_each_row_a_requirement(lamp_arm: Path) -> None:
    def rows(lines: list[str]) -> None:
        lines.append(lines[1])
        lines.append(lines[1].replace("REQ-001", "REQ-099"))
        del lines[2]  # REQ-002

    edit_csv(lamp_arm, "verification.csv", rows)
    assert found(validate(lamp_arm)) == {
        ("verification.duplicate", "hw/verification.csv", "/6/requirement"),
        ("verification.unknown_requirement", "hw/verification.csv", "/7/requirement"),
        ("verification.missing", "hw/verification.csv", None),
    }


def test_a_requirement_id_given_twice_is_reported_at_the_later_requirement(lamp_arm: Path) -> None:
    def duplicate(requirements: dict[str, Any]) -> None:
        requirements["requirements"][1]["id"] = requirements["requirements"][0]["id"]

    edit(lamp_arm, "requirements.yaml", duplicate)
    assert found(validate(lamp_arm)) >= {
        ("requirements.duplicate", "hw/requirements.yaml", "/requirements/1/id"),
    }


# --- assembly -------------------------------------------------------------------------------------------


def test_joint_ends_resolve_to_one_placed_occurrence_each(lamp_arm: Path) -> None:
    def joints(assembly: dict[str, Any]) -> None:
        assembly["joints"][0]["parent"] = "LMP-0099"  # no part record
        assembly["joints"][1]["child"] = "LMP-0011"  # placed three times
        assembly["joints"][2]["child"] = "@ring-nowhere"
        assembly["subassemblies"][1]["parts"].remove("LMP-0010")
        assembly["joints"][3]["child"] = "LMP-0010"  # a part record, placed nowhere

    edit(lamp_arm, "assembly.yaml", joints)
    findings = validate(lamp_arm)
    assert found(findings) >= {
        ("assembly.joint_reference", "hw/assembly.yaml", "/joints/0/parent"),
        ("assembly.joint_reference", "hw/assembly.yaml", "/joints/1/child"),
        ("assembly.joint_reference", "hw/assembly.yaml", "/joints/2/child"),
        ("assembly.joint_reference", "hw/assembly.yaml", "/joints/3/child"),
    }
    messages = [finding.message for finding in findings if finding.code == "assembly.joint_reference"]
    assert any("is placed 3 times" in message for message in messages)
    assert any("LMP-0010 is not placed in any subassembly" in message for message in messages)


def test_joint_limits_are_ordered_and_hold_the_nominal(lamp_arm: Path) -> None:
    def limits(assembly: dict[str, Any]) -> None:
        assembly["joints"][0].update(min=90, max=80)
        assembly["joints"][1].update(nominal=10)

    edit(lamp_arm, "assembly.yaml", limits)
    assert found(validate(lamp_arm)) == {
        ("assembly.joint_limits", "hw/assembly.yaml", "/joints/0/min"),
        ("assembly.joint_limits", "hw/assembly.yaml", "/joints/1/nominal"),
    }


def test_every_explicit_occurrence_has_a_part_and_one_subassembly(lamp_arm: Path) -> None:
    def occurrences(assembly: dict[str, Any]) -> None:
        assembly["occurrences"].append({"id": "ring-spare", "PN": "LMP-0098"})
        assembly["subassemblies"][0]["occurrences"] = ["@ring-base", "@ring-gone"]

    edit(lamp_arm, "assembly.yaml", occurrences)
    assert found(validate(lamp_arm)) >= {
        ("assembly.unknown_part", "hw/assembly.yaml", "/occurrences/3/PN"),
        ("assembly.occurrence", "hw/assembly.yaml", "/occurrences/3"),
        ("assembly.occurrence", "hw/assembly.yaml", "/subassemblies/0/occurrences/1"),
        ("assembly.occurrence", "hw/assembly.yaml", "/subassemblies/1/occurrences"),
    }


def test_a_part_modelled_in_assembly_coordinates_is_placed_once_at_the_identity(lamp_arm: Path) -> None:
    ring = lamp_arm / "hw/parts/LMP-0011/part.yaml"
    ring.write_text(
        ring.read_text(encoding="utf-8").replace("model_frame: part_local\n", ""), encoding="utf-8"
    )

    def place_insert(assembly: dict[str, Any]) -> None:
        assembly["subassemblies"][1]["parts"].remove("LMP-0010")
        assembly["subassemblies"][1]["occurrences"].append("@insert")
        assembly["occurrences"].append(
            {"id": "insert", "PN": "LMP-0010", "placement": {"translation_mm": [0, 0, 0]}}
        )
        assembly["joints"][8]["child"] = "@insert"

    edit(lamp_arm, "assembly.yaml", place_insert)
    assert found(validate(lamp_arm)) == {("assembly.model_frame", "hw/parts/LMP-0011/part.yaml", None)}
    assert "LMP-0011 is placed 3 times but its model_frame is assembly_zero" in validate(lamp_arm)[0].message

    edit(
        lamp_arm,
        "assembly.yaml",
        lambda assembly: assembly["occurrences"][3]["placement"].update(
            rotation={"axis": [0, 0, 1], "angle_deg": 90}
        ),
    )
    assert found(validate(lamp_arm)) == {
        ("assembly.model_frame", "hw/parts/LMP-0011/part.yaml", None),
        ("assembly.model_frame", "hw/parts/LMP-0010/part.yaml", None),
    }


@pytest.mark.parametrize(
    ("coupling", "key", "message"),
    [
        (
            {"type": "linear", "driver": "J-099", "ratio": 1},
            "driver",
            "driver J-099 is not a joint of this assembly",
        ),
        ({"type": "linear", "driver": "J-003", "ratio": 1}, "driver", "J-003 is coupled to itself"),
        (
            {"type": "periodic_table", "driver": "J-002", "profile": "tilt"},
            "profile",
            "profile 'tilt' is not in",
        ),
        (
            {"type": "slider_crank", "mechanism": "crank", "output": "rod_angle"},
            "mechanism",
            "mechanism 'crank'",
        ),
    ],
)
def test_a_coupling_names_a_driver_profile_or_mechanism_the_assembly_has(
    lamp_arm: Path, coupling: dict[str, Any], key: str, message: str
) -> None:
    def couple_head(assembly: dict[str, Any]) -> None:
        del assembly["joints"][2]["nominal"]
        assembly["joints"][2]["coupling"] = coupling

    edit(lamp_arm, "assembly.yaml", couple_head)
    findings = validate(lamp_arm)
    assert found(findings) == {("assembly.coupling", "hw/assembly.yaml", f"/joints/2/coupling/{key}")}
    assert message in findings[0].message


def test_a_coupling_cycle_is_rejected_by_name(lamp_arm: Path) -> None:
    def couple_elbow_and_head(assembly: dict[str, Any]) -> None:
        elbow, head = assembly["joints"][1:3]
        for joint, driver in ((elbow, head["id"]), (head, elbow["id"])):
            del joint["nominal"]
            joint["coupling"] = {"type": "linear", "driver": driver, "ratio": 1}

    edit(lamp_arm, "assembly.yaml", couple_elbow_and_head)
    [finding] = [finding for finding in validate(lamp_arm) if finding.code == "assembly.coupling"]
    assert finding.message.startswith("coupling cycle: J-00")
    assert finding.message.endswith("(each joint drives the next)")


# --- interfaces -----------------------------------------------------------------------------------------


def clearance(identifier: str, pair: list[str]) -> dict[str, Any]:
    return {
        "id": identifier,
        "from": "head",
        "to": "lower_link",
        "type": "clearance",
        "description": "keep the head clear of the lower link",
        "pair": pair,
        "min_clearance_mm": 1.0,
    }


def test_a_clearance_pair_resolves_to_two_occurrences_and_takes_one_requirement(lamp_arm: Path) -> None:
    def insert_occurrence(assembly: dict[str, Any]) -> None:
        assembly["occurrences"].append({"id": "insert", "PN": "LMP-0010"})
        arm = assembly["subassemblies"][1]
        arm["parts"].remove("LMP-0010")
        arm["occurrences"].append("@insert")

    def interfaces(document: dict[str, Any]) -> None:
        document["interfaces"] += [
            clearance("IF-010", ["LMP-0004", "LMP-0002"]),
            clearance("IF-011", ["LMP-0002", "LMP-0004"]),
            clearance("IF-012", ["LMP-0099", "@ring-gone"]),
            clearance("IF-013", ["LMP-0010", "@insert"]),
        ]

    edit(lamp_arm, "assembly.yaml", insert_occurrence)
    edit(lamp_arm, "interfaces.yaml", interfaces)
    findings = validate(lamp_arm)
    assert found(findings) == {
        ("interface.pair", "hw/interfaces.yaml", "/interfaces/6/pair"),
        ("interface.reference", "hw/interfaces.yaml", "/interfaces/7/pair/0"),
        ("interface.reference", "hw/interfaces.yaml", "/interfaces/7/pair/1"),
        ("interface.pair", "hw/interfaces.yaml", "/interfaces/8/pair"),
    }
    assert "already has a clearance at interfaces/5" in findings[0].message
    assert "the same occurrence @insert" in findings[-1].message


def test_fit_and_heat_set_ends_and_at_references_resolve(lamp_arm: Path) -> None:
    def interfaces(document: dict[str, Any]) -> None:
        first = document["interfaces"][0]
        first["from"] = "@ring-gone"
        first["limits"]["running_fit"]["hole"] = {"PN": "LMP-0005", "feature": "bore"}
        first["limits"]["press_fit"]["shaft"] = {"PN": "LMP-0005", "occurrence": "@ring-base", "feature": "x"}
        first["limits"]["heat_set"][0]["pair"] = ["LMP-0001", "LMP-0011"]

    edit(lamp_arm, "interfaces.yaml", interfaces)
    assert found(validate(lamp_arm)) == {
        ("interface.reference", "hw/interfaces.yaml", "/interfaces/0/from"),
        ("interface.pair", "hw/interfaces.yaml", "/interfaces/0/limits/running_fit"),
        ("interface.reference", "hw/interfaces.yaml", "/interfaces/0/limits/press_fit/shaft"),
        ("interface.reference", "hw/interfaces.yaml", "/interfaces/0/limits/heat_set/0/pair/1"),
    }


# --- drawing --------------------------------------------------------------------------------------------


def test_the_general_tolerance_policy_is_a_declared_policy(lamp_arm: Path) -> None:
    edit(
        lamp_arm,
        "product.yaml",
        lambda product: product["drawing"].update(general_tolerance_policy="casting"),
    )
    assert found(validate(lamp_arm)) == {
        ("drawing.policy", "hw/product.yaml", "/drawing/general_tolerance_policy")
    }


def test_the_general_tolerance_states_its_policy(lamp_arm: Path) -> None:
    edit(lamp_arm, "product.yaml", lambda product: product.update(general_tolerance="ISO 2768-f"))
    assert found(validate(lamp_arm)) == {
        ("drawing.general_tolerance", "hw/product.yaml", "/general_tolerance")
    }


def test_an_unknown_general_tolerance_validates_but_no_detail_drawing_can_state_it(lamp_arm: Path) -> None:
    unknown = {"status": "unknown", "reason": "not asked yet", "question": "Q-001"}
    edit(lamp_arm, "product.yaml", lambda product: product.update(general_tolerance=unknown))
    findings = found(validate(lamp_arm))
    assert ("drawing.general_tolerance", "hw/product.yaml", "/general_tolerance") in findings
    assert ("drawing.general_tolerance", "hw/parts/LMP-0001/part.yaml", "/drawing") in findings
    assert not any(path == "hw/parts/LMP-0008/part.yaml" for _, path, _ in findings)  # a vendor sheet


def test_part_drawing_datums_and_tolerance_policies_are_declared(lamp_arm: Path) -> None:
    def drawing(part: dict[str, Any]) -> None:
        part["drawing"]["coordinate_frame"]["origin"] = {"intersection": ["A", "D"]}
        part["drawing"]["views"][1]["through"] = "E"
        part["drawing"]["tolerance_policy"] = "machining"

    edit(lamp_arm, "parts/LMP-0001/part.yaml", drawing)
    assert found(validate(lamp_arm)) == {
        ("drawing.datum", "hw/parts/LMP-0001/part.yaml", "/drawing/coordinate_frame/origin/intersection/1"),
        ("drawing.datum", "hw/parts/LMP-0001/part.yaml", "/drawing/views/1/through"),
        ("drawing.policy", "hw/parts/LMP-0001/part.yaml", "/drawing/tolerance_policy"),
    }


@pytest.mark.parametrize(
    "junk",
    [
        ".DS_Store",
        "._part.yaml",
        "Thumbs.db",
        "desktop.ini",
        "Desktop.ini",
        "__pycache__/model.cpython-312.pyc",
    ],
)
def test_os_and_tool_junk_anywhere_in_hw_changes_nothing(lamp_arm: Path, junk: str) -> None:
    # A file browser writes these into every folder it opens (test-project issue 10). The reader
    # reads only the documents the layout names, so junk must neither break a read nor add a finding.
    before = validate(lamp_arm)
    hw = lamp_arm / "hw"
    folders = [hw, *(path for path in hw.rglob("*") if path.is_dir())]
    for folder in folders:
        target = folder / junk
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00\x00\x00\x01Bud1")
    assert validate(lamp_arm) == before
