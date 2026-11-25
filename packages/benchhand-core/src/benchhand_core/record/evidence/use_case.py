"""Whether the use case supports a final material and process choice (the intent.use_case obligation).

A port of the prototype's manufacturing_intent.assess_use_case (skills/cad-record/scripts/
manufacturing_intent.py at release.toml reference_commit 412b5d9, lines 2350-2387, with USE_CASE_FACTS at
160-171 and the use-case reader at 1549-1607).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchhand_core.record.evidence.view import JsonMap, RecordView, is_fact, items, mapping

USE_CASE_FACTS = (
    "purpose",
    "users",
    "environment.temperature",
    "environment.heat_sources",
    "environment.moisture",
    "environment.chemicals",
    "environment.uv",
    "environment.corrosion",
    "motion.speed",
    "motion.range",
    "motion.duty_cycle",
    "motion.friction",
    "motion.wear",
    "motion.service_life",
    "accuracy.tolerance",
    "accuracy.repeatability",
    "accuracy.surface_finish",
    "accuracy.dimensional_stability",
    "consequences.failure",
    "consequences.severity",
    "consequences.forbidden_outcomes",
    "consequences.standards",
    "consequences.supervision",
    "consequences.approval_authority",
    "logistics.quantity",
    "logistics.budget",
    "logistics.lead_time",
    "logistics.maintenance",
    "logistics.repair",
    "capability.operator",
    "capability.outsourcing",
    "release_scope.purpose",
    "release_scope.operating_limits",
    "release_scope.exclusions",
)
_NOT_RECORDED = {"status": "unknown"}


@dataclass(frozen=True)
class UseCaseAssessment:
    final_ready: bool
    blocking: tuple[str, ...]


def fact_at(use_case: JsonMap, dotted: str) -> JsonMap:
    """The fact at a dotted use-case path; anything that is not a recorded fact reads as unknown
    (manufacturing_intent.py:1352)."""
    value: Any = use_case
    for key in dotted.split("."):
        value = value.get(key) if isinstance(value, Mapping) else None
    return value if is_fact(value) else _NOT_RECORDED


def _fields(use_case: JsonMap) -> dict[str, JsonMap]:
    fields = {name: fact_at(use_case, name) for name in USE_CASE_FACTS}
    fields["service_class"] = fact_at(use_case, "service_class")
    loads = use_case.get("loads")
    if not isinstance(loads, list):
        fields["loads"] = loads if is_fact(loads) else _NOT_RECORDED
    equipment = mapping(use_case.get("capability")).get("equipment")
    if not isinstance(equipment, list):
        fields["capability.equipment"] = equipment if is_fact(equipment) else _NOT_RECORDED
    policy = use_case.get("evidence_policy")
    if not (isinstance(policy, Mapping) and "obligations" in policy):
        fields["evidence_policy"] = policy if is_fact(policy) else _NOT_RECORDED
    return fields


def _untracked(record: RecordView, fields: Mapping[str, JsonMap]) -> list[str]:
    """Unknown use-case fields that no open question tracks."""
    questions = {q.get("id"): q for q in items(record.requirements_document.get("open_questions"))}
    blocking = []
    for name in sorted(name for name, value in fields.items() if value.get("status") == "unknown"):
        tracking = fields[name].get("question")
        question = questions.get(tracking) if tracking else None
        if question is None:
            blocking.append(f"use_case.{name} is unknown and no open question tracks it")
        elif question.get("status") != "open":
            state = question.get("status")
            blocking.append(
                f"use_case.{name} is unknown but its question {question.get('id')} is {state}; "
                "record the answer in the fact or reopen the question"
            )
    return blocking


def _open_questions(record: RecordView) -> list[str]:
    return sorted(
        str(q.get("id"))
        for q in items(record.requirements_document.get("open_questions"))
        if q.get("status") == "open" and (q.get("material_to_choice") or q.get("safety_relevant"))
    )


def assess_use_case(record: RecordView) -> UseCaseAssessment:
    """A final choice needs a confirmed use case, a known service class, no open question material to the
    choice or to safety, and no unknown that no open question tracks (manufacturing_intent.py:2350)."""
    use_case = record.use_case
    blocking: list[str] = []
    if use_case.get("status") != "confirmed" or not use_case.get("decision"):
        blocking.append("the use case is not confirmed by a decision")
    fields = _fields(use_case)
    service = fields["service_class"]
    service_value = service.get("value") if service.get("status") == "known" else None
    if service_value in (None, "unknown"):
        blocking.append("the service class is unknown")
    blocking.extend(_untracked(record, fields))
    open_questions = _open_questions(record)
    if open_questions:
        blocking.append(f"open questions material to the choice or safety: {', '.join(open_questions)}")
    if service_value == "safety_critical":
        for name in ("consequences.standards", "consequences.approval_authority"):
            if fields[name].get("status") != "known":
                blocking.append(f"a safety-critical use case needs use_case.{name}")
    return UseCaseAssessment(not blocking, tuple(blocking))
