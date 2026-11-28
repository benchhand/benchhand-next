# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""``python -m issue_register check [--write]`` and ``python -m issue_register sync [--update-snapshot]``."""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from .register import OUTPUT_FILE, RegisterError, load_register
from .render import render_register
from .sync import (
    CHALLENGE_ENV,
    LEDGER_ENV,
    PROJECT_ENV,
    SOURCES_FILE,
    SyncError,
    load_sources,
    read_ledger,
    read_sources,
    snapshot_block,
    triage,
    write_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="issue_register", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate the register, its source list and its summary page")
    check.add_argument("--write", action="store_true", help=f"regenerate {OUTPUT_FILE}")
    sync = commands.add_parser(
        "sync", help=f"compare the register with the ledger and the files in {SOURCES_FILE}"
    )
    sync.add_argument(
        "--ledger",
        default=os.environ.get(LEDGER_ENV),
        help=f"the prototype checkout (default: ${LEDGER_ENV})",
    )
    sync.add_argument(
        "--project",
        default=os.environ.get(PROJECT_ENV),
        help=f"the test project's root folder, the `project` root (default: ${PROJECT_ENV})",
    )
    sync.add_argument(
        "--challenge",
        default=os.environ.get(CHALLENGE_ENV),
        help=f"the prototype challenge's handover folder, the `challenge` root (default: ${CHALLENGE_ENV})",
    )
    sync.add_argument("--sources", type=Path, help=f"the source list (default: {SOURCES_FILE})")
    sync.add_argument("--update-snapshot", action="store_true", help="record today's statuses and hashes")
    sync.add_argument(
        "--acknowledge",
        action="store_true",
        help="with --update-snapshot: everything reported has been triaged, so the snapshot may clear it",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "check":
            print(run_check(REPO_ROOT, arguments.write))
            return 0
        ledger = _required_dir(arguments.ledger, "--ledger", LEDGER_ENV, "the prototype checkout")
        roots = {
            "project": _required_dir(
                arguments.project, "--project", PROJECT_ENV, "the test project's root folder"
            ),
            "challenge": _required_dir(
                arguments.challenge, "--challenge", CHALLENGE_ENV, "the challenge's handover folder"
            ),
        }
        sources = arguments.sources or REPO_ROOT / SOURCES_FILE
        mode = "report"
        if arguments.update_snapshot:
            mode = "acknowledge" if arguments.acknowledge else "update"
        return run_sync(REPO_ROOT, ledger, roots, sources, mode)
    except RegisterError as error:
        print("issues: " + "\nissues: ".join(error.problems), file=sys.stderr)
        return 1
    except SyncError as error:
        print(f"issues-sync: {error}", file=sys.stderr)
        return 2


def _required_dir(value: str | None, option: str, env: str, what: str) -> Path:
    if not value:
        raise SyncError(f"no {what}: pass {option} or set {env}")
    return Path(value)


def run_check(repo_root: Path, write: bool) -> str:
    register = load_register(repo_root)
    try:
        sources = load_sources(repo_root / SOURCES_FILE)
    except SyncError as error:
        raise RegisterError([str(error)]) from error
    rendered = render_register(register)
    output = repo_root / OUTPUT_FILE
    if write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    elif not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        raise RegisterError([f"{OUTPUT_FILE} is out of date; run `just issues --write`"])
    beads = len(register.bead_references())
    return (
        f"issues: {len(register.issues)} issues, {len(register.design_rules)} design rules, "
        f"{beads} beads referenced once each; {len(sources)} tracked sources"
    )


def run_sync(repo_root: Path, ledger_dir: Path, roots: dict[str, Path], sources_file: Path, mode: str) -> int:
    """Report what needs triage, one line per item; exit 1 while anything does.

    ``mode`` is `report`, `update` (`--update-snapshot`) or `acknowledge` (with `--acknowledge` too). An update
    clears changed statuses and changed files, sections and items only when acknowledged: otherwise a report
    that needs triage leaves the file as it was.
    """
    register = load_register(repo_root, check_snapshot=False)
    sources = load_sources(sources_file)
    ledger = read_ledger(ledger_dir)
    found = read_sources(sources, roots)
    for tracked in found.files:
        print(f"issues-sync: tracking {tracked.label} ({tracked.split}, {len(tracked.sections)} sections)")
    lines = triage(register, ledger, found).lines()
    for line in lines:
        print(f"issues-sync: {line}")
    sections = sum(len(tracked.sections) for tracked in found.files)
    print(
        f"issues-sync: {len(ledger)} beads in the ledger; {len(found.files)} files, {sections} sections "
        f"({len(found.tool_issues)} tool issues, {len(found.brief_items)} brief items); {len(lines)} to triage"
    )
    if mode == "report":
        return 1 if lines else 0
    if lines and mode != "acknowledge":
        print("issues-sync: snapshot not updated; triage the lines above, then rerun with --acknowledge")
        return 1
    today = datetime.date.today().isoformat()
    left = triage(write_snapshot(repo_root, snapshot_block(register, ledger, found, today)), ledger, found)
    print(f"issues-sync: snapshot updated; {len(left.lines())} still to triage in the register")
    return 1 if left.lines() else 0
