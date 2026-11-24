# ADR-0001: MCP is the only workflow interface; `benchhand` is a thin CLI

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype ran 15 skills as `uv run --script` commands that agents typed from prose. Gates, paths and environments depended on the agent copying commands correctly.

## Decision

The workflow runs only through the benchhand MCP server. The `benchhand` CLI launches and administers it: `mcp`, `serve`, `install`, `doctor`, `setup`, `policy` and `debug call`. `debug call` goes through the same code path as an MCP call. Providers may add subcommands, mounted as `benchhand <provider> <cmd>`.

## Consequences

Every harness gets the same behaviour. Scripts and CI drive the system through `debug call` or an MCP client, not through private entry points.
