---
spec: approvals
title: Decision records and scoped re-approval
status: draft
capabilities:
  - decision-records
  - scoped-reapproval
questions:
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
    - id: IR-087
      to: design-recheck
      reason: >-
        A recheck stamp binds to the transition a decision approves, which AP-2 records. The register puts the entry in
        Phase 2, and the catalogue gives design-recheck no phase; the open question no-phase asks the owner.
blocks:
  - id: AP-9
    title: The transition request in the flow contract
    size: S
    requirements: [REQ-2, REQ-20]
    depends_on: []
  - id: AP-1
    title: The decision writer
    size: M
    requirements: [REQ-1, REQ-2, REQ-3, REQ-4]
    depends_on: [AP-9]
  - id: AP-2
    title: Decisions for undeclared transitions
    size: S
    requirements: [REQ-5, REQ-19]
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
    depends_on: [AP-1, FE-4]
  - id: AP-5
    title: The approval scope in the decision contract
    size: M
    requirements: [REQ-8, REQ-9]
    depends_on: [AP-1, capability:evidence-assessment]
  - id: AP-6
    title: Changed since approval
    size: M
    requirements: [REQ-10, REQ-11, REQ-12, REQ-13, REQ-19]
    depends_on: [AP-5, FE-1, FE-4]
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

Baseline: pointers checked against `main` at `58dea29e`.

## Capabilities

