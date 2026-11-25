"""pytest plugin: append each instance the tests validate to the JSON lines file ``$EQUIV_LOG``.

``just contracts-equivalence`` runs the package tests with it, so that the replay judges real instances
against the hand-written and the published schemas. An instance with a NaN or Infinity is left out: the
validator refuses it before any schema sees it.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

import benchhand_contracts
import benchhand_contracts.validation as validation

_violations = validation.violations
_log = open(os.environ["EQUIV_LOG"], "a", encoding="utf-8")  # noqa: SIM115 - open for the whole session


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def _recording_violations(schema_id: str, instance: Any) -> list[validation.ContractViolation]:
    if _finite(instance):
        try:
            _log.write(json.dumps({"schema_id": schema_id, "instance": instance}) + "\n")
        except (TypeError, ValueError):  # not JSON, such as a date; the contract refuses it anyway
            pass
    return _violations(schema_id, instance)


validation.violations = _recording_violations
benchhand_contracts.violations = _recording_violations
