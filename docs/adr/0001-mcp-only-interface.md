# ADR-0001: MCP is the only workflow interface; `benchhand` is a thin CLI

Status: accepted; amended 2026-11-27 (read-only subcommands). Source: [the approved plan](../design-plan.md).

## Context

The prototype ran 15 skills as `uv run --script` commands that agents typed from prose. Gates, paths and environments depended on the agent copying commands correctly.

## Decision

The workflow runs only through the benchhand MCP server. The `benchhand` CLI launches and administers it: `mcp`, `serve`, `install`, `doctor`, `setup`, `policy` and `debug call`. `debug call` goes through the same code path as an MCP call. Providers may add subcommands, mounted as `benchhand <provider> <cmd>`.

## Consequences

Every harness gets the same behaviour. Scripts and CI drive the system through `debug call` or an MCP client, not through private entry points.

## Amendment, 2026-11-27

The owner decided D-28 of the CAD-libraries study ([decision record](../design/cad-libraries-2026-11-27.md)). The CLI also gets read-only subcommands over the same core as the MCP tools, such as `benchhand docset` and `benchhand inspect`.

- They only read. Every write stays on an MCP tool or `debug call`, so the workflow and its gates still run only through the server.
- A host whose model can't see MCP tools can still inspect a project.
- The list of read-only subcommands is chosen in the CLI spec. Each one is generated from its tool's contract, so the two surfaces can't drift.
