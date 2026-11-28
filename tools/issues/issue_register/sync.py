# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Compare the register with the prototype's live ledger and the test project's lead files.

Local only: CI has neither. It reads, and writes nothing unless asked to update the snapshot. What it
writes is bead ids, statuses, a date and hashes: never ledger or test-project text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .register import BRIEF_SOURCE, REGISTER_FILE, SNAPSHOT_KEY, Register, item_order, register_from_text

LEDGER_ENV = "BENCHHAND_PROTOTYPE_LEDGER"
LEAD_ENV = "BENCHHAND_TEST_PROJECT_LEAD"
TOOL_ISSUES_FILE = "tool-issues.md"
BRIEF_FILE = "architect-prompt-tool-issues.md"
TRACKED_LEAD_FILES: tuple[str, ...] = (
    TOOL_ISSUES_FILE,  # the tool-issue log: a `## <number>` section per issue and per status update
    BRIEF_FILE,  # the owner's brief on every logged issue, as numbered items (`4.`, `4b.`)
    "architect-prompt-reference-geometry.md",  # side brief: customer-furnished reference geometry
    "architect-prompt-inclined-bores.md",  # side brief: drawing features off the frame axes
    "architect-prompt-cad-libraries.md",  # side brief: geometry libraries and external tools
    "architect-prompt-access.md",  # older side brief: the access check's tools, paths and scenes
    "architect-prompt-gitignore.md",  # older side brief: a per-project ignore file for snapshots
    "agent-prompt-drawing-fix.md",  # an upstream fix brief for three drawing defects, with causes and tests
    "gate-v15-blockers.md",  # a gate report's blockers, grouped by obligation
    "gate-v16-blockers.md",  # the same report on the next version
)
"""The lead files that carry tool lessons. The folder's other files (unit briefs, copies of the project's
decision records, calculations) are project work and stay untracked."""
_SECTION_START = re.compile(r"^(?=## )", re.MULTILINE)
_ISSUE_HEADING = re.compile(r"## ([0-9]+)\b")
_BRIEF_ITEM = re.compile(r"([0-9]+[a-z]?)\. ")
"""A brief item starts at the margin and runs over its blank and indented lines."""
_LEDGER_ENV_OVERRIDE = "BEADS_DIR"
"""`bd` reads this before it looks for a ledger from its working directory, so `--ledger` unsets it."""


class SyncError(Exception):
    """The ledger or the log could not be read, or the new snapshot was refused."""


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
class LeadHashes:
    """SHA-256 prefixes of the lead files: per tool issue, per brief item, and per file.

    A file's hash covers its text outside the issues or items hashed on their own, so a change is reported once.
    """

    tool_issues: dict[str, str]
    brief_items: dict[str, str]
    files: dict[str, str]


def read_lead(lead_dir: Path) -> LeadHashes:
    """Hash the tracked files in ``lead_dir``; the tool-issues log must be there, a missing other one is reported."""
    log = lead_dir / TOOL_ISSUES_FILE
    if not log.is_file():
        raise SyncError(f"cannot read {log}: no such file")
    try:
        texts = {
            name: (lead_dir / name).read_text(encoding="utf-8")
            for name in TRACKED_LEAD_FILES
            if (lead_dir / name).is_file()
        }
    except OSError as error:
        raise SyncError(f"cannot read the lead files in {lead_dir}: {error}") from error
    return lead_hashes(texts)


def lead_hashes(texts: dict[str, str]) -> LeadHashes:
    """The hashes of the tracked files present in ``texts``, which maps a file name to its text."""
    issues, issue_frame = tool_issue_sections(texts.get(TOOL_ISSUES_FILE, ""))
    items, brief_frame = brief_item_sections(texts.get(BRIEF_FILE, ""))
    frames = {name: [text.strip()] for name, text in texts.items() if name in TRACKED_LEAD_FILES}
    if TOOL_ISSUES_FILE in texts:
        frames[TOOL_ISSUES_FILE] = issue_frame
    if BRIEF_FILE in texts:
        frames[BRIEF_FILE] = brief_frame
    return LeadHashes(
        tool_issues={number: _digest(parts) for number, parts in _by_number(issues)},
        brief_items={number: _digest(parts) for number, parts in _by_number(items)},
        files={name: _digest(frames[name]) for name in TRACKED_LEAD_FILES if name in frames},
    )


def tool_issue_hashes(text: str) -> dict[str, str]:
    """Per issue number, a SHA-256 prefix of its sections: each `## <number>` heading and the body under it.

    An issue gains a section per status update, and a follow-up may change only a body, so both count.
    """
    return lead_hashes({TOOL_ISSUES_FILE: text}).tool_issues


