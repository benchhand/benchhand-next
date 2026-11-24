# ADR-0007: A high-level build API around agent-written part scripts

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

Agents wrote glue code for exports, renders, drawings, previews and record edits.

## Decision

The agent writes `model.py` for geometry. Tools do the rest:

- output: STEP, GLB, STL and 3MF, renders, drawings, BOM and motion renders;
- the part SDK and parametric generators;
- inspection and draft preview;
- concept scene edits, viewer control and preview hosting;
- typed record operations and engineering calculators;
- a layout skeleton that records every inferred value as a bounded assumption.

## Consequences

The tool surface is large, so the guide service (ADR-0011) has to tell the agent which tools matter at each stage.
