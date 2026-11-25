"""The lint findings the published schemas keep (``contracts_gen.lint``, ADR-0017)."""

from __future__ import annotations

import json

from contracts_gen.lint import ALLOWED, unexpected

SCHEMAS = "/repo/packages/benchhand-contracts/src/benchhand_contracts/schemas"


def _error(rel_path: str, pointer: str) -> dict[str, object]:
    tokens = [int(token) if token.isdigit() else token for token in pointer.split("/")[1:]]
    rule = "required_properties_in_properties"
    return {"path": f"{SCHEMAS}/{rel_path}", "id": rule, "schemaLocation": tokens}


def test_a_new_finding_and_a_listed_finding_no_longer_reported_both_fail() -> None:
    kept = [_error(path, pointer) for path, pointers in ALLOWED.items() for pointer in pointers]
    assert unexpected(json.dumps({"valid": False, "errors": kept})) == ([], [])
    new = _error("record/part.schema.json", "/$defs/component/then/required/0")
    gone = kept.pop(0)
    report = json.dumps({"valid": False, "errors": [*kept, new]})
    gone_at = "/" + "/".join(str(token) for token in gone["schemaLocation"])  # type: ignore[union-attr]
    assert unexpected(report) == (
        ["record/part.schema.json#/$defs/component/then/required/0: required_properties_in_properties"],
        [f"record/common.schema.json#{gone_at}"],
    )
