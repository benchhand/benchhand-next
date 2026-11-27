# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A test stand-in for the CI-compiled rules bundle: evaluates restricted cel-policy rule lists and their merge.

Phase 2 evaluates the one checked expression that the pinned cel-go tool writes for each rule list before load
(ADR-0020). Until then this helper runs the same flat first-match semantics itself on cel-expr-python, which
has no policy API: the conditions in order, then the output of the first that holds. A condition must give a CEL
bool, and a condition or output that doesn't, an evaluation error included, fails the test. Every activation variable
is declared dyn, so a test that uses it proves the values a list gives, not that its expressions type-check.
Phase 2 replaces the dyn variables with the environment generated from the contracts.

`merged` runs the merge of a kind's contributed lists with the flow's own (docs/contract/policy.md), which the
owner decided on 2026-11-27. A merged fidelity outside F0 to F3, or a dispatch handler id that doesn't exist,
is out of the kind's domain: it gives OutOfDomain, which Phase 2's evaluator records as UNKNOWN with a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cel_expr_python import cel

# The value a list of a fall-through kind gives when none of its own choices apply, so the next list is
# evaluated. rigor has none: every rigor list is evaluated.
NO_MATCH: dict[str, Any] = {"checks_by_iteration": [], "dispatch": "unknown", "fidelity": "none"}
FIDELITIES = frozenset({"F0", "F1", "F2", "F3"})


@dataclass(frozen=True)
class OutOfDomain:
    """A result outside its kind's domain: UNKNOWN, with a finding that names the value, never a pass."""

    kind: str
    value: Any


def _in_domain(kind: str, value: Any, handlers: frozenset[str]) -> bool:
    if kind == "fidelity":
        return value in FIDELITIES
    if kind == "dispatch":
        return value == NO_MATCH["dispatch"] or value in handlers
    return True


def _env(data: dict[str, Any]) -> cel.Env:
    return cel.NewEnv(variables=dict.fromkeys(data, cel.Type.DYN))


def holds(expression: str, data: dict[str, Any]) -> bool:
    """Whether a condition holds. A value other than a CEL bool, an evaluation error included, fails the test."""
    value = _env(data).compile(expression).eval(data=data)
    assert value.type() == cel.Type.BOOL, f"{expression!r} gives {value.type()} {value.value()!r}, not a bool"
    return bool(value.value())


def first_match(rule_list: dict[str, Any], data: dict[str, Any]) -> Any:
    env = _env(data)
    for choice in rule_list["rule"]["match"]:
        if "condition" not in choice or holds(choice["condition"], data):
            output = env.compile(choice["output"]).eval(data=data)
            assert output.type() != cel.Type.ERROR, f"{choice['output']!r} fails: {output.value()}"
            return output.plain_value()
    raise AssertionError("no choice matched: the last choice of a rule list must be unconditional")


def merged(
    kind: str,
    contributed: dict[str, dict[str, Any]],
    flow_list: dict[str, Any],
    data: dict[str, Any],
    *,
    handlers: frozenset[str] = frozenset(),
) -> Any:
    """The kind's result: the contributed lists, by ascending provider name, then the flow's, whose result is final.

    rigor gives the union of every list's messages, each once, in the order first given. handlers are the dispatch
    handler ids that exist. A result outside its kind's domain is OutOfDomain.
    """
    value = _merged(kind, contributed, flow_list, data)
    return value if _in_domain(kind, value, handlers) else OutOfDomain(kind, value)


def _merged(
    kind: str, contributed: dict[str, dict[str, Any]], flow_list: dict[str, Any], data: dict[str, Any]
) -> Any:
    ordered = [contributed[provider] for provider in sorted(contributed)]
    if kind == "rigor":
        messages = [
            message for rule_list in [*ordered, flow_list] for message in first_match(rule_list, data)
        ]
        return list(dict.fromkeys(messages))
    for rule_list in ordered:
        value = first_match(rule_list, data)
        if value != NO_MATCH[kind]:
            return value
    return first_match(flow_list, data)