- [`decision-records`](../architecture/capabilities.md#decision-records): record who approved what, through which channel, with the user's words quoted. The engine writes `hw/decisions/` itself, including its own VOIDs. Tool: `flow.transition` (planned, Phase 3), which the owner chose on 2026-11-27 over the dropped `flow.record_decision` and `flow.record_provisional` (`docs/contract/flow.md:62`). Contracts: `flow/flow#/$defs/GateDecisionRequest`, `record/decision`.
- [`scoped-reapproval`](../architecture/capabilities.md#scoped-reapproval): an approval records the items it covers with their fingerprints, and a later change reopens only the changed items. No tool of its own. Contracts: `flow/flow#/$defs/ApprovalScope`, `flow/flow#/$defs/ApprovedItemState`.

## Problem and users

The prototype's agent writes decision files by hand, and a later change to something an earlier gate approved leaves that approval recorded as if nothing changed (`docs/adr/0019-scoped-reapproval.md:13`). Reopening the whole stage throws away approved work the change doesn't touch. ADR-0019 has an approval cover named items, and a change reopen only those.

- **The user** approves gates, and later confirms only the items that changed, each shown with a diff.
- **The agent** records decisions through the engine and never edits `hw/decisions/`.
- **A migrated project** carries prototype approvals that list no items. The next human gate confirms them (`docs/phases/phase-0-1.md:133`).

## Requirements

- **REQ-1.** The engine writes each decision as `hw/decisions/DR-###-<slug>.md` in the record version 3 shape: front matter with `id` matching the file name, `title`, `date` and a discriminated `kind`. Numbering continues after the highest record, and a number that is taken is refused. Source: `docs/contract/record-migration.md:35-37` for the shape, `reference/skills/cad-record/tests/test_decision_records.py:112-124` for the numbering, `docs/contract/flow.md:54`, `docs/design-plan.md:161`.
- **REQ-2.** A human gate's `flow.transition` carries an `approval` of channel `chat` or `app`, with `by` and `quote`, both non-blank, unless the gate's mode is `auto`, when the engine records `channel: auto`. A VOID the user names is `decision: void` with an approval, and cites the provisional decision it withdraws. `form` is refused. Source: `docs/contract/flow.md:56-59`, `docs/contract/flow.md:66-67`.
- **REQ-3.** An approval records the channel and the user's words. Source: `docs/design-plan.md:618`.
- **REQ-4.** The engine supplies the citation of the decision that accepts unproved between-sample intervals from the record: the decision on the same version. The request has no field for it. Source: `docs/contract/flow.md:60`, `docs/phases/phase-0-1.md:132`.
- **REQ-5.** A decision for a gate whose transition the flow doesn't declare, such as a backward gate, is refused when the engine writes it and is a finding when validate meets it in the record. A decision states the transition it approves (RULE-35). Source: IR-081.
- **REQ-6.** The design-decision contract holds several chosen options and a carry-forward disposition. Source: IR-084. The field names are a **Proposal** for the owner in AP-3.
- **REQ-7.** The engine records the provisional decision of a staged gate itself, on `flow.transition` with a `version` and no `approval`. The step is refused unless every fast check for that version passed and is current, its fingerprints matching. The decision has `channel: auto` and cites the evidence. The step is idempotent per gate and version, and it refuses an `approval`. Source: `docs/design-plan.md:621`, `docs/contract/flow.md:12`, `docs/contract/flow.md:65`.
- **REQ-8.** Each human-gate approval lists the items it approved, each with its kind, id and fingerprint at approval time, and the decision contract refers to `ApprovalScope`. The fingerprint is computed the way the evidence service fingerprints its inputs. Source: `docs/adr/0019-scoped-reapproval.md:19`, `docs/contract/flow.md:66`, `docs/contract/flow.md:70`.
- **REQ-9.** AP-5 uses the evidence service's fingerprint unchanged (`packages/benchhand-core/src/benchhand_core/record/evidence/fingerprints.py:508-517`). It digests the record's values per domain, with each relied-on file's SHA-256 under its path (`packages/benchhand-core/src/benchhand_core/record/evidence/fingerprints.py:223-228`), and reads no modification time. Changed bytes change it, and so does a moved file, which then asks for re-approval. **Proposal** for the owner: the fingerprint also covers the digest of the code that computed the evidence, so a fact holds only for its input hashes and that code. That changes the evidence service's fingerprint for every consumer, so it goes to `evidence-assessment` with a compatibility review, not into AP-5.
- **REQ-10.** An approved item whose fingerprint differs from the one recorded at approval is `changed_since_approval`. The stage and `flow.stage` stay where they are, and the other items and their evidence stay valid. Source: `docs/adr/0019-scoped-reapproval.md:20`, `docs/contract/flow.md:68`.
- **REQ-11.** `reapproval_scope`, a CEL expression in `flow.yaml`, selects the approved items a change affects, and the loader checks it at start. Source: `docs/contract/flow.md:67`, `docs/adr/0019-scoped-reapproval.md:25`, `docs/design-plan.md:161`.
- **REQ-12.** A new part, joint or interface is not a change to an approval. It goes through the current stage's checks and shows at the next gate as an addition. Source: `docs/adr/0019-scoped-reapproval.md:22`.
- **REQ-13.** An approval binds to its gate, its version and its evidence digest. Changed evidence shows as changed since approval and needs a new approval. Source: IR-060.
- **REQ-14.** The next human gate lists each changed item with a diff against what was approved. Approving the gate re-approves those items, and the new decision cites the original one. Source: `docs/adr/0019-scoped-reapproval.md:21`, `docs/adr/0019-scoped-reapproval.md:30`.
- **REQ-15.** A stage with a changed item can't freeze or release until the item is confirmed. Source: `docs/adr/0019-scoped-reapproval.md:21`, `docs/contract/flow.md:79`.
- **REQ-16.** A flow test: a change to an approved item reopens only that item's approval, and the next gate shows its diff. Source: `docs/design-plan.md:620`, `docs/adr/0019-scoped-reapproval.md:29`.
- **REQ-17.** A migrated decision has no approval scope. It needs confirmation at the next human gate, and it doesn't cover the whole stage. Source: `docs/adr/0019-scoped-reapproval.md:35`, `docs/contract/record-migration.md:137`. Migrate removes a prototype decision's `gate` key and keeps it `kind: design`, with only an info finding to show it was a gate approval (`packages/benchhand-core/src/benchhand_core/record/migrate/decisions.py:79-100`). How the engine tells such a decision from an ordinary design decision after a reload, and how the confirmation is recorded, wait on `unscoped-confirmation`.
- **REQ-18.** Whether a stage can freeze or release before that confirmation follows the owner's answer to `unscoped-freeze` (`docs/adr/0019-scoped-reapproval.md:37`).
- **REQ-19.** A gate decision persists what it is bound to. A decision states the transition it approves (RULE-35), and an edge has its own `from` and `to` (`contracts/flow/flow.tsp:115-119`), while `gate_decision` stores only the gate and one stage (`contracts/record/decision.tsp:59-79`). **Proposal** for the owner: `gate_decision` gains `transition`, the `from` and `to` stages of the declared edge, and `evidence_sha256`, the assessment's canonical digest at the decision, the digest a freeze anchors (`contracts/record/product.tsp:325-330`). Both are optional in the contract, so a migrated record stays valid, and the writer always fills them: a minor bump (`docs/contract/versioning.md:86`).
- **REQ-20.** `GateDecisionRequest` becomes the request of `flow.transition`, `{to?, version?, decision?, approval?}`: `to` names the stage, `version` the built version, `decision` a `void`, and `approval` the human channel, who and their words. Source: `docs/contract/flow.md:62`.

## Interfaces

- **MCP tools**, Phase 3: `flow.transition` (planned) takes the transition request of AP-9. `flow.record_decision` and `flow.record_provisional` are dropped.
- **CLI:** none.
- **Contracts:**
  - changed: `record/decision`'s `gate_decision` (`contracts/record/decision.tsp:59`) refers to `ApprovalScope` for a human-gate approval (AP-5), a minor bump;
  - changed: `record/decision`'s `design_decision` (`contracts/record/decision.tsp:86`) gains the chosen options and the carry-forward disposition (AP-3), a minor bump;
  - changed: `gate_decision` gains `transition` (AP-2) and `evidence_sha256` (AP-6), as REQ-19 proposes, each a minor bump;
  - changed: `flow/flow`'s `GateDecisionRequest` becomes the transition request (AP-9). Its fields change, so the bump follows `docs/contract/versioning.md` while the contract is provisional;
  - read: `flow/flow`'s `ApprovalScope`, `ApprovedItemState` and `reapproval_scope`. They stay provisional until AP-6 merges, and then the owner decides whether they leave `x-status: provisional`.
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
- Recheck stamps (IR-087): the `design-recheck` capability, deferred above. It reads the transition that AP-2 records.
- Refusing a release while an item is unconfirmed: `release-packaging`, Phase 4. AP-7 gives it the unconfirmed items, and refuses the freeze itself.
- Making the fingerprint cover the code digest, REQ-9's proposal: `evidence-assessment`.

## Open questions

| Question | Blocking | Blocks that wait |
|---|---|---|
| [`unscoped-confirmation`](../architecture/capabilities.md#unscoped-confirmation) | yes | AP-8 |
| [`unscoped-freeze`](../architecture/capabilities.md#unscoped-freeze) | yes | AP-8 |

## Blocks

### AP-9: The transition request in the flow contract

Size S. No dependencies.

**Scope.** In TypeSpec, `GateDecisionRequest` becomes the request of `flow.transition` as REQ-20 gives it, and the generated files and the reference pages follow. The envelope example that names `flow.record_provisional` (`contracts/envelope/envelope.tsp:105`) names `flow.transition`.

**Acceptance.** `just contracts-check` is clean and records the bump. Contract tests validate a provisional step with only `to` and `version`, a human-gate approval, and a `void` with its approval, and refuse `form` and a blank quote.

### AP-1: The decision writer

Size M. No dependencies.

**Scope.** A service that turns a transition request, or the engine's own VOID or provisional step, into a version 3 decision file, with numbering, the index, and the interval citation of REQ-4. It writes through the record store.

**Acceptance.** Ported `test_decision_records.py` write and index cases, against the version 3 shape:

- the first record is DR-001, and numbering continues after the highest;
- a taken number is refused and leaves the directory unchanged;
- the next write overwrites a hand edit of the index.

Request tests for REQ-2: `form`, a blank quote, and a `void` without its provisional are each refused. An interval-acceptance test for REQ-4: the engine cites the accepting decision on the decided version, and not one on an earlier version.

### AP-2: Decisions for undeclared transitions

Size S. After AP-1 and FE-1.

**Scope.** Add `transition` to `gate_decision` in TypeSpec, as the owner approves REQ-19, and regenerate. The writer records the declared edge a decision approves, and refuses one whose transition the loaded flow doesn't declare. Validate reports such a decision in the record.

**Acceptance.** The IR-081 test in the table above. A flow with two edges through one gate: a decision for one edge doesn't authorise the other.

### AP-3: Several chosen options and a carry-forward disposition

Size M. No dependencies.

**Scope.** Add the chosen options and the carry-forward disposition to `design_decision` in TypeSpec, as the owner approves their names, and regenerate. The writer and the reader handle them.

**Acceptance.** The IR-084 test in the table above. `just contracts-check` records the minor bump, and the migrate reference test still passes.

### AP-4: Recording a provisional approval

Size S. After AP-1 and FE-4.

**Scope.** The provisional step of REQ-7: check that every fast check for the named version passed and is current, write the provisional decision with `channel: auto` and its evidence, and return the existing decision on a repeat.

**Acceptance.** Tests:

- passing, current fast checks give one provisional decision with `channel: auto` that cites the evidence;
- a repeat for the same gate and version writes nothing and returns that decision;
- a failing fast check, and a passing one whose fingerprints no longer match, are each refused with the check to run in `next_actions`;
- a step without `version`, and one with an `approval`, are refused.

### AP-5: The approval scope in the decision contract

Size M. After AP-1. Needs `evidence-assessment`'s fingerprints.

**Scope.** Make `gate_decision` refer to `ApprovalScope` for a human-gate approval, and have the writer fill each item's fingerprint from the evidence service. Apply REQ-9 once the owner approves it.

**Acceptance.** A decision test where an approval of two interfaces and a part records three items with their fingerprints. A fingerprint test where changing a byte of a relied-on file changes the item's fingerprint, and touching its modification time without changing its bytes keeps it.

### AP-6: Changed since approval

Size M. After AP-5 and FE-1.

**Scope.** Compute each approved item's `ApprovedItemState` from the record, evaluate `reapproval_scope` for a change, and keep a new item as an addition. Add `evidence_sha256` to `gate_decision`, as the owner approves REQ-19, and bind an approval to its gate, transition, version and that digest.

**Acceptance.** The IR-060 test in the table above, across a reread: approve, change an evidence file, reload the record from disk, and the approval no longer authorises the advance. A test where changing one of two approved interfaces marks only that one `changed_since_approval` and leaves `flow.stage` unchanged, and one where a new part is an addition with no earlier stage reopened.

### AP-7: Confirmation at the next human gate

Size M. After AP-6, FE-4 and FE-12.

**Scope.** At the next human gate, list the changed items with their diffs. Approving the gate re-approves them in a decision that cites the original. A freeze is refused while an item is unconfirmed. A service lists the unconfirmed items, which `release-packaging` reads to refuse a release in Phase 4.

**Acceptance.** The plan's flow test of REQ-16. A freeze refused while one item is `changed_since_approval`, and allowed after the next gate confirms it. The unconfirmed-items service lists that item before the confirmation and nothing after it.

### AP-8: Migrated decisions without a scope

Size M. After AP-7. Waits on `unscoped-confirmation` and `unscoped-freeze`.

**Scope.** A migrated record reached its stage through prototype gate decisions that migrate turned into design decisions (`docs/contract/record-migration.md:135`). Find those decisions by the means the owner picks in `unscoped-confirmation`, treat them as covering no items so the next human gate confirms them, and record that confirmation as the owner decides.

**Acceptance.** A test on a migrated synthetic record that holds a former gate approval and an ordinary design decision. After a reload, the next human gate asks to confirm only the former, and records the confirmation. Whether the stage freezes first follows the owner's answer.
