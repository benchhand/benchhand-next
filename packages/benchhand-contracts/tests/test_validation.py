"""Runtime validation in benchhand_contracts.validation: a violation is typed and points at the bad value."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from typing import Any

import pytest
from benchhand_contracts import ContractViolation, UnknownSchemaError, validate, violations

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
MANIFEST_ID = f"{CONTRACTS}provider/manifest.schema.json"
HOOK_KIND_ID = "https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json#/$defs/HookKind"


def _schema_text(rel_path: str) -> str:
    return (files("benchhand_contracts") / "schemas" / rel_path).read_text(encoding="utf-8")


def _resolve(document: Any, pointer: str) -> Any:
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def _manifest_example() -> dict[str, Any]:
    return copy.deepcopy(json.loads(_schema_text("provider/manifest.schema.json"))["examples"][0])


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
    # schema_path is where the failing keyword is, past the $ref that led to it.
    resource, _, pointer = caught.value.schema_path.partition("#")
    protocol = json.loads(_schema_text("provider/protocol.schema.json"))
    assert resource == f"{CONTRACTS}provider/protocol.schema.json"
    assert _resolve(protocol, pointer) is protocol["$defs"]["HookKind"]["enum"]


def test_violations_lists_every_violation_with_the_most_relevant_first() -> None:
    manifest = _manifest_example()
    del manifest["name"]
    manifest["hooks"][0]["kind"] = "nonsense"
    found = violations(MANIFEST_ID, manifest)
    assert {violation.pointer for violation in found} == {"", "/hooks/0/kind"}
    with pytest.raises(ContractViolation) as caught:
        validate(MANIFEST_ID, manifest)
    assert (caught.value.pointer, caught.value.message) == (found[0].pointer, found[0].message)
    assert violations(MANIFEST_ID, _manifest_example()) == []


def test_of_two_violations_at_one_place_the_first_keyword_is_reported() -> None:
    # {"extra": 1} breaks both additionalProperties and required at the root. The validator reports the
    # keyword that comes first in the schema, so the published keyword order is part of the diagnostic.
    finding_id = f"{CONTRACTS}common/finding.schema.json"
    with pytest.raises(ContractViolation) as caught:
        validate(finding_id, {"extra": 1})
    assert caught.value.pointer == ""
    assert caught.value.schema_path == f"{finding_id}#/additionalProperties"
    paths = [violation.schema_path.partition("#")[2] for violation in violations(finding_id, {"extra": 1})]
    assert paths[0] == "/additionalProperties"
    assert set(paths[1:]) == {"/required"}


def test_an_unknown_schema_id_is_an_error() -> None:
    with pytest.raises(UnknownSchemaError):
        validate(f"{MANIFEST_ID}#/$defs/NoSuchDefinition", {})


def test_a_oneof_violation_is_listed_once() -> None:
    gate = {"kind": "gate", "status": "provisional", "gate": "layout_freeze", "stage": "nowhere"}
    front = {"id": "DR-021", "title": "Layout freeze", "date": "2026-11-21", **gate}
    found = violations(f"{CONTRACTS}record/decision.schema.json", front)
    listed = [(violation.pointer, violation.schema_path, violation.message) for violation in found]
    assert len(listed) == len(set(listed)) >= 1
