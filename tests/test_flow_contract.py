"""flow/flow and flow/rules: they express the prototype's flow, and the gate-decision request follows ADR-0018."""

from __future__ import annotations

import copy
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import violations
from rule_lists import first_match

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
FLOW_ID = f"{CONTRACTS}flow/flow.schema.json"
RULES_ID = f"{CONTRACTS}flow/rules.schema.json"
REQUEST_ID = f"{FLOW_ID}#/$defs/GateDecisionRequest"
PROTOTYPE = Path(__file__).parent / "fixtures/flow/prototype-412b5d9"
RULE_KINDS = ("checks_by_iteration", "dispatch", "fidelity", "rigor")
# The no-match value of each kind (docs/contract/policy.md): a contributed list ends with it, so the next list
# is evaluated. rigor has none: every list must give true.
NO_MATCH = {"checks_by_iteration": "[]", "dispatch": '"unknown"', "fidelity": '"none"'}
# The obligation families the prototype's process-check producer owns (dispatch.py OWNED_PREFIXES and
# OWNED_FAMILIES), minus physically_validated ones. The dispatch list sees only these.
OWNED_DISPATCH_PREFIXES = ("process.", "purchase.", "route.")
OWNED_DISPATCH_FAMILIES = frozenset({"optical.route"})
CEL_REF = "../common/cel.schema.json#/$defs/CelExpression"
CEL_LIST_REF = "../common/cel.schema.json#/$defs/CelExpressions"
CEL_FIELDS = [
    ("flow", "/properties/void_scope"),
    ("flow", "/properties/reapproval_scope"),
    ("flow", "/$defs/FlowEdge/properties/guard"),
    ("rules", "/$defs/RuleMatch/properties/condition"),
    ("rules", "/$defs/RuleMatch/properties/output"),
    ("rules", "/$defs/RuleMatch/properties/explanation"),
]
CEL_LISTS = [
    ("flow", "/$defs/FlowSingleHumanGate/properties/requires/properties/human"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/provisional"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/full"),
    ("flow", "/$defs/FlowStagedGate/properties/requires/properties/human"),
]


def _prototype_flow() -> dict[str, Any]:
    return yaml.safe_load((PROTOTYPE / "flow.yaml").read_text())


def _prototype_rules(kind: str) -> dict[str, Any]:
    return yaml.safe_load((PROTOTYPE / _prototype_flow()["rules"][kind]["file"]).read_text())


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


@pytest.mark.parametrize("kind", RULE_KINDS)
def test_each_prototype_rule_list_validates(kind: str) -> None:
    assert violations(RULES_ID, _prototype_rules(kind)) == []


@pytest.mark.parametrize("kind", RULE_KINDS)
def test_each_prototype_rule_list_ends_with_an_unconditional_item(kind: str) -> None:
    # The CI policy compiler refuses a list whose last item has a condition; the schema can't say "last".
    *_, last = _prototype_rules(kind)["rule"]["match"]
    assert last.get("condition", "true") == "true"


@pytest.mark.parametrize("kind", ["dispatch", "checks_by_iteration"])
def test_a_flow_list_gives_its_no_match_value_only_from_its_last_item(kind: str) -> None:
    *items, last = _prototype_rules(kind)["rule"]["match"]
    assert last["output"] == NO_MATCH[kind]
    assert NO_MATCH[kind] not in [item["output"] for item in items if kind == "checks_by_iteration"]


def test_the_flow_fidelity_list_never_gives_the_contribution_only_none() -> None:
    outputs = [item["output"] for item in _prototype_rules("fidelity")["rule"]["match"]]
    assert NO_MATCH["fidelity"] not in outputs


@pytest.mark.parametrize("key", ["kind", "rules_version", "rules"])
def test_a_rule_list_file_no_longer_carries_its_kind_or_the_old_shape(key: str) -> None:
    # flow.yaml's reference to the file carries kind and rules_version.
    assert violations(RULES_ID, {**_prototype_rules("fidelity"), key: 1})


@pytest.mark.parametrize("feature", ["aggregate", "variables"])
def test_a_rule_list_outside_the_restricted_profile_is_refused(feature: str) -> None:
    fidelity = _prototype_rules("fidelity")
    fidelity["rule"][feature] = []
    assert violations(RULES_ID, fidelity)


