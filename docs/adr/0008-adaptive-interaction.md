# ADR-0008: Interaction adapts to client capabilities

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Hosts differ: Claude Desktop renders Apps but has no elicitation, Claude Code is the reverse, and Pi has neither.

## Decision

An interaction layer picks the best channel for each interaction, with a fallback chain whose last entry always works (plan section 11). URL-mode elicitation is not used.

## Consequences

The fallbacks are tested against mock client profiles.
