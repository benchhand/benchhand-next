# Policy

Status: `record/policy` is version `1.1.0`. `policy/contribution` is provisional, version `0.1.0`, and Phase 2 builds the merge in the flow interpreter. Decisions: [ADR-0003](../adr/0003-gates-guide.md), [ADR-0014](../adr/0014-flow-rules-cel.md), [ADR-0020](../adr/0020-cel-rule-pipeline.md). Sources: [`contracts/record/policy.tsp`](../../contracts/record/policy.tsp) and [`contracts/policy/contribution.tsp`](../../contracts/policy/contribution.tsp). Reference: [the generated policy reference](generated/record/policy.md) and [the generated contribution reference](generated/policy/contribution.md).

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

- rule-list files, by kind, in the shape of the flow's [`*.celpolicy` files](flow.md#rule-lists). Each is a `{file, rules_version}` reference relative to the provider's root, the same shape as `flow.yaml`'s. `benchhand rules compile` compiles it like the flow's own lists (ADR-0020).
- requirements for the `provisional`, `full` and `human` steps of a gate, by gate id.

Every compiled list ends with an unconditional choice, so the interpreter can't put a contributed list's choices in front of the flow's. It evaluates whole lists instead:

1. The interpreter evaluates the lists of one kind in order: the contributions in ascending order of provider name, then the list in `flow.yaml`. The flow's result is final.
2. `checks_by_iteration`, `dispatch` and `fidelity` fall through on the kind's [reserved no-match value](flow.md#reserved-values): `[]`, `"unknown"` and `"none"`. A contributed list ends in its kind's value. A list that gives it passes to the next list, and the first other value is the result. A contributed list therefore replaces the flow's value whenever it matches, and a contributed `checks_by_iteration` list can't select "no checks".
3. `rigor` doesn't fall through. Every list is evaluated, the contributions and the flow's, and the result is the union of their messages, each once, in the order first given. Rigor holds only when the union is empty, so a contribution can add requirements but never waive the flow's.
4. A gate's contributed requirements hold as well as the requirements of `flow.yaml`. The interpreter checks the `flow.yaml` requirements first, then each provider's in the same provider order.

When the flow loads, the interpreter refuses a requirement for a gate that `flow.yaml` doesn't declare, or for a step that the gate doesn't have.

`tests/test_policy_contract.py` runs this merge on the prototype's lists, with a test for each kind and each reserved value.

**Open for the owner:** composing policy providers' rule lists is open for the owner ([ADR-0020](../adr/0020-cel-rule-pipeline.md), "Open items"). Each list compiles to its own CheckedExpr and ends with an unconditional choice, so an evaluation order alone doesn't stop an earlier list's default from masking every later list. The merge order, the three no-match values and the rigor union above are this branch's proposal. Until the owner decides, the composition is undecided, and Phase 2 builds the merge only after that.
