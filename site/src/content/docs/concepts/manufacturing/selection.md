---
title: Selection
description: How a process and a supplier are chosen for each part.
sidebar:
  order: 3
---

The [selection contract](/reference/contracts/record/manufacturing-selection/) lists its fields.

## What selection records

`hw/manufacturing/selection.yaml` compares whole candidate routes, side by side, and records the recommendation.
A candidate is a complete answer, not one choice at a time:

- its architecture;
- each part, with its material profile and its complete route, including the capability profile of each step;
- an evaluation of every mandatory requirement, each with its outcome, method and source;
- the changes it brings to the design, equipment, finishing, inspection, interfaces and assembly;
- its cost and lead time at a stated quantity, its maintenance, and how confident its evidence is;
- the validation still outstanding;
- its pros, cons and tradeoffs, and a score for each preference.

A candidate can bring a part the record doesn't hold yet, marked as proposed.
A proposed part gets no check obligations, and it becomes a part only when an approved change creates its `part.yaml`.
A bought step can carry the purchase criteria of the item, so a bought alternative to a made part can be assessed before any part record exists.

## How candidates are ranked

- A mandatory requirement that a candidate fails eliminates it.
- A mandatory requirement whose outcome is unknown keeps the candidate conditional.
- Preferences rank only the candidates that are still feasible.

The recommendation names the primary candidate, and it can name a prototype route, an end-use route and a fallback.
It gives its reasons, its limits, what the prototype route can and can't validate, and what would change it.
A recommendation is `conditional` while inputs that matter to the choice, or to safety, are missing, and `final` otherwise.

The selection has three states: `not_assessed`, `assessed` and `confirmed`.
A confirmed selection has a final recommendation and cites the decision that confirms it.

## When a selection changes

The selection is a comparison, and the product records stay as they are when it changes.
A confirmed choice reaches the parts, the routes and the materials through an approved change to those records.

The assessment records a digest of the record inputs it read.
When those inputs change, the current digest differs, and the assessment is stale until it is assessed again.

Once a change reaches the record, it follows the rules for any other change:

- An approved item that changes, such as a part or a joint choice, is marked `changed_since_approval`, and the next human gate confirms it. [Approvals and scoped re-approval](/concepts/process/approvals/) explains this.
- Evidence that relied on the old material, process, route or capability has a changed fingerprint, so it is stale until an impact assessment carries it forward.

## Standard parts

A standard part, such as an ISO or DIN fastener, is identified by its designation and edition, and it needs no paywalled standard.
The agent takes its dimensions from a standard library, in this order:

1. the `bd_warehouse` data tables, recording the package version and the table row;
2. the FreeCAD Fasteners workbench, run out of process as a generator, recording its version, the table and row, and the hash of the generated STEP;
3. open tables, such as the Onshape hole tables and BOSL2;
4. a supplier datasheet for that exact designation, frozen with its reference, date, SHA-256 and URL.

The library row is the basis for the part's dimensions.
When no source covers the designation, a named finding records the search, and it doesn't block.
A part with no supplier chosen stays open as a sourcing decision.
A part with nothing to freeze, such as a customer envelope without a datasheet, has its specification recorded as `not_applicable` with the reason, and its gate can still pass.
