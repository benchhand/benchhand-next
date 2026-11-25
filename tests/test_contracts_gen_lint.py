"""The lint findings the published schemas keep (``contracts_gen.lint``, ADR-0017)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from contracts_gen.lint import ALLOWED, unexpected
from contracts_gen.sources import REPO_ROOT, SCHEMAS_OUT

RULE = "required_properties_in_properties"
REASON_AT = "/$defs/not_assessed_rule/then/required/0"


def _error(schemas: Path, rel_path: str, pointer: str) -> dict[str, Any]:
    tokens = [int(token) if token.isdigit() else token for token in pointer.split("/")[1:]]
    return {"path": str(schemas / rel_path), "id": RULE, "schemaLocation": tokens}


def _report(errors: list[dict[str, Any]]) -> str:
    return json.dumps({"valid": not errors, "errors": errors})


def _kept(schemas: Path) -> list[dict[str, Any]]:
    return [_error(schemas, path, pointer) for path, pointers in ALLOWED.items() for pointer in pointers]


def _published_copy(tmp_path: Path) -> Path:
    schemas = tmp_path / "schemas"
    shutil.copytree(REPO_ROOT / SCHEMAS_OUT, schemas)
    return schemas


def test_the_published_schemas_hold_the_kept_findings_and_a_new_or_missing_one_fails(tmp_path: Path) -> None:
    schemas = _published_copy(tmp_path)
    kept = _kept(schemas)
    assert unexpected(_report(kept)) == ([], [])
    gone = kept.pop(0)
    new = _error(schemas, "record/extra.schema.json", "/$defs/sheet/required/0")
    (schemas / "record/extra.schema.json").write_text(json.dumps({"$defs": {"sheet": {"required": ["x"]}}}))
    gone_at = "/" + "/".join(str(token) for token in gone["schemaLocation"])
    new_line = f"record/extra.schema.json#/$defs/sheet/required/0: {RULE} names 'x'"
    assert unexpected(_report([*kept, new])) == ([new_line], [f"record/common.schema.json#{gone_at}"])


def test_a_different_name_at_a_kept_location_fails(tmp_path: Path) -> None:
    """A misspelt ``reason`` at the same pointer is a new finding, not the kept one."""
    schemas = _published_copy(tmp_path)
    common = schemas / "record/common.schema.json"
    schema = json.loads(common.read_text())
    assert schema["$defs"]["not_assessed_rule"]["then"]["required"] == ["reason"]
    schema["$defs"]["not_assessed_rule"]["then"]["required"] = ["raeson"]
    common.write_text(json.dumps(schema))
    new, stale = unexpected(_report(_kept(schemas)))
    assert new == [f"record/common.schema.json#{REASON_AT}: {RULE} names 'raeson', the exemption 'reason'"]
    assert stale == []
