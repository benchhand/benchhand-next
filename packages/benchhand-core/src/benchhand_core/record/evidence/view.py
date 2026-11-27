# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The record as the evidence rules read it: each document's JSON, keyed as the prototype's normalized record.

The rules port the prototype's manufacturing_intent.Record reader (skills/cad-record/scripts/
manufacturing_intent.py at release.toml reference_commit 412b5d9, `_Reader`, lines 1283-2340). A v3 record
has already met its contracts on read, so this view only regroups the documents: no shape is checked again.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from benchhand_core.record.model import Record, as_json

JsonMap = Mapping[str, Any]
FACT_STATUSES = ("known", "unknown", "not_applicable")


def is_fact(value: object) -> TypeGuard[Mapping[str, Any]]:
    """A recorded fact (known, unknown or not applicable) in place of a list or an id (prototype
    manufacturing_intent.py:459 `_looks_like_fact`)."""
    return isinstance(value, Mapping) and value.get("status") in FACT_STATUSES


def mapping(value: object) -> JsonMap:
    """`value` when it is a mapping, else an empty one (an absent block reads as empty)."""
    return value if isinstance(value, Mapping) else {}


def items(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class RecordView:
    """Every document of one record as JSON. Parts, interfaces, requirements, material and capability
    profiles are keyed by id; `approved` holds the decisions whose citation approves (a gate approved or
    a design accepted)."""

    product: JsonMap
    requirements_document: JsonMap
    requirements: Mapping[str, JsonMap]
    interfaces: Mapping[str, JsonMap]
    assembly: JsonMap
    parts: Mapping[str, JsonMap]
    materials: Mapping[str, JsonMap]
    capabilities: Mapping[str, JsonMap]
    evidence: tuple[JsonMap, ...]
    dispositions: tuple[JsonMap, ...]
    verification: tuple[JsonMap, ...]
    approved: frozenset[str]
    selection: JsonMap = field(default_factory=dict)
    # the project's own guideline sets (hw/manufacturing/guidelines/), by file stem order
    guidelines: tuple[JsonMap, ...] = ()
    # capability profile id -> material profile name -> id@revision -> sha256 of every guideline set it
    # resolves through (guidelines.record_digests); empty until `with_guideline_digests`
    guideline_digests: Mapping[str, Mapping[str, Mapping[str, str]]] = field(default_factory=dict)

    @property
    def use_case(self) -> JsonMap:
        return mapping(self.product.get("use_case"))

    @property
    def operations(self) -> Any:
        """assembly.yaml `operations`: a list, a fact, or None when the assembly records none."""
        return self.assembly.get("operations")

    def approves(self, decision: object) -> bool:
        return isinstance(decision, str) and decision in self.approved

    def made(self, pn: str) -> bool:
        """Custom-made: make, or bought made to drawing (manufacturing_intent.py:1680)."""
        part = self.parts.get(pn) or {}
        procurement = mapping(part.get("procurement"))
        return part.get("make_buy") == "make" or procurement.get("mode") == "made_to_drawing"


def _keyed(entries: object) -> dict[str, JsonMap]:
    return {item["id"]: item for item in items(entries) if isinstance(item, Mapping) and "id" in item}


def _profiles(record: Record, name: str) -> dict[str, JsonMap]:
    document = record.manufacturing.get(name)
    return _keyed(as_json(document).get("profiles")) if document is not None else {}


def _ledger(record: Record, name: str, key: str) -> tuple[JsonMap, ...]:
    document = record.manufacturing.get(name)
    return tuple(items(as_json(document).get(key))) if document is not None else ()


def view(record: Record) -> RecordView:
    requirements = as_json(record.requirements)
    return RecordView(
        product=as_json(record.product),
        requirements_document=requirements,
        requirements=_keyed(requirements.get("requirements")),
        interfaces=_keyed(as_json(record.interfaces).get("interfaces")),
        assembly=as_json(record.assembly),
        parts={pn: as_json(part) for pn, part in sorted(record.parts.items())},
        materials=_profiles(record, "materials"),
        capabilities=_profiles(record, "capabilities"),
        evidence=_ledger(record, "evidence", "entries"),
        dispositions=_ledger(record, "findings", "dispositions"),
        verification=tuple(as_json(row) for row in record.verification),
        approved=frozenset(ident for ident, decision in record.decisions.items() if decision.approves),
        selection=as_json(record.manufacturing["selection"]) if "selection" in record.manufacturing else {},
        guidelines=tuple(as_json(record.guidelines[stem]) for stem in sorted(record.guidelines)),
    )