def test_a_nested_rule_is_refused() -> None:
    fidelity = _prototype_rules("fidelity")
    fidelity["rule"]["match"][0] = {"condition": "true", "rule": {"match": [{"output": '"F1"'}]}}
    assert violations(RULES_ID, fidelity)


def test_a_match_item_needs_an_output() -> None:
    fidelity = _prototype_rules("fidelity")
    del fidelity["rule"]["match"][0]["output"]
    assert violations(RULES_ID, fidelity)


def test_the_flow_names_one_rule_list_of_each_kind() -> None:
    assert _schema()["properties"]["rules"]["$ref"] == "rules.schema.json#/$defs/FlowRuleLists"
    assert sorted(_schema("rules")["$defs"]["FlowRuleLists"]["required"]) == sorted(RULE_KINDS)
    flow = _prototype_flow()
    del flow["rules"]["rigor"]
    assert violations(FLOW_ID, flow)


def test_the_prototype_flow_names_its_rule_files() -> None:
    for reference in _prototype_flow()["rules"].values():
        assert (PROTOTYPE / reference["file"]).is_file()


def test_the_prototype_flow_has_every_stage_and_its_gates() -> None:
    flow = _prototype_flow()
    kinds = {gate["id"]: gate["kind"] for gate in flow["gates"]}
    assert list(flow["stages"]) == [
        *("ground", "intent", "specify", "concept", "layout", "parts", "detail"),
        *("bom", "analysis", "critique", "reconcile", "design_freeze", "release"),
    ]
    assert kinds == {
        **dict.fromkeys(("intent", "variant", "design_freeze", "release"), "single-human"),
        **dict.fromkeys(("layout_freeze", "parts", "detail", "analysis"), "provisional+full+human"),
    }


def test_every_prototype_human_gate_needs_explicit_approval() -> None:
    # flow.md "Gate control": "only explicit user approval resolves it"; policy.mode auto is benchhand's.
    for gate in _prototype_flow()["gates"]:
        assert "answer.approved" in gate["requires"]["human"]
        assert not any("policy.mode" in requirement for requirement in gate["requires"]["human"])


def test_every_prototype_staged_human_gate_checks_the_unproved_sweep_intervals() -> None:
    # The full sweep runs at L1 to L4 (flow.md "Full gate"), so any of those gates can leave intervals.
    for gate in _prototype_flow()["gates"]:
        if gate["kind"] == "provisional+full+human":
            assert any("unproved_intervals" in requirement for requirement in gate["requires"]["human"])


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


def test_a_stage_key_outside_the_record_enum_is_refused() -> None:
    flow = _prototype_flow()
    flow["stages"]["polish"] = {"guides": {"lead": "guides/polish.md"}}
    assert [violation.pointer for violation in violations(FLOW_ID, flow)] == ["/stages"]


def test_a_flow_without_one_of_the_record_stages_is_refused() -> None:
    flow = _prototype_flow()
    del flow["stages"]["bom"]
    assert [violation.pointer for violation in violations(FLOW_ID, flow)] == ["/stages"]


def test_the_flow_lists_every_stage_of_the_record_enum() -> None:
    stage_enum = json.loads((files("benchhand_contracts") / "schemas/record/common.schema.json").read_text())
    assert _schema()["$defs"]["FlowStages"]["required"] == stage_enum["$defs"]["stage"]["enum"]


@pytest.mark.parametrize("part", ["gates", "edges"])
def test_a_flow_without_gates_or_edges_is_refused(part: str) -> None:
    assert violations(FLOW_ID, {**_prototype_flow(), part: []})


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


