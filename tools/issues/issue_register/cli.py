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
    LEAD_ENV,
    LEDGER_ENV,
    SyncError,
    read_lead,
    read_ledger,
    snapshot_block,
    triage,
    write_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="issue_register", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate the register and its summary page")
    check.add_argument("--write", action="store_true", help=f"regenerate {OUTPUT_FILE}")
    sync = commands.add_parser(
        "sync", help="compare the register with the ledger and the test project's lead files"
    )
    sync.add_argument(
        "--ledger",
        default=os.environ.get(LEDGER_ENV),
        help=f"the prototype checkout (default: ${LEDGER_ENV})",
    )
    sync.add_argument(
        "--lead",
        default=os.environ.get(LEAD_ENV),
        help=f"the test project's lead folder, which holds the tool-issues log (default: ${LEAD_ENV})",
    )
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
        lead = _required_dir(arguments.lead, "--lead", LEAD_ENV, "the test project's lead folder")
        return run_sync(REPO_ROOT, ledger, lead, arguments.update_snapshot, arguments.acknowledge)
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
        f"{beads} beads referenced once each"
    )


def run_sync(repo_root: Path, ledger_dir: Path, lead_dir: Path, update: bool, acknowledge: bool) -> int:
    """Report what needs triage; exit 1 while anything does.

    `--update-snapshot` clears changed statuses and changed lead files and items only with `--acknowledge`:
    without it, a report that needs triage leaves the file as it was.
    """
    register = load_register(repo_root, check_snapshot=False)
    ledger = read_ledger(ledger_dir)
    lead = read_lead(lead_dir)
    found = triage(register, ledger, lead).lines()
    for line in found:
        print(f"issues-sync: {line}")
    print(
        f"issues-sync: {len(ledger)} beads in the ledger, {len(lead.tool_issues)} tool issues, "
        f"{len(lead.brief_items)} brief items and {len(lead.files)} lead files; {len(found)} to triage"
    )
    if not update:
        return 1 if found else 0
    if found and not acknowledge:
        print("issues-sync: snapshot not updated; triage the lines above, then rerun with --acknowledge")
        return 1
    today = datetime.date.today().isoformat()
    left = triage(write_snapshot(repo_root, snapshot_block(register, ledger, lead, today)), ledger, lead)
    print(f"issues-sync: snapshot updated; {len(left.lines())} still to triage in the register")
    return 1 if left.lines() else 0
