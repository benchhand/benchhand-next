# Policy

Status: `record/policy` is version `1.1.0`. `policy/contribution` is provisional, version `0.1.0`, and Phase 2 builds the merge in the flow interpreter. Decisions: [ADR-0003](../adr/0003-gates-guide.md), [ADR-0014](../adr/0014-flow-rules-cel.md). Sources: [`contracts/record/policy.tsp`](../../contracts/record/policy.tsp) and [`contracts/policy/contribution.tsp`](../../contracts/policy/contribution.tsp). Reference: [the generated policy reference](generated/record/policy.md) and [the generated contribution reference](generated/policy/contribution.md).

Gates guide the standard process. They are not a security control (ADR-0003).

## The project's policy file

`hw/policy.yaml` sets how each gate asks for approval:

- `ask`, the default, asks the user.
- `chat` asks in the conversation.
- `auto` approves without a human, for development and tests.

`default` sets the mode of every gate without its own entry in `gates`. A mode other than `ask` cites the decision that records the relaxation.

`rigor` is the rigor policy, `standard` or `regulated`. Under `regulated`, the requirements of the flow's `rigor` rules apply as well as each gate's own.

Without `hw/policy.yaml`, every gate asks and the rigor is `standard`. Migrate relies on this. The prototype's `flow.profile.human_approval` has no place in record version 3, so migrate removes it and writes no policy file. A migrated project therefore asks at every gate until someone adds `hw/policy.yaml` ([record migration](record-migration.md)).

## Provider contributions

A policy provider adds CEL to the flow without code:

- rule-list files, by kind, in the shape of the flow's [`*.rules.yaml` files](flow.md#rule-lists). Each is a `{file, rules_version}` reference relative to the provider's root, and CI compiles it like the flow's own lists.
- requirements for the `provisional`, `full` and `human` steps of a gate, by gate id.

Every compiled list ends with an unconditional item, so the interpreter can't put a contributed list's items in front of the flow's. It evaluates whole lists instead. The merge order:

1. The interpreter evaluates the lists of one kind in order: the contributions in ascending order of provider name, then the list in `flow.yaml`.
2. For `checks_by_iteration`, `dispatch` and `fidelity`, the first list whose output isn't the kind's no-match value gives the value. The no-match values are `[]`, `"unknown"` and `"none"`, and a contributed list ends with its kind's value, so the next list is evaluated. A contributed list therefore replaces the flow's value whenever it matches, and a contributed `checks_by_iteration` list can't select "no checks".
3. For `rigor`, every list must give `true`.
4. A gate's contributed requirements hold as well as the requirements of `flow.yaml`. The interpreter checks the `flow.yaml` requirements first, then each provider's in the same provider order.

When the flow loads, the interpreter refuses a requirement for a gate that `flow.yaml` doesn't declare, or for a step that the gate doesn't have.

**Open for the owner:** this merge order and the three no-match values are a proposal. The owner confirms them at the Phase 1 gate, before Phase 2 builds the merge.
