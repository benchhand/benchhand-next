# Flow definition and rule lists

Status: provisional, version `0.1.0`. Phase 2 writes `flow/flow.yaml`, the `flow/*.celpolicy` files and the interpreter that runs them. Decisions: [ADR-0003](../adr/0003-gates-guide.md), [ADR-0014](../adr/0014-flow-rules-cel.md), [ADR-0018](../adr/0018-baseline-and-no-forms.md), [ADR-0019](../adr/0019-scoped-reapproval.md), [ADR-0020](../adr/0020-cel-rule-pipeline.md). Sources: [`contracts/flow/flow.tsp`](../../contracts/flow/flow.tsp), [`contracts/flow/rules.tsp`](../../contracts/flow/rules.tsp) and [`contracts/common/cel.tsp`](../../contracts/common/cel.tsp). Reference: [the generated flow reference](generated/flow/flow.md) and [the generated rule-list reference](generated/flow/rules.md).

`flow.yaml` holds the stage and gate graph as data. Every condition in the graph is a CEL expression. The schema checks the shape. Each expression is a `$ref` to the one CEL type, [`common/cel`](generated/common/cel.md), and that `$ref` is how the interpreter finds every expression. The type also carries `x-cel: true`, a readable annotation that nothing depends on. The generator refuses a plain string whose description says CEL. The flow interpreter checks every standalone expression when it loads the file, so a typo fails at load and not in the middle of a flow. Rule lists are compiled before load instead (ADR-0020).

## Stages, gates and edges

- `stages` has an entry for every stage of the record's stage enum, by its id, and the schema refuses a flow without one. Each stage names a guide fragment for each role. `lead` is required, and any other key is an agent profile such as `cad-part-designer`. `flow.guide` returns the role's own fragment, or else the lead's. A fragment is a Markdown file under `guides/`, with an optional heading anchor.
- `gates` lists the gates. The `kind` of a gate sets its steps:
  - `single-human`: the user approves in one step, and the edge advances then. Its `requires` has one list, `human`.
  - `provisional+full+human`: the gate approves a built version in three steps. The provisional gate follows the fast checks, and the edge advances there. The full check then runs on the same version, and the human gate opens after it. Its `requires` has the lists `provisional`, `full` and `human`. The `full` list says when the full check counts as done.
- Every expression in a `requires` list must hold.
- `edges` are the transitions. An edge can pass through a gate, and its `guard` must hold as well.
- `void_scope` selects the later stages that a VOID reopens, besides the voided stage.

The schema checks one file's shape: every stage, at least one gate and at least one edge. The flow loader checks the references within the file when it loads it. It refuses a duplicate YAML key, two gates with the same id, an edge that names a gate the file doesn't declare, and a standalone expression that doesn't compile or type-check. It also refuses a fidelity rule list with an output that is the literal `"none"`. The schema's example has every stage but only the LAYOUT freeze gate and its edge: it shows the shape, not a working flow.

## Rule lists

