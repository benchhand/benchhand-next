---
title: Approvals and scoped re-approval
description: What an approval covers, and what happens when an approved item changes.
sidebar:
  order: 4
---

## What an approval records

An approval at a human gate is a gate decision under `hw/decisions/`, with status `approved`.
It records:

- the channel it came through: `app` for the gate card, `chat` for the conversation, or `auto` for a gate in mode `auto`;
- who approved, and their words, for every channel but `auto`;
- the provisional decision it follows, at a three-step gate;
- its scope: the items it approved, such as the concept, the envelope, the interfaces, the parts and the joint choices.

Each item in the scope has its kind, its id and its fingerprint at approval time.
The fingerprint is computed the same way as the fingerprints of the inputs that evidence depends on.

## When an approved item changes

Later work can change something an earlier gate approved.
A DETAIL change can move a LAYOUT interface, or a joint can go from a heat-set insert to a press fit.

When an approved item's fingerprint differs from the one in its approval, that item is `changed_since_approval`.
Only that item is affected:

- the stage, and `flow.stage`, stay where they are;
- the other approved items, and their evidence, stay valid;
- a CEL expression in `flow.yaml`, `reapproval_scope`, selects the approved items that a change affects.

The next human gate confirms the change.
Its packet has a section of the items changed since approval, each with a diff against what you approved.
Approving the gate re-approves those items, and the new decision cites the original one.
A stage freezes or releases only after you have confirmed every changed item.

A new item is not a change to an approval.
A new part, joint or interface goes through the current stage's checks, and it appears at the next gate as an addition.
No earlier stage reopens for it.

## Migrated decisions

A decision migrated from a prototype record has no scope: the prototype didn't record which items an approval covered.
Such a decision doesn't count as covering the whole stage.
The next human gate confirms it.

## VOID and engineering change

Two cases reopen work instead of marking items.

A change you name at a stage's own human gate voids that gate's provisional decision.
The stage reopens, together with the later stages built on that version, as [Gates](/concepts/process/gates/) describes.

After the DESIGN freeze, a change is an engineering change:

1. An approved decision opens the change. `flow.change` in `hw/product.yaml` records that decision, the frozen version it starts from, and the affected parts.
2. The affected parts and the parts that depend on them go back through DETAIL, with its three-step gate. Unaffected parts keep their evidence.
3. Only the affected analysis cases run again, through ANALYSIS and its gate.
4. A new version is frozen, with a new freeze record, and goes to the RELEASE gate.

[Versions and the freeze](/concepts/record/versions-and-freeze/) explains what the freeze records.
