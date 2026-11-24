"""Validators for contracts/jobs/job.schema.json (ADR-0017: every boundary validates)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_CONTRACT = Path("contracts") / "jobs" / "job.schema.json"


def _find_contract() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / _CONTRACT).is_file():
            return parent / _CONTRACT
    raise FileNotFoundError(f"{_CONTRACT} not found above {__file__}")


@cache
def _validator(definition: str) -> Draft202012Validator:
    document = json.loads(_find_contract().read_text(encoding="utf-8"))
    registry = Registry().with_resource(document["$id"], Resource.from_contents(document))
    return Draft202012Validator({"$ref": f"{document['$id']}#/$defs/{definition}"}, registry=registry)


def validate_record(record: Any) -> None:
    """Raise jsonschema.ValidationError unless `record` is a JobRecord."""
    _validator("JobRecord").validate(record)


def validate_handle(handle: Any) -> None:
    """Raise jsonschema.ValidationError unless `handle` is a JobHandle."""
    _validator("JobHandle").validate(handle)
