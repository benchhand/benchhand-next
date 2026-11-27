"""A test stand-in for the CI-compiled rules bundle: evaluates restricted cel-policy rule lists and their merge.

Phase 2 evaluates the one checked expression that the pinned cel-go tool writes for each rule list before load
(ADR-0020). Until then this helper runs the same flat first-match semantics itself on cel-expr-python, which
has no policy API: the conditions in order, then the output of the first that holds. Every activation variable
is declared dyn, so a test that uses it proves the values a list gives, not that its expressions type-check.
Phase 2 replaces the dyn variables with the environment generated from the contracts.

`merged` runs the proposed merge of a kind's contributed lists with the flow's own (docs/contract/policy.md),
which is open for the owner.
"""

from __future__ import annotations

from typing import Any

from cel_expr_python import cel

# The value a list of a fall-through kind gives when none of its own choices apply, so the next list is
# evaluated. rigor has none: every rigor list is evaluated.
NO_MATCH: dict[str, Any] = {"checks_by_iteration": [], "dispatch": "unknown", "fidelity": "none"}


def first_match(rule_list: dict[str, Any], data: dict[str, Any]) -> Any:
    env = cel.NewEnv(variables=dict.fromkeys(data, cel.Type.DYN))
    for choice in rule_list["rule"]["match"]:
        if env.compile(choice.get("condition", "true")).eval(data=data).value():
            return env.compile(choice["output"]).eval(data=data).plain_value()
    raise AssertionError("no choice matched: the last choice of a rule list must be unconditional")


def merged(
    kind: str, contributed: dict[str, dict[str, Any]], flow_list: dict[str, Any], data: dict[str, Any]
) -> Any:
    """The kind's result: the contributed lists, by ascending provider name, then the flow's, whose result is final.

    rigor gives the union of every list's messages, in evaluation order.
    """
    ordered = [contributed[provider] for provider in sorted(contributed)]
    if kind == "rigor":
        return [message for rule_list in [*ordered, flow_list] for message in first_match(rule_list, data)]
    for rule_list in ordered:
        value = first_match(rule_list, data)
        if value != NO_MATCH[kind]:
            return value
    return first_match(flow_list, data)
