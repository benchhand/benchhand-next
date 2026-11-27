# Flow definition and rule lists

Status: provisional, version `0.1.0`. Phase 2 writes `flow/flow.yaml`, the `flow/*.rules.yaml` files and the interpreter that runs them. Decisions: [ADR-0003](../adr/0003-gates-guide.md), [ADR-0014](../adr/0014-flow-rules-cel.md), [ADR-0018](../adr/0018-baseline-and-no-forms.md), [ADR-0019](../adr/0019-scoped-reapproval.md). Sources: [`contracts/flow/flow.tsp`](../../contracts/flow/flow.tsp), [`contracts/flow/rules.tsp`](../../contracts/flow/rules.tsp) and [`contracts/common/cel.tsp`](../../contracts/common/cel.tsp). Reference: [the generated flow reference](generated/flow/flow.md) and [the generated rule-list reference](generated/flow/rules.md).

`flow.yaml` holds the stage and gate graph as data. Every condition in the graph is a CEL expression. The schema checks the shape. Each expression is a `$ref` to the one CEL type, [`common/cel`](generated/common/cel.md), and that `$ref` is how the interpreter finds every expression. The type also carries `x-cel: true`, a readable annotation that nothing depends on. The generator refuses a plain string whose description says CEL. The flow interpreter compiles and type-checks every expression when it loads the file, so a typo fails at load and not in the middle of a flow (plan section 5).

## Stages, gates and edges

- `stages` has an entry for every stage of the record's stage enum, by its id, and the schema refuses a flow without one. Each stage names a guide fragment for each role. `lead` is required, and any other key is an agent profile such as `cad-part-designer`. `flow.guide` returns the role's own fragment, or else the lead's. A fragment is a Markdown file under `guides/`, with an optional heading anchor.
- `gates` lists the gates. The `kind` of a gate sets its steps:
  - `single-human`: the user approves in one step, and the edge advances then. Its `requires` has one list, `human`.
  - `provisional+full+human`: the gate approves a built version in three steps. The provisional gate follows the fast checks, and the edge advances there. The full check then runs on the same version, and the human gate opens after it. Its `requires` has the lists `provisional`, `full` and `human`. The `full` list says when the full check counts as done.
- Every expression in a `requires` list must hold.
- `edges` are the transitions. An edge can pass through a gate, and its `guard` must hold as well.
- `void_scope` selects the later stages that a VOID reopens, besides the voided stage.

The schema checks one file's shape: every stage, at least one gate and at least one edge. The flow loader checks the references within the file when it loads it. It refuses a duplicate YAML key, two gates with the same id, an edge that names a gate the file doesn't declare, and an expression that doesn't compile or type-check. The schema's example has every stage but only the LAYOUT freeze gate and its edge: it shows the shape, not a working flow.

## Rule lists

Each rule list is a file of its own, `<name>.rules.yaml`, written in the [cel-policy](https://github.com/cel-expr/cel-policy) format and checked against the `flow/rules` schema (plan sections 2 and 5). benchhand supports a restricted profile:

- The top-level keys are `name`, `description`, `imports` and `rule`.
- `rule` has `id`, `description` and `match` only: no `aggregate`, no `variables` and no nested `rule`.
- Each `match` item has a `condition`, an `output` and an optional `explanation`, and each of them is a CEL expression. An item without a `condition` always holds.
- The first item whose `condition` holds gives its `output`. The last item must be unconditional, so every list gives a value.

CI compiles each list with the pinned cel-go policy compiler into one checked expression, and the host compares digests at load. The compile step also refuses a list whose last item has a condition and the features outside the profile; the schema can't check which item comes last.

The file doesn't say which list it is. `flow.yaml` names one file of each kind under `rules`, as `{file, rules_version}` relative to `flow.yaml`. `rules_version` is the version of the rule-list format. The kind sets the type of every output:

| Kind | Output | Last item gives |
|---|---|---|
| `checks_by_iteration` | a list of check ids, in fail-fast run order | `[]`, no checks |
| `dispatch` | a handler id, or `"unknown"` | `"unknown"`: UNKNOWN coverage, never a pass |
| `fidelity` | the form-check fidelity, `"F0"` to `"F3"` | the fidelity of the other stages |
| `rigor` | a bool, true when the extra requirement under the project's rigor policy holds | `true`, no extra requirement |

A check that runs only under its own condition, such as "only when stale" or "once a joint exists", is concatenated into the output as `cond ? ["id"] : []`. A dispatch handler id is the obligation family that it judges, such as `process.fdm.orientation`. The dispatch list sees only the obligations that the process-check producer owns. The producer selects them, and the list has no rule for ownership.

Three values are reserved as no-match values for [contributed lists](policy.md#provider-contributions): `[]`, `"unknown"` and `"none"`. A flow's own list gives `[]` or `"unknown"` only from its last item, and never gives `"none"`. The flow loader refuses a fidelity list in `flow.yaml` that gives `"none"`.

## Gate decisions

`GateDecisionRequest` is what the flow engine takes to record a human-gate decision. The engine writes the decision record itself, in the [decision](generated/record/decision.md) shape.

- `status` is `approved`, or `void` for a change the user names at the human gate. A `void` needs a human channel, `app` or `chat`, and cites the provisional decision it withdraws. The interpreter records the other VOIDs itself, after a failing full check or a MAJOR light-review finding, without this request.
- `channel` uses the decision record's channel values. A request refuses `form`, because v1 doesn't use form elicitation (ADR-0018). The record contract still accepts `form`.
- Every channel except `auto` names who decided (`by`) and quotes their words (`quote`). A quote has at least one character that isn't whitespace, because an empty answer is no answer (plan section 11). An `auto` decision quotes nobody.
- `provisional` cites the provisional decision of a `provisional+full+human` gate.

## Approval scope

`ApprovalScope`, `ApprovedItemState` and the flow's `reapproval_scope` are provisional, and Phase 2 owns them (ADR-0019).

- An `ApprovalScope` lists the items that a human-gate approval covers. Each item has its kind, its id and its fingerprint at approval time.
- `reapproval_scope` selects the approved items that a change affects.
- An `ApprovedItemState` gives an item's status now. The status is `approved` while the fingerprint matches the one recorded at approval, and `changed_since_approval` after it changes. The stage stays where it is, and the next human gate confirms the item with a diff.

The decision contract doesn't refer to `ApprovalScope` yet. Phase 2 adds the reference.

## The prototype fixture

`tests/fixtures/flow/prototype-412b5d9/` writes the prototype's flow at the reference commit in these shapes:

- `flow.yaml`: every stage and its guides, the four single human gates, the three-step gates at L1 to L4, and the VOID cascade scope. Every human gate needs the user's explicit approval. The full sweep runs at each of L1 to L4. Each of those human gates therefore also needs the sweep to leave no unproved between-sample intervals, or a decision on the same version that accepts them.
- one `*.rules.yaml` file per rule list, with the checks-by-iteration table among them

The fixture holds the prototype's rules only. benchhand's `policy.mode == "auto"`, ADR-0019's `reapproval_scope` and the veto on an item that is `changed_since_approval` came after the prototype, so the schema's example shows them instead.

`tests/test_flow_contract.py` validates each file. The fixture tests the schemas. Phase 2 writes the real flow.
