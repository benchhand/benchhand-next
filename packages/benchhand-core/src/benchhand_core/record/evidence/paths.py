# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Where the files an accepted ledger entry cites may live: the pure half of the path rules.

A port of the prototype's evidence_paths.py (skills/cad-record/scripts/evidence_paths.py at release.toml
reference_commit 412b5d9) and its use in evidence.py (`_entry` 947-949, the reliant loop 794-806 and
`acceptance_inventory` 1283-1295). Evidence in the record must be reproducible from the record: a cited file
lies inside the project root and is tracked by git or lies in a record-managed result location (a sealed
hw/versions/<V>/ or a version-bound bundle hw/<kind>/<V>/<S>/). Scratch (`.cad-work/`, `hw/.cad/`), temp
directories, the home directory and anything outside the root are refused.

The reader judges each cited path against the filesystem and git (`PathQuery` -> `Verdict`); these rules
only read those verdicts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchhand_core.record.evidence.view import JsonMap, items, mapping

SCRATCH_PREFIXES = (".cad-work/", "hw/.cad/", ".cad/", "/tmp/", "/var/folders/", "~/")
PROMOTE = (
    "promote the file into the record (for example under hw/checks/<V>/<S>/evidence/) and list it in "
    "artifacts, or cite a tracked packet"
)
# Entry fields that are not prose (evidence_paths.py:36-49); record v3 renamed the waiver's `expires`
# to `valid_until`. `[]` in a pointer stands for any list index.
_SOURCE_FIELDS = ("accessed", "artifact", "date", "decision", "kind", "sha256", "url")
_WAIVER_FIELDS = ("decision", "valid_until", "obligation", "subject")
ENTRY_STRUCTURED = frozenset(
    {
        "id",
        "requirement",
        "obligation",
        "subject",
        "level",
        "result",
        "configuration",
        "fingerprints",
        "artifacts",
        "bundle",
        "decisions",
        "physical.date",
        "criterion.id",
        "criterion.property",
        "criterion.operator",
        "criterion.value",
        "criterion.units",
        "criterion.state",
        *(f"source.{name}" for name in _SOURCE_FIELDS),
        *(f"criterion.source.{name}" for name in _SOURCE_FIELDS),
        *(f"waiver.{name}" for name in _WAIVER_FIELDS),
    }
)
DISPOSITION_STRUCTURED = frozenset(
    {
        "finding",
        "code",
        "producer",
        "status",
        "decision",
        "replacement_evidence",
        *(f"waiver.{name}" for name in _WAIVER_FIELDS),
    }
)
PATH_CODES = frozenset({"evidence.scratch_path", "evidence.uncited_artifact"})
# The version-bound bundle roots below hw/ (the prototype's layout.json bundle.* entries).
BUNDLE_KINDS = frozenset(("checks", "drawings", "renders", "captures", "motion", "analysis"))
_TOKEN = re.compile(r"[^\s\"'`()\[\]{}<>,;=|]+")
_EXTENSION = re.compile(r"(?=[0-9]*[A-Za-z])[A-Za-z0-9]{1,8}$")
_NUMBER = re.compile(r"[+\-\u2212\u00b1]?[0-9]+(?:\.[0-9]+)?$")
_URL = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$")
_EVIDENCE_ID = re.compile(r"\bEV-[0-9]{3}\b")
_LOCATION = re.compile(r"[:#].*$")


@dataclass(frozen=True)
class PathQuery:
    """One cited path to judge: `structured` for a path field (artifacts, bundle, source.artifact), else a
    path-like token of prose."""

    cited: str
    structured: bool


@dataclass(frozen=True)
class Verdict:
    """Where one cited path lies (evidence_paths.py:55): `rel` is its project path when it resolves inside the
    root, `problem` why the rule refuses it, `managed` whether it lies in a record-managed result location."""

    rel: str | None
    problem: str | None
    managed: bool = False


@dataclass(frozen=True)
class PathProblem:
    code: str  # evidence.scratch_path or evidence.uncited_artifact
    where: str
    message: str


Verdicts = Mapping[PathQuery, Verdict]
UNJUDGED = Verdict(None, "was not judged against the project")


def verdict_of(verdicts: Verdicts, path: str, structured: bool) -> Verdict:
    """The reader's verdict on `path`; a path it did not judge is refused."""
    return verdicts.get(PathQuery(path, structured), UNJUDGED)


def is_path_like(token: str) -> bool:
    """A scratch prefix, an absolute path, a `..` segment, or a file extension after a `/`
    (evidence_paths.py:72)."""
    bare = token
    while bare.startswith("./"):
        bare = bare[2:]
    if bare.startswith(SCRATCH_PREFIXES) or bare in (".cad-work", "hw/.cad", ".cad"):
        return True
    if token.startswith("/"):
        return re.match(r"^/[^/]+/.+|^/[^/]+\.[A-Za-z]", token) is not None
    if "/" not in token:
        return False
    if ".." in token.split("/"):
        return True
    stem, dot, extension = token.rsplit("/", 1)[1].rpartition(".")
    return bool(dot) and _EXTENSION.match(extension) is not None and _NUMBER.match(stem) is None


def path_tokens(text: str) -> list[str]:
    """The path-like tokens of prose, without a trailing sentence mark, line number or anchor; URLs other than
    file:// are not file paths (evidence_paths.py:90)."""
    found = []
    for raw in _TOKEN.findall(text):
        token = raw.rstrip(".:!?")
        match = _URL.match(token)
        if match:
            if match.group(1).lower() != "file":
                continue
            token = "/" + match.group(2).lstrip("/")
        token = _LOCATION.sub("", token)
        if token and is_path_like(token):
            found.append(token)
    return found


