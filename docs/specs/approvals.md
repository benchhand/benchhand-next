---
spec: approvals
title: Decision records and scoped re-approval
status: draft
capabilities:
  - decision-records
  - scoped-reapproval
questions:
  - provisional-recording
  - unscoped-confirmation
  - unscoped-freeze
rules:
  - RULE-05
  - RULE-35
issues:
  closes:
    - id: IR-060
      block: AP-6
      test: test_an_approval_whose_evidence_digest_changed_no_longer_authorises_the_advance
    - id: IR-081
      block: AP-2
      test: test_a_decision_for_an_undeclared_backward_gate_is_refused_when_written_and_a_finding_in_the_record
    - id: IR-084
      block: AP-3
      test: test_a_design_decision_records_two_chosen_options_and_a_carry_forward_disposition
  defers:
    - id: IR-061
      to: gate-policy
      reason: Which gates close without the user is gate policy; the decision it writes is AP-1's.
    - id: IR-083
      to: flow-engine
      reason: Its acceptance test is the flow end to end, which FE-13 runs on AP-1's writer.
blocks:
  - id: AP-1
    title: The decision writer
    size: M
    requirements: [REQ-1, REQ-2, REQ-3, REQ-4]
    depends_on: []
  - id: AP-2
    title: Decisions for undeclared transitions
    size: S
    requirements: [REQ-5]
    depends_on: [AP-1, FE-1]
  - id: AP-3
    title: Several chosen options and a carry-forward disposition
    size: M
    requirements: [REQ-6]
    depends_on: []
  - id: AP-4
    title: Recording a provisional approval
    size: S
    requirements: [REQ-7]
    depends_on: [AP-1, FE-4, question:provisional-recording]
  - id: AP-5
    title: The approval scope in the decision contract
    size: M
    requirements: [REQ-8, REQ-9]
    depends_on: [AP-1, capability:evidence-assessment]
  - id: AP-6
    title: Changed since approval
    size: M
    requirements: [REQ-10, REQ-11, REQ-12, REQ-13]
    depends_on: [AP-5, FE-1]
  - id: AP-7
    title: Confirmation at the next human gate
    size: M
    requirements: [REQ-14, REQ-15, REQ-16]
    depends_on: [AP-6, FE-4, FE-12]
  - id: AP-8
    title: Migrated decisions without a scope
    size: M
    requirements: [REQ-17, REQ-18]
    depends_on: [AP-7, question:unscoped-confirmation, question:unscoped-freeze]
---

# Decision records and scoped re-approval

Status: draft, 2026-11-27, written against `main` at `4c783f55`. Waiting for the owner's review.

## Capabilities

