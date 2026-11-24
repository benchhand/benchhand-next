# ADR-0014: The flow is data, the rules are CEL

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Gate rules and check tables lived in prose.

## Decision

`flow.yaml` holds the stage and gate graph as data. Every condition is a CEL expression: guards, gate requirements, VOID scope, and ordered first-match rule lists for check selection, dispatch, fidelity and rigor. GoRules ZEN was rejected, because it duplicates CEL. React Flow renders the state.

## Consequences

One rules language. CEL is compiled and type-checked at load, against types generated from the contracts.
