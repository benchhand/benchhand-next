---
title: Gates
description: What each gate asks of you, and the gate modes ask, chat and auto.
sidebar:
  order: 2
---

## What a gate is

A gate sits at the end of a stage and holds the project until its requirements pass.
Each requirement is a CEL expression in `flow.yaml`, such as "every fast check on the version passed" or "the previous stage's human gate is approved".

Gates guide the process; they are not a security control.
They make the guided path the easy one, and they catch honest mistakes: a skipped step, an approval nobody asked you for, or a stale version.
They don't defend against an agent that sets out to get around them.

Every gate decision is a decision record under `hw/decisions/`, with `kind: gate`, the gate, the stage and, for a built version, the version it decided on.
Decisions are append-only: a later decision supersedes an earlier one, and none is rewritten.

## The two kinds of gate

| Gate | Stage | Kind |
|---|---|---|
| INTENT | `intent` | single human |
| VARIANT | `concept` | single human |
| LAYOUT freeze | `layout` | provisional, full check, human |
| PARTS | `parts` | provisional, full check, human |
| DETAIL | `detail` | provisional, full check, human |
| ANALYSIS | `analysis` | provisional, full check, human |
| DESIGN freeze | `design_freeze` | single human |
| RELEASE | `release` | single human |

A **single human gate** presents a packet and asks you.
It records APPROVED only on your explicit approval, and only then does the project move to the next stage.

A **three-step gate** approves a built version:

1. **PROVISIONAL.** Every fast check on the version passed. The gate records a provisional decision, and the next stage can start on that version.
2. **The full check.** The full check runs on the same version. At PARTS, a light mechanical review and a light manufacturing review run beside it, and the full check counts as done only once both have returned.
3. **The human gate.** Once the full check passes and the previous stage's human gate is approved, the gate asks you. Your explicit approval records APPROVED, and the approval cites the provisional decision.

The DESIGN freeze opens only after every three-step gate has passed its human gate.
Nothing is frozen or released before that.

## At the human gate

The agent presents the gate packet: what you are approving, the renders, and the evidence for the gate.
You can approve it, name a change, or ask for a finer sweep.

- **An approval** is recorded with the channel it came through, who gave it, and your words.
- **A change you name** voids the provisional decision, and the stage reopens.
- **A finer sweep** reruns only the full check on the same version, and the gate is presented again.

A blank, declined or cancelled answer is no answer, and the gate stays open.
When the full sweep leaves between-sample intervals it couldn't prove, the approval also needs a decision on the same version that accepts them.

## PROVISIONAL, APPROVED and VOID

These are the three statuses of a gate decision:

- **PROVISIONAL**: the fast checks passed, and later stages may build on the version until its full check and human gate.
- **APPROVED**: the gate passed. An approval supersedes its provisional decision.
- **VOID**: a provisional or approved decision is withdrawn.

A gate goes VOID when its full check fails, when a light review at PARTS returns a MAJOR finding, or when you name a change at the human gate.
The agent then builds a fixed version in the same stage.

A VOID can reach later stages.
Suppose the LAYOUT full check fails on v4 while PARTS and DETAIL already run on v4.
The gate's `void_scope`, a CEL expression in `flow.yaml`, selects the later stages built on v4.
One void decision supersedes their provisional decisions, their long jobs stop, and `flow.stage` returns to `layout`.
Each reopened stage is rebuilt on the fixed version, and its human gate stays closed until its own full check passes on a version built from the fix.

A change to something an earlier gate approved doesn't reopen that stage.
[Approvals and scoped re-approval](/concepts/process/approvals/) explains what happens instead.

## Gate modes

Each gate has a mode, set in [`hw/policy.yaml`](/concepts/policy/policy-yaml/):

| Mode | How the gate asks |
|---|---|
| `ask` | The default. The gate asks you through the richest channel your host offers: the gate card where the host draws MCP Apps, otherwise the conversation. |
| `chat` | The gate asks you in the conversation. |
| `auto` | The gate approves without asking anyone. It is meant for development and tests. |

A mode other than `ask` is a relaxation, and the policy file cites the decision record that holds it.
`benchhand policy set` writes both.
Under `auto`, an approval goes through the channel `auto` and quotes nobody, and validation accepts such an approval only while the gate's mode is `auto`.

A project without `hw/policy.yaml` asks at every gate.
