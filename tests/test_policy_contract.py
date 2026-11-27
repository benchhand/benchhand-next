"""record/policy.schema.json's rigor, and policy/contribution.schema.json's rules and gate requirements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import violations
from rule_lists import NO_MATCH, first_match, merged

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
POLICY_ID = f"{CONTRACTS}record/policy.schema.json"
CONTRIBUTION_ID = f"{CONTRACTS}policy/contribution.schema.json"
PROTOTYPE = Path(__file__).parent / "fixtures/flow/prototype-412b5d9"


@pytest.mark.parametrize("rigor", ["standard", "regulated"])
def test_a_policy_names_its_rigor(rigor: str) -> None:
    assert violations(POLICY_ID, {"policy_version": 1, "rigor": rigor}) == []


def test_a_rigor_outside_standard_and_regulated_is_refused() -> None:
    found = violations(POLICY_ID, {"policy_version": 1, "rigor": "pro"})
    assert [violation.pointer for violation in found] == ["/rigor"]


def _reference(file: str) -> dict[str, Any]:
    return {"file": file, "rules_version": 1}


@pytest.mark.parametrize(
    "contribution",
    [
        pytest.param({}, id="empty"),
        pytest.param({"rules": {}}, id="no-rule-list"),
        pytest.param({"rules": {"routing": _reference("routing.celpolicy")}}, id="unknown-rule-list"),
        pytest.param({"rules": {"dispatch": _reference("dispatch.yaml")}}, id="not-a-celpolicy-file"),
        pytest.param({"rules": {"dispatch": _reference("dispatch.rules.yaml")}}, id="old-rules-yaml-name"),
        pytest.param({"rules": {"dispatch": _reference("../dispatch.celpolicy")}}, id="outside-the-provider"),
        pytest.param(
            {"rules": {"dispatch": {**_reference("dispatch.celpolicy"), "rules_version": 2}}},
            id="unknown-version",
        ),
        pytest.param(
            {"rules": {"dispatch": {"rules_version": 1, "policy": {"name": "dispatch"}}}}, id="inline-policy"
        ),
        pytest.param({"gates": {"parts": {}}}, id="gate-without-step"),
        pytest.param({"gates": {"parts": {"review": ["true"]}}}, id="unknown-step"),
        pytest.param({"gates": {"Parts": {"human": ["true"]}}}, id="bad-gate-id"),
        pytest.param({"gates": {"parts": {"human": [""]}}}, id="empty-expression"),
    ],
)
def test_a_contribution_outside_the_flow_shapes_is_refused(contribution: dict[str, Any]) -> None:
    assert violations(CONTRIBUTION_ID, contribution)


def test_a_contribution_adds_rule_lists_and_gate_requirements() -> None:
    contribution = {
        "rules": {"checks_by_iteration": _reference("rules/checks.celpolicy")},
        "gates": {"release": {"human": ["record.frozen.present"]}},
    }
    assert violations(CONTRIBUTION_ID, contribution) == []


# The proposed merge of a kind's lists (docs/contract/policy.md, open for the owner), run on the prototype's own
# lists as the flow's and on lists written for these tests as the contributions.
def _flow_list(kind: str) -> dict[str, Any]:
    flow = yaml.safe_load((PROTOTYPE / "flow.yaml").read_text())
    return yaml.safe_load((PROTOTYPE / flow["rules"][kind]["file"]).read_text())


def _contributed(kind: str, condition: str, output: str) -> dict[str, Any]:
    """A contributed list: one conditional choice, then its kind's no-match value."""
    no_match = {"checks_by_iteration": "[]", "dispatch": '"unknown"', "fidelity": '"none"', "rigor": "[]"}[kind]
    return {"name": kind, "rule": {"match": [{"condition": condition, "output": output}, {"output": no_match}]}}


