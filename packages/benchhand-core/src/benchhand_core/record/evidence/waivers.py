# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Waivers: when an approved, scoped waiver stands (prototype evidence.py:351 `waiver_problem`, 412b5d9).

A waived obligation stays waived, never pass. A waiver needs an approved decision, the exact subject of the
evidence it waives, the obligation it names, and an unexpired valid_until (record v3 renamed the prototype's
`expires`). It never overrides a geometry-integrity check (cad.*), a requirement that forbids waivers or
carries critical risk, a mandatory requirement of a safety-critical use case, or a critical finding of a
safety-critical use case.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from benchhand_core.record.evidence.view import JsonMap, RecordView, mapping


@dataclass(frozen=True)
class WaiverProblem:
    code: str  # waiver.unapproved, waiver.expired, waiver.scope or waiver.forbidden
    message: str


@dataclass(frozen=True)
class WaiverScope:
    """What a waiver is asked to cover: the evidence subject, the obligation it waives (id and family, when
    the evidence names one) with the requirements that obligation derives from, further requirement ids, and
    whether it waives a critical finding."""

    subject: JsonMap | None
    obligation: str | None = None
    family: str | None = None
    obligation_requirements: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    critical: bool = False


def service_class(record: RecordView) -> str | None:
    """The use case's known service class, None while it is unknown (evidence.py:311)."""
    fact = mapping(record.use_case.get("service_class"))
    value = fact.get("value")
    return value if fact.get("status") == "known" and value != "unknown" else None


def _expiry_problem(waiver: JsonMap, today: date) -> WaiverProblem | None:
    decision, until = waiver.get("decision"), waiver.get("valid_until")
    if not isinstance(until, str):
        return None
    try:
        expired = date.fromisoformat(until) < today
    except ValueError:
        return WaiverProblem(
            "waiver.expired", f"the waiver approved by {decision} has an unreadable valid_until {until!r}"
        )
    if expired:
        return WaiverProblem("waiver.expired", f"the waiver approved by {decision} expired on {until}")
    return None


def _scope_problem(waiver: JsonMap, scope: WaiverScope) -> WaiverProblem | None:
    decision = waiver.get("decision")
    if scope.subject is not None and dict(mapping(waiver.get("subject"))) != dict(scope.subject):
        return WaiverProblem(
            "waiver.scope",
            f"the waiver approved by {decision} names {waiver.get('subject')}, not {dict(scope.subject)}",
        )
    if scope.obligation is not None and waiver.get("obligation") not in (None, scope.obligation):
        return WaiverProblem(
            "waiver.scope",
            f"the waiver approved by {decision} waives {waiver['obligation']}, not {scope.obligation}",
        )
    return None


def _requirement_problem(requirement: JsonMap, safety_critical: bool) -> WaiverProblem | None:
    ident = requirement.get("id")
    if requirement.get("waiver_policy") == "forbidden":
        return WaiverProblem("waiver.forbidden", f"{ident} forbids waivers (waiver_policy: forbidden)")
    if mapping(requirement.get("risk")).get("severity") == "critical":
        return WaiverProblem("waiver.forbidden", f"{ident} carries critical risk; no waiver overrides it")
    if safety_critical and str(requirement.get("priority", "")).lower() == "must":
        return WaiverProblem(
            "waiver.forbidden", f"{ident} is a governing requirement of a safety-critical use case"
        )
    return None


def _governed(record: RecordView, scope: WaiverScope) -> Iterable[JsonMap]:
    """The requirements the waived evidence speaks to (evidence.py:340 `_requirements_of`)."""
    ids = set(scope.requirements) | set(scope.obligation_requirements)
    return [record.requirements[ident] for ident in sorted(ids) if ident in record.requirements]


def waiver_problem(
    waiver: Mapping[str, Any], scope: WaiverScope, record: RecordView, today: date
) -> WaiverProblem | None:
    """Why `waiver` cannot stand, or None (evidence.py:351)."""
    decision = waiver.get("decision")
    if not record.approves(decision):
        return WaiverProblem(
            "waiver.unapproved", f"waiver decision {decision} is missing or is not the user's approval"
        )
    problem = _expiry_problem(waiver, today) or _scope_problem(waiver, scope)
    if problem is not None:
        return problem
    safety_critical = service_class(record) == "safety_critical"
    if scope.family is not None and scope.family.startswith("cad."):
        return WaiverProblem(
            "waiver.forbidden", f"{scope.obligation} is a geometry-integrity check; no waiver overrides it"
        )
    if scope.critical and safety_critical:
        return WaiverProblem(
            "waiver.forbidden", "a critical finding of a safety-critical use case cannot be waived"
        )
    for requirement in _governed(record, scope):
        problem = _requirement_problem(requirement, safety_critical)
        if problem is not None:
            return problem
    return None
