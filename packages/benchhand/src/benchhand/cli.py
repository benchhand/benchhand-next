"""The benchhand CLI. Most subcommands arrive with Phase 3 (ADR-0001)."""

from pathlib import Path
from typing import Annotated

import typer

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
    hw: Annotated[Path, typer.Argument(help="The project's hw/ directory.")],
    apply: Annotated[bool, typer.Option("--apply", help="Write the changes; else print them.")] = False,
    backup: Annotated[
        bool, typer.Option("--backup", help="With --apply: copy hw/ to .benchhand/backups/ first.")
    ] = False,
) -> None:
    """Migrate a prototype record (record_version 2) to record version 3. A dry run unless --apply, which
    needs hw/ clean in git or --backup. Stop every other process that writes under hw/ first."""
    from benchhand_core.record.migrate import MigrationStatus, migrate

    hw = hw.absolute()
    if hw.name != "hw":
        typer.echo(f"{hw}: expected the project's hw/ directory", err=True)
        raise typer.Exit(2)
    result = migrate(hw.parent, apply=apply, backup=backup)
    for change in result.changes:
        typer.echo(f"# {change.path}: {', '.join(change.rules)}")
        if not apply:
            typer.echo(change.diff(), nl=False)
    for finding in (*result.findings, *result.remaining):
        where = f"{finding.path}{'#' + finding.pointer if finding.pointer else ''}"
        typer.echo(f"{finding.severity.value} {finding.code} {where}: {finding.message}")
        if finding.action:
            typer.echo(f"  fix: {finding.action}")
    if result.recovery is not None:
        typer.echo(f"to undo: {result.recovery}")
    shown = f"{len(result.written)} of {len(result.changes)}" if apply else str(len(result.changes))
    typer.echo(f"{result.status.value}: {shown} files")
    if result.status in (MigrationStatus.refused, MigrationStatus.failed):
        raise typer.Exit(1)
