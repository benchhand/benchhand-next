---
title: policy.yaml
description: The project policy file and what it controls.
sidebar:
  order: 1
---

The [policy contract](/reference/contracts/record/policy/) lists its fields.

## Where it lives

A project's policy is the file `hw/policy.yaml`.
It sets how each gate asks for approval and the project's rigor level.

Without the file, every gate asks you and the rigor is `standard`.
A new project and a migrated project both start that way, until someone writes the file.

Change the gate modes with `benchhand policy get` and `benchhand policy set`.
`policy set` changes a mode and records the decision that holds the change.

## Gate modes

Each gate has one of three modes: `ask`, `chat` or `auto`.
[Gates](/concepts/process/gates/) describes what each one does.

`default` sets the mode of every gate without its own entry.
`gates` sets the mode of single gates, keyed by the gate id that `flow.yaml` declares: `intent`, `variant`, `layout_freeze`, `parts`, `detail`, `analysis`, `design_freeze` and `release`.

Any mode other than `ask` relaxes a gate, and the file must cite the decision that records the relaxation.
The schema refuses a `chat` or `auto` mode without a `decision`.
For example, this policy asks in the conversation at the LAYOUT freeze, and through the richest channel everywhere else:

```yaml
policy_version: 1
default: ask
gates:
  layout_freeze:
    mode: chat
    decision: DR-014
  parts:
    mode: ask
```

A project for development or tests can approve every gate without a human:

```yaml
policy_version: 1
default: auto
decision: DR-001
```

Because every relaxation cites a decision, the record keeps who relaxed which gate, and why.

## Rigor

`rigor` is `standard` or `regulated`.
[Rigor levels](/concepts/process/rigor/) explains what `regulated` adds.

## Project rule lists

A project can carry its own rule lists, cel-policy files in the same restricted form as the flow's.
Compile them before the server loads them:

```sh
benchhand rules compile --project .
```

The command compiles each list with benchhand's pinned CEL checker into the project's rules bundle, which sits beside the lists it covers.
When a list changes and its bundle entry is stale or missing, the server doesn't load the list, and its error names the command to run.
[Rule lists](/concepts/policy/rule-lists/) describes the format.
