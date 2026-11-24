"""The benchhand CLI. Subcommands arrive with Phase 3 (ADR-0001)."""

import typer

app = typer.Typer(no_args_is_help=True, help="benchhand: agent-guided mechanical CAD.")


@app.callback()
def main() -> None:
    """benchhand: agent-guided mechanical CAD."""


@app.command()
def version() -> None:
    """Print the benchhand version."""
    from importlib.metadata import version as v

    typer.echo(v("benchhand"))
