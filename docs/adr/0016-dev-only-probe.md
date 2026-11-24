# ADR-0016: The capability probe is dev-only

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Client capabilities have to be measured in real hosts.

## Decision

`tools/probe/` is a throwaway MCP server that a developer registers by hand in each host. Its results are committed to `docs/client-support.md`. It isn't shipped and isn't run in CI.

## Consequences

The results go stale and are rechecked before each release.
