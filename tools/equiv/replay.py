"""Judge every replay case, and mutations of every accepted one, against the hand-written and the published
schemas with the real ``benchhand_contracts.violations``.

Usage: ``python tools/equiv/replay.py <work dir>``, after ``cases.py``. For each instance it compares
whether it's valid and the whole list of violations, each ``(pointer, schema_path, message)`` in order,
so a changed first violation shows up even when both schemas refuse the instance. The evidence for the one
intended narrowing is a second comparison: the published schemas with the Timestamp ``pattern`` taken
out must give exactly the hand-written verdict, with no difference left. Writes ``<work dir>/python.json``
and ``mutants.jsonl``, the published verdicts and the mutants, for ``replay.mjs`` to judge in Ajv, and
exits 1 on any difference left without the pattern.
"""

from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import benchhand_contracts.validation as validation
from referencing import Registry, Resource

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
JOB_ID = f"{CONTRACTS}jobs/job.schema.json"
PUBLISHED = (
    Path(__file__).resolve().parents[2] / "packages/benchhand-contracts/src/benchhand_contracts/schemas"
)
MUTANTS_PER_CASE = 4000
"""A cap per accepted instance, so that a large record doesn't dominate the run."""
UNRESOLVABLE = "unresolvable"
Verdict = tuple[tuple[str, str, str], ...] | str
"""The violations of an instance in order, ``()`` when it is valid, or ``UNRESOLVABLE``."""


def _registry(directory: Path) -> Registry:
    paths = sorted(directory.rglob("*.schema.json"))
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)


def _use_registry(registry: Registry) -> None:
    """Make ``validation`` validate against ``registry`` instead of the packaged schemas."""
    validation._registry = cache(lambda: registry)  # noqa: SLF001 - the replay swaps the loaded contracts
    validation._validator.cache_clear()  # noqa: SLF001
    validation._schema_locations.cache_clear()  # noqa: SLF001


def judge(schema_id: str, instance: Any) -> Verdict:
    try:
        found = validation.violations(schema_id, instance)
    except validation.UnknownSchemaError:
        return UNRESOLVABLE
    return tuple((v.pointer, v.schema_path, v.message) for v in found)


def without_timestamp_pattern(directory: Path) -> Registry:
    """The schemas of ``directory`` with the Timestamp ``pattern`` taken out again."""
    registry = _registry(directory)
    job = copy.deepcopy(registry.contents(JOB_ID))
    del job["$defs"]["Timestamp"]["pattern"]
    return registry.with_resource(JOB_ID, Resource.from_contents(job))


