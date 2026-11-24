# ADR-0010: stdio transport by default

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

stdio and localhost streamable HTTP were both options.

## Decision

stdio is the default: the harness owns the lifecycle, and no auth is needed. `benchhand mcp --http` serves on loopback for a shared server or a remote container. The preview host is a separate loopback HTTP listener in the same process.

## Consequences

HTTP mode needs a bearer token and Host checks.
