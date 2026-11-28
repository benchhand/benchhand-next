# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Compare the register with the prototype's live ledger and the private files that feed it.

Local only: CI has none of them. It reads, and writes nothing unless asked to update the snapshot. The files it
reads are listed in tools/issues/tracked-sources.yaml as globs relative to two roots: the test project's lead
folder and the prototype challenge's handover folder. The report names files and section titles, because it is
local. The snapshot it writes holds bead ids, statuses, a date, tool-issue and brief-item numbers, and hashes
only: a file or section is keyed by the hash of its name, so no private name enters the register.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .register import BRIEF_SOURCE, REGISTER_FILE, SNAPSHOT_KEY, Register, item_order, register_from_text

LEDGER_ENV = "BENCHHAND_PROTOTYPE_LEDGER"
LEAD_ENV = "BENCHHAND_TEST_PROJECT_LEAD"
CHALLENGE_ENV = "BENCHHAND_CHALLENGE_DIR"
SOURCES_FILE = "tools/issues/tracked-sources.yaml"
ROOTS = ("lead", "challenge")
SPLITS = ("issues", "items", "headings")
_SECTION_START = re.compile(r"^(?=## )", re.MULTILINE)
_ISSUE_HEADING = re.compile(r"## ([0-9]+)\b")
_BRIEF_ITEM = re.compile(r"([0-9]+[a-z]?)\. ")
"""A brief item starts at the margin and runs over its blank and indented lines."""
_HEADING = re.compile(r"#{1,6} +(\S.*)")
_FENCE = re.compile(r"(```|~~~)")
TOP_OF_FILE = "(top of file)"
_TITLE_CHARS = 110
_LEDGER_ENV_OVERRIDE = "BEADS_DIR"
"""`bd` reads this before it looks for a ledger from its working directory, so `--ledger` unsets it."""


class SyncError(Exception):
    """The ledger, the source list or a source could not be read, or the new snapshot was refused."""