- [`decision-records`](../architecture/capabilities.md#decision-records): record who approved what, through which channel, with the user's words quoted. The engine writes `hw/decisions/` itself, including its own VOIDs. Tools: `flow.record_decision` (planned, Phase 3) and `flow.record_provisional` (unresolved). Contracts: `flow/flow#/$defs/GateDecisionRequest`, `record/decision`.
- [`scoped-reapproval`](../architecture/capabilities.md#scoped-reapproval): an approval records the items it covers with their fingerprints, and a later change reopens only the changed items. No tool of its own. Contracts: `flow/flow#/$defs/ApprovalScope`, `flow/flow#/$defs/ApprovedItemState`.

## Problem and users

The prototype's agent writes decision files by hand, and a later change to something an earlier gate approved leaves that approval recorded as if nothing changed (`docs/adr/0019-scoped-reapproval.md:13`). Reopening the whole stage throws away approved work the change doesn't touch. ADR-0019 has an approval cover named items, and a change reopen only those.

- **The user** approves gates, and later confirms only the items that changed, each shown with a diff.
- **The agent** records decisions through the engine and never edits `hw/decisions/`.
- **A migrated project** carries prototype approvals that list no items. The next human gate confirms them (`docs/phases/phase-0-1.md:133`).

## Requirements

- **REQ-1.** The engine writes each decision as `hw/decisions/DR-###-<slug>.md` in the record version 3 shape: front matter with `id` matching the file name, `title`, `date` and a discriminated `kind`. Numbering continues after the highest record, and a number that is taken is refused. Source: `docs/contract/record-migration.md:35-37`, `docs/contract/flow.md:54`, `docs/design-plan.md:161`.
- **REQ-2.** A `GateDecisionRequest` is `approved` or `void`. A `void` needs `app` or `chat` and cites the provisional decision it withdraws. `form` is refused, and every channel but `auto` names who decided and quotes them, both non-blank. Source: `docs/contract/flow.md:56-59`.
- **REQ-3.** An approval records the channel and the user's words. Source: `docs/design-plan.md:618`.
- **REQ-4.** The engine supplies the citation of the decision that accepts unproved between-sample intervals from the record; the request has no field for it. Source: `docs/contract/flow.md:60`, `docs/phases/phase-0-1.md:132`.
- **REQ-5.** A decision for a gate whose transition the flow doesn't declare, such as a backward gate, is refused when the engine writes it and is a finding when validate meets it in the record. A decision states the transition it approves (RULE-35). Source: IR-081.
- **REQ-6.** The design-decision contract holds several chosen options and a carry-forward disposition. Source: IR-084. The field names are a **Proposal** for the owner in AP-3.
- **REQ-7.** A provisional approval is recorded after the fast checks pass, by the party the owner names. Source: `docs/design-plan.md:621`, `docs/contract/flow.md:12`. Waits on `provisional-recording`.
- **REQ-8.** Each human-gate approval lists the items it approved, each with its kind, id and fingerprint at approval time, and the decision contract refers to `ApprovalScope`. The fingerprint is computed the way the evidence service fingerprints its inputs. Source: `docs/adr/0019-scoped-reapproval.md:19`, `docs/contract/flow.md:66`, `docs/contract/flow.md:70`.
- **REQ-9.** An approved item's fingerprint keys on the hashes of its inputs and the code digest, never on a path or a modification time. **Proposal** for the owner, from the agentcad product-test lessons that the supervisor passed on (finding 1, the invalidation rule); the prompt isn't in the repository. REQ-8 already ties the fingerprint to the evidence service's.
- **REQ-10.** An approved item whose fingerprint differs from the one recorded at approval is `changed_since_approval`. The stage and `flow.stage` stay where they are, and the other items and their evidence stay valid. Source: `docs/adr/0019-scoped-reapproval.md:20`, `docs/contract/flow.md:68`.
- **REQ-11.** `reapproval_scope`, a CEL expression in `flow.yaml`, selects the approved items a change affects, and the loader checks it at start. Source: `docs/contract/flow.md:67`, `docs/adr/0019-scoped-reapproval.md:25`, `docs/design-plan.md:161`.
- **REQ-12.** A new part, joint or interface is not a change to an approval. It goes through the current stage's checks and shows at the next gate as an addition. Source: `docs/adr/0019-scoped-reapproval.md:22`.
- **REQ-13.** An approval binds to its gate, its version and its evidence digest. Changed evidence shows as changed since approval and needs a new approval. Source: IR-060.
- **REQ-14.** The next human gate lists each changed item with a diff against what was approved. Approving the gate re-approves those items, and the new decision cites the original one. Source: `docs/adr/0019-scoped-reapproval.md:21`, `docs/adr/0019-scoped-reapproval.md:30`.
- **REQ-15.** A stage with a changed item can't freeze or release until the item is confirmed. Source: `docs/adr/0019-scoped-reapproval.md:21`, `docs/contract/flow.md:79`.
- **REQ-16.** A flow test: a change to an approved item reopens only that item's approval, and the next gate shows its diff. Source: `docs/design-plan.md:620`, `docs/adr/0019-scoped-reapproval.md:29`.
- **REQ-17.** A migrated decision has no approval scope. It needs confirmation at the next human gate, and it doesn't cover the whole stage. Source: `docs/adr/0019-scoped-reapproval.md:35`, `docs/contract/record-migration.md:137`. How the confirmation is recorded waits on `unscoped-confirmation`.
- **REQ-18.** Whether a stage can freeze or release before that confirmation follows the owner's answer to `unscoped-freeze` (`docs/adr/0019-scoped-reapproval.md:37`).

## Interfaces

- **MCP tools**, Phase 3: `flow.record_decision` (planned) takes a `GateDecisionRequest`. `flow.record_provisional` stays unresolved until `provisional-recording` is answered.
- **CLI:** none.
- **Contracts:**
  - changed: `record/decision`'s `gate_decision` (`contracts/record/decision.tsp:59`) refers to `ApprovalScope` for a human-gate approval (AP-5), a minor bump;
  - changed: `record/decision`'s `design_decision` (`contracts/record/decision.tsp:86`) gains the chosen options and the carry-forward disposition (AP-3), a minor bump;
  - read: `flow/flow`'s `GateDecisionRequest`, `ApprovalScope`, `ApprovedItemState` and `reapproval_scope`. They stay provisional until AP-6 merges, and then the owner decides whether they leave `x-status: provisional`.
- **Provider methods:** none.
- **Code:** the decision writer in `packages/benchhand-core` (the reference map's home for `decision_records.py`), the item states beside the interpreter, and validate's decision rules (`packages/benchhand-core/src/benchhand_core/record/rules/decisions.py:104`).

## Issue register

| Entry | Disposition | Block | Test |
|---|---|---|---|
| IR-060 | already-covered | AP-6 | `test_an_approval_whose_evidence_digest_changed_no_longer_authorises_the_advance` |
| IR-081 | port-fix | AP-2 | `test_a_decision_for_an_undeclared_backward_gate_is_refused_when_written_and_a_finding_in_the_record` |
| IR-084 | already-covered | AP-3 | `test_a_design_decision_records_two_chosen_options_and_a_carry_forward_disposition` |

IR-084 is the plan's `c7q.3` (`docs/design-plan.md:565`).

| Entry | Deferred to | Why |
|---|---|---|
| IR-061 | `gate-policy` | Gate policy decides which gates close without the user. |
| IR-083 | `flow-engine` | Its test is the flow end to end (FE-13). |

## Prototype behaviour replaced

| Prototype | Inventory | Replaced by | Oracle tests |
|---|---|---|---|
| `decision_records.py` `write_decision` | `docs/architecture/prototype-inventory.md:2219` | the decision writer (AP-1) | `reference/skills/cad-record/tests/test_decision_records.py:83-124` |
| `decision_records.py` `regenerate_index` | `docs/architecture/prototype-inventory.md:2218` | the writer's index | `reference/skills/cad-record/tests/test_decision_records.py:411-440` |
| `decision_records.py` `parse_record`, `read_decisions` | `docs/architecture/prototype-inventory.md:2212-2214` | the record store's decision reader, on `main` | `reference/skills/cad-record/tests/test_decision_records.py:203-377` |
| `validate.py` `approval_problem`, `decision_approves` | `docs/architecture/prototype-inventory.md:2660-2661` | validate's decision rules, and AP-2 | `reference/skills/cad-record/tests/test_validate.py:463`, `reference/skills/cad-record/tests/test_validate.py:541` |

The prototype writes MADR 4.0.0 files with a `gate: {from, to}` key. Record version 3 has `kind: gate` instead, and migrate maps the old files (`docs/contract/record-migration.md:135`). The blocks port the oracle cases against the version 3 shape.

## Non-goals

- The gate packet and its "changed since approval" section on screen: the Phase 3 `gate-packet` capability. AP-7 gives it the items and their diffs.
- Working out what a change affects across the record's dependency domains: `change-impact`, which builds on AP-6.
- The VOID cascade: the [flow engine spec](flow-engine.md), FE-6, on AP-1's writer.
- Recheck stamps (IR-087): the `design-recheck` capability, which has no phase.

## Open questions

| Question | Blocking | Blocks that wait |
|---|---|---|
| [`provisional-recording`](../architecture/capabilities.md#provisional-recording) | yes | AP-4, and FE-10 in the flow engine spec |
| [`unscoped-confirmation`](../architecture/capabilities.md#unscoped-confirmation) | yes | AP-8 |
| [`unscoped-freeze`](../architecture/capabilities.md#unscoped-freeze) | yes | AP-8 |

## Blocks

### AP-1: The decision writer

Size M. No dependencies.

**Scope.** A service that turns a `GateDecisionRequest`, or the engine's own VOID, into a version 3 decision file, with numbering, the index, and the interval citation of REQ-4. It writes through the record store.

**Acceptance.** Ported `test_decision_records.py` write and index cases, against the version 3 shape:

- the first record is DR-001, and numbering continues after the highest;
- a taken number is refused and leaves the directory unchanged;
- the next write overwrites a hand edit of the index.

Request tests for REQ-2: `form`, a blank quote, and a `void` without its provisional are each refused.

### AP-2: Decisions for undeclared transitions

Size S. After AP-1 and FE-1.

**Scope.** The writer refuses a gate decision whose gate and stage don't match a declared edge of the loaded flow, and validate reports such a decision in the record.

**Acceptance.** The IR-081 test in the table above.

### AP-3: Several chosen options and a carry-forward disposition

Size M. No dependencies.

**Scope.** Add the chosen options and the carry-forward disposition to `design_decision` in TypeSpec, as the owner approves their names, and regenerate. The writer and the reader handle them.

**Acceptance.** The IR-084 test in the table above. `just contracts-check` records the minor bump, and the migrate reference test still passes.

### AP-4: Recording a provisional approval

Size S. After AP-1 and FE-4. Waits on `provisional-recording`.

**Scope.** Record the provisional decision of a staged gate after its fast checks pass, through the tool or the interpreter that the owner names.

**Acceptance.** A flow test where passing fast checks give one provisional decision, and failing ones give none and a refusal.

### AP-5: The approval scope in the decision contract

Size M. After AP-1. Needs `evidence-assessment`'s fingerprints.

**Scope.** Make `gate_decision` refer to `ApprovalScope` for a human-gate approval, and have the writer fill each item's fingerprint from the evidence service. Apply REQ-9 once the owner approves it.

**Acceptance.** A decision test where an approval of two interfaces and a part records three items with their fingerprints. Once the owner approves REQ-9, a fingerprint test where moving a file without changing its bytes keeps the fingerprint, and changing a byte changes it.

### AP-6: Changed since approval

Size M. After AP-5 and FE-1.

**Scope.** Compute each approved item's `ApprovedItemState` from the record, evaluate `reapproval_scope` for a change, keep a new item as an addition, and bind an approval to its gate, version and evidence digest.

**Acceptance.** The IR-060 test in the table above. A test where changing one of two approved interfaces marks only that one `changed_since_approval` and leaves `flow.stage` unchanged, and one where a new part is an addition with no earlier stage reopened.

### AP-7: Confirmation at the next human gate

Size M. After AP-6, FE-4 and FE-12.

**Scope.** At the next human gate, list the changed items with their diffs. Approving the gate re-approves them in a decision that cites the original. A freeze or a release is refused while an item is unconfirmed.

**Acceptance.** The plan's flow test of REQ-16. A freeze refused while one item is `changed_since_approval`, and allowed after the next gate confirms it.

### AP-8: Migrated decisions without a scope

Size M. After AP-7. Waits on `unscoped-confirmation` and `unscoped-freeze`.

**Scope.** A migrated record reached its stage through prototype gate decisions that migrate turned into design decisions (`docs/contract/record-migration.md:135`). Treat those approvals as covering no items, so the next human gate confirms them, and record that confirmation as the owner decides.

**Acceptance.** A test on a migrated synthetic record whose approvals have no scope. The next human gate asks to confirm them and records the confirmation. Whether the stage freezes first follows the owner's answer.
