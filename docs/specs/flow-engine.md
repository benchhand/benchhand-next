---
spec: flow-engine
title: The flow engine, gate policy and next actions
status: draft
capabilities:
  - flow-engine
  - gate-policy
  - result-envelope
questions:
  - tool-stage-check
  - freeze-digest
  - provisional-recording
  - key-gate-auto
  - policy-resources
  - envelope-phase
  - bounded-results
rules:
  - RULE-05
  - RULE-08
  - RULE-14
  - RULE-27
  - RULE-34
  - RULE-35
issues:
  closes:
    - id: IR-001
      block: FE-5
      test: test_an_approved_waiver_settles_a_process_check_fail_at_the_gate_and_the_same_fail_without_it_blocks
    - id: IR-048
      block: FE-5
      test: test_an_out_of_scope_obligation_blocks_no_gate_and_shows_an_info_row_while_a_production_design_still_blocks
    - id: IR-061
      block: FE-9
      test: test_under_key_approvals_the_detail_gate_closes_without_the_user_and_the_design_freeze_gate_asks
    - id: IR-083
      block: FE-13
      test: test_a_stage_advances_and_its_decision_record_is_written_through_the_services_with_no_hand_edit
    - id: IR-085
      block: FE-3
      test: test_a_yaml_error_is_a_finding_with_its_line_and_a_malformed_record_gives_status_error_with_findings
  defers:
    - id: IR-081
      to: decision-records
      reason: The refusal of an undeclared backward gate is a check on the decision the engine writes.
    - id: IR-166
      to: guide-service
      reason: >-
        Its acceptance test is on the stage guides. The checks_by_iteration list that reads the profile is data the
        guide spec cites.
    - id: IR-173
      to: selection-assessment
      reason: The use-case questions and their not_applicable fill belong to the use-case assessment.
    - id: IR-175
      to: guide-service
      reason: The intent-stage questions are guide content.
blocks:
  - id: FE-1
    title: The flow loader
    size: M
    requirements: [REQ-1, REQ-2, REQ-3]
    depends_on: [CP-5]
  - id: FE-2
    title: The real flow/flow.yaml
    size: M
    requirements: [REQ-1]
    depends_on: [FE-1, CP-7]
  - id: FE-3
    title: The result envelope in core
    size: S
    requirements: [REQ-19, REQ-21, REQ-22]
    depends_on: [question:envelope-phase]
  - id: FE-4
    title: The interpreter, its transitions and refusals
    size: L
    requirements: [REQ-4, REQ-5, REQ-6, REQ-7, REQ-9]
    depends_on: [FE-2, FE-3, AP-1]
  - id: FE-5
    title: Gate obligations from the evidence assessment
    size: M
    requirements: [REQ-10, REQ-11]
    depends_on: [FE-4, capability:evidence-assessment]
  - id: FE-6
    title: The VOID cascade
    size: M
    requirements: [REQ-8]
    depends_on: [FE-4, AP-1]
  - id: FE-7
    title: Gate modes, rigor and policy changes
    size: M
    requirements: [REQ-12, REQ-13, REQ-14]
    depends_on: [FE-4, AP-1]
  - id: FE-8
    title: Merging contributed rule lists and gate requirements
    size: M
    requirements: [REQ-15, REQ-16, REQ-17]
    depends_on: [FE-1, CP-7]
  - id: FE-9
    title: Middle gates without the user under the key-gates profile
    size: S
    requirements: [REQ-18]
    depends_on: [FE-7, question:key-gate-auto]
  - id: FE-10
    title: Next actions from the gate state
    size: M
    requirements: [REQ-20]
    depends_on: [FE-4, question:provisional-recording]
  - id: FE-11
    title: Tool calls against flow.stage
    size: S
    requirements: [REQ-23]
    depends_on: [FE-4, question:tool-stage-check]
  - id: FE-12
    title: The design freeze
    size: M
    requirements: [REQ-24]
    depends_on: [FE-5, capability:version-snapshots, question:freeze-digest]
  - id: FE-13
    title: The flow end to end through the services
    size: M
    requirements: [REQ-25]
    depends_on: [FE-6, FE-7, FE-10, capability:selection-assessment]
