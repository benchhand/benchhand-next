# ADR-0006: Every integration is a provider

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Kernels, FreeCAD, solvers, renderers, checks and storage were hard-wired into skills.

## Decision

Each sits behind a provider interface from 1.0. Kernels, process checks and policy get full docs and conformance kits first. The rest are experimental until stabilised.

## Consequences

Integrations can be swapped and added without touching the core.
