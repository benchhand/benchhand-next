# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""flow/flow and flow/rules: they express the prototype's flow, and the gate-decision request follows ADR-0018."""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from benchhand_contracts import violations
from rule_lists import NO_MATCH, explanation, first_match, holds

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
FLOW_ID = f"{CONTRACTS}flow/flow.schema.json"
RULES_ID = f"{CONTRACTS}flow/rules.schema.json"
REQUEST_ID = f"{FLOW_ID}#/$defs/GateDecisionRequest"
PROTOTYPE = Path(__file__).parent / "fixtures/flow/prototype-412b5d9"
RULE_KINDS = ("checks_by_iteration", "dispatch", "fidelity", "rigor")
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
def test_each_prototype_rule_list_ends_with_an_unconditional_choice(kind: str) -> None:
    # The schema says exactly one choice is unconditional; the cel-go tool refuses one that isn't last.
    *_, last = _prototype_rules(kind)["rule"]["match"]
    assert "condition" not in last


@pytest.mark.parametrize(
    "match",
    [
        pytest.param([{"condition": 'stage == "parts"', "output": '"F2"'}], id="no-unconditional-choice"),
        pytest.param([{"output": '"F2"'}, {"output": '"F0"'}], id="two-unconditional-choices"),
    ],
)
def test_a_rule_list_without_exactly_one_unconditional_choice_is_refused(match: list[dict[str, str]]) -> None:
    found = violations(RULES_ID, {"name": "fidelity", "rule": {"match": match}})
    assert [violation.pointer for violation in found] == ["/rule/match"]


def test_the_schema_leaves_the_position_of_the_unconditional_choice_to_the_compiler() -> None:
    first = [{"output": '"F0"'}, {"condition": 'stage == "parts"', "output": '"F2"'}]
    assert violations(RULES_ID, {"name": "fidelity", "rule": {"match": first}}) == []


def _constant(output: str) -> Any:
    """The value of an output that reads no variable."""
    return first_match({"rule": {"match": [{"output": output}]}}, {})


@pytest.mark.parametrize("kind", ["dispatch", "checks_by_iteration"])
def test_the_flow_list_may_end_in_its_kinds_no_match_value(kind: str) -> None:
    # The flow's result is final: a dispatch that ends in "unknown" is UNKNOWN coverage, a [] runs no check.
    *_, last = _prototype_rules(kind)["rule"]["match"]
    assert _constant(last["output"]) == NO_MATCH[kind]


def test_the_prototype_fidelity_list_ends_in_f0_and_no_output_is_none() -> None:
    # Only the fixture: no schema can refuse "none" in a flow's fidelity list, since the file doesn't say its kind.
    # The Phase 2 loader refuses a literal "none"; test_policy_contract shows a computed one is UNKNOWN.
    outputs = [_constant(choice["output"]) for choice in _prototype_rules("fidelity")["rule"]["match"]]
    assert outputs[-1] == "F0"
    assert NO_MATCH["fidelity"] not in outputs


def test_the_flow_rigor_list_ends_in_no_unmet_requirement() -> None:
    *_, last = _prototype_rules("rigor")["rule"]["match"]
    assert _constant(last["output"]) == []


@pytest.mark.parametrize("key", ["kind", "rules_version", "rules"])
def test_a_rule_list_file_no_longer_carries_its_kind_or_the_old_shape(key: str) -> None:
    # flow.yaml's reference to the file carries kind and rules_version.
    assert violations(RULES_ID, {**_prototype_rules("fidelity"), key: 1})


@pytest.mark.parametrize(
    ("where", "feature"),
    [
        ("list", "imports"),
        ("list", "description"),
        ("rule", "aggregate"),
        ("rule", "variables"),
        ("rule", "id"),
        ("rule", "description"),
    ],
)
def test_a_rule_list_outside_the_restricted_profile_is_refused(where: str, feature: str) -> None:
    # ADR-0020's profile: a name and one rule with one match block of conditions, outputs and explanations.
    fidelity = _prototype_rules("fidelity")
    holder = {"list": fidelity, "rule": fidelity["rule"], "choice": fidelity["rule"]["match"][0]}[where]
    holder[feature] = '"text"'
    assert violations(RULES_ID, fidelity)


