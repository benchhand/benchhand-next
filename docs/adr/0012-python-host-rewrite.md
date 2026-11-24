# ADR-0012: Python host and core, TypeScript UIs, rewrite rather than port

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Greenfield language choice. The CAD kernels and FreeCAD are Python-only.

## Decision

The host and core are Python, the browser UIs are TypeScript, and Rust is not used. The prototype is a behavioural reference and test oracle. Code is kept only where it is already clean and fits the new boundaries.

## Consequences

One runtime on users' machines. TypeScript stays possible for the host later, because the contracts are language-neutral.
