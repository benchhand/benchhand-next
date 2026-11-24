# ADR-0011: Guidance comes from the server

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype's skills carried the whole process in prose, duplicated across harness formats.

## Decision

`flow.guide` returns the current stage's steps, the relevant tools, the open gates and the next action. Every result envelope carries `next_actions`. Steering shrinks to one bootstrap skill and the server `instructions`. The agent profiles keep only their role.

## Consequences

The guide content (`flow/guides/`) becomes the main prose asset and needs review like code.
