# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The cross-reference checks of the specs: ids that exist, pointers that resolve, Phase 2 coverage, register
coverage, requirements with sources, and a block graph without cycles."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .specs import INDEX_FILE, PAGE_FILE, PHASE, REQUIREMENTS_HEADING, SPECS_DIR, Index, Sources, Spec

_SPAN = re.compile(r"`([^`\s]+)`")
_POINTER = re.compile(r"^(?P<path>[A-Za-z0-9_.][A-Za-z0-9_./-]*):(?P<first>[0-9]+)(?:-(?P<last>[0-9]+))?$")
_CITATION_SHAPED = re.compile(r"^[^\s:]+:[0-9]")
"""A span that reads as a pointer, a path then a colon and a digit, whether or not it is a well-formed one."""
_ID = re.compile(r"\b(?:IR|RULE)-[0-9]+\b")
PROPOSAL = "**Proposal**"
QUESTION = "question:"
CAPABILITY = "capability:"


def check_specs(index: Index, specs: list[Spec], sources: Sources, repo_root: Path) -> list[str]:
    """Every problem, spec by spec in index order; empty when the specs hold together."""
    return [
        *_files(index, specs, repo_root),
        *_references(specs, sources),
        *_coverage(index, specs, sources),
        *_block_ids(specs),
        *_dependencies(specs, sources),
        *_cycles(specs),
        *_requirements(specs, sources, repo_root),
        *_malformed_requirements(specs),
        *_block_sections(specs),
        *_issue_entries(specs, sources),
        *_deferrals(specs),
        *_joined_issues(specs, sources),
        *_body_ids(specs, sources),
        *_pointers(specs, repo_root),
    ]


def _files(index: Index, specs: list[Spec], repo_root: Path) -> Iterator[str]:
    """Each spec's id is its file name, and every Markdown file in docs/specs/ is a spec, the index or the page."""
    for spec in specs:
        if spec.path != f"{SPECS_DIR}/{spec.id}.md":
            yield f"{spec.path}: its spec id is {spec.id}; a spec's id is its file name"
    known = {INDEX_FILE, PAGE_FILE, *(f"{SPECS_DIR}/{spec_id}.md" for spec_id in index.specs)}
    for path in sorted((repo_root / SPECS_DIR).glob("*.md")):
        relative = path.relative_to(repo_root).as_posix()
        if relative not in known:
            yield f"{relative}: not listed in {INDEX_FILE} specs"


def _references(specs: list[Spec], sources: Sources) -> Iterator[str]:
    """Every capability, question, design rule and register id a spec names exists."""
    for spec in specs:
        named = (
            ("capability", spec.capabilities, sources.capabilities, "the catalogue"),
            ("question", spec.front["questions"], sources.questions, "the catalogue's open questions"),
            ("design rule", spec.front["rules"], sources.rules, "the issue register"),
            (
                "issue",
                [entry["id"] for entry in [*spec.closes, *spec.defers]],
                sources.issues,
                "the issue register",
            ),
        )
        for kind, names, known, where in named:
            yield from (
                f"{spec.path}: {kind} {name} is not in {where}" for name in names if name not in known
            )
        for entry in spec.defers:
            if entry["to"] not in sources.capabilities:
                yield f"{spec.path}: {entry['id']} is deferred to {entry['to']}, which is not a capability"


def _coverage(index: Index, specs: list[Spec], sources: Sources) -> Iterator[str]:
    """A capability is covered by one spec at most, and each Phase 2 capability by one spec or the index's list."""
    covered = Counter(capability for spec in specs for capability in spec.capabilities)
    for capability, count in covered.items():
        if count > 1:
            yield f"capability {capability} is covered by {count} specs"
    for capability in index.not_yet_specced:
        item = sources.capabilities.get(capability)
        if item is None:
            yield f"{INDEX_FILE}: not_yet_specced names {capability}, which is not a capability"
        elif item.get("phase") != PHASE:
            yield f"{INDEX_FILE}: not_yet_specced names {capability}, which is not a Phase {PHASE} capability"
        elif capability in covered:
            yield f"{INDEX_FILE}: not_yet_specced names {capability}, which a spec covers"
    for capability in sources.phase_capabilities():
        if capability not in covered and capability not in index.not_yet_specced:
            yield f"Phase {PHASE} capability {capability} has no spec and is not in {INDEX_FILE} not_yet_specced"


def _block_ids(specs: list[Spec]) -> Iterator[str]:
    counts = Counter(block["id"] for spec in specs for block in spec.blocks)
    yield from (f"block {block} is defined {count} times" for block, count in counts.items() if count > 1)


def _dependencies(specs: list[Spec], sources: Sources) -> Iterator[str]:
    """A dependency names a block, a question the spec lists, or a capability that no spec covers."""
    blocks = {block["id"] for spec in specs for block in spec.blocks}
    covered = {capability: spec.id for spec in specs for capability in spec.capabilities}
    for spec in specs:
        for block in spec.blocks:
            for target in block["depends_on"]:
                problem = _dependency_problem(target, spec, blocks, covered, sources)
                if problem:
                    yield f"{spec.path}: block {block['id']} depends on {target}: {problem}"


