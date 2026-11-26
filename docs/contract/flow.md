# Flow definition and rule lists

Status: provisional, version `0.1.0`. Phase 2 writes `flow/flow.yaml`, the `flow/*.rules.yaml` files and the interpreter that runs them. Decisions: [ADR-0003](../adr/0003-gates-guide.md), [ADR-0014](../adr/0014-flow-rules-cel.md), [ADR-0018](../adr/0018-baseline-and-no-forms.md), [ADR-0019](../adr/0019-scoped-reapproval.md). Sources: [`contracts/flow/flow.tsp`](../../contracts/flow/flow.tsp), [`contracts/flow/rules.tsp`](../../contracts/flow/rules.tsp) and [`contracts/common/cel.tsp`](../../contracts/common/cel.tsp). Reference: [the generated flow reference](generated/flow/flow.md) and [the generated rule-list reference](generated/flow/rules.md).

`flow.yaml` holds the stage and gate graph as data. Every condition in the graph is a CEL expression. The schema checks the shape. Each expression is a `$ref` to the one CEL type, [`common/cel`](generated/common/cel.md), and that `$ref` is how the interpreter finds every expression. The type also carries `x-cel: true`, a readable annotation that nothing depends on. The generator refuses a plain string whose description says CEL. The flow interpreter compiles and type-checks every expression when it loads the file, so a typo fails at load and not in the middle of a flow (plan section 5).

## Stages, gates and edges

- `stages` lists every stage of the record's stage enum, in flow order. Each stage names a guide fragment for each role. `lead` is required, and any other key is an agent profile such as `cad-part-designer`. `flow.guide` returns the role's own fragment, or else the lead's. A fragment is a Markdown file under `guides/`, with an optional heading anchor.
- `gates` lists the gates. The `kind` of a gate sets its steps:
  - `single-human`: the user approves in one step, and the edge advances then. Its `requires` has one list, `human`.
  - `provisional+full+human`: the gate approves a built version in three steps. The provisional gate follows the fast checks, and the edge advances there. The full check then runs on the same version, and the human gate opens after it. Its `requires` has the lists `provisional`, `full` and `human`. The `full` list says when the full check counts as done.
- Every expression in a `requires` list must hold.
- `edges` are the transitions. An edge can pass through a gate, and its `guard` must hold as well.
- `void_scope` selects the later stages that a VOID reopens, besides the voided stage.

## Rule lists

Each rule list is a file of its own, `flow/<kind>.rules.yaml`, in the `flow/rules` shape (plan sections 2 and 5). `kind` names the list and sets the shape of `then`. `rules` is an ordered list of `{when, then}` rules, and the first rule whose `when` holds gives the value.

| `kind` | `then` | No match |
|---|---|---|
| `checks_by_iteration` | the checks to run, in fail-fast order | no checks |
| `dispatch` | the process-check handlers for an obligation | UNKNOWN coverage, never a pass |
| `fidelity` | the form-check fidelity, `F0` to `F3` | no fidelity |
| `rigor` | extra requirements under a rigor policy such as `regulated` | none |

A check in `checks_by_iteration` is either a check id or `{check, when}`. The second form runs only when its own `when` holds as well. Conditions such as "only when stale" and "once a joint exists" use it.

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

- `flow.yaml`: every stage and its guides, the four single human gates, the three-step gates at L1 to L4, and the VOID cascade scope
- one `*.rules.yaml` file per rule list, with the checks-by-iteration table among them

`tests/test_flow_contract.py` validates each file. The fixture tests the schemas. Phase 2 writes the real flow.