def test_a_rule_list_file_is_a_celpolicy_file() -> None:
    flow = _prototype_flow()
    flow["rules"]["fidelity"]["file"] = "fidelity.rules.yaml"
    assert violations(FLOW_ID, flow)


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


STAGED_GATES = ("layout_freeze", "parts", "detail", "analysis")


def _staged_human_activation(*, unproved: bool, cites: list[str], approved: bool = True) -> dict[str, Any]:
    """A staged gate's human step on v3: DR-012 is its provisional decision, DR-013 accepts v3's intervals."""
    return {
        "full_check": {
            "status": "pass",
            "sweep": {"unproved_intervals": [{"pair": "lid/base"}] if unproved else []},
        },
        "prev_human_gate": {"approved": True},
        "version": {"label": "v3"},
        "provisional": {"id": "DR-012"},
        "decisions": [
            {"id": "DR-012", "accepts_unproved_intervals": False, "version": "v3"},
            {"id": "DR-013", "accepts_unproved_intervals": True, "version": "v3"},
        ],
        "answer": {"approved": approved, "cites": cites},
    }


@pytest.mark.parametrize("gate_id", STAGED_GATES)
@pytest.mark.parametrize(
    ("unproved", "cites", "approved", "passes"),
    [
        pytest.param(False, ["DR-012"], True, True, id="no-intervals-cites-the-provisional"),
        pytest.param(True, ["DR-012", "DR-013"], True, True, id="cites-the-interval-acceptance"),
        pytest.param(True, ["DR-012"], True, False, id="uncited-interval-acceptance"),
        pytest.param(False, ["DR-013"], True, False, id="uncited-provisional"),
        pytest.param(False, ["DR-012"], False, False, id="not-approved"),
    ],
)
def test_a_prototype_staged_human_gate_passes_only_on_an_approval_that_cites_its_decisions(
    gate_id: str, unproved: bool, cites: list[str], approved: bool, passes: bool
) -> None:
    # flow.md "Gate control" 3: the approval cites the provisional decision and, when the sweep left unproved
    # between-sample intervals, the DR that accepts them. The full sweep runs at L1 to L4, so each gate can.
    gate = next(gate for gate in _prototype_flow()["gates"] if gate["id"] == gate_id)
    data = _staged_human_activation(unproved=unproved, cites=cites, approved=approved)
    assert all(holds(requirement, data) for requirement in gate["requires"]["human"]) is passes


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


# Every character the gate request counts as whitespace: Python's str.isspace (Unicode White_Space and U+001C to
# U+001F), ECMAScript's \s (which adds U+FEFF and leaves out U+0085) and every Zs character.
WHITESPACE = sorted(
    {chr(code) for code in range(0x10000) if chr(code).isspace() or unicodedata.category(chr(code)) == "Zs"}
    | set("\t\n\v\f\r \u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff")
    | {chr(code) for code in range(0x2000, 0x200B)}
)


@pytest.mark.parametrize("field", ["by", "quote"])
@pytest.mark.parametrize("blank", [" ", "\u0085", "\t\n", "\u00a0\u3000", "\ufeff", *WHITESPACE], ids=ascii)
def test_a_name_or_quote_of_only_whitespace_is_no_answer(field: str, blank: str) -> None:
    assert [violation.pointer for violation in violations(REQUEST_ID, {**_request(), field: blank})] == [
        f"/{field}"
    ]


def test_by_and_quote_share_the_one_nonblank_text() -> None:
    properties = _schema()["$defs"]["GateDecisionRequest"]["properties"]
    assert properties["by"]["$ref"] == properties["quote"]["$ref"] == "#/$defs/NonblankText"


