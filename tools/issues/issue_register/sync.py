# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Compare the register with the prototype's live ledger and the test project's tool-issues log.

Local only: CI has neither. It reads, and writes nothing unless asked to update the snapshot. What it
writes is bead ids, statuses, a date and per-issue hashes: never ledger or test-project text.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .register import REGISTER_FILE, SNAPSHOT_KEY, Register, register_from_text

LEDGER_ENV = "BENCHHAND_PROTOTYPE_LEDGER"
LEAD_ENV = "BENCHHAND_TEST_PROJECT_LEAD"
TOOL_ISSUES_FILE = "tool-issues.md"
_SECTION_START = re.compile(r"^(?=## )", re.MULTILINE)
_ISSUE_HEADING = re.compile(r"## ([0-9]+)\b")


class SyncError(Exception):
    """The ledger or the log could not be read, or the new snapshot was refused."""


def read_ledger(ledger_dir: Path) -> dict[str, str]:
    """Every bead in the ledger at ``ledger_dir`` with its status, from ``bd list --all --json``."""
    try:
        listed = subprocess.run(
            ["bd", "list", "--all", "--json"], cwd=ledger_dir, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SyncError(f"`bd list --all --json` failed in {ledger_dir}: {error}") from error
    return ledger_statuses(json.loads(listed.stdout))


def ledger_statuses(beads: list[dict[str, object]]) -> dict[str, str]:
    return {str(bead["id"]): str(bead["status"]) for bead in beads}


def read_tool_issue_hashes(lead_dir: Path) -> dict[str, str]:
    log = lead_dir / TOOL_ISSUES_FILE
    try:
        return tool_issue_hashes(log.read_text(encoding="utf-8"))
    except OSError as error:
        raise SyncError(f"cannot read {log}: {error}") from error


def tool_issue_hashes(text: str) -> dict[str, str]:
    """Per issue number, a SHA-256 prefix of its sections: each `## <number>` heading and the body under it.

    An issue gains a section per status update, and a follow-up may change only a body, so both count.
    """
    sections: dict[str, list[str]] = {}
    for section in _SECTION_START.split(text):
        heading = _ISSUE_HEADING.match(section)
        if heading:
            sections.setdefault(heading.group(1), []).append(section.strip())
    return {
        number: hashlib.sha256("\n\n".join(parts).encode("utf-8")).hexdigest()[:16]
        for number, parts in sorted(sections.items(), key=lambda item: int(item[0]))
    }


@dataclass
class Triage:
    new_beads: list[tuple[str, str]] = field(default_factory=list)
    changed_beads: list[tuple[str, str, str]] = field(default_factory=list)
    gone_beads: list[str] = field(default_factory=list)
    new_issues: list[str] = field(default_factory=list)
    changed_issues: list[str] = field(default_factory=list)
    gone_issues: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        """The report: ids, statuses and issue numbers only."""
        out = [f"{bead} ({status}): not in the register" for bead, status in self.new_beads]
        out += [f"{bead}: {old} -> {new} since the snapshot" for bead, old, new in self.changed_beads]
        out += [f"{bead}: in the register, not in the ledger" for bead in self.gone_beads]
        out += [f"test-project tool-issues #{number}: new" for number in self.new_issues]
        out += [f"test-project tool-issues #{number}: its text changed" for number in self.changed_issues]
        out += [f"test-project tool-issues #{number}: no longer in the log" for number in self.gone_issues]
        return out


def triage(register: Register, ledger: dict[str, str], hashes: dict[str, str]) -> Triage:
    referenced = set(register.bead_references())
    recorded: dict[str, str] = register.snapshot["statuses"]
    known: dict[str, str] = register.snapshot.get("tool_issue_hashes", {})
    return Triage(
        new_beads=sorted((bead, status) for bead, status in ledger.items() if bead not in referenced),
        changed_beads=sorted(
            (bead, recorded[bead], ledger[bead])
            for bead in referenced
            if bead in ledger and bead in recorded and recorded[bead] != ledger[bead]
        ),
        gone_beads=sorted(bead for bead in referenced if bead not in ledger),
        new_issues=[number for number in hashes if number not in known],
        changed_issues=[number for number in hashes if number in known and known[number] != hashes[number]],
        gone_issues=sorted((number for number in known if number not in hashes), key=int),
    )


def snapshot_block(
    register: Register, ledger: dict[str, str], hashes: dict[str, str], today: str
) -> dict[str, object]:
    """The new snapshot: the status of every register bead still in the ledger, and the per-issue hashes."""
    statuses = {bead: ledger[bead] for bead in sorted(set(register.bead_references())) if bead in ledger}
    return {"date": today, "statuses": statuses, "tool_issue_hashes": hashes}


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