# Per fall-through kind: an activation, the flow's own value for it, a contributed choice's output and its value.
FALL_THROUGH = {
    "checks_by_iteration": (
        {"iteration": "release", "gates": {"release": {"approved": False}}},
        [],
        '["weld.bead"]',
        ["weld.bead"],
    ),
    "dispatch": (
        {"obligation": {"family": "process.welding.bead"}},
        "unknown",
        '"process.welding.bead"',
        "process.welding.bead",
    ),
    "fidelity": ({"stage": "layout", "stage_order": {"layout": 4, "detail": 6}}, "F1", '"F3"', "F3"),
}


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_the_flow_runs_its_own_list_of_each_kind(kind: str) -> None:
    data, flow_value, _, _ = FALL_THROUGH[kind]
    assert merged(kind, {}, _flow_list(kind), data) == first_match(_flow_list(kind), data) == flow_value


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_a_contributed_list_that_does_not_match_gives_its_no_match_value_and_falls_through(kind: str) -> None:
    data, flow_value, output, _ = FALL_THROUGH[kind]
    contributed = _contributed(kind, "false", output)
    assert first_match(contributed, data) == NO_MATCH[kind]
    assert merged(kind, {"welding": contributed}, _flow_list(kind), data) == flow_value


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_a_contributed_list_that_matches_gives_the_value(kind: str) -> None:
    data, _, output, value = FALL_THROUGH[kind]
    assert merged(kind, {"welding": _contributed(kind, "true", output)}, _flow_list(kind), data) == value


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_contributions_run_in_ascending_provider_name_before_the_flow(kind: str) -> None:
    data, _, output, value = FALL_THROUGH[kind]
    later = _contributed(kind, "true", '["other"]' if kind == "checks_by_iteration" else '"F2"')
    contributed = {"zinc": later, "alpha": _contributed(kind, "true", output)}
    assert merged(kind, contributed, _flow_list(kind), data) == value


def test_the_flows_unknown_dispatch_is_final_and_means_unknown_coverage() -> None:
    data = {"obligation": {"family": "process.welding.bead"}}
    contributed = {"welding": _contributed("dispatch", "false", '"process.welding.bead"')}
    assert merged("dispatch", contributed, _flow_list("dispatch"), data) == "unknown"


def test_the_flows_empty_checks_list_is_final_and_runs_no_check() -> None:
    data, _, output, _ = FALL_THROUGH["checks_by_iteration"]
    contributed = {"welding": _contributed("checks_by_iteration", "false", output)}
    assert merged("checks_by_iteration", contributed, _flow_list("checks_by_iteration"), data) == []


def test_a_contributed_none_fidelity_falls_through_to_the_flows_stage_fidelity() -> None:
    data, flow_value, output, _ = FALL_THROUGH["fidelity"]
    contributed = {"welding": _contributed("fidelity", "false", output)}
    assert first_match(contributed["welding"], data) == "none"
    assert merged("fidelity", contributed, _flow_list("fidelity"), data) == flow_value


REGULATED_OFF = {"policy": {"rigor": "regulated"}, "record": {"flow": {"profile": [{"turns_check_off": True}]}}}
FLOW_RIGOR_MESSAGE = "regulated rigor refuses a flow profile that turns a check off"


def test_rigor_gives_the_union_of_every_lists_messages_in_evaluation_order() -> None:
    contributed = {
        "zinc": _contributed("rigor", "true", '["a weld map is reviewed"]'),
        "alpha": _contributed("rigor", "true", '["every part names its material"]'),
    }
    assert merged("rigor", contributed, _flow_list("rigor"), REGULATED_OFF) == [
        "every part names its material",
        "a weld map is reviewed",
        FLOW_RIGOR_MESSAGE,
    ]


def test_a_contribution_cannot_waive_the_flows_rigor_requirements() -> None:
    contributed = {"welding": _contributed("rigor", "true", "[]")}
    assert merged("rigor", contributed, _flow_list("rigor"), REGULATED_OFF) == [FLOW_RIGOR_MESSAGE]


def test_rigor_holds_only_when_no_list_gives_a_message() -> None:
    standard = {"policy": {"rigor": "standard"}, "record": {"flow": {"profile": []}}}
    contributed = {"welding": _contributed("rigor", "false", '["a weld map is reviewed"]')}
    assert merged("rigor", contributed, _flow_list("rigor"), standard) == []
    assert merged("rigor", {"welding": _contributed("rigor", "true", '["x"]')}, _flow_list("rigor"), standard)