@pytest.mark.parametrize("field", ["by", "quote"])
def test_a_name_or_quote_with_one_visible_character_is_an_answer(field: str) -> None:
    assert violations(REQUEST_ID, {**_request(), field: "\u0085\u3000y "}) == []


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
            f"full, {stage}, {assembly}",
            "full",
            stage,
            overrides,
            ["validate", "static.all_pairs", "form_check.due", *motion, "bom.reconcile", "fits.stackup"]
            + [*sweep, *extra, "evidence.check", "recheck.stamp"],
        )
        for stage, extra in [
            ("layout", []),
            ("parts", ["sourcing.selection"]),
            ("detail", ["drawings.all"]),
            ("analysis", ["fea.all_cases"]),
            ("reconcile", ["fea.stale_cases"]),
        ]
        # evidence.py _not_applicable: no motion render or sweep without an independent movable joint.
        for assembly, overrides, motion, sweep in [
            ("fixed joints only", {}, [], []),
            (
                "a movable joint",
                JOINT,
                ["motion.default_render"],
                [] if stage == "reconcile" else ["sweep.full"],
            ),
        ]
    ),
    (
        "design freeze, a stale sweep, a movable joint",
        "design_freeze",
        "design_freeze",
        {"stale": [{"family": "sweep"}], **JOINT},
        ["validate", "bom.reconcile", "fits.stackup", "evidence.check", "recheck.stamp", "sweep.full"],
    ),
    (
        "design freeze, a stale sweep, fixed joints only",
        "design_freeze",
        "design_freeze",
        {"stale": [{"family": "sweep"}]},
        ["validate", "bom.reconcile", "fits.stackup", "evidence.check", "recheck.stamp"],
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


@pytest.mark.parametrize(
    ("family", "operation", "text"),
    [
        ("process.fdm.orientation", {"kind": "fdm"}, "handled by process.fdm.orientation"),
        (
            "process.welding.coverage",
            {"kind": "welding"},
            "no handler exists for process.welding.coverage: its kind has no check contract, so its"
            " manufacturability is not assessed",
        ),
        ("purchase.price", None, "this producer has no handler for purchase.price, so it is not assessed"),
        (
            "process.fdm.orientation",
            {"kind": "cnc"},
            "this producer has no handler for process.fdm.orientation, so it is not assessed",
        ),
    ],
)
def test_the_prototype_dispatch_list_explains_a_missing_handler_as_the_prototype_did(
    family: str, operation: dict[str, str] | None, text: str
) -> None:
    # dispatch.py coverage_gap and _no_handler: a coverage obligation has no check contract, and any other
    # unhandled family has no handler; both are UNKNOWN, and the explanation carries the finding's text.
    obligation = {"family": family, **({"operation": operation} if operation else {})}
    assert explanation(_prototype_rules("dispatch"), {"obligation": obligation}) == text


def test_every_choice_of_the_prototype_dispatch_list_has_an_explanation() -> None:
    assert all("explanation" in choice for choice in _prototype_rules("dispatch")["rule"]["match"])


@pytest.mark.parametrize("explained", [[0], [1]], ids=["first-only", "last-only"])
def test_a_rule_list_with_an_explanation_on_some_choices_only_is_refused(explained: list[int]) -> None:
    # In cel-go's explanation copy a choice without one is dropped, so its explanation would answer another choice.
    fidelity = _prototype_rules("fidelity")
    for index in explained:
        fidelity["rule"]["match"][index]["explanation"] = '"why"'
    found = violations(RULES_ID, fidelity)
    assert found
    assert all(violation.pointer.startswith("/rule/match") for violation in found)


def test_a_rule_list_with_an_explanation_on_every_choice_validates() -> None:
    fidelity = _prototype_rules("fidelity")
    for choice in fidelity["rule"]["match"]:
        choice["explanation"] = '"the fidelity of " + stage'
    assert violations(RULES_ID, fidelity) == []
    assert explanation(fidelity, {"stage": "parts", "stage_order": {}}) == "the fidelity of parts"


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
    unmet = first_match(_prototype_rules("rigor"), data)
    assert (unmet == []) is holds
    assert all(isinstance(message, str) and message for message in unmet)
