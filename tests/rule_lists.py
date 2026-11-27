"""A test stand-in for the CI-compiled rules bundle: evaluates one restricted cel-policy rule list.

Phase 2 evaluates the one checked expression that the pinned cel-go policy compiler writes for each rule list
in CI (owner decision of 2026-11-27). Until then this helper runs the same flat first-match semantics itself on
cel-expr-python, which has no policy API: the conditions in order, then the output of the first that holds.
Every activation variable is declared dyn, so a test that uses it proves the values a list gives, not that its
expressions type-check. Phase 2 replaces the dyn variables with the environment generated from the contracts.
"""

from __future__ import annotations

from typing import Any

from cel_expr_python import cel


def first_match(rule_list: dict[str, Any], data: dict[str, Any]) -> Any:
    env = cel.NewEnv(variables=dict.fromkeys(data, cel.Type.DYN))
    for item in rule_list["rule"]["match"]:
        if env.compile(item.get("condition", "true")).eval(data=data).value():
            return env.compile(item["output"]).eval(data=data).plain_value()
    raise AssertionError("no item matched: the last item of a rule list must be unconditional")
