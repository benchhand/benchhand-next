# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The rules of envelope/envelope.schema.json that tie the parts of a tool result to its status."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from typing import Any

import pytest
from benchhand_contracts import violations

ENVELOPE_ID = "https://benchhand.github.io/benchhand/contracts/envelope/envelope.schema.json"


def _example(status: str) -> dict[str, Any]:
    schema = json.loads((files("benchhand_contracts") / "schemas/envelope/envelope.schema.json").read_text())
    return copy.deepcopy(next(example for example in schema["examples"] if example["status"] == status))


@pytest.mark.parametrize("status", ["ok", "refused", "pending", "error"])
def test_each_status_has_a_valid_example(status: str) -> None:
    assert violations(ENVELOPE_ID, _example(status)) == []


@pytest.mark.parametrize("status", ["refused", "pending", "error"])
def test_a_verdict_belongs_only_to_an_ok_result(status: str) -> None:
    envelope = {**_example(status), "verdict": "pass"}
    assert violations(ENVELOPE_ID, envelope)


def test_a_refusal_gives_a_reason_and_a_next_action() -> None:
    without_reason = _example("refused")
    del without_reason["reason"]
    without_action = {**_example("refused"), "next_actions": []}
    assert violations(ENVELOPE_ID, without_reason)
    assert violations(ENVELOPE_ID, without_action)


def test_a_job_handle_comes_with_a_pending_result_only() -> None:
    without_job = _example("pending")
    del without_job["job"]
    job_on_ok = {**_example("ok"), "job": _example("pending")["job"]}
    assert violations(ENVELOPE_ID, without_job)
    assert violations(ENVELOPE_ID, job_on_ok)


def test_an_error_carries_a_finding() -> None:
    assert violations(ENVELOPE_ID, {**_example("error"), "findings": []})


def test_an_artifact_path_is_absolute() -> None:
    envelope = _example("ok")
    envelope["artifacts"][0]["path"] = "hw/checks/v3/static/result.json"
    assert [violation.pointer for violation in violations(ENVELOPE_ID, envelope)] == ["/artifacts/0/path"]
