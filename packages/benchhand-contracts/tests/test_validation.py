"""Runtime validation in benchhand_contracts.validation: a violation is typed and points at the bad value."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from typing import Any

import pytest
from benchhand_contracts import ContractViolation, UnknownSchemaError, validate

MANIFEST_ID = "https://benchhand.github.io/benchhand/contracts/provider/manifest.schema.json"
HOOK_KIND_ID = "https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json#/$defs/HookKind"


def _manifest_example() -> dict[str, Any]:
    path = files("benchhand_contracts") / "_generated" / "schemas" / "provider" / "manifest.schema.json"
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["examples"][0])


def test_a_valid_instance_passes() -> None:
    validate(MANIFEST_ID, _manifest_example())
    validate(HOOK_KIND_ID, "kernel")


def test_a_violation_carries_the_instance_pointer_and_schema_path() -> None:
    manifest = _manifest_example()
    manifest["hooks"][0]["kind"] = "nonsense"
    with pytest.raises(ContractViolation) as caught:
        validate(MANIFEST_ID, manifest)
    assert caught.value.schema_id == MANIFEST_ID
    assert caught.value.pointer == "/hooks/0/kind"
    assert caught.value.schema_path.endswith("/enum")


def test_an_unknown_schema_id_is_an_error() -> None:
    with pytest.raises(UnknownSchemaError):
        validate(f"{MANIFEST_ID}#/$defs/NoSuchDefinition", {})
