# ADR-0008: Interaction adapts to client capabilities

Status: accepted, narrowed by [ADR-0018](0018-baseline-and-no-forms.md): plain tool calls are the baseline, and form elicitation is not used in v1. Source: [the approved plan](../design-plan.md).

## Context

Hosts differ: Claude Desktop renders Apps but has no elicitation, Claude Code is the reverse, and Pi has neither.

## Decision

An interaction layer picks the best channel for each interaction, with a fallback chain whose last entry always works (plan section 11). URL-mode elicitation is not used.

## Consequences

The fallbacks are tested against mock client profiles.
