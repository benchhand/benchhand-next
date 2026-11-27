---
title: Writing CEL rules
description: Write a rule list, and compile it with benchhand rules compile.
sidebar:
  order: 2
---

A rule list decides one thing for the flow, such as which checks to run or which handler judges a process check.
A project can carry its own lists, and so can a policy provider.
[Rule lists](/concepts/policy/rule-lists/) explains the format, the four kinds and how lists combine.

## Pick the kind

The kind sets the type of every output in the list:

| Kind | Each output | No-match value |
|---|---|---|
| `checks_by_iteration` | a list of check ids, in run order | `[]` |
| `dispatch` | a handler id, a string | `"unknown"` |
| `fidelity` | `"F0"` to `"F3"` | `"none"` |
| `rigor` | a list of messages, one for each requirement the record doesn't meet | none: `[]` means no unmet requirement |

Every list ends with a choice that has no condition, and its output has the kind's type too.
A policy provider's list ends in its kind's no-match value, so it answers only when one of its own conditions holds, and otherwise passes to the next list.
A rigor list can only add requirements: every rigor list is evaluated, and their messages add up.

## What a rule can read

Every rule is checked against a scope: the variables it can read.
Every variable points at a node of a published contract, so its fields and their types are the ones in the [contracts reference](/reference/contracts/).
A scope may leave fields out, and a rule that reads a field the scope leaves out fails the compile.

The contract's JSON types map to CEL types like this:

| In the contract | In CEL |
|---|---|
| `string`, `integer`, `number`, `boolean` | `string`, `int`, `double`, `bool` |
| an object with fixed properties | a message, whose fields you select with `.` |
| an object of named entries | `map(string, V)` |
| an array | `list(T)` |
| an enum of strings | `string` |

No field is typed `dyn`, so a wrong field name or a wrong operand type fails the compile instead of failing later.

## Write the list

A list is a file of its own, `<name>.celpolicy`.
This one runs the form check and the changed-only static check on a commit in the PARTS and DETAIL stages:

```yaml
name: project.checks_by_iteration
rule:
  match:
    - condition: 'stage in ["parts", "detail"] && iteration == "commit"'
      output: '["form_check", "check_changed_only"]'
    - output: "[]"
```

Keep to these rules:

- The file has a `name` and a `rule`, and the `rule` has one `match` block.
- Every choice has an `output`. Every choice but the last has a `condition`, and the last has none.
- Conditions are tried in order, and the first that holds gives its output. Put the narrow cases first.
- Every output has the kind's type, the last one included.
- The list has no `variables`, `aggregate`, nested `rule` or `imports`. A sub-expression that several conditions share is written out in each.

A check that runs only under its own condition goes into the output as a ternary:

```yaml
    - condition: 'iteration == "commit"'
      output: '["validate", "build"] + (stage == "detail" ? ["fits.stackup"] : [])'
```

### Explain the choices

A choice may carry an `explanation`, a CEL expression that gives a string, such as the text of a finding:

```yaml
name: project.dispatch
rule:
  match:
    - condition: 'obligation.family in ["route.consistency", "route.operation_plan"]'
      output: obligation.family
      explanation: '"handled by " + obligation.family'
    - output: '"unknown"'
      explanation: '"no handler for " + obligation.family'
```

Give every choice an explanation, or none.
A list with only some is refused, because the compiled explanation of a choice without one would answer for another choice.

### Read optional fields with `has()`

Whether a rule can tell a value from its absence depends on the field:

- **An optional or nullable field, or a message**, can be tested with `has()`. Guard each read: `has(part.supplier) && part.supplier != ""`.
- **A required field** can't. At its zero value, such as `""`, `0` or `false`, it reads as missing, so `has()` on it tells you nothing. Read it directly: `part.finish == "anodise"`.

Every record is validated against its contract before a rule sees it, so a `null` the contract forbids is refused before it reaches a rule.
The loader flags a bare read of an optional or nullable field outside a `has()` guard, and a `has()` on a required field.

### Spell values exactly

The compiler checks types, and treats an enum value as any other string.
`decision.status == "aproved"` compiles, and is always false.
Copy each value from the contract's reference page.

## Compile it

Rule lists are compiled before the server loads them.
Compile a project's lists with:

```sh
benchhand rules compile --project .
```

The command runs benchhand's pinned CEL checker over each list and writes the rules bundle beside the lists it covers.
It refuses:

- a field the scope doesn't declare, an undeclared variable, or a wrong operand type;
- a last choice with a condition, a condition that is literally `false`, or a literally true choice before the last;
- a feature outside the restricted format;
- an output whose type isn't the kind's;
- an explanation whose result isn't a string.

The same command compiles a policy provider's lists.

## When a list fails to load

The server checks each list against the bundle when it loads the flow.
It refuses the load when a list has no bundle entry, when the list's source has changed since it was compiled, or when the bundle was compiled for another environment.
The refusal names the file and the command to run, `benchhand rules compile`.

That happens after you edit a list, since an edit takes effect only once it is compiled.
It also happens after a benchhand upgrade whose contracts change a scope, which makes every bundle for that scope stale.
Compile again in both cases.

A rule that fails while it runs, such as arithmetic on a missing value, never passes a check.
benchhand records a finding and UNKNOWN coverage.
So does a `dispatch` or `fidelity` result outside the kind's values, such as `"F4"` or a handler id that no handler has.

## Gate requirements

A policy provider can also add requirements to the steps of a gate, `provisional`, `full` and `human`.
Each is a single CEL expression that gives a `bool`, such as `record.verification.all(v, v.reviewed_by.present)` on the `human` step of the `design_freeze` gate.

These aren't compiled into the bundle.
The server checks each one when it loads the flow, and reports every problem at once, with the expression's path in its file, the line, the column and a caret under the fault.
It refuses a requirement for a gate that the flow doesn't declare, or for a step the gate doesn't have.
The [policy contribution contract](/reference/contracts/policy/contribution/) gives the full shape.
