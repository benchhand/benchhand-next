# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""rule_lists: the test stand-in for the rules bundle evaluates a list the way the compiled expression would."""

from __future__ import annotations

from typing import Any

import pytest
from rule_lists import first_match, holds


def _list(condition: str) -> dict[str, Any]:
    return {"rule": {"match": [{"condition": condition, "output": '"F2"'}, {"output": '"F0"'}]}}


@pytest.mark.parametrize(
    ("stage", "fidelity"),
    [("parts", "F2"), ("layout", "F0")],
)
def test_first_match_gives_the_output_of_the_first_condition_that_holds(stage: str, fidelity: str) -> None:
    assert first_match(_list('stage == "parts"'), {"stage": stage}) == fidelity


@pytest.mark.parametrize(
    "condition",
    [
        pytest.param('"false"', id="string"),
        pytest.param("stage.size()", id="int"),
        pytest.param("[stage]", id="list"),
        pytest.param("record.missing", id="missing-key"),
        pytest.param('stage == "parts" || 1 / 0 == 1', id="divide-by-zero"),
    ],
)
def test_a_condition_that_does_not_give_a_cel_bool_fails_the_test(condition: str) -> None:
    data = {"stage": "layout", "record": {}}
    with pytest.raises(AssertionError, match="not a bool"):
        holds(condition, data)
    with pytest.raises(AssertionError, match="not a bool"):
        first_match(_list(condition), data)


def test_an_output_that_fails_to_evaluate_fails_the_test() -> None:
    rule_list = {"rule": {"match": [{"output": "record.fidelity"}]}}
    with pytest.raises(AssertionError, match="fails"):
        first_match(rule_list, {"record": {}})