---

# The flow engine, gate policy and next actions

Status: draft, 2026-11-27, written against `main` at `4c783f55`. Waiting for the owner's review. Its companion is the [CEL pipeline spec](cel-pipeline.md), which compiles and verifies the expressions this engine runs.

## Capabilities

- [`flow-engine`](../architecture/capabilities.md#flow-engine): load `flow.yaml`, check its expressions, and run the state machine. Tool: `flow.advance` (proposed, Phase 3). Contracts: `flow/flow`, `record/product`, `common/cel`.
- [`gate-policy`](../architecture/capabilities.md#gate-policy): the gate modes and rigor of `hw/policy.yaml`, and policy providers' rule lists and gate requirements. Tools: `policy.get` and `policy.set` (proposed, Phase 3); CLI: `policy get`, `policy set` (Phase 3). Contracts: `record/policy`, `policy/contribution`.
- [`result-envelope`](../architecture/capabilities.md#result-envelope): the one envelope every tool returns, with `next_actions`. The contract is on `main` at `0.1.0`, provisional. Contracts: `envelope/envelope`, `common/finding`, `provider/protocol#/$defs/Artifact`.

## Problem and users

In the prototype the process lives in prose. The agent writes `hw/decisions/` and `flow.stage` itself, and `validate.py` catches mistakes only afterwards (`docs/design-plan.md:38`). The engine makes the flow data, refuses an out-of-order step with its reason and the next step, and becomes the normal writer of `flow.stage`. Gates steer the process. They are not a security control (`docs/contract/policy.md:5`).

- **The user** approves gates and sets how each gate asks.
- **The agent** calls the engine, through the Phase 3 tools, and follows its refusals and next actions instead of rereading the guide.
- **Policy-provider authors** add rule lists and gate requirements as data.

## Requirements

- **REQ-1.** `flow/flow.yaml` holds every stage with a guide fragment per role, the gates with their kind and CEL `requires`, the edges with their gate and guard, `void_scope` and `rules`, and validates against `flow/flow`. Source: `docs/contract/flow.md:9-15`, `docs/design-plan.md:149-152`.
- **REQ-2.** The loader refuses a duplicate YAML key, two gates with one id, an edge that names an undeclared gate, an expression that doesn't compile or type-check, and a literal `"none"` from the flow's own fidelity list. Source: `docs/contract/flow.md:17`, `docs/contract/flow.md:48`, `docs/phases/phase-0-1.md:201`.
- **REQ-3.** The loader checks every standalone expression once at start against its scope's manifest, and reports every issue at once with its path in the file, its line, its column and a caret. `requires`, guards and `when` must give `bool`. Source: `docs/design-plan.md:161`, `docs/adr/0020-cel-rule-pipeline.md:163`.
- **REQ-4.** Every record is validated against its JSON Schema before it enters an activation. Source: `docs/design-plan.md:161`, `docs/adr/0020-cel-rule-pipeline.md:98`.
- **REQ-5.** An out-of-order transition is refused with a reason and at least one next action. Source: `docs/design-plan.md:176`, `docs/design-plan.md:616`, `docs/contract/envelope.md:14`.
- **REQ-6.** A `single-human` gate advances on the user's approval. A `provisional+full+human` gate advances at the provisional step, the full check runs on the same version, and the human gate opens after it. A PROVISIONAL without passing fast checks is refused. Source: `docs/contract/flow.md:11-12`, `docs/design-plan.md:621`.
- **REQ-7.** An empty or declined answer leaves the gate open. Source: `docs/design-plan.md:351`, `docs/design-plan.md:617`.
- **REQ-8.** A VOID reopens the voided stage and every later stage that `void_scope` selects. The interpreter records the VOIDs after a failing full check itself. Source: `docs/contract/flow.md:15`, `docs/contract/flow.md:56`, `docs/design-plan.md:619`.
- **REQ-9.** The interpreter is the normal writer of `flow.stage`. A direct edit of `hw/` is not prevented; `validate` reports it. A stage advance is approved only by its gate's decision record (RULE-35). Source: `docs/design-plan.md:161`, `docs/design-plan.md:176`.
- **REQ-10.** A gate judges each obligation from the evidence assessment, which applies approved and scoped dispositions, never from the raw packet outcomes. Source: IR-001.
- **REQ-11.** The gates read the service-class rules at every stage. An out-of-scope obligation is skipped with an info finding that names the rule and the class, and a known fail out of scope blocks no gate (RULE-27). Unknown never passes (RULE-05), and a packet of passes and not-assessed checks is not_assessed (RULE-34). Source: IR-048.
- **REQ-12.** `hw/policy.yaml` sets each gate's mode, `ask`, `chat` or `auto`, and the rigor. A mode other than `ask` cites the decision that records the relaxation. Without the file every gate asks and the rigor is `standard`. A gate's `requires` reads the mode as `policy.mode`. Source: `docs/contract/policy.md:9-19`, `docs/design-plan.md:151`.
- **REQ-13.** A policy change writes a decision record. Source: `docs/design-plan.md:11`, `docs/design-plan.md:622`.
- **REQ-14.** Under `regulated`, the requirements of the rigor lists apply as well as each gate's own, and rigor holds only when the union of their messages is empty. Source: `docs/contract/policy.md:17`, `docs/contract/policy.md:32`.
- **REQ-15.** For each kind, the engine evaluates the contributed lists in ascending provider name, then the flow's list, whose result is final. A list that gives its kind's reserved no-match value passes to the next. Rigor is the union of every list's messages, each once, and no list can waive one. Source: `docs/contract/policy.md:28-32`, `docs/adr/0020-cel-rule-pipeline.md:228-234`, `docs/phases/phase-0-1.md:125`.
- **REQ-16.** A gate's contributed requirements hold as well as the flow's, checked after them in provider order. The loader refuses a requirement for a gate that `flow.yaml` doesn't declare, or for a step the gate doesn't have. Source: `docs/contract/policy.md:33-35`.
- **REQ-17.** A merged fidelity outside F0 to F3, or a dispatch handler id that no handler has, gives UNKNOWN with a finding that names the value, never a pass. Source: `docs/phases/phase-0-1.md:201`, RULE-05.
- **REQ-18.** Under the key-gates profile, a middle gate closes without the user when its full check passes, citing the relaxation decision and the full-check packet. The key gates still need the user, and the variant gate means CONCEPT (RULE-14). Migrate tells such a project how to set `hw/policy.yaml` (`docs/contract/record-migration.md:134`). Source: IR-061. Whether a key gate may be set to `auto` waits on `key-gate-auto`.
- **REQ-19.** `packages/benchhand-core` builds the envelope, the home of the prototype's `emit.py` (`docs/architecture/reference-map.yaml:762-763`). `status` is `ok`, `refused`, `pending` or `error`, with the parts each one requires, and `verdict` is set only by a check on an `ok` result. Source: `docs/contract/envelope.md:11-18`.
- **REQ-20.** Every result carries `next_actions`: the tool calls that make sense next, most useful first, with the arguments the server can fill, a `reason`, and `needs_user` when the call needs the user. Source: `docs/contract/envelope.md:24`, `docs/design-plan.md:316`. **Proposal** for the owner on how the engine derives them: an open human gate gives `flow.record_decision` with its gate filled and `needs_user` true, and a refused transition gives the step that comes first. The provisional step's entry waits on `provisional-recording`.
- **REQ-21.** A YAML error is a finding with its file and line, and a malformed record gives status `error` with findings, never a crash. Exit 2 stays for usage and infrastructure errors (RULE-08). Source: IR-085.
- **REQ-22.** The envelope's first finding is the first actionable one, and `guidance` names it with its subject and `path:line`, such as a build error's PN and file line, or a blocking pair and its overlap volume. **Proposal** for the owner, from the agentcad product-test lessons that the supervisor passed on (finding 4, "Bounded results that carry the first actionable finding"); the prompt isn't in the repository. The prototype's compact summary names the blockers (`reference/skills/cad-record/tests/test_emit.py:97`). The bounded envelope itself stays with `bounded-results`.
- **REQ-23.** If the owner decides that writing tool calls are checked against `flow.stage`, the engine refuses an out-of-stage call in the shape of REQ-5. Source: `docs/architecture/data-flow.md:344`. Waits on `tool-stage-check`.
- **REQ-24.** The design-freeze gate records `flow.frozen` on a sealed version, with the evidence digest of its assessment. Source: `docs/design-plan.md:561`. A freeze whose assessment refuses, and so has no digest, waits on `freeze-digest` (`docs/architecture/data-flow.md:346`).
- **REQ-25.** A flow test advances a stage, writes its decision record and refreshes the selection digest through the services, with no hand edit of the record. Source: IR-083.

## Interfaces

- **MCP tools**, all Phase 3: `flow.advance` (proposed), `flow.record_decision` (planned, in the [approvals spec](approvals.md)), `policy.get` and `policy.set` (proposed; the MCP path waits on `policy-resources`). Phase 2 builds the services they call.
- **CLI**, Phase 3: `benchhand policy get` and `benchhand policy set`.
- **Contracts:** `flow/flow`, `record/policy`, `policy/contribution`, `envelope/envelope` and `common/finding`, all read as they are on `main`. No contract changes here. `flow/flow`'s `reapproval_scope` belongs to the approvals spec.
- **Provider methods:** none. A policy provider's contribution is data.
- **Code:** a `flow` package in `packages/benchhand-core` (loader, interpreter, policy, merge, envelope), and `flow/flow.yaml`.

## Issue register

| Entry | Disposition | Block | Test |
|---|---|---|---|
| IR-001 | design-input | FE-5 | `test_an_approved_waiver_settles_a_process_check_fail_at_the_gate_and_the_same_fail_without_it_blocks` |
| IR-048 | design-input | FE-5 | `test_an_out_of_scope_obligation_blocks_no_gate_and_shows_an_info_row_while_a_production_design_still_blocks` |
| IR-061 | design-input | FE-9 | `test_under_key_approvals_the_detail_gate_closes_without_the_user_and_the_design_freeze_gate_asks` |
| IR-083 | already-covered | FE-13 | `test_a_stage_advances_and_its_decision_record_is_written_through_the_services_with_no_hand_edit` |
| IR-085 | already-covered | FE-3 | `test_a_yaml_error_is_a_finding_with_its_line_and_a_malformed_record_gives_status_error_with_findings` |

IR-083 and IR-085 are the plan's `c7q.2` and `c7q.4` (`docs/design-plan.md:565`).

| Entry | Deferred to | Why |
|---|---|---|
| IR-081 | `decision-records` | A check on the decision the engine writes. |
| IR-166 | `guide-service` | Its acceptance test is on the stage guides. |
| IR-173 | `selection-assessment` | The use-case questions belong to the use-case assessment. |
| IR-175 | `guide-service` | The intent-stage questions are guide content. |

## Prototype behaviour replaced

| Prototype | Inventory | Replaced by | Oracle tests |
|---|---|---|---|
| `stages.py` `stages`, the stage order | `docs/architecture/prototype-inventory.md:2621` | `flow/flow.yaml` stages and edges | the fixture `tests/fixtures/flow/prototype-412b5d9/flow.yaml` |
| `validate.py` `check_flow` | `docs/architecture/prototype-inventory.md:2662` | the interpreter's transitions | `reference/skills/cad-record/tests/test_validate.py:454` |
| `emit.py` `envelope` | `docs/architecture/prototype-inventory.md:2235` | the core envelope | `reference/skills/cad-record/tests/test_emit.py:158` |
| `emit.py` `verdict_of`, `describe` | `docs/architecture/prototype-inventory.md:2241-2243` | `verdict` and the finding text | `reference/skills/cad-record/tests/test_emit.py:154`, `reference/skills/cad-record/tests/test_emit.py:179` |
| `emit.py` `emit`, the compact summary | `docs/architecture/prototype-inventory.md:2244` | `guidance` and REQ-22 | `reference/skills/cad-record/tests/test_emit.py:97` |
| `skills/cad-flow/references/` "Gate control" prose | the reference map's `flow/flow.yaml` home | gates, VOID cascade and refusals | ported as flow tests |

The prototype's `emit.py` output modes (`--json`, `CAD_OUTPUT`, a terminal against a pipe) are CLI behaviour, not the envelope, and stay out.

## Non-goals

- The MCP tools and CLI commands that return the envelope: Phase 3.
- The stage guides (`flow/guides/*.md`) and `flow.guide`: the `guide-service` capability, not yet specced. FE-2 keeps the fixture's fragment names.
- Decision records, approval scopes and `changed_since_approval`: the [approvals spec](approvals.md).
- Running the checks that a gate reads: check orchestration, Phase 4.
- The bounded envelope with `truncated` and a retrieve handle: `bounded-results`.

## Open questions

| Question | Blocking | Blocks that wait |
|---|---|---|
| [`tool-stage-check`](../architecture/capabilities.md#tool-stage-check) | yes | FE-11 |
| [`freeze-digest`](../architecture/capabilities.md#freeze-digest) | yes | FE-12 |
| [`provisional-recording`](../architecture/capabilities.md#provisional-recording) | yes | FE-10, and AP-4 in the approvals spec |
| [`key-gate-auto`](../architecture/capabilities.md#key-gate-auto) | yes | FE-9 |
| [`policy-resources`](../architecture/capabilities.md#policy-resources) | yes | no Phase 2 block: it decides the Phase 3 MCP path to the policy |
| [`envelope-phase`](../architecture/capabilities.md#envelope-phase) | no | FE-3 builds the envelope in Phase 2 and leaves the tools to Phase 3 |
| [`bounded-results`](../architecture/capabilities.md#bounded-results) | yes | no Phase 2 block: REQ-22 orders findings and needs no bounded envelope |

## Blocks

### FE-1: The flow loader

Size M. After CP-5.

**Scope.** Load `flow.yaml` with the strict YAML reader, validate it against `flow/flow`, check the in-file references of REQ-2, and check every standalone expression through the CEL adapter, collecting every issue with its location.

**Acceptance.** Loader tests: one refusal for each case of REQ-2; a typo in a guard and a non-`bool` `requires` reported together in one run, each with its path, line, column and caret; the fixture flow loads.

### FE-2: The real flow/flow.yaml

Size M. After FE-1 and CP-7.

**Scope.** Write `flow/flow.yaml` from the prototype fixture: every stage, the four single human gates, the staged gates at L1 to L4, the edges and `void_scope`, with `policy.mode` in the human requirements and the shipped rule lists under `rules`.

**Acceptance.** The flow loads with no issue. A test walks every edge of the fixture and finds the same edge in the flow.

### FE-3: The result envelope in core

Size S. Depends on `envelope-phase`, which this block settles by building the envelope in Phase 2 and leaving the tools to Phase 3.

**Scope.** A builder in `packages/benchhand-core` that makes a valid `envelope/envelope` for each status, puts the first actionable finding first (REQ-22, once approved), and turns a parse error or a malformed record into findings.

**Acceptance.** Envelope tests: each status with its required parts, and a refused envelope without `next_actions` refused by the contract; the IR-085 test; once the owner approves REQ-22, a check result with an info finding and a blocking one lists the blocking one first and names it in `guidance`.

### FE-4: The interpreter, its transitions and refusals

Size L. After FE-2, FE-3 and AP-1.

**Scope.** The state machine of REQ-5 to REQ-7:

- read the record, validated first;
- refuse an out-of-order transition with a reason and a next action;
- run both gate kinds, and leave a gate open on an empty or declined answer;
- record decisions through AP-1, and write `flow.stage` through the record store.

**Acceptance.** The plan's flow tests at `docs/design-plan.md:616-617` and `docs/design-plan.md:621`. A ported `reference/skills/cad-record/tests/test_validate.py:454` case: only the user's approval freezes a version through a provisional and VOID cycle.

### FE-5: Gate obligations from the evidence assessment

Size M. After FE-4. Needs `evidence-assessment` (Phase 1, partial) to apply scoped dispositions and the service-class scope.

**Scope.** Gate `requires` read the evidence assessment's per-obligation outcomes and the service-class scope, and the gate reports an out-of-scope obligation as an info finding.

**Acceptance.** The IR-001 and IR-048 tests in the table above. A gate test where an UNKNOWN obligation never passes and a packet of passes and not-assessed checks gives not_assessed.

### FE-6: The VOID cascade

Size M. After FE-4 and AP-1.

**Scope.** Evaluate `void_scope` for each later stage on a VOID, reopen the voided stage and the selected ones, and record the interpreter's own VOID after a failing full check.

**Acceptance.** The plan's cascade test (`docs/design-plan.md:619`): a VOID at the parts gate reopens parts and the stages `void_scope` selects, and leaves the earlier stages. A failing full check writes one VOID decision that cites the provisional one.

### FE-7: Gate modes, rigor and policy changes

Size M. After FE-4 and AP-1.

**Scope.** Read `hw/policy.yaml`, apply each gate's mode, evaluate the rigor lists under `regulated`, and record a policy change as a decision through a policy service that the Phase 3 tools and CLI call.

**Acceptance.** Policy tests:

- with no policy file, every gate asks;
- `chat` and `auto` each close a gate through their channel;
- a relaxation without its decision is refused;
- a policy change writes a decision record (`docs/design-plan.md:622`);
- a regulated record with an unmet rigor message fails its gate.

### FE-8: Merging contributed rule lists and gate requirements

Size M. After FE-1 and CP-7.

**Scope.** The merge of REQ-15, the contributed gate requirements of REQ-16, and the out-of-domain handling of REQ-17, on the compiled bundles.

**Acceptance.** The merge cases of `tests/test_policy_contract.py` run on the engine's merge instead of the stand-in. Tests:

- each reserved value passes to the next list;
- a later list keeps an earlier list's rigor message;
- a requirement that names an undeclared gate is refused;
- an out-of-domain fidelity and handler id each give UNKNOWN with a finding.

### FE-9: Middle gates without the user under the key-gates profile

Size S. After FE-7. Waits on `key-gate-auto`.

**Scope.** Close a middle gate on a passing full check under `auto`, citing the relaxation decision and the full-check packet, and treat the key gates as the owner decides.

**Acceptance.** The IR-061 test in the table above.

### FE-10: Next actions from the gate state

Size M. After FE-4. Waits on `provisional-recording` for the provisional step's action.

**Scope.** Derive `next_actions` from the gate state, as REQ-20's proposal says once the owner approves it, and fill the arguments the server knows.

**Acceptance.** Tests for an open human gate (`flow.record_decision`, `needs_user` true), a refused transition (the step that comes first), and a passing fast check on a staged gate (the provisional step, as the owner decides).

### FE-11: Tool calls against flow.stage

Size S. After FE-4. Waits on `tool-stage-check`.

**Scope.** A stage check the Phase 3 tools call before a writing operation, for the tools the owner names.

**Acceptance.** A test where a named writing call at the wrong stage is refused with a reason and a next action, and a read-only call is not checked.

### FE-12: The design freeze

Size M. After FE-5. Needs `version-snapshots`, and waits on `freeze-digest`.

**Scope.** On the design-freeze approval, record `flow.frozen` on the sealed version with the assessment's evidence digest, and handle a refused assessment as the owner decides.

**Acceptance.** A freeze test that seals a version and records its digest, and one for a refused assessment that follows the owner's answer.

### FE-13: The flow end to end through the services

Size M. After FE-6, FE-7 and FE-10. Needs `selection-assessment` for the selection digest.

**Scope.** An end-to-end flow test from GROUND to LAYOUT on a synthetic record, through the engine's services only.

**Acceptance.** The IR-083 test in the table above, which also refreshes the selection digest.
