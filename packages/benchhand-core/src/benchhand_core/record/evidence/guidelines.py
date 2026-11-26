"""Which guideline sets a record's capability profiles resolve through, and their digests: the part of the
prototype's guidelines.py (release.toml reference_commit 412b5d9) that the `source` fingerprint folds in
(impact.py:343-351).

The reader discovers the sets and hashes their bytes (`GuidelineCatalog`); these rules only match them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from benchhand_core.record.evidence.joints import LENGTH_MM
from benchhand_core.record.evidence.view import JsonMap, RecordView, items, mapping

SCOPE_FACTS = ("material_family", "filler", "shore", "nozzle_material")
MICROMETRE_TOLERANCE = 1e-6  # guidelines.py:90
# file-name prefix of a shipped set a version build copies into its record/ (guidelines.py:74)
SHIPPED_COPY = "shipped--"
# capability profile id -> material profile name -> id@revision -> sha256
GuidelineDigests = Mapping[str, Mapping[str, Mapping[str, str]]]


@dataclass(frozen=True)
class GuidelineSet:
    """One valid guideline set: what matching reads of it, and the sha256 of its file (guidelines.py:121)."""

    id: str
    revision: int
    extends: tuple[str, ...]
    abstract: bool
    scope: JsonMap
    sha256: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.revision}"


@dataclass(frozen=True)
class Refusal:
    """A guideline file discovery refused: where it is shown and why (guidelines.py:152)."""

    path: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class GuidelineCatalog:
    """The sets discovered by id, the ids a refused file declared (they resolve to nothing), whether any set
    is a shipped set or a version's copy of one, and the refused files (guidelines.py:175)."""

    sets: Mapping[str, GuidelineSet] = field(default_factory=dict)
    blocked: frozenset[str] = frozenset()
    has_shipped: bool = False
    refused: tuple[Refusal, ...] = ()


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def quantity_problem(where: str, data: Any) -> str | None:
    """Why `data` is no quantity the resolver can read: no units, a number that is not finite, or a reversed
    interval (guidelines.py:242 `_quantity_problems`, manufacturing_intent.py:357 `quantity`). The contract
    already limits units to the known names."""
    data = mapping(data)
    if not isinstance(data.get("units"), str):
        return f"{where}: a quantity needs units"
    numbers = [data[key] for key in ("value", "lower", "upper") if key in data]
    if not numbers or not all(_finite(n) for n in numbers):
        return f"{where}: a quantity needs finite numbers"
    if "value" not in data and data.get("lower", 0) > data.get("upper", 0):
        return f"{where}: interval {data['lower']:g}..{data['upper']:g} {data['units']} is reversed"
    return None


def _sizes_problems(where: str, sizes: Any) -> list[str]:
    """A discrete size set: every item readable, a whole number of micrometres, no two the same size
    (guidelines.py:222)."""
    problems: list[str] = []
    seen: dict[int, int] = {}
    for position, item in enumerate(items(sizes)):
        problem = quantity_problem(f"{where}/{position}", item)
        scale = LENGTH_MM.get(mapping(item).get("units") or "")
        if problem is not None or scale is None or "value" not in mapping(item):
            problems.extend([problem] if problem else [])
            continue
        exact = float(item["value"]) * scale * 1000.0
        if abs(exact - round(exact)) > MICROMETRE_TOLERANCE:
            problems.append(f"{where}/{position}: {exact:g} um is not a whole number of micrometres")
        elif round(exact) in seen:
            problems.append(
                f"{where}/{position}: duplicate of {where}/{seen[round(exact)]} ({round(exact)} um)"
            )
        else:
            seen[round(exact)] = position
    return problems