Each rule list is a file of its own, `flow/<name>.celpolicy`, written in the [cel-policy](https://github.com/cel-expr/cel-policy) format and checked against the `flow/rules` schema. benchhand supports the restricted profile of ADR-0020:

- The top-level keys are `name` and `rule`.
- `rule` has one `match` block and nothing else: no `aggregate`, no `variables` and no nested `rule`.
- Each choice of `match` has an `output` and, except the last, a `condition`. Both are CEL expressions. The profile has no `imports` and no `description`.
- A choice may have an `explanation`, a CEL expression that gives a `string`: why the choice gives its output, such as a finding's text. Every choice of a list has one, or none does, and the schema refuses a list with only some (ADR-0020, "The restricted cel-policy profile"). The owner admitted `explanation` on 2026-11-27; the all-or-none rule and the string check are the supervisor's.
- The first choice whose `condition` holds gives its `output`. The last choice has no condition, so every list gives a value.

The pinned cel-go tool compiles each list before load into a bundle entry. The entry has one output expression and, when the list has explanations, a second expression for them, whose checked type must be `string`. It also refuses a list whose last choice has a condition, a feature outside the profile, a result type other than its kind's, and an explanation whose result isn't a `string`. The schema checks that exactly one choice has no condition (`contains`, `minContains: 1` and `maxContains: 1` on the choices without `condition`). It can't check that this choice is the last; the compiler does.

The file doesn't say which list it is. `flow.yaml` names one file of each kind under `rules`, as `{file, rules_version}` relative to `flow.yaml`. A [policy contribution](policy.md#provider-contributions) names its files in the same shape. `rules_version` is the version of the rule-list format. The kind sets the type of every output:

| Kind | Output type | Output | Last choice of the flow's list |
|---|---|---|---|
| `checks_by_iteration` | `list(string)` | the check ids, in fail-fast run order | `[]`, no checks |
| `dispatch` | `string` | a handler id, or `"unknown"` | `"unknown"`: UNKNOWN coverage, never a pass |
| `fidelity` | `string` | the form-check fidelity, `"F0"` to `"F3"`, or `"none"` | `"F0"`, the fidelity of the other stages |
| `rigor` | `list(string)` | the messages of the requirements the record doesn't meet under the project's rigor policy | `[]`, no unmet requirement |

A check that runs only under its own condition, such as "only when stale" or "once a joint exists", is concatenated into the output as a CEL ternary, `cond ? ["id"] : []`. The slot type of `fidelity` and `dispatch` is `string`, so the compiler accepts any string an output gives, a computed one included, such as `"F4"` or a handler id that no handler has. The Phase 2 evaluator checks the kind's result against its domain, `"F0"` to `"F3"` for `fidelity` and the handler ids that exist, or `"unknown"`, for `dispatch`. It records a result out of the domain as UNKNOWN with a finding that names the value, never as a pass. A dispatch handler id is the obligation family that it judges, such as `process.fdm.orientation`. The dispatch list sees only the obligations that the process-check producer owns. The producer selects them, and the list has no rule for ownership.

### Reserved values

Each kind but `rigor` reserves one no-match value. A list that gives it falls through to the next list of its kind ([merge](policy.md#provider-contributions)):

- `checks_by_iteration`: `[]`. The flow's own list may end in `[]`, which runs no check.
- `dispatch`: `"unknown"`. The flow's own list may end in `"unknown"`, which means UNKNOWN coverage.
- `fidelity`: `"none"`. Only a contributed list gives it. The flow's own list ends in `"F0"`. No schema can refuse `"none"` in it: a rule-list file doesn't say its kind, and `flow.yaml` only names the file. The Phase 2 flow loader refuses an output of the flow's fidelity list that is the literal `"none"`. A computed `"none"` is seen only when the list is evaluated, and the evaluator records it as out of the domain, UNKNOWN with a finding.

The flow's list is evaluated last, and its result is final, so a flow's `[]` or `"unknown"` is the value. `rigor` reserves no value and doesn't fall through: its final `[]` means no unmet requirement.

## Gate decisions

`GateDecisionRequest` is what the flow engine takes to record a human-gate decision. The engine writes the decision record itself, in the [decision](generated/record/decision.md) shape.

- `status` is `approved`, or `void` for a change the user names at the human gate. A `void` needs a human channel, `app` or `chat`, and cites the provisional decision it withdraws. The interpreter records the other VOIDs itself, after a failing full check or a MAJOR light-review finding, without this request.
- `channel` uses the decision record's channel values. A request refuses `form`, because v1 doesn't use form elicitation (ADR-0018). The record contract still accepts `form`.
- Every channel except `auto` names who decided (`by`) and quotes their words (`quote`). Both have at least one character that isn't whitespace, `NonblankText`, because an empty answer is no answer (plan section 11) and a blank name is nobody. Whitespace there is every Unicode `White_Space` character, which includes every `Zs` character and U+0085 NEXT LINE. It also covers U+FEFF, from the ECMAScript whitespace class, and U+001C to U+001F, from Python's `str.isspace`. The pattern lists them as code points, because the regex engines read `\s` differently. An `auto` decision quotes nobody.
- `provisional` cites the provisional decision of a `provisional+full+human` gate.
- The request has no field for the decision that accepts unproved between-sample intervals that the full sweep left. The engine supplies that citation from the record: the decision on the same version that accepts them. The owner decided this on 2026-11-27, at the Phase 0 and 1 gate.

## Approval scope

`ApprovalScope`, `ApprovedItemState` and the flow's `reapproval_scope` are provisional, and Phase 2 owns them (ADR-0019).

- An `ApprovalScope` lists the items that a human-gate approval covers. Each item has its kind, its id and its fingerprint at approval time.
- `reapproval_scope` selects the approved items that a change affects.
- An `ApprovedItemState` gives an item's status now. The status is `approved` while the fingerprint matches the one recorded at approval, and `changed_since_approval` after it changes. The stage stays where it is, and the next human gate confirms the item with a diff.

The decision contract doesn't refer to `ApprovalScope` yet. Phase 2 adds the reference.

## The prototype fixture

`tests/fixtures/flow/prototype-412b5d9/` writes the prototype's flow at the reference commit in these shapes:

- `flow.yaml`: every stage and its guides, the four single human gates, the three-step gates at L1 to L4, and the VOID cascade scope. Every human gate needs the user's explicit approval. The full sweep runs at each of L1 to L4. Each of those human gates therefore also needs the sweep to leave no unproved between-sample intervals, or a decision on the same version that accepts them. The approval cites its provisional decision and, when intervals are left, the decision that accepts them. The fixture's `answer.cites` stands in for both citations in the tests: the request's `provisional` field, and the citation that the engine supplies from the record.
- one `*.celpolicy` file per rule list, with the checks-by-iteration table among them

The fixture holds the prototype's rules only. benchhand's `policy.mode == "auto"`, ADR-0019's `reapproval_scope` and the veto on an item that is `changed_since_approval` came after the prototype, so the schema's example shows them instead.

`tests/test_flow_contract.py` validates each file, and `tests/test_policy_contract.py` runs the merge on the fixture's lists. The fixture tests the schemas. Phase 2 writes the real flow.
