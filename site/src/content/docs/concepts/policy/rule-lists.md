---
title: Rule lists
description: Ordered CEL rule lists, the kinds that use them, and how they are combined.
sidebar:
  order: 2
---

The [flow contract](/reference/contracts/flow/) defines the rule-list format and its kinds.

## What a rule list is

A rule list is a decision table written in CEL.
Each list is a file of its own, `<name>.celpolicy`, in the [cel-policy](https://github.com/cel-expr/cel-policy) format.
benchhand accepts a restricted form of it:

- The file has a `name` and a `rule`, and the `rule` has one `match` block of choices.
- Each choice has an `output`, and every choice but the last has a `condition`. Both are CEL expressions.
- The last choice has no condition, so every list gives a value.
- The first choice whose condition holds gives its output.
- A choice may have an `explanation`, a CEL expression that gives a string, such as the text of a finding. Every choice of a list has one, or none does.
- The form has no `variables`, no `aggregate`, no nested `rule` and no `imports`.

For example, a list of the checks to run, where the checks of a commit in the PARTS and DETAIL stages are the form check and the changed-only static check:

```yaml
name: example.checks_by_iteration
rule:
  match:
    - condition: 'stage in ["parts", "detail"] && iteration == "commit"'
      output: '["form_check", "check_changed_only"]'
    - output: "[]"
```

A check that runs only under its own condition is added with a CEL ternary, such as `cond ? ["id"] : []`.

## The kinds

`flow.yaml` names one list of each kind, and the kind sets the type of every output:

| Kind | Output | Last choice of the flow's list |
|---|---|---|
| `checks_by_iteration` | the check ids to run, in fail-fast order | `[]`, no checks |
| `dispatch` | the handler of a process check, or `"unknown"` | `"unknown"`: UNKNOWN coverage, never a pass |
| `fidelity` | the form-check fidelity of a stage, `"F0"` to `"F3"` | `"F0"` |
| `rigor` | the messages of the requirements the record doesn't meet under the project's rigor level | `[]`, no unmet requirement |

A dispatch handler is named by the check family it judges, such as `process.fdm.orientation`, and dispatch picks one for each process, operation and material.
A result outside a kind's values, such as a fidelity of `"F4"` or a handler that doesn't exist, is recorded as UNKNOWN, with a finding that names the value, never as a pass.

## Compiled before load

Rule lists are compiled before the server loads them.
benchhand's own lists ship compiled, and a project's or a policy provider's lists are compiled with `benchhand rules compile`.

The compiler checks each list against the types of the record, so a wrong field name or a wrong type fails at compile time.
It refuses a list whose last choice has a condition, a feature outside the restricted form, an output of the wrong type for its kind, and an explanation that isn't a string.
The server loads each list from its compiled bundle, and refuses a missing or stale entry with the command to run.

## Lists from policy providers

A policy provider can add rule lists of each kind, and requirements for the steps of a gate, without code.
Its lists combine with the flow's own like this:

1. benchhand evaluates the lists of one kind in order: the providers' lists in ascending order of provider name, then the flow's list.
2. For `checks_by_iteration`, `dispatch` and `fidelity`, a list that gives its kind's no-match value passes to the next list: `[]`, `"unknown"` and `"none"`. A provider's list ends in that value, so it only answers when one of its conditions holds. The first other value is the result. When no provider's list answers, the flow's list, evaluated last, gives the result, and its value stands even when it is the no-match value.
3. For `rigor`, every list is evaluated, and the result is the union of their messages, each message once. Rigor holds only when the union is empty, so a provider can add requirements and never remove one.
4. A gate's requirements from a provider hold as well as the requirements in `flow.yaml`. The flow's are checked first, then each provider's in the same order.

When the flow loads, benchhand refuses a provider's requirement for a gate that `flow.yaml` doesn't declare, or for a step the gate doesn't have.
The [policy contract](/reference/contracts/policy/) states the merge in full.