def _paths(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    yield path
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _paths(child, (*path, index))


def _at(value: Any, path: tuple[Any, ...]) -> Any:
    for key in path:
        value = value[key]
    return value


def _other_type(value: Any) -> Any:
    if isinstance(value, str):
        return 12345
    if isinstance(value, bool | int | float):
        return "s"
    if value is None:
        return "n"
    return {"a": 1} if isinstance(value, list) else ["x"]


def _replaced(instance: Any, path: tuple[Any, ...], replacement: Any) -> Any:
    mutant = copy.deepcopy(instance)
    _at(mutant, path[:-1])[path[-1]] = replacement
    return mutant


def _removed(instance: Any, path: tuple[Any, ...]) -> Any:
    mutant = copy.deepcopy(instance)
    del _at(mutant, path[:-1])[path[-1]]
    return mutant


def _grown(instance: Any, path: tuple[Any, ...]) -> Any:
    mutant = copy.deepcopy(instance)
    target = _at(mutant, path)
    if isinstance(target, dict):
        target["x-conformance-unknown"] = 1
    else:
        target.append(copy.deepcopy(target[0]))
    return mutant


def mutants(instance: Any) -> Iterator[Any]:
    """At every path: drop the key, set a value of another type or an edge value, add an unknown property
    to an object, and repeat the first item of an array."""
    for path in _paths(instance):
        value = _at(instance, path)
        if path:
            if isinstance(_at(instance, path[:-1]), dict):
                yield _removed(instance, path)
            for replacement in (_other_type(value), None, 0, -1, 1e9, "", "Z", True, [], {}):
                if replacement != value:
                    yield _replaced(instance, path, replacement)
        if isinstance(value, dict) or isinstance(value, list) and value:
            yield _grown(instance, path)


def _mutant_cases(case: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for index, mutant in enumerate(mutants(case["instance"])):
        if index >= MUTANTS_PER_CASE:
            return
        yield {"source": f"mutant of {case['source']}", "schema_id": case["schema_id"], "instance": mutant}


def _verdicts(cases: list[dict[str, Any]]) -> list[Verdict]:
    return [judge(case["schema_id"], case["instance"]) for case in cases]


def _valid(verdict: Verdict) -> bool | str:
    return verdict if isinstance(verdict, str) else not verdict


def _first(verdict: Verdict) -> Any:
    return verdict if isinstance(verdict, str) else verdict[:1]


def _short(verdict: Verdict) -> str:
    if isinstance(verdict, str):
        return verdict
    if not verdict:
        return "valid"
    pointer, schema_path, message = verdict[0]
    location = schema_path.removeprefix(CONTRACTS)
    return f"{len(verdict)} violation(s), first at {pointer or '/'} by {location}: {message[:50]}"


def _report(title: str, cases: list[dict[str, Any]], verdicts: dict[str, list[Verdict]]) -> int:
    """``verdicts``: the ``old``, ``new`` and ``counterfactual`` (new without the pattern) verdicts. Returns
    the number of instances whose verdict still differs once the Timestamp pattern is taken out."""
    rows = list(zip(cases, verdicts["old"], verdicts["new"], verdicts["counterfactual"], strict=True))
    validity = Counter(f"{_valid(o)}/{_valid(n)}" for _, o, n, _ in rows)
    differ = [row for row in rows if row[1] != row[2]]
    left = [row for row in rows if row[1] != row[3]]
    first_changed = sum(1 for _, o, n, _ in differ if _first(o) != _first(n))
    print(f"{title}: {len(cases)} instances")
    print(f"  valid hand-written/published: {dict(sorted(validity.items()))}")
    print(f"  hand-written vs published: {len(differ)} differ, the first violation in {first_changed}")
    print(f"  hand-written vs published without the Timestamp pattern: {len(left)} differ, of {len(rows)}")
    for case, o, n, _ in (left or differ)[:8]:
        mark = "DIFFERS WITHOUT THE PATTERN" if left else "only with the pattern"
        where = case["schema_id"].removeprefix(CONTRACTS)
        print(f"    {mark}: {case['source']}, {where}, {json.dumps(case['instance'])[:70]}")
        print(f"      hand-written: {_short(o)}")
        print(f"      published:    {_short(n)}")
    return len(left)


def main(work: Path) -> int:
    cases = json.loads((work / "cases.json").read_text(encoding="utf-8"))
    new = _verdicts(cases)
    accepted = [case for case, verdict in zip(cases, new, strict=True) if verdict == ()]
    mutated = [mutant for case in accepted for mutant in _mutant_cases(case)]
    replay = {"new": new}
    mutation = {"new": _verdicts(mutated)}
    for name, registry in (
        ("old", _registry(work / "old")),
        ("counterfactual", without_timestamp_pattern(PUBLISHED)),
    ):
        _use_registry(registry)
        replay[name], mutation[name] = _verdicts(cases), _verdicts(mutated)
    (work / "python.json").write_text(json.dumps([_valid(v) for v in new]), encoding="utf-8")
    with (work / "mutants.jsonl").open("w", encoding="utf-8") as out:
        for mutant, verdict in zip(mutated, mutation["new"], strict=True):
            out.write(json.dumps({"case": mutant, "python": _valid(verdict)}) + "\n")
    print(f"cases by source: {dict(Counter(case['source'] for case in cases))}")
    failures = _report("replay", cases, replay)
    failures += _report("mutations of each instance the published schemas accept", mutated, mutation)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
