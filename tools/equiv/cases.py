"""Build the replay cases, and write the hand-written schemas of ``decoded.BASE``, into a work directory.

Usage: ``python tools/equiv/cases.py <work dir>``, after the package tests ran with ``record_plugin`` and
wrote ``<work dir>/calls.jsonl``. Writes ``<work dir>/old/<path>.schema.json`` and ``<work dir>/cases.json``,
a list of ``{"source", "schema_id", "instance"}`` with each ``(schema_id, instance)`` once:

- ``test-suite``: every instance the package tests validated;
- ``old-fixture``, ``new-fixture``: every valid and invalid conformance fixture at ``BASE`` and now;
- ``old-examples``, ``new-examples``: every ``examples`` entry, wherever it is in a schema;
- ``edge-timestamp``: date-times around the one intended narrowing.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from decoded import BASE, DATA_KEYWORDS, REPO_ROOT, SCHEMA_MAPS, _git, new_schemas, old_schemas

CONTRACTS = "https://benchhand.github.io/benchhand/contracts/"
OLD_EXAMPLES = "packages/benchhand-contracts/src/benchhand_contracts/examples"
NEW_EXAMPLES = REPO_ROOT / OLD_EXAMPLES
TIMESTAMP_ID = f"{CONTRACTS}jobs/job.schema.json#/$defs/Timestamp"
TIMESTAMPS = (
    "2026-11-25T05:08:13Z",
    "2026-11-25T05:08:13.134Z",
    "2026-11-25T05:08:13+01:00",
    "2026-11-25t05:08:13Z",
    "2026-11-25T05:08:13z",
    "2026-11-25 05:08:13Z",
    "not a time",
    "2026-13-01T00:00:00Z",
)


def _fixture_instances(fixtures: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for case in fixtures["cases"]:
        for instance in case["valid"]:
            yield case["schema_id"], instance
        for variant in case["invalid"]:
            yield case["schema_id"], variant["instance"]


def _old_fixtures() -> Iterator[tuple[str, Any]]:
    for path in _git("ls-tree", "-r", "--name-only", BASE, "--", f"{OLD_EXAMPLES}/").splitlines():
        if path.endswith(".examples.json"):
            yield from _fixture_instances(json.loads(_git("show", f"{BASE}:{path}")))


def _new_fixtures() -> Iterator[tuple[str, Any]]:
    for path in sorted(NEW_EXAMPLES.rglob("*.examples.json")):
        yield from _fixture_instances(json.loads(path.read_text(encoding="utf-8")))


def _examples(node: Any, schema_id: str, pointer: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from _examples(item, schema_id, f"{pointer}/{index}")
        return
    if not isinstance(node, dict):
        return
    for example in node.get("examples", []) if isinstance(node.get("examples"), list) else []:
        yield (f"{schema_id}#{pointer}" if pointer else schema_id), example
    for key, value in node.items():
        if key in DATA_KEYWORDS or key.startswith("x-"):
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            for name, item in value.items():
                yield from _examples(item, schema_id, f"{pointer}/{key}/{name}")
        else:
            yield from _examples(value, schema_id, f"{pointer}/{key}")


def _schema_examples(schemas: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for schema in schemas.values():
        yield from _examples(schema, schema["$id"])


def _calls(work: Path) -> Iterator[tuple[str, Any]]:
    for line in (work / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        call = json.loads(line)
        yield call["schema_id"], call["instance"]


def main(work: Path) -> None:
    old = old_schemas()
    for rel_path, schema in old.items():
        target = work / "old" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema), encoding="utf-8")
    new = new_schemas()
    sources = {
        "test-suite": _calls(work),
        "old-fixture": _old_fixtures(),
        "new-fixture": _new_fixtures(),
        "old-examples": _schema_examples(old),
        "new-examples": _schema_examples(new),
        "edge-timestamp": ((TIMESTAMP_ID, value) for value in TIMESTAMPS),
    }
    cases, seen = [], set()
    for source, instances in sources.items():
        for schema_id, instance in instances:
            key = json.dumps([schema_id, instance], sort_keys=True)
            if key not in seen:
                seen.add(key)
                cases.append({"source": source, "schema_id": schema_id, "instance": instance})
    (work / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    print(f"{len(cases)} cases, {len(old)} hand-written schemas at {BASE}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
