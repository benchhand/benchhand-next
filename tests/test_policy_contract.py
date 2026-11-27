"""record/policy.schema.json's rigor, and policy/contribution.schema.json's rules and gate requirements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

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
# lists as the flow's and on lists written for these tests as the contributions. Every contributed condition reads
# the activation, as the policy compiler refuses a literal false and a literally true choice before the last one.
def _flow_list(kind: str) -> dict[str, Any]:
    flow = yaml.safe_load((PROTOTYPE / "flow.yaml").read_text())
    return yaml.safe_load((PROTOTYPE / flow["rules"][kind]["file"]).read_text())


def _contributed(kind: str, condition: str, output: str) -> dict[str, Any]:
    """A contributed list: one conditional choice, then its kind's no-match value."""
    no_match = {"checks_by_iteration": "[]", "dispatch": '"unknown"', "fidelity": '"none"', "rigor": "[]"}[
        kind
    ]
    return {
        "name": kind,
        "rule": {"match": [{"condition": condition, "output": output}, {"output": no_match}]},
    }


WELDED = "record.welded_parts.size() > 0"
STAGE_ORDER = {"layout": 4, "detail": 6}


class FallThrough(NamedTuple):
    """A contributed choice of a fall-through kind, an activation it matches, and one it doesn't match."""

    condition: str
    output: str
    value: Any
    matching: dict[str, Any]
    missing: dict[str, Any]
    # The flow's own value on `missing`: never the kind's no-match value, so a merge that stopped at the
    # contribution's no-match can't give it.
    flow_value: Any


RELEASE_APPROVED = {"iteration": "release", "gates": {"release": {"approved": True}}}
FALL_THROUGH = {
    "checks_by_iteration": FallThrough(
        WELDED,
        '["weld.bead"]',
        ["weld.bead"],
        {**RELEASE_APPROVED, "record": {"welded_parts": ["PN-0101"]}},
        {**RELEASE_APPROVED, "record": {"welded_parts": []}},
        ["validate", "bom.reconcile", "build_guide", "release.seal"],
    ),
    "dispatch": FallThrough(
        'obligation.family.startsWith("process.welding.")',
        "obligation.family",
        "process.welding.bead",
        {"obligation": {"family": "process.welding.bead"}},
        {"obligation": {"family": "route.operation_plan"}},
        "route.operation_plan",
    ),
    "fidelity": FallThrough(
        WELDED,
        '"F3"',
        "F3",
        {"stage": "layout", "stage_order": STAGE_ORDER, "record": {"welded_parts": ["PN-0101"]}},
        {"stage": "layout", "stage_order": STAGE_ORDER, "record": {"welded_parts": []}},
        "F1",
    ),
}


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_the_flow_runs_its_own_list_of_each_kind(kind: str) -> None:
    case = FALL_THROUGH[kind]
    flow_list = _flow_list(kind)
    assert (
        merged(kind, {}, flow_list, case.missing) == first_match(flow_list, case.missing) == case.flow_value
    )


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_a_contributed_list_that_does_not_match_gives_its_no_match_value_and_falls_through(kind: str) -> None:
    case = FALL_THROUGH[kind]
    contributed = _contributed(kind, case.condition, case.output)
    assert first_match(contributed, case.missing) == NO_MATCH[kind] != case.flow_value
    assert merged(kind, {"welding": contributed}, _flow_list(kind), case.missing) == case.flow_value


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_a_contributed_list_that_matches_gives_the_value(kind: str) -> None:
    case = FALL_THROUGH[kind]
    contributed = {"welding": _contributed(kind, case.condition, case.output)}
    assert first_match(_flow_list(kind), case.matching) != case.value
    assert merged(kind, contributed, _flow_list(kind), case.matching) == case.value


@pytest.mark.parametrize("kind", sorted(FALL_THROUGH))
def test_contributions_run_in_ascending_provider_name_before_the_flow(kind: str) -> None:
    case = FALL_THROUGH[kind]
    later = _contributed(kind, case.condition, '["other"]' if kind == "checks_by_iteration" else '"F2"')
    contributed = {"zinc": later, "alpha": _contributed(kind, case.condition, case.output)}
    assert merged(kind, contributed, _flow_list(kind), case.matching) == case.value


def test_the_flows_unknown_dispatch_is_final_and_means_unknown_coverage() -> None:
    data = {"obligation": {"family": "process.welding.bead"}}
    assert merged("dispatch", {}, _flow_list("dispatch"), data) == "unknown"


def test_the_flows_empty_checks_list_is_final_and_runs_no_check() -> None:
    data = {"iteration": "release", "gates": {"release": {"approved": False}}}
    assert merged("checks_by_iteration", {}, _flow_list("checks_by_iteration"), data) == []


def test_a_contributed_none_fidelity_falls_through_to_the_flows_stage_fidelity() -> None:
    case = FALL_THROUGH["fidelity"]
    contributed = {"welding": _contributed("fidelity", case.condition, case.output)}
    assert first_match(contributed["welding"], case.missing) == "none"
    assert merged("fidelity", contributed, _flow_list("fidelity"), case.missing) == "F1"


def _rigor_activation(rigor: str, *, turns_check_off: bool, welded_parts: list[str]) -> dict[str, Any]:
    profile = [{"turns_check_off": True}] if turns_check_off else []
    return {
        "policy": {"rigor": rigor},
        "record": {"flow": {"profile": profile}, "welded_parts": welded_parts},
    }


REGULATED_OFF_WELDED = _rigor_activation("regulated", turns_check_off=True, welded_parts=["PN-0101"])
FLOW_RIGOR_MESSAGE = "regulated rigor refuses a flow profile that turns a check off"


def test_rigor_gives_the_union_of_every_lists_messages_in_evaluation_order() -> None:
    contributed = {
        "zinc": _contributed("rigor", WELDED, '["a weld map is reviewed"]'),
        "alpha": _contributed("rigor", 'policy.rigor == "regulated"', '["every part names its material"]'),
    }
    assert merged("rigor", contributed, _flow_list("rigor"), REGULATED_OFF_WELDED) == [
        "every part names its material",
        "a weld map is reviewed",
        FLOW_RIGOR_MESSAGE,
    ]


def test_a_contribution_cannot_waive_the_flows_rigor_requirements() -> None:
    contributed = {"welding": _contributed("rigor", WELDED, "[]")}
    assert merged("rigor", contributed, _flow_list("rigor"), REGULATED_OFF_WELDED) == [FLOW_RIGOR_MESSAGE]


def test_rigor_holds_only_when_no_list_gives_a_message() -> None:
    contributed = {"welding": _contributed("rigor", WELDED, '["a weld map is reviewed"]')}
    unwelded = _rigor_activation("standard", turns_check_off=False, welded_parts=[])
    welded = _rigor_activation("standard", turns_check_off=False, welded_parts=["PN-0101"])
    assert merged("rigor", contributed, _flow_list("rigor"), unwelded) == []
    assert merged("rigor", contributed, _flow_list("rigor"), welded) == ["a weld map is reviewed"]
