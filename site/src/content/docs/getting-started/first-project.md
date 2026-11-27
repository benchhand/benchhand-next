---
title: A first project
description: Start a benchhand project, see how the server guides the agent, and look at the record it writes.
sidebar:
  order: 2
---

A benchhand project is a directory with a design record under `hw/`.
You describe what you want to your agent, and the benchhand server returns the steps of each stage to the agent.

## Start a project

Open your agent host in the directory where the project lives, and ask the agent to start a design, for example:

> Start a benchhand project for a wall bracket that holds a 2 kg shelf.

The server works on the directory the host starts it in, or the one that `benchhand mcp --project DIR` names.
Claude Desktop starts servers without a directory, so there the agent opens the project with `project.open`.

The agent learns which tools to call from the server.
The server's MCP instructions and the bootstrap skill that `benchhand install` wrote say the same thing:

> This project uses benchhand. Call `flow.guide` before starting and whenever unsure; follow its next action; ask the user at gates as instructed.

## Ask the server for guidance

`flow.guide` carries the process.
It takes an optional role and unit, and returns:

- the current stage and its goal;
- the steps for that stage and role;
- the tools that matter at that stage, each with a short note on why and when to use it;
- the open gates, and what each one needs;
- the next action.

Every other benchhand tool returns the same result envelope, and each envelope lists `next_actions`: the calls that make sense next, most useful first.
An entry with `needs_user` set waits for you, such as an approval at a gate.
So after the first call, the agent rarely needs to ask for the guide again.

The tool descriptions say only what a tool does and what it needs first.
The guide says when to use it.

When the agent hands work to a subagent, such as a part designer or a reviewer, the subagent calls `flow.guide` with its own role and gets that role's steps.
The same guide text is also published as MCP prompts and as `guide://stage/<stage>` resources, for hosts that use those.

A call that is out of order is refused.
The envelope says why, and its `next_actions` names what comes first.

## Answer the first questions

The first stages are GROUND, INTENT and SPECIFY.
In them the agent asks you what the product is for, who uses it and what it must do, and records each answer through the `record.*` tools.

Where the host shows MCP Apps, the questions come as a form.
Everywhere else the agent asks them in chat.

The INTENT gate sits between INTENT and SPECIFY.
The agent shows you what it recorded about the product's intent and asks you to approve it, and SPECIFY starts only after you do.
A blank or declined answer counts as no answer, and the gate stays open.
[Gates](/concepts/process/gates/) explains how gates ask, and [The design process](/concepts/process/overview/) lists every stage.

## Look at the record

The record is plain files under `hw/`, each with its own contract:

| File | What it holds |
|---|---|
| [`hw/product.yaml`](/reference/contracts/record/product/) | the product's identity, units, drawing regime and general tolerance, its use case, and `flow.stage`, the stage the project is at |
| [`hw/requirements.yaml`](/reference/contracts/record/requirements/) | the requirements, preferences, assumptions and open questions, each kept in its own list |
| [`hw/policy.yaml`](/reference/contracts/record/policy/) | how each gate asks for approval; without the file, every gate asks you |
| [`hw/decisions/DR-###-<slug>.md`](/reference/contracts/record/decision/) | one decision record per gate decision or design decision |

A new project starts with `flow.stage` at `ground`.
A fact you haven't given isn't guessed: it is recorded as unknown, with a reason and the open question that asks for it.
For example, this excerpt of `hw/product.yaml` is from before you describe the use case:

```yaml
flow:
  stage: ground
  recheck_from: ground
use_case:
  status: unknown
  purpose:
    status: unknown
    reason: not recorded yet
    question: Q-002
```

A mandatory requirement is never turned into a preference or an assumption to get past a check.

The flow engine writes `flow.stage` and the gate decisions, so the agent doesn't edit them by hand.
benchhand doesn't stop direct edits to `hw/`, but its validation reports them as findings.

To browse the project without an agent, run:

```sh
benchhand serve --project . --open
```

It opens the preview host, with the viewer, the flow view and the gallery.
[The record layout](/concepts/record/layout/) describes every file under `hw/`.

Next: [A first part](/getting-started/first-part/).