def read_ledger(ledger_dir: Path) -> dict[str, str]:
    """Every bead in the ledger at ``ledger_dir`` with its status, from ``bd list --all --json``."""
    env = {name: value for name, value in os.environ.items() if name != _LEDGER_ENV_OVERRIDE}
    try:
        listed = subprocess.run(
            ["bd", "list", "--all", "--json"],
            cwd=ledger_dir,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SyncError(f"`bd list --all --json` failed in {ledger_dir}: {error}") from error
    return ledger_statuses(json.loads(listed.stdout))


def ledger_statuses(beads: list[dict[str, object]]) -> dict[str, str]:
    return {str(bead["id"]): str(bead["status"]) for bead in beads}


@dataclass(frozen=True)
class TrackedSource:
    """One entry of the source list: a glob under a root, and how its files are cut into sections."""

    root: str
    glob: str
    split: str
    what: str
    optional: bool = False

    @property
    def label(self) -> str:
        return f"{self.root}:{self.glob}"


def load_sources(path: Path) -> list[TrackedSource]:
    """The source list, checked: every entry names a known root and split and a relative glob."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SyncError(f"cannot read the source list {path}: {error}") from error
    entries = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise SyncError(f"{path}: expected a non-empty `sources` list")
    problems = [
        problem for number, entry in enumerate(entries, 1) for problem in _source_problems(number, entry)
    ]
    if problems:
        raise SyncError(f"{path}: " + "; ".join(problems))
    return [TrackedSource(**entry) for entry in entries]


def _source_problems(number: int, entry: Any) -> list[str]:
    if not isinstance(entry, dict) or set(entry) - {"root", "glob", "split", "what", "optional"}:
        return [f"entry {number}: expected root, glob, split, what and optional only"]
    problems = []
    if entry.get("root") not in ROOTS:
        problems.append(f"entry {number}: root must be one of {', '.join(ROOTS)}")
    if entry.get("split") not in SPLITS:
        problems.append(f"entry {number}: split must be one of {', '.join(SPLITS)}")
    pattern = entry.get("glob")
    if not isinstance(pattern, str) or not pattern or pattern.startswith(("/", "~")):
        problems.append(f"entry {number}: glob must be a path relative to its root")
    if not isinstance(entry.get("what"), str) or not entry["what"].strip():
        problems.append(f"entry {number}: say what the files are in `what`")
    if not isinstance(entry.get("optional", False), bool):
        problems.append(f"entry {number}: optional is true or false")
    return problems


@dataclass(frozen=True)
class Section:
    """A part of a file hashed on its own: a tool issue (`#7`), a brief item (`item 4b`) or a heading section."""

    key: str
    title: str
    text: str


def sections(text: str, split: str) -> list[Section]:
    """``text`` cut by ``split``; every character of it is in one section."""
    if split == "issues":
        return _issue_sections(text)
    if split == "items":
        return _item_sections(text)
    return heading_sections(text)


def _issue_sections(text: str) -> list[Section]:
    """One section per issue number, joining its `## <number>` status updates; the rest by heading."""
    issues: dict[str, list[str]] = {}
    rest: list[str] = []
    for part in _SECTION_START.split(text):
        heading = _ISSUE_HEADING.match(part)
        if heading:
            issues.setdefault(heading.group(1), []).append(part.strip())
        else:
            rest.append(part)
    numbered = [
        Section(f"#{number}", _title(parts[0].splitlines()[0].removeprefix("## ")), "\n\n".join(parts))
        for number, parts in sorted(issues.items(), key=lambda item: int(item[0]))
    ]
    return heading_sections("".join(rest)) + numbered


def _item_sections(text: str) -> list[Section]:
    """One section per numbered item at the margin, with its blank and indented lines; the rest by heading."""
    items: dict[str, list[str]] = {}
    rest: list[str] = []
    current = rest
    for line in text.splitlines():
        start = _BRIEF_ITEM.match(line)
        if start:
            current = items.setdefault(start.group(1), [])
        elif line.strip() and not line[0].isspace():
            current = rest
        current.append(line)
    numbered = [
        Section(f"item {number}", _title(lines[0]), "\n".join(lines).strip())
        for number, lines in sorted(items.items(), key=lambda item: item_order(item[0]))
    ]
    return heading_sections("\n".join(rest)) + numbered


def heading_sections(text: str) -> list[Section]:
    """One section per Markdown heading, outside code fences, and one for any text above the first heading."""
    found: list[tuple[str, list[str]]] = [(TOP_OF_FILE, [])]
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line.lstrip()):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            found.append((heading.group(1).strip(), []))
        found[-1][1].append(line)
    seen: dict[str, int] = {}
    out = []
    for title, lines in found:
        body = "\n".join(lines).strip()
        if not body:
            continue
        seen[title] = seen.get(title, 0) + 1
        if title == TOP_OF_FILE and len(out) == 0:
            key = TOP_OF_FILE
        elif seen[title] == 1:
            key = f"§ {title}"
        else:
            key = f"§ {title} ({seen[title]})"
        out.append(Section(key, _title(title), body))
    return out


def _title(line: str) -> str:
    title = line.replace("**", "").strip()
    return title if len(title) <= _TITLE_CHARS else title[: _TITLE_CHARS - 1] + "…"


def digest(parts: Iterable[str]) -> str:
    """A 16-hex SHA-256 prefix of ``parts`` joined by blank lines."""
    return hashlib.sha256("\n\n".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TrackedFile:
    """A file a source matched: its label (`root:relative/path`), its whole-text hash and its sections' hashes."""

    label: str
    split: str
    file_hash: str
    sections: list[tuple[Section, str]]

    @property
    def key(self) -> str:
        return digest([self.label])


def tracked_file(label: str, split: str, text: str) -> TrackedFile:
    cut = sections(text, split)
    return TrackedFile(
        label, split, digest([text.strip()]), [(section, digest([section.text])) for section in cut]
    )


@dataclass(frozen=True)
class SourceHashes:
    files: list[TrackedFile]
    unmatched: list[str] = field(default_factory=list)
    """The labels of required sources whose glob matched no file."""

    def numbered(self, split: str, prefix: str) -> dict[str, tuple[str, TrackedFile, Section]]:
        """The sections of ``split`` files whose key starts with ``prefix``, by number, with their hash."""
        return {
            section.key.removeprefix(prefix): (value, tracked, section)
            for tracked in self.files
            if tracked.split == split
            for section, value in tracked.sections
            if section.key.startswith(prefix)
        }

    @property
    def tool_issues(self) -> dict[str, str]:
        return {number: entry[0] for number, entry in self.numbered("issues", "#").items()}

    @property
    def brief_items(self) -> dict[str, str]:
        return {number: entry[0] for number, entry in self.numbered("items", "item ").items()}

    def other_sections(self, tracked: TrackedFile) -> list[tuple[Section, str]]:
        """A file's sections that are neither a tool issue nor a brief item."""
        return [(section, value) for section, value in tracked.sections if section.key.startswith(("§", "("))]


def read_sources(sources: list[TrackedSource], roots: dict[str, Path]) -> SourceHashes:
    """Hash every file each source matches; a required source that matches nothing is reported, not an error."""
    files: list[TrackedFile] = []
    unmatched: list[str] = []
    for source in sources:
        root = roots[source.root]
        matched = sorted(name for name in glob.glob(source.glob, root_dir=root) if (root / name).is_file())
        if not matched and not source.optional:
            unmatched.append(source.label)
        for name in matched:
            try:
                text = (root / name).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise SyncError(f"cannot read {root / name}: {error}") from error
            files.append(tracked_file(f"{source.root}:{name}", source.split, text))
    return SourceHashes(files, unmatched)


def tool_issue_hashes(text: str) -> dict[str, str]:
    """Per issue number, a SHA-256 prefix of its sections: each `## <number>` heading and the body under it.

    An issue gains a section per status update, and a follow-up may change only a body, so both count.
    """
    return SourceHashes([tracked_file("lead:log", "issues", text)]).tool_issues


@dataclass
class Triage:
    new_beads: list[tuple[str, str]] = field(default_factory=list)
    changed_beads: list[tuple[str, str, str]] = field(default_factory=list)
    gone_beads: list[str] = field(default_factory=list)
    source_lines: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        """The report, one line per thing to triage: bead lines, then each source's lines with file and section."""
        out = [f"{bead} ({status}): not in the register" for bead, status in self.new_beads]
        out += [f"{bead}: {old} -> {new} since the snapshot" for bead, old, new in self.changed_beads]
        out += [f"{bead}: in the register, not in the ledger" for bead in self.gone_beads]
        return out + self.source_lines


def triage(register: Register, ledger: dict[str, str], found: SourceHashes) -> Triage:
    referenced = set(register.bead_references())
    snapshot = register.snapshot
    recorded: dict[str, str] = snapshot["statuses"]
    return Triage(
        new_beads=sorted((bead, status) for bead, status in ledger.items() if bead not in referenced),
        changed_beads=sorted(
            (bead, recorded[bead], ledger[bead])
            for bead in referenced
            if bead in ledger and bead in recorded and recorded[bead] != ledger[bead]
        ),
        gone_beads=sorted(bead for bead in referenced if bead not in ledger),
        source_lines=source_lines(snapshot, found),
    )


def source_lines(snapshot: dict[str, Any], found: SourceHashes) -> list[str]:
    """What changed in the sources since ``snapshot``: numbered issues and items, then heading sections and files."""
    issues, touched = _numbered_lines(
        snapshot.get("tool_issue_hashes", {}),
        found.numbered("issues", "#"),
        "test-project tool-issues #{}",
        "log",
    )
    items, touched_items = _numbered_lines(
        snapshot.get("brief_item_hashes", {}),
        found.numbered("items", "item "),
        BRIEF_SOURCE + " item {}",
        "brief",
    )
    out = issues + items
    known_files: dict[str, dict[str, Any]] = snapshot.get("source_hashes", {})
    for tracked in found.files:
        explained = tracked.label in touched | touched_items
        out += _file_lines(known_files.get(tracked.key), tracked, found.other_sections(tracked), explained)
    current = {tracked.key for tracked in found.files}
    gone = sorted(key for key in known_files if key not in current)
    out += [
        f"a tracked file recorded in the snapshot (key {key}) is gone or no longer matched" for key in gone
    ]
    return out + [f"{label}: tracked, but matches no file" for label in found.unmatched]


def _numbered_lines(
    known: dict[str, str], current: dict[str, tuple[str, TrackedFile, Section]], subject: str, holder: str
) -> tuple[list[str], set[str]]:
    """The lines for new, changed and gone numbers, and the labels of the files they touch."""
    out = []
    touched: set[str] = set()
    for number, (value, tracked, section) in current.items():
        where = f"{tracked.label} § {section.title}"
        if number not in known:
            out.append(f"{subject.format(number)}: new — {where}")
        elif known[number] != value:
            out.append(f"{subject.format(number)}: its text changed — {where}")
        else:
            continue
        touched.add(tracked.label)
    gone = sorted((number for number in known if number not in current), key=item_order)
    if gone:
        touched |= {tracked.label for _, tracked, _ in current.values()}
    return out + [f"{subject.format(number)}: no longer in the {holder}" for number in gone], touched


def _where(tracked: TrackedFile, section: Section) -> str:
    """`root:path \u00a7 Title`, with a repeated title's number, so each line names one section."""
    key = section.key if section.key.startswith("\u00a7") else f"\u00a7 {section.key}"
    return f"{tracked.label} {key}"


def _file_lines(
    known: dict[str, Any] | None, tracked: TrackedFile, own: list[tuple[Section, str]], explained: bool
) -> list[str]:
    """A file's own section lines; ``explained`` when a tool issue or brief item in it is already reported."""
    if known is None:
        return [f"{_where(tracked, section)}: new" for section, _ in own] or [f"{tracked.label}: new file"]
    recorded: dict[str, str] = known.get("sections", {})
    out = []
    for section, value in own:
        key = digest([section.key])
        if key not in recorded:
            out.append(f"{_where(tracked, section)}: new")
        elif recorded[key] != value:
            out.append(f"{_where(tracked, section)}: its text changed")
    present = {digest([section.key]) for section, _ in own}
    gone = sum(1 for key in recorded if key not in present)
    if gone:
        out.append(f"{tracked.label}: {gone} section(s) recorded in the snapshot are gone or retitled")
    if not out and not explained and known.get("file") != tracked.file_hash:
        out.append(f"{tracked.label}: its text changed, with no section changed (order or spacing)")
    return out


def snapshot_block(
    register: Register, ledger: dict[str, str], found: SourceHashes, today: str
) -> dict[str, object]:
    """The new snapshot: register beads' statuses, and the sources' hashes keyed by number or by hashed name."""
    statuses = {bead: ledger[bead] for bead in sorted(set(register.bead_references())) if bead in ledger}
    files = {
        tracked.key: {
            "file": tracked.file_hash,
            "sections": {digest([section.key]): value for section, value in found.other_sections(tracked)},
        }
        for tracked in found.files
    }
    return {
        "date": today,
        "statuses": statuses,
        "tool_issue_hashes": found.tool_issues,
        "brief_item_hashes": found.brief_items,
        "source_hashes": files,
    }


def write_snapshot(repo_root: Path, block: dict[str, object]) -> Register:
    """Replace only the snapshot, which `just issues` keeps as the file's last key.

    The new file passes every `just issues` check before it is written; otherwise the file is left as it was.
    """
    path = repo_root / REGISTER_FILE
    text = path.read_text(encoding="utf-8")
    start = re.search(rf"^{SNAPSHOT_KEY}:", text, re.MULTILINE)
    if start is None:
        raise SyncError(f"{REGISTER_FILE} has no `{SNAPSHOT_KEY}` key")
    dumped = yaml.safe_dump({SNAPSHOT_KEY: block}, sort_keys=False, default_flow_style=False, width=110)
    candidate = text[: start.start()] + dumped
    register = register_from_text(candidate, repo_root)
    path.write_text(candidate, encoding="utf-8")
    return register
