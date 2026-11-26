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

- rule lists in the shape of the flow's [`*.rules.yaml` files](flow.md#rule-lists)
- requirements for the `provisional`, `full` and `human` steps of a gate, by gate id.

The merge order is fixed:

1. A contributed rule list's rules come before the rules of the flow's list of the same `kind`, so a contributed rule matches first.
2. The interpreter takes the contributions in ascending order of provider name. Each contribution keeps its own rule order.
3. A gate's contributed requirements hold as well as the requirements of `flow.yaml`. The interpreter checks the `flow.yaml` requirements first, then each provider's in the same provider order.

When the flow loads, the interpreter refuses a requirement for a gate that `flow.yaml` doesn't declare, or for a step that the gate doesn't have.
