# ADR-0014: The flow is data, the rules are CEL

Status: accepted; superseded in part by [ADR-0020](0020-cel-rule-pipeline.md) (2026-11-27). Source: [the approved plan](../design-plan.md).

Superseded parts:

- **Rule lists** are cel-policy files compiled before load by a pinned cel-go tool, not CEL compiled and type-checked at load. The host loads them from a rules bundle and refuses a missing or stale entry.
- **"Types generated from the contracts"** are a FileDescriptorSet and an environment profile manifest per structural rule scope.

The rest stands. In particular, standalone expressions (guards, gate requirements, VOID scope) are still compiled and type-checked at load.

## Context

Gate rules and check tables lived in prose.

## Decision

`flow.yaml` holds the stage and gate graph as data. Every condition is a CEL expression: guards, gate requirements, VOID scope, and ordered first-match rule lists for check selection, dispatch, fidelity and rigor. GoRules ZEN was rejected, because it duplicates CEL. React Flow renders the state.

## Consequences

One rules language. CEL is compiled and type-checked at load, against types generated from the contracts.
