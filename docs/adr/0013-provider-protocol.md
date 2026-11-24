# ADR-0013: The provider protocol is JSON-RPC 2.0 over stdio, after slopvac 3.0

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Providers need isolation: CadQuery and build123d pin incompatible OCP versions, and FreeCAD has its own Python.

## Decision

Providers are subprocesses that speak JSON-RPC 2.0 with LSP framing, version and feature negotiation, and timeouts owned by the host, as in slopvac 3.0. benchhand adds `$/progress`, `$/log`, artifacts and resident providers, and drops slopvac's trust step. See `docs/contract/provider-protocol.md`.

## Consequences

Every provider runs in its own environment, and crashes stay contained.
