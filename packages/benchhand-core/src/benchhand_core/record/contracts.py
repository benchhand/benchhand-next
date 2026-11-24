"""The record contracts (contracts/record/*.schema.json), as packaged in benchhand_contracts, and validation
against them."""

from __future__ import annotations

import functools
import json
from importlib.resources import files
from typing import Any

import benchhand_contracts
from benchhand_contracts import ContractViolation

CONTRACTS_URI = "https://benchhand.github.io/benchhand/contracts/"


def schema_id(contract: str) -> str:
    """The `$id` of a record contract, by file stem: `product`, `bom-row`, `decision`…"""
    return f"{CONTRACTS_URI}record/{contract}.schema.json"


@functools.cache
def schema(contract: str) -> dict[str, Any]:
    """The schema of a record contract, by file stem."""
    path = files("benchhand_contracts") / "schemas" / "record" / f"{contract}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def violations(contract: str, instance: Any) -> list[ContractViolation]:
    """Every violation of `contract` by `instance`, the most relevant first."""
    return benchhand_contracts.violations(schema_id(contract), instance)


def shown_location(schema_path: str) -> str:
    """A violation's schema location relative to the contracts directory: `record/common.schema.json#/…`."""
    return schema_path.removeprefix(CONTRACTS_URI)
