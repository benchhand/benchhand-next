# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The benchhand CLI. Most subcommands arrive with Phase 3 (ADR-0001)."""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from benchhand_core.record.migrate import Migration

app = typer.Typer(no_args_is_help=True, help="benchhand: agent-guided mechanical CAD.")
record = typer.Typer(no_args_is_help=True, help="Work on a project's hw/ record.")
app.add_typer(record, name="record")


@app.callback()
def main() -> None:
    """benchhand: agent-guided mechanical CAD."""


@app.command()
def version() -> None:
    """Print the benchhand version."""
    from importlib.metadata import version as v

    typer.echo(v("benchhand"))


@record.command("migrate")
def record_migrate(
    hw: Annotated[Path | None, typer.Argument(help="The project's hw/ directory.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Write the changes; else print them.")] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="With --apply: finish a stopped apply from its backup.")
    ] = False,
    undo: Annotated[
        Path | None,
        typer.Option("--undo", help="Put back the files an apply changed, from BACKUP.", metavar="BACKUP"),
    ] = None,
) -> None:
    """Migrate a prototype record (record_version 2) to record version 3. A dry run unless --apply, which
    first backs up the files it changes to .benchhand/migrate-backups/. Stop every other process that writes
    under hw/ first."""
    from benchhand_core.record.migrate import migrate
    from benchhand_core.record.migrate import undo as undo_migration

    if undo is not None:
        if hw is not None or apply or resume:
            typer.echo("--undo BACKUP takes no HW, --apply or --resume", err=True)
            raise typer.Exit(2)
        _print_migration(undo_migration(undo), diffs=False, undoing=True)
        return
    if hw is None or hw.absolute().name != "hw" or (resume and not apply):
        typer.echo(f"{hw}: expected the project's hw/ directory (--resume needs --apply)", err=True)
        raise typer.Exit(2)
    result = migrate(hw.absolute().parent, apply=apply, resume=resume)
    _print_migration(result, diffs=not apply, undoing=False)


def _print_migration(result: "Migration", *, diffs: bool, undoing: bool) -> None:
    """Print a Migration: the changes (with diffs on a dry run), the findings, and the counts; exit 1 on a
    refusal or a failure."""
    from benchhand_core.record.migrate import MigrationStatus

    for change in result.changes:
        typer.echo(f"# {change.path}: {', '.join(change.rules)}")
        if diffs:
            typer.echo(change.diff(), nl=False)
    for finding in (*result.findings, *result.remaining):
        where = f"{finding.path}{'#' + finding.pointer if finding.pointer else ''}"
        typer.echo(f"{finding.severity.value} {finding.code} {where}: {finding.message}")
        if finding.action:
            typer.echo(f"  fix: {finding.action}")
    if result.recovery is not None and not undoing:
        typer.echo(f"to undo: {result.recovery}")
    if undoing:
        shown = str(len(result.written))
    elif diffs:
        shown = str(len(result.changes))
    else:
        shown = f"{len(result.written)} of {len(result.changes)}"
    typer.echo(f"{result.status.value}: {shown} files")
    if result.status in (MigrationStatus.refused, MigrationStatus.failed) or result.refusals:
        raise typer.Exit(1)