def _limit_problems(index: int, limit: JsonMap) -> list[str]:
    """guidelines.py:203 `_limit_problems`."""
    problems: list[str] = []
    if "quantity" in limit and (problem := quantity_problem(f"limits/{index}/quantity", limit["quantity"])):
        problems.append(problem)
    if "quantities" in limit:
        problems.extend(_sizes_problems(f"limits/{index}/quantities", limit["quantities"]))
    relative = limit.get("relative")
    if not isinstance(relative, Mapping):
        return problems
    if not _finite(relative.get("factor")):
        problems.append(f"limits/{index}/relative/factor: {relative.get('factor')} is not finite")
    floor = relative.get("floor")
    problem = quantity_problem(f"limits/{index}/relative/floor", floor)
    if problem is not None:
        problems.append(problem)
    elif mapping(floor).get("units") not in LENGTH_MM:
        problems.append(f"limits/{index}/relative: the floor of a line-width limit is a length")
    return problems


def guideline_problems(data: JsonMap) -> list[str]:
    """The rules of a guideline set the contract cannot state (guidelines.py:186-200 `validate`): its scope's
    nozzle interval and every limit's quantities can be read."""
    problems: list[str] = []
    scope = mapping(data.get("scope"))
    if "nozzle_diameter" in scope and (
        problem := quantity_problem("scope/nozzle_diameter", scope["nozzle_diameter"])
    ):
        problems.append(problem)
    for index, limit in enumerate(items(data.get("limits"))):
        problems.extend(_limit_problems(index, mapping(limit)))
    return problems


@dataclass(frozen=True)
class Context:
    """What a capability profile and a material profile say about the scope selectors; None is unknown
    (guidelines.py:391)."""

    process: str | None
    facts: Mapping[str, str | None]
    nozzle_diameter_mm: float | None
    pin: tuple[str, ...] | None


class _Unresolved(Exception):
    """A closure that does not resolve (guidelines.py GuidelineError)."""


def _text_fact(data: Any) -> str | None:
    """guidelines.py:406."""
    if not isinstance(data, Mapping):
        return None
    if data.get("status") == "known" and isinstance(data.get("value"), str):
        return str(data["value"])
    return "none" if data.get("status") == "not_applicable" else None


def _millimetres(fact: Any) -> float | None:
    """A known single length in millimetres (guidelines.py:414)."""
    fact = mapping(fact)
    quantity = mapping(fact.get("value"))
    units = quantity.get("units")
    scale = LENGTH_MM.get(units) if isinstance(units, str) else None
    value = quantity.get("value")
    if fact.get("status") != "known" or scale is None or not isinstance(value, int | float):
        return None
    return float(value) * scale


def context_for(profile: JsonMap, material: JsonMap | None = None) -> Context:
    """guidelines.py:422."""
    parameters = mapping(profile.get("parameters"))
    facts: dict[str, str | None] = {name: _text_fact(mapping(material).get(name)) for name in SCOPE_FACTS[:3]}
    nozzle = mapping(parameters.get("nozzle_material"))
    known = nozzle.get("status") == "known" and isinstance(nozzle.get("value"), str)
    facts["nozzle_material"] = str(nozzle["value"]) if known else None
    pin = profile.get("guidelines")
    process = profile.get("process")
    return Context(
        process if isinstance(process, str) else None,
        facts,
        _millimetres(parameters.get("nozzle_diameter")),
        tuple(pin) if isinstance(pin, list) and pin else None,
    )


def _interval_mm(quantity: Any) -> tuple[float, float] | None:
    quantity = mapping(quantity)
    units = quantity.get("units")
    scale = LENGTH_MM.get(units) if isinstance(units, str) else None
    if scale is None:
        return None
    if isinstance(quantity.get("value"), int | float):
        return quantity["value"] * scale, quantity["value"] * scale
    lower, upper = quantity.get("lower"), quantity.get("upper")
    if isinstance(lower, int | float) and isinstance(upper, int | float):
        return lower * scale, upper * scale
    return None


