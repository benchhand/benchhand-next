# ADR-0017: Contracts are generated from one source and enforced

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype's schemas, CLI outputs and prose drifted apart.

## Decision

JSON Schema 2020-12 under `contracts/` is the only source. Python models, TypeScript types, MCP tool schemas, CEL type declarations and reference docs are generated from it. CI fails on drift and on a breaking change without a major version bump. Every boundary validates at runtime, in both directions.

## Consequences

Hand-written copies of message shapes are not allowed.
