---
title: The design process
description: The stages of a benchhand project, from requirements to release.
sidebar:
  order: 1
---

A benchhand project moves through a fixed sequence of stages, from the first questions about the product to a released design.
Gates sit between some of the stages, and each gate holds the project until its requirements are met.
The stages, the gates and the transitions between them are data in `flow.yaml`, so the server can read, validate and draw the process.

## The stages

The stage a project is at is `flow.stage` in [`hw/product.yaml`](/reference/contracts/record/product/).
The stages come in this order:

| Stage | What happens | Gate at the end |
|---|---|---|
| `ground` | The agent asks you about the product and its use, and records your answers. | none |
| `intent` | The agent records what the product is for, and how you settled each project-start question. | INTENT |
| `specify` | The agent writes the requirements, preferences, assumptions and open questions in `hw/requirements.yaml`. | none |
| `concept` | The agent builds concept variants as scenes for you to compare. | VARIANT |
| `layout` | A layout skeleton, drafted from the chosen concept, fixes the envelope and the interfaces. | LAYOUT freeze |
| `parts` | The agent models each part in `model.py` and builds the design as a version. | PARTS |
| `detail` | The parts get their fits, drawings and assembly steps. | DETAIL |
| `bom` | The bill of materials is written to `hw/bom.csv`. | none |
| `analysis` | The analysis cases run, such as a static FEA. | ANALYSIS |
| `critique` | The mechanical and manufacturing reviewers review the analysed version. | none |
| `reconcile` | The last stage of work before the freeze. | none |
| `design_freeze` | You approve one built version as the frozen configuration. | DESIGN freeze |
| `release` | The frozen version is packaged as a release. | RELEASE |

In `ground`, `intent` and `specify` the agent mostly asks you questions.
From `layout` on, the agent builds versions of the design, and checks run against each version.
At the end, the record holds a frozen version, its evidence and a release under `hw/releases/<REV>/`.

The gates and what each one asks are on [Gates](/concepts/process/gates/).

## How the server steers the agent

The agent doesn't need a list of which tool to call when.
It calls `flow.guide`, which returns:

- the current stage and its goal;
- the steps for that stage and for the agent's role;
- the tools that matter at that stage, with a short note on why and when to use each;
- the open gates, and what each one needs;
- the next action.

Every other tool's result envelope lists `next_actions`, the calls that make sense next, so the agent rarely needs the guide twice in a row.
A subagent, such as a part designer or a reviewer, calls `flow.guide` with its own role and gets that role's steps.
[A first project](/getting-started/first-project/) shows the guide at the start of a project.

## Moving between stages

Each transition in `flow.yaml` is an edge, and an edge can pass through a gate.
Every condition on an edge or a gate is a CEL expression, and the server checks all of them when it loads `flow.yaml`, so a typo fails at start and not halfway through a project.

The flow engine moves `flow.stage` and writes the gate decisions under `hw/decisions/`.
A call that is out of order, such as one that would skip a gate, is refused.
The result says why, and its `next_actions` names what has to come first.

The process guides the agent; it doesn't police it.
The server doesn't sign decisions or stop direct edits to `hw/`.
It catches honest mistakes, such as a skipped step, an approval nobody asked you for, or a check on a stale version.
Validation reports a direct edit to the record as a finding.

The preview host's flow view draws `flow.yaml` with the project's live state: the current stage, the open gates, the provisional and void history, and the evidence for each gate.
