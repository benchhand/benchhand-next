"""flow/flow.schema.json: it expresses the prototype's flow, and its gate-decision request follows ADR-0018."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import violations

FLOW_ID = "https://benchhand.github.io/benchhand/contracts/flow/flow.schema.json"
REQUEST_ID = f"{FLOW_ID}#/$defs/GateDecisionRequest"
PROTOTYPE_FLOW = Path(__file__).parent / "fixtures/flow/prototype-412b5d9.yaml"
CEL_REF = "../common/cel.schema.json"
CEL_FIELDS = [
    "/properties/void_scope",
    "/properties/reapproval_scope",
    "/$defs/CelExpressions/items",
    "/$defs/FlowEdge/properties/guard",
    "/$defs/FlowCheckRule/properties/when",
    "/$defs/FlowConditionalCheck/properties/when",
    "/$defs/FlowDispatchRule/properties/when",
    "/$defs/FlowFidelityRule/properties/when",
    "/$defs/FlowRigorRule/properties/when",
]
CEL_LISTS = [
    "/$defs/FlowSingleHumanGate/properties/requires/properties/human",
    "/$defs/FlowStagedGate/properties/requires/properties/provisional",
    "/$defs/FlowStagedGate/properties/requires/properties/full",
    "/$defs/FlowStagedGate/properties/requires/properties/human",
    "/$defs/FlowRigorRule/properties/then",
]


def _prototype_flow() -> dict[str, Any]:
    return yaml.safe_load(PROTOTYPE_FLOW.read_text())


def _schema() -> dict[str, Any]:
    return json.loads((files("benchhand_contracts") / "schemas/flow/flow.schema.json").read_text())


def _at(schema: dict[str, Any], pointer: str) -> Any:
    for part in pointer.split("/")[1:]:
        schema = schema[part]
    return schema


def _request() -> dict[str, Any]:
    return copy.deepcopy(_schema()["$defs"]["GateDecisionRequest"]["examples"][0])


@pytest.mark.parametrize("pointer", CEL_FIELDS)
def test_every_cel_field_refers_to_the_one_cel_type(pointer: str) -> None:
    assert _at(_schema(), pointer)["$ref"] == CEL_REF


@pytest.mark.parametrize("pointer", CEL_LISTS)
def test_every_cel_list_is_a_list_of_the_one_cel_type(pointer: str) -> None:
    assert _at(_schema(), pointer)["$ref"] == "#/$defs/CelExpressions"


def test_the_prototype_flow_validates() -> None:
    assert violations(FLOW_ID, _prototype_flow()) == []


def test_the_prototype_flow_has_every_stage_and_its_gates() -> None:
    flow = _prototype_flow()
    kinds = {gate["id"]: gate["kind"] for gate in flow["gates"]}
    assert [stage["id"] for stage in flow["stages"]] == [
        *("ground", "intent", "specify", "concept", "layout", "parts", "detail"),
        *("bom", "analysis", "critique", "reconcile", "design_freeze", "release"),
    ]
    assert kinds == {
        **dict.fromkeys(("intent", "variant", "design_freeze", "release"), "single-human"),
        **dict.fromkeys(("layout_freeze", "parts", "detail", "analysis"), "provisional+full+human"),
    }


def test_a_single_human_gate_has_no_provisional_step() -> None:
    flow = _prototype_flow()
    flow["gates"][0]["requires"]["provisional"] = ["true"]
    assert violations(FLOW_ID, flow)


def test_a_staged_gate_needs_every_step() -> None:
    flow = _prototype_flow()
    staged = next(gate for gate in flow["gates"] if gate["kind"] == "provisional+full+human")
    del staged["requires"]["full"]
    assert violations(FLOW_ID, flow)


def test_a_stage_outside_the_record_enum_is_refused() -> None:
    flow = _prototype_flow()
    flow["edges"][0]["to"] = "polish"
    assert [violation.pointer for violation in violations(FLOW_ID, flow)] == ["/edges/0/to"]


def test_a_gate_decision_through_a_form_is_refused() -> None:
    assert violations(REQUEST_ID, {**_request(), "channel": "form"})


@pytest.mark.parametrize("missing", ["by", "quote"])
def test_a_human_channel_names_who_decided_and_quotes_them(missing: str) -> None:
    request = _request()
    del request[missing]
    assert violations(REQUEST_ID, request)


def test_an_auto_decision_quotes_nobody() -> None:
    assert violations(REQUEST_ID, {**_request(), "channel": "auto"})