# The prototype's check sets per iteration (skills/cad-flow/references/flow.md, "Checks by iteration"),
# as (case, iteration, stage, activation overrides, expected checks in run order).
STAGES = ("ground", "intent", "specify", "concept", "layout", "parts", "detail")
STAGES += ("bom", "analysis", "critique", "reconcile", "design_freeze", "release")
JOINT = {"version": {"has_independent_joint": True, "git_commit": True}}
CHECKS_BY_ITERATION = [
    (
        "inner, layout",
        "inner",
        "layout",
        {},
        ["validate", "scratch.build", "form_check.unit", "evidence.check_scratch"],
    ),
    ("inner, concept, before L1", "inner", "concept", {}, ["validate", "evidence.check_scratch"]),
    (
        "inner, detail, a moving pair changed and a visibility binding",
        "inner",
        "detail",
        {
            "unit": {"moving_pairs_changed": True, "role": "cad-part-designer"},
            "record": {"requirements": [{"binds_visibility": True}]},
        },
        ["validate", "scratch.build", "form_check.unit", "evidence.check_scratch", "fits.stackup"]
        + ["drawings.completeness_unit", "sweep.smoke_changed", "render.visibility"],
    ),
    (
        "inner, analysis, an analyst",
        "inner",
        "analysis",
        {"unit": {"moving_pairs_changed": False, "role": "cad-analyst"}},
        ["validate", "scratch.build", "form_check.unit", "evidence.check_scratch", "fea.smoke_coarse"],
    ),
    (
        "commit, parts, a joint, at a git commit",
        "commit",
        "parts",
        JOINT,
        ["validate", "build", "static.changed_only", "sweep.smoke_changed", "render.views"]
        + ["motion.default_render", "bom.reconcile", "recheck.stamp"],
    ),
    (
        "commit, detail, stale form, drawings and sourcing",
        "commit",
        "detail",
        {"stale": [{"family": "form", "changed_part": True}, {"family": "drawing"}, {"family": "sourcing"}]},
        ["validate", "build", "form_check.changed", "static.changed_only", "render.views", "bom.reconcile"]
        + ["fits.stackup", "drawings.parts", "sourcing.selection"],
    ),
    (
        "provisional, a joint",
        "provisional",
        "layout",
        JOINT,
        ["validate.result", "render.visibility_result", "motion.default_render_result", "bom.result"]
        + ["fits.stackup_result", "form_check.result", "static.result", "sweep.smoke_result"]
        + ["evidence.check_stage", "evidence.check_stage_after_advance"],
    ),
    *(
        (
            f"full, {stage}",
            "full",
            stage,
            {},
            ["validate", "static.all_pairs", "form_check.due", "motion.default_render", "bom.reconcile"]
            + ["fits.stackup", "sweep.full", *extra, "evidence.check", "recheck.stamp"],
        )
        for stage, extra in [
            ("layout", []),
            ("parts", ["sourcing.selection"]),
            ("detail", ["drawings.all"]),
            ("analysis", ["fea.all_cases"]),
        ]
    ),
    (
        "full, reconcile",
        "full",
        "reconcile",
        {},
        ["validate", "static.all_pairs", "form_check.due", "motion.default_render", "bom.reconcile"]
        + ["fits.stackup", "fea.stale_cases", "evidence.check", "recheck.stamp"],
    ),
    (
        "design freeze, a stale sweep",
        "design_freeze",
        "design_freeze",
        {"stale": [{"family": "sweep"}]},
        ["validate", "bom.reconcile", "fits.stackup", "evidence.check", "recheck.stamp", "sweep.full"],
    ),
    (
        "design freeze, stale drawings and FEA",
        "design_freeze",
        "design_freeze",
        {"stale": [{"family": "drawing"}, {"family": "fea"}]},
        ["validate", "bom.reconcile", "fits.stackup", "evidence.check", "recheck.stamp", "drawings.all"]
        + ["fea.stale_cases"],
    ),
    ("release, before the approval", "release", "release", {}, []),
    (
        "release, approved",
        "release",
        "release",
        {"gates": {"release": {"approved": True}}},
        ["validate", "bom.reconcile", "build_guide", "release.seal"],
    ),
]
# What an output names besides check ids: stage names, evidence families and agent roles.
NOT_CHECK_IDS = {*STAGES, "form", "drawing", "sourcing", "sweep", "fea", "cad-analyst"}


def _checks_activation(iteration: str, stage: str, overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "iteration": iteration,
        "stage": stage,
        "stage_order": {name: index for index, name in enumerate(STAGES)},
        "unit": {"moving_pairs_changed": False, "role": "cad-part-designer"},
        "record": {"requirements": []},
        "stale": [],
        "version": {"has_independent_joint": False, "git_commit": False},
        "gates": {"release": {"approved": False}},
        **overrides,
    }