def _dependency_problem(
    target: str, spec: Spec, blocks: set[str], covered: dict[str, str], sources: Sources
) -> str | None:
    if target.startswith(QUESTION):
        question = target.removeprefix(QUESTION)
        if question not in sources.questions:
            return "no such open question in the catalogue"
        return None if question in spec.front["questions"] else "the spec's questions don't list it"
    if target.startswith(CAPABILITY):
        capability = target.removeprefix(CAPABILITY)
        if capability not in sources.capabilities:
            return "no such capability in the catalogue"
        if capability in covered:
            return f"spec {covered[capability]} covers it; depend on its block instead"
        return None
    return None if target in blocks else "no spec defines that block"


def _cycles(specs: list[Spec]) -> Iterator[str]:
    """The blocks and their block dependencies form a graph without cycles; each cycle is reported once."""
    edges = {block["id"]: block_dependencies(block) for spec in specs for block in spec.blocks}
    done: set[str] = set()
    for start in edges:
        path = _cycle_from(start, edges, [], done)
        if path:
            yield "block dependencies have a cycle: " + " -> ".join(path)
            done.update(path)


def block_dependencies(block: dict[str, Any]) -> list[str]:
    """The blocks a block depends on, leaving out its questions and capabilities."""
    return [target for target in block["depends_on"] if not target.startswith((QUESTION, CAPABILITY))]


def _cycle_from(node: str, edges: dict[str, list[str]], trail: list[str], done: set[str]) -> list[str]:
    if node in trail:
        return [*trail[trail.index(node) :], node]
    if node in done or node not in edges:
        return []
    for target in edges[node]:
        found = _cycle_from(target, edges, [*trail, node], done)
        if found:
            return found
    done.add(node)
    return []


def _requirements(specs: list[Spec], sources: Sources, repo_root: Path) -> Iterator[str]:
    """REQ ids are unique and cite a source that exists; every block's REQ exists, and every REQ has a block."""
    for spec in specs:
        if spec.requirements_section() is None:
            yield f"{spec.path}: no `{REQUIREMENTS_HEADING}` section"
        requirements = spec.requirements()
        counts = Counter(requirement.id for requirement in requirements)
        yield from (
            f"{spec.path}: {req} is defined {count} times" for req, count in counts.items() if count > 1
        )
        for requirement in requirements:
            if not _sourced(requirement.text, sources, repo_root):
                yield (
                    f"{spec.path}:{requirement.line}: {requirement.id} cites no source "
                    "(a `path:line` that resolves, an IR or RULE id of the register, or **Proposal**)"
                )
        claimed = {req for block in spec.blocks for req in block["requirements"]}
        for block in spec.blocks:
            for req in block["requirements"]:
                if req not in counts:
                    yield f"{spec.path}: block {block['id']} names {req}, which the spec doesn't define"
        for requirement in requirements:
            if requirement.id not in claimed:
                yield f"{spec.path}:{requirement.line}: {requirement.id} is in no block"


def _sourced(text: str, sources: Sources, repo_root: Path) -> bool:
    """Whether `text` cites a register id that exists, a pointer that resolves, or marks itself a proposal."""
    if PROPOSAL in text or any(_known_id(token, sources) for token in _ID.findall(text)):
        return True
    return any(
        _POINTER.match(span) and pointer_problem(repo_root, span) is None for span in _SPAN.findall(text)
    )


def _known_id(token: str, sources: Sources) -> bool:
    return token in sources.issues or token in sources.rules


def _malformed_requirements(specs: list[Spec]) -> Iterator[str]:
    """A bullet in the Requirements section is a REQ bullet, and no REQ bullet sits outside it."""
    for spec in specs:
        for line, _ in spec.malformed_requirements():
            yield (
                f"{spec.path}:{line}: not a requirement bullet: a requirement starts `- **REQ-n.**` and sits "
                f"in the `{REQUIREMENTS_HEADING}` section"
            )


def _block_sections(specs: list[Spec]) -> Iterator[str]:
    """Each block has exactly one `### <id>` section with its scope and acceptance, and each section a block."""
    for spec in specs:
        sections = spec.block_sections()
        blocks = {block["id"] for block in spec.blocks}
        for block in spec.blocks:
            found = sections.get(block["id"], [])
            if not found:
                yield f"{spec.path}: block {block['id']} has no `### {block['id']}` section"
                continue
            if len(found) > 1:
                yield f"{spec.path}: block {block['id']} has {len(found)} `### {block['id']}` sections, not one"
                continue
            section = "\n".join(found[0])
            for part in ("**Scope.**", "**Acceptance.**"):
                if part not in section:
                    yield f"{spec.path}: the section of block {block['id']} has no {part}"
        for heading in sections:
            if heading not in blocks:
                yield f"{spec.path}: section `### {heading}` names no block of the front matter"