def _matches(scope: JsonMap, context: Context) -> bool | None:
    """True when every selector matches, False when one does not, None when none fails but a fact is unknown
    (guidelines.py:436)."""
    unknown = False
    if context.process is not None and scope.get("process") != context.process:
        return False
    for name in SCOPE_FACTS:
        if name not in scope:
            continue
        have = context.facts.get(name)
        if have is None:
            unknown = True
        elif have not in scope[name]:
            return False
    if "nozzle_diameter" in scope:
        bounds = _interval_mm(scope["nozzle_diameter"])
        if context.nozzle_diameter_mm is None or bounds is None:
            unknown = True
        elif not bounds[0] - 1e-9 <= context.nozzle_diameter_mm <= bounds[1] + 1e-9:
            return False
    return None if unknown else True


def _pinned(guideline: GuidelineSet, context: Context) -> bool:
    return context.pin is not None and guideline.ref in context.pin


def _allowed(guideline: GuidelineSet, context: Context) -> bool:
    """False when the pin names another revision of the set (guidelines.py:492)."""
    if context.pin is None:
        return True
    return guideline.ref in context.pin or all(not pin.startswith(f"{guideline.id}@") for pin in context.pin)


def closure(
    catalog: GuidelineCatalog, ident: str, context: Context, seen: tuple[str, ...] = ()
) -> list[GuidelineSet]:
    """`ident` and its parents, parents first; _Unresolved for a cycle, a missing or refused parent, or a set
    the pin names at another revision (guidelines.py:467)."""
    guideline = catalog.sets.get(ident)
    if ident in seen or ident in catalog.blocked or guideline is None or not _allowed(guideline, context):
        raise _Unresolved(ident)
    chain: list[GuidelineSet] = []
    for parent in guideline.extends:
        chain.extend(g for g in closure(catalog, parent, context, (*seen, ident)) if g not in chain)
    chain.append(guideline)
    return chain


def applicable(catalog: GuidelineCatalog, context: Context) -> list[GuidelineSet]:
    """guidelines.py:517."""
    return [
        g
        for g in sorted(catalog.sets.values(), key=lambda g: g.id)
        if (not g.abstract or _pinned(g, context))
        and _allowed(g, context)
        and _matches(g.scope, context) is not False
    ]


def applicable_digests(catalog: GuidelineCatalog, context: Context) -> dict[str, str]:
    """id@revision -> sha256 of every set the context can resolve through, parents included
    (guidelines.py:524)."""
    found: dict[str, str] = {}
    for guideline in applicable(catalog, context):
        try:
            chain = closure(catalog, guideline.id, context)
        except _Unresolved:
            chain = [guideline]
        found.update({g.ref: g.sha256 for g in chain})
    return dict(sorted(found.items()))


def record_digests(record: RecordView, catalog: GuidelineCatalog) -> dict[str, dict[str, dict[str, str]]]:
    """Capability profile id -> material profile name -> applicable digests; a record without materials has
    the one name "", and a profile no set resolves through is left out (guidelines.py:537)."""
    found: dict[str, dict[str, dict[str, str]]] = {}
    materials: dict[str, JsonMap | None] = dict(record.materials) or {"": None}
    for ident, profile in sorted(record.capabilities.items()):
        by_material = {
            name: applicable_digests(catalog, context_for(profile, material))
            for name, material in sorted(materials.items())
        }
        if any(by_material.values()):
            found[ident] = by_material
    return found


def digests_for(by_material: Mapping[str, Mapping[str, str]] | None, names: Sequence[str]) -> dict[str, str]:
    """The union of the material profiles' entries; a part naming none, or one the record lacks, takes every
    entry: it goes stale more often, never less (guidelines.py:551)."""
    pool = by_material or {}
    chosen = list(names) if names and all(name in pool for name in names) else list(pool)
    return dict(sorted({ref: sha for name in chosen for ref, sha in pool[name].items()}.items()))


def with_guideline_digests(record: RecordView, catalog: GuidelineCatalog) -> RecordView:
    """`record` with the digests of the guideline sets its capability profiles resolve through
    (manufacturing_intent.py:1235 `with_guidelines`)."""
    return replace(record, guideline_digests=record_digests(record, catalog))