def tool_issue_sections(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """The log's sections per issue number, and the rest: its preamble and any unnumbered section."""
    sections: dict[str, list[str]] = {}
    frame: list[str] = []
    for section in _SECTION_START.split(text):
        heading = _ISSUE_HEADING.match(section)
        if heading:
            sections.setdefault(heading.group(1), []).append(section.strip())
        elif section.strip():
            frame.append(section.strip())
    return sections, frame


def brief_item_sections(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """The brief's numbered items, each with its blank and indented lines, and the rest of its text."""
    items: dict[str, list[str]] = {}
    frame: list[str] = []
    current = frame
    for line in text.splitlines():
        start = _BRIEF_ITEM.match(line)
        if start:
            current = items.setdefault(start.group(1), [])
        elif line.strip() and not line[0].isspace():
            current = frame
        current.append(line)
    return (
        {number: ["\n".join(lines).strip()] for number, lines in items.items()},
        ["\n".join(frame).strip()],
    )


def _by_number(sections: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    return sorted(sections.items(), key=lambda item: item_order(item[0]))


def _digest(parts: Iterable[str]) -> str:
    return hashlib.sha256("\n\n".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Changes:
    """Keys added, changed or gone between a snapshot's hashes and the current ones."""

    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)


def compare(known: dict[str, str], current: dict[str, str]) -> Changes:
    return Changes(
        new=[key for key in current if key not in known],
        changed=[key for key in current if key in known and known[key] != current[key]],
        gone=[key for key in known if key not in current],
    )


@dataclass
class Triage:
    new_beads: list[tuple[str, str]] = field(default_factory=list)
    changed_beads: list[tuple[str, str, str]] = field(default_factory=list)
    gone_beads: list[str] = field(default_factory=list)
    issues: Changes = field(default_factory=Changes)
    items: Changes = field(default_factory=Changes)
    files: Changes = field(default_factory=Changes)

    def lines(self) -> list[str]:
        """The report: ids, statuses, issue and item numbers and file names only."""
        out = [f"{bead} ({status}): not in the register" for bead, status in self.new_beads]
        out += [f"{bead}: {old} -> {new} since the snapshot" for bead, old, new in self.changed_beads]
        out += [f"{bead}: in the register, not in the ledger" for bead in self.gone_beads]
        out += _change_lines(self.issues, "test-project tool-issues #{}", "no longer in the log")
        out += _change_lines(self.items, BRIEF_SOURCE + " item {}", "no longer in the brief")
        out += _change_lines(self.files, "test-project lead file {}", "tracked, but not in the lead folder")
        return out


def _change_lines(changes: Changes, subject: str, gone: str) -> list[str]:
    out = [f"{subject.format(key)}: new" for key in changes.new]
    out += [f"{subject.format(key)}: its text changed" for key in changes.changed]
    return out + [f"{subject.format(key)}: {gone}" for key in changes.gone]


def triage(register: Register, ledger: dict[str, str], lead: LeadHashes) -> Triage:
    """What changed since the snapshot. A tracked file missing from the lead folder is reported on every run."""
    referenced = set(register.bead_references())
    snapshot = register.snapshot
    recorded: dict[str, str] = snapshot["statuses"]
    files = compare(snapshot.get("lead_file_hashes", {}), lead.files)
    missing = [name for name in TRACKED_LEAD_FILES if name not in lead.files]
    return Triage(
        new_beads=sorted((bead, status) for bead, status in ledger.items() if bead not in referenced),
        changed_beads=sorted(
            (bead, recorded[bead], ledger[bead])
            for bead in referenced
            if bead in ledger and bead in recorded and recorded[bead] != ledger[bead]
        ),
        gone_beads=sorted(bead for bead in referenced if bead not in ledger),
        issues=_sorted(compare(snapshot.get("tool_issue_hashes", {}), lead.tool_issues)),
        items=_sorted(compare(snapshot.get("brief_item_hashes", {}), lead.brief_items)),
        files=Changes(files.new, files.changed, missing),
    )


def _sorted(changes: Changes) -> Changes:
    return Changes(changes.new, changes.changed, sorted(changes.gone, key=item_order))


def snapshot_block(
    register: Register, ledger: dict[str, str], lead: LeadHashes, today: str
) -> dict[str, object]:
    """The new snapshot: the status of every register bead still in the ledger, and the lead files' hashes."""
    statuses = {bead: ledger[bead] for bead in sorted(set(register.bead_references())) if bead in ledger}
    return {
        "date": today,
        "statuses": statuses,
        "tool_issue_hashes": lead.tool_issues,
        "brief_item_hashes": lead.brief_items,
        "lead_file_hashes": lead.files,
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