def _strings(node: Any, skip: frozenset[str], key: str = "", pointer: str = "") -> Iterable[tuple[str, str]]:
    """(dotted key, text) of every string below `node` whose exact pointer is not in `skip`."""
    if pointer in skip:
        return
    if isinstance(node, str):
        yield key, node
    elif isinstance(node, Mapping):
        for name, value in node.items():
            child_key = f"{key}.{name}" if key else str(name)
            yield from _strings(value, skip, child_key, f"{pointer}.{name}" if pointer else str(name))
    elif isinstance(node, Sequence):
        for index, value in enumerate(node):
            yield from _strings(value, skip, f"{key}[{index}]", f"{pointer}[]")


def _structured(entry: JsonMap) -> list[tuple[str, str, bool]]:
    """(where, project path, listed) of an entry's path fields; `listed` paths are what its prose may cite."""
    artifacts = enumerate(items(entry.get("artifacts")))
    found = [(f"artifacts[{i}]", mapping(a).get("path"), True) for i, a in artifacts]
    found.append(("bundle", mapping(entry.get("bundle")).get("path"), True))
    for where, holder in (
        ("source.artifact", entry.get("source")),
        ("criterion.source.artifact", mapping(entry.get("criterion")).get("source")),
    ):
        artifact = mapping(holder).get("artifact")
        found.append((where, f"hw/{artifact}" if isinstance(artifact, str) else None, False))
    return [(where, path, listed) for where, path, listed in found if isinstance(path, str)]


def entry_queries(entry: JsonMap) -> set[PathQuery]:
    """Every path of one ledger entry the reader must judge."""
    found = {PathQuery(path, True) for _, path, _ in _structured(entry)}
    for _, text in _strings(entry, ENTRY_STRUCTURED):
        found.update(PathQuery(token, False) for token in path_tokens(text))
    return found


def disposition_queries(disposition: JsonMap) -> set[PathQuery]:
    bundle = mapping(disposition.get("producer")).get("bundle")
    found = {PathQuery(bundle, True)} if isinstance(bundle, str) else set()
    for _, text in _strings(disposition, DISPOSITION_STRUCTURED):
        found.update(PathQuery(token, False) for token in path_tokens(text))
    return found


def _refused(where: str, path: str, verdict: Verdict) -> PathProblem:
    return PathProblem("evidence.scratch_path", where, f"{where} {path} {verdict.problem}: {PROMOTE}")


def _text_problems(
    verdicts: Verdicts, node: JsonMap, listed: Sequence[str] | None, skip: frozenset[str]
) -> list[PathProblem]:
    """evidence_paths.py:202 `_text_problems`."""
    problems = []
    for key, text in _strings(node, skip):
        for token in path_tokens(text):
            verdict = verdict_of(verdicts, token, False)
            if verdict.problem:
                message = f"{key} cites {token}, which {verdict.problem}: {PROMOTE}"
                problems.append(PathProblem("evidence.scratch_path", key, message))
            elif (
                listed is not None
                and verdict.managed
                and verdict.rel is not None
                and not any(verdict.rel == item or verdict.rel.startswith(f"{item}/") for item in listed)
            ):
                message = (
                    f"{key} cites {verdict.rel}, a record result its artifacts do not list: list it in "
                    "artifacts with its sha256"
                )
                problems.append(PathProblem("evidence.uncited_artifact", key, message))
    return problems


def entry_problems(verdicts: Verdicts, entry: JsonMap) -> list[PathProblem]:
    """Why an entry cites files the record cannot hold: a refused path field, a refused path in its prose, or
    a record result its prose cites but its artifacts do not list (evidence_paths.py:178)."""
    problems, listed = [], []
    for where, path, lists in _structured(entry):
        verdict = verdict_of(verdicts, path, True)
        if verdict.problem:
            problems.append(_refused(where, path, verdict))
        elif lists and verdict.rel:
            listed.append(verdict.rel)
    return problems + _text_problems(verdicts, entry, listed, ENTRY_STRUCTURED)


def disposition_problems(verdicts: Verdicts, disposition: JsonMap) -> list[PathProblem]:
    """A disposition lists no artifacts, so only the inside rule applies (evidence_paths.py:220)."""
    problems = []
    bundle = mapping(disposition.get("producer")).get("bundle")
    if isinstance(bundle, str) and verdict_of(verdicts, bundle, True).problem:
        problems.append(_refused("producer.bundle", bundle, verdict_of(verdicts, bundle, True)))
    return problems + _text_problems(verdicts, disposition, None, DISPOSITION_STRUCTURED)


def evidence_refs(entry: JsonMap) -> list[str]:
    """The other evidence ids the prose of `entry` names, in order of first mention
    (evidence_paths.py:228)."""
    own = entry.get("id")
    found: dict[str, None] = {}
    for _, text in _strings(entry, ENTRY_STRUCTURED):
        found.update((ident, None) for ident in _EVIDENCE_ID.findall(text) if ident != own)
    return list(found)


def dependents(entries: Sequence[JsonMap], refused: Iterable[str]) -> dict[str, list[str]]:
    """The entries that rest on a refused entry, directly or through other dependents, with the refused or
    dependent entries each names; a cycle among accepted entries taints nobody (evidence_paths.py:238)."""
    roots = set(refused)
    tainted = set(roots)
    refs = {str(e.get("id")): evidence_refs(e) for e in entries}
    changed = True
    while changed:
        changed = False
        for ident, cited in refs.items():
            if ident not in tainted and any(c in tainted for c in cited):
                tainted.add(ident)
                changed = True
    return {
        ident: [c for c in cited if c in tainted]
        for ident, cited in refs.items()
        if ident in tainted and ident not in roots
    }
