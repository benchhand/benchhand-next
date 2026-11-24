# ADR-0003: Gates guide the standard process; they are not a security control

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype enforced gates through prose. Agents occasionally skipped steps or approved without asking.

## Decision

The flow engine steers the agent: it refuses out-of-order transitions with a reason and the next action, and records who approved what through which channel. It doesn't defend against a malicious agent: no signatures, no tokens. A mode is set per gate in `hw/policy.yaml`: `ask` (the default), `chat` or `auto`. Every relaxation is recorded in a DR.

## Consequences

Simple, honest guarantees. Direct edits to `hw/` are reported by `validate` as findings, not prevented.
