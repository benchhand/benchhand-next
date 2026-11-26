"""record/policy.schema.json's rigor, and policy/contribution.schema.json's rules and gate requirements."""

from __future__ import annotations

from typing import Any

import pytest
from benchhand_contracts import violations

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
POLICY_ID = f"{CONTRACTS}record/policy.schema.json"
CONTRIBUTION_ID = f"{CONTRACTS}policy/contribution.schema.json"


@pytest.mark.parametrize("rigor", ["standard", "regulated"])
def test_a_policy_names_its_rigor(rigor: str) -> None:
    assert violations(POLICY_ID, {"policy_version": 1, "rigor": rigor}) == []


def test_a_rigor_outside_standard_and_regulated_is_refused() -> None:
    found = violations(POLICY_ID, {"policy_version": 1, "rigor": "pro"})
    assert [violation.pointer for violation in found] == ["/rigor"]


@pytest.mark.parametrize(
    "contribution",
    [
        pytest.param({}, id="empty"),
        pytest.param({"rules": {}}, id="no-rule-list"),
        pytest.param({"rules": {"dispatch": []}}, id="empty-rule-list"),
        pytest.param({"rules": {"dispatch": [{"when": "true", "then": []}]}}, id="dispatch-without-handlers"),
        pytest.param({"rules": {"fidelity": [{"when": "true", "then": "F4"}]}}, id="unknown-fidelity"),
        pytest.param({"rules": {"routing": [{"when": "true", "then": ["x"]}]}}, id="unknown-rule-list"),
        pytest.param({"gates": {"parts": {}}}, id="gate-without-step"),
        pytest.param({"gates": {"parts": {"review": ["true"]}}}, id="unknown-step"),
        pytest.param({"gates": {"Parts": {"human": ["true"]}}}, id="bad-gate-id"),
        pytest.param({"gates": {"parts": {"human": [""]}}}, id="empty-expression"),
    ],
)
def test_a_contribution_outside_the_flow_shapes_is_refused(contribution: dict[str, Any]) -> None:
    assert violations(CONTRIBUTION_ID, contribution)


def test_a_contribution_adds_flow_rules_and_gate_requirements() -> None:
    contribution = {
        "rules": {"checks_by_iteration": [{"when": 'iteration == "full"', "then": ["static.all_pairs"]}]},
        "gates": {"release": {"human": ["record.frozen.present"]}},
    }
    assert violations(CONTRIBUTION_ID, contribution) == []
