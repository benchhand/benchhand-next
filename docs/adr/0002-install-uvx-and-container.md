# ADR-0002: Install through `uvx`, with an optional container

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype needed a clone, an installer, environment variables, setup, setup --yes and a warm-up.

## Decision

Each harness's MCP config runs `uvx benchhand@<ver> mcp`. `uv tool install benchhand` is optional, for pinned or offline use. An optional OCI image carries FreeCAD, both kernels and Chromium. `benchhand mcp --container` launches it through a configurable runtime (docker, podman, nerdctl, Colima), supervises it, and cleans up on every exit path.

## Consequences

There is no install step beyond the MCP entry. The container launcher has to handle several runtimes and clean up after itself (plan section 8).
