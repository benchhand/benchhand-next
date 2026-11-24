# ADR-0004: The MCP server process is the runner

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype ran the concept server, the viewer host and the render driver as separate long-lived processes, each with its own lifecycle.

## Decision

The harness starts the MCP server from its config, and that process hosts the preview pages on loopback HTTP and supervises the providers and jobs. It lives as long as the harness session. `benchhand serve` runs the same preview host without an agent.

## Consequences

No daemon to manage. A slow first start is accepted next to how long CAD jobs take.
