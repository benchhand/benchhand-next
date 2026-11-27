---
title: Testing rules
description: Check that a rule list gives the outputs you expect.
sidebar:
  order: 3
---

benchhand checks a rule list at three points: when you compile it, when the server loads it, and when it runs.
Compiling proves that the list is well typed.
Which output it gives for each record is for your test cases to show.
[Writing CEL rules](/guides/writing-cel-rules/) covers writing and compiling a list.

## What compiling proves

`benchhand rules compile` proves that:

- every field a rule reads exists in its scope, with the type the rule uses;
- every output has the type of the list's kind;
- the list keeps to the restricted format, and its last choice always matches.

It doesn't prove:

- **that a value is spelled right.** An enum value is a plain string to the compiler, so `decision.status == "aproved"` compiles and is always false.
- **that a condition can hold.** A condition that is literally `false` is refused, but one that is always false in another way compiles.
- **that a result is in range.** A `dispatch` handler id that no handler has, or a computed `fidelity` such as `"F4"`, compiles. When the list runs, benchhand records such a result as UNKNOWN, with a finding that names the value.
- **how long a rule takes.** A rule has no cost bound.

## Write the cases as a table

benchhand tests its own rule lists with table-driven cases: each row gives the inputs and the output the list must give.
Write your cases the same way, with a row for each of these:

- **Each choice.** A record for which its condition holds and no earlier condition does.
- **The order.** A record for which two conditions hold, expecting the earlier one's output.
- **The last choice.** A record for which no condition holds, expecting the list's default.
- **Absence.** For each optional field a rule reads, a record without it, and one with its zero value, such as `""` or `0`. A required field at its zero value reads as missing, so give it a case too.
- **The fall-through.** For a policy provider's list, a record for which none of its conditions holds, expecting its kind's no-match value: `[]`, `"unknown"` or `"none"`.

For the checks list in [Writing CEL rules](/guides/writing-cel-rules/#write-the-list), the cases are:

| `stage` | `iteration` | Expected output |
|---|---|---|
| `parts` | `commit` | `["form_check", "check_changed_only"]` |
| `detail` | `commit` | `["form_check", "check_changed_only"]` |
| `layout` | `commit` | `[]` |
| `parts` | `inner` | `[]` |

The last two rows reach the default from each side of the condition.

## Read the results in the flow

A list's output shows where the flow uses it:

- **`checks_by_iteration`** sets the checks that run, in order, and each check's results land in the version's sealed check bundle.
- **`dispatch`** picks the handler of each process check. A `"unknown"` result is UNKNOWN coverage, never a pass, and a list with explanations gives the finding its text, such as "no handler for route.consistency".
- **`fidelity`** sets the form-check fidelity of a stage.
- **`rigor`** gives the messages of the requirements the record doesn't meet. Under `regulated` rigor, a gate holds only when no list gives a message.

A rule that fails while it runs, such as arithmetic on a missing value, gives a finding and UNKNOWN coverage, never a pass.
A case that ends that way points at a read that needs a `has()` guard.
