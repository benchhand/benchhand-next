"""flow/flow and flow/rules: they express the prototype's flow, and the gate-decision request follows ADR-0018."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import violations

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
FLOW_ID = f"{CONTRACTS}flow/flow.schema.json"
RULES_ID = f"{CONTRACTS}flow/rules.schema.json"
REQUEST_ID = f"{FLOW_ID}#/$defs/GateDecisionRequest"
PROTOTYPE = Path(__file__).parent / "fixtures/flow/prototype-412b5d9"
RULE_KINDS = {
    "checks-by-iteration": "checks_by_iteration",
    "dispatch": "dispatch",
    "fidelity": "fidelity",
    "rigor": "rigor",
}
CEL_REF = "../common/cel.schema.json#/$defs/CelExpression"
CEL_LIST_REF = "../common/cel.schema.json#/$defs/CelExpressions"
CEL_FIELDS = [
    ("flow", "/properties/void_scope"),
    ("flow", "/properties/reapproval_scope"),
    ("flow", "/$defs/FlowEdge/properties/guard"),
    ("rules", "/$defs/ChecksByIterationRule/properties/when"),
    ("rules", "/$defs/ConditionalCheck/properties/when"),
    ("rules", "/$defs/DispatchRule/properties/when"),
    ("rules", "/$defs/FidelityRule/properties/when"),
    ("rules", "/$defs/RigorRule/properties/when"),
]
CEL_LISTS = [
    ("flow", "/$defs/FlowSingleHumanGate/properties/requires/properties/human"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/provisional"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/full"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/human"),
    ("rules", "/$defs/RigorRule/properties/then"),
]


def _prototype_flow() -> dict[str, Any]:
    return yaml.safe_load((PROTOTYPE / "flow.yaml").read_text())


def _prototype_rules(name: str) -> dict[str, Any]:
    return yaml.safe_load((PROTOTYPE / f"{name}.rules.yaml").read_text())


def _schema(name: str = "flow") -> dict[str, Any]:
    return json.loads((files("benchhand_contracts") / f"schemas/flow/{name}.schema.json").read_text())


def _at(schema: dict[str, Any], pointer: str) -> Any:
    for part in pointer.split("/")[1:]:
        schema = schema[part]
    return schema


def _request() -> dict[str, Any]:
    return copy.deepcopy(_schema()["$defs"]["GateDecisionRequest"]["examples"][0])


@pytest.mark.parametrize(("contract", "pointer"), CEL_FIELDS)
def test_every_cel_field_refers_to_the_one_cel_type(contract: str, pointer: str) -> None:
    assert _at(_schema(contract), pointer)["$ref"] == CEL_REF


@pytest.mark.parametrize(("contract", "pointer"), CEL_LISTS)
def test_every_cel_list_is_a_list_of_the_one_cel_type(contract: str, pointer: str) -> None:
    assert _at(_schema(contract), pointer)["$ref"] == CEL_LIST_REF


def test_the_prototype_flow_validates() -> None:
    assert violations(FLOW_ID, _prototype_flow()) == []


@pytest.mark.parametrize(("name", "kind"), RULE_KINDS.items())
def test_each_prototype_rule_list_validates_as_its_kind(name: str, kind: str) -> None:
    rules = _prototype_rules(name)
    assert rules["kind"] == kind
    assert violations(RULES_ID, rules) == []


def test_a_rule_whose_then_belongs_to_another_kind_is_refused() -> None:
    fidelity = _prototype_rules("fidelity")
    fidelity["rules"][0]["then"] = ["process.fdm"]
    assert violations(RULES_ID, fidelity)


def test_a_dispatch_rule_names_at_least_one_handler() -> None:
    dispatch = _prototype_rules("dispatch")
    dispatch["rules"][0]["then"] = []
    assert violations(RULES_ID, dispatch)


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


def test_a_void_names_the_user_and_the_provisional_decision_it_withdraws() -> None:
    void = {**_request(), "status": "void", "quote": "Don't freeze this."}
    assert violations(REQUEST_ID, void) == []
    del void["provisional"]
    assert violations(REQUEST_ID, void)


def test_a_void_through_channel_auto_is_refused() -> None:
    # The interpreter records an automatic VOID itself; this request is the user's.
    void = {"gate": "layout_freeze", "status": "void", "channel": "auto", "provisional": "DR-012"}
    assert violations(REQUEST_ID, void)


@pytest.mark.parametrize("quote", [" ", "\t\n", "\u00a0\u3000"])
def test_a_quote_of_only_whitespace_is_no_answer(quote: str) -> None:
    assert [violation.pointer for violation in violations(REQUEST_ID, {**_request(), "quote": quote})] == [
        "/quote"
    ]