def _issue_entries(specs: list[Spec], sources: Sources) -> Iterator[str]:
    """A register entry is closed by one spec, by a block of it, and a deferral lands where a spec closes it."""
    closed = {entry["id"]: spec for spec in specs for entry in spec.closes}
    counts = Counter(entry["id"] for spec in specs for entry in spec.closes)
    yield from (f"{issue} is closed by {count} entries" for issue, count in counts.items() if count > 1)
    covered = {capability: spec for spec in specs for capability in spec.capabilities}
    for spec in specs:
        blocks = {block["id"] for block in spec.blocks}
        for entry in spec.closes:
            if entry["block"] not in blocks:
                yield f"{spec.path}: {entry['id']} is closed by block {entry['block']}, which the spec doesn't define"
        for entry in spec.defers:
            if entry["id"] in {closing["id"] for closing in spec.closes}:
                yield f"{spec.path}: {entry['id']} is both closed and deferred"
            owner = covered.get(entry["to"])
            if owner is not None and closed.get(entry["id"]) is not owner:
                yield f"{spec.path}: {entry['id']} is deferred to {entry['to']}, but its spec {owner.id} doesn't close it"


def joined_issues(spec: Spec, sources: Sources) -> list[str]:
    """The Phase 2 register entries whose prototype paths match a prototype path of the spec's capabilities."""
    paths = [
        path
        for capability in spec.capabilities
        for path in sources.capabilities.get(capability, {}).get("prototype", [])
    ]
    joined: list[str] = []
    for issue in sources.phase_issues():
        issue_paths = sources.issues[issue].get("prototype_paths") or []
        if any(_path_matches(issue_path, path) for issue_path in issue_paths for path in paths):
            joined.append(issue)
    return joined


def _path_matches(issue_path: str, capability_path: str) -> bool:
    if capability_path.endswith("/"):
        return issue_path.startswith(capability_path)
    return issue_path == capability_path


def _joined_issues(specs: list[Spec], sources: Sources) -> Iterator[str]:
    """Every Phase 2 register entry joined to a spec's capabilities is closed or deferred by that spec."""
    for spec in specs:
        listed = {entry["id"] for entry in [*spec.closes, *spec.defers]}
        for issue in joined_issues(spec, sources):
            if issue not in listed:
                yield f"{spec.path}: Phase {PHASE} entry {issue} touches its capabilities; close or defer it"


def _pointers(specs: list[Spec], repo_root: Path) -> Iterator[str]:
    """Every span in a spec's body that reads as a pointer is a `path:line` or `path:first-last` that names a
    file of the repository and lines in it."""
    for spec in specs:
        for offset, line in enumerate(spec.body):
            for span in _SPAN.findall(line):
                problem = pointer_problem(repo_root, span)
                if problem:
                    yield f"{spec.path}:{spec.body_line + offset}: {problem}"


def _body_ids(specs: list[Spec], sources: Sources) -> Iterator[str]:
    """Every IR and RULE id in a spec's body is an entry of the issue register."""
    for spec in specs:
        for offset, line in enumerate(spec.body):
            for token in _ID.findall(line):
                if not _known_id(token, sources):
                    yield f"{spec.path}:{spec.body_line + offset}: {token} is not in the issue register"


def _deferrals(specs: list[Spec]) -> Iterator[str]:
    """Specs that defer one entry agree on where it goes, and an entry deferred to a capability no spec covers
    isn't closed by another spec (a deferral to a covered capability is checked in _issue_entries)."""
    targets: dict[str, set[str]] = {}
    for spec in specs:
        for entry in spec.defers:
            targets.setdefault(entry["id"], set()).add(entry["to"])
    for issue, where in targets.items():
        if len(where) > 1:
            yield f"{issue} is deferred to {len(where)} capabilities: {', '.join(sorted(where))}"
    covered = {capability for spec in specs for capability in spec.capabilities}
    closing = {entry["id"]: spec.id for spec in specs for entry in spec.closes}
    for spec in specs:
        for entry in spec.defers:
            if entry["to"] not in covered and closing.get(entry["id"], spec.id) != spec.id:
                yield (
                    f"{spec.path}: {entry['id']} is deferred to {entry['to']}, which no spec covers, but spec "
                    f"{closing[entry['id']]} closes it"
                )


def pointer_problem(repo_root: Path, span: str) -> str | None:
    """Why `span`, when it reads as a pointer, doesn't resolve; None when it does or doesn't read as one."""
    if not _CITATION_SHAPED.match(span):
        return None
    if span.startswith(("/", "~")):
        return f"{span}: a pointer is a path relative to the repository"
    found = _POINTER.match(span)
    if not found:
        return f"{span}: not a `path:line` or `path:first-last` pointer"
    relative = Path(found["path"])
    if ".." in relative.parts:
        return f"{span}: a pointer stays inside the repository"
    target = repo_root / relative
    if not target.is_file():
        return f"{span}: no file {found['path']}"
    count = len(target.read_text(encoding="utf-8").splitlines())
    first = int(found["first"])
    last = int(found["last"] or first)
    if first > last:
        return f"{span}: the range runs backwards"
    if not 1 <= last <= count or first < 1:
        return f"{span}: {found['path']} has {count} lines"
    return None