@pytest.mark.parametrize(
    ("iteration", "stage", "overrides", "expected"),
    [case[1:] for case in CHECKS_BY_ITERATION],
    ids=[case[0] for case in CHECKS_BY_ITERATION],
)
def test_the_prototype_checks_by_iteration_list_gives_the_prototypes_checks(
    iteration: str, stage: str, overrides: dict[str, Any], expected: list[str]
) -> None:
    rule_list = _prototype_rules("checks_by_iteration")
    assert first_match(rule_list, _checks_activation(iteration, stage, overrides)) == expected


@pytest.mark.parametrize("iteration", sorted({case[1] for case in CHECKS_BY_ITERATION}))
def test_the_prototype_checks_by_iteration_list_names_only_the_prototypes_check_ids(iteration: str) -> None:
    # Without evaluating: every literal in the iteration's output is a check id the cases expect, or a name.
    items = _prototype_rules("checks_by_iteration")["rule"]["match"]
    named = {
        literal
        for item in items
        if f'iteration == "{iteration}"' in item.get("condition", "")
        for literal in re.findall(r'"([^"]*)"', item["output"])
    }
    expected = {check for case in CHECKS_BY_ITERATION if case[1] == iteration for check in case[4]}
    assert named - NOT_CHECK_IDS == expected


DISPATCH = [
    ("process.fdm.orientation", {"kind": "fdm"}, "process.fdm.orientation"),
    ("process.waterjet.edge", {"kind": "waterjet"}, "process.waterjet.edge"),
    ("process.moulding.draft", {"kind": "moulding"}, "process.moulding.draft"),
    ("process.fdm.orientation", {"kind": "cnc"}, "unknown"),
    ("process.fdm.orientation", None, "unknown"),
    ("process.fdm.overhang", {"kind": "fdm"}, "unknown"),
    ("process.fdm.coverage", {"kind": "fdm"}, "unknown"),
    ("process.welding.coverage", {"kind": "welding"}, "unknown"),
    ("purchase.rating", None, "purchase.rating"),
    ("purchase.price", None, "unknown"),
    ("route.operation_plan", None, "route.operation_plan"),
    ("optical.route", None, "optical.route"),
]


@pytest.mark.parametrize(("family", "operation", "handler"), DISPATCH)
def test_the_prototype_dispatch_list_follows_handler_for(
    family: str, operation: dict[str, str] | None, handler: str
) -> None:
    # dispatch.py handler_for: the operation's kind must match a process family, and the check must be in
    # that kind's table; anything else, and every coverage obligation, is UNKNOWN.
    obligation = {"family": family, **({"operation": operation} if operation else {})}
    assert first_match(_prototype_rules("dispatch"), {"obligation": obligation}) == handler


def test_every_dispatch_case_is_an_owned_obligation() -> None:
    for family, _, _ in DISPATCH:
        assert family in OWNED_DISPATCH_FAMILIES or family.startswith(OWNED_DISPATCH_PREFIXES)


def test_the_prototype_dispatch_list_only_routes_owned_families() -> None:
    families = re.findall(r'"([a-z_]+\.[a-z_.]+)"', yaml.safe_dump(_prototype_rules("dispatch")))
    assert families
    for family in families:
        assert family in OWNED_DISPATCH_FAMILIES or family.startswith(OWNED_DISPATCH_PREFIXES)


@pytest.mark.parametrize(
    ("stage", "fidelity"),
    [("concept", "F0"), ("layout", "F1"), ("parts", "F2"), ("detail", "F3"), ("analysis", "F3")],
)
def test_the_prototype_fidelity_list_gives_the_stage_fidelity(stage: str, fidelity: str) -> None:
    stage_order = {name: index for index, name in enumerate(STAGES)}
    assert first_match(_prototype_rules("fidelity"), {"stage": stage, "stage_order": stage_order}) == fidelity


@pytest.mark.parametrize(
    ("rigor", "turns_check_off", "holds"),
    [("regulated", True, False), ("regulated", False, True), ("standard", True, True)],
)
def test_the_prototype_rigor_list_refuses_a_profile_that_turns_a_check_off_under_regulated(
    rigor: str, turns_check_off: bool, holds: bool
) -> None:
    data = {
        "policy": {"rigor": rigor},
        "record": {"flow": {"profile": [{"turns_check_off": turns_check_off}]}},
    }
    assert first_match(_prototype_rules("rigor"), data) is holds
