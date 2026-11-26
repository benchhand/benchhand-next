# ADR-0019: A design change reopens the approvals it touches, not the stage

Status: accepted. Source: the owner, 2026-11-26. It refines [ADR-0014](0014-flow-rules-cel.md) and section 5 of [the plan](../design-plan.md).

## Context

The prototype at the reference commit (`skills/cad-flow/references/flow.md`) handles a design change in three ways:

- **During a stage:** the change is the next commit batch. Nothing is reopened.
- **At the stage's own human gate:** a change the user names voids the provisional approval. It reopens that stage and every later stage built on the version ("Gate control", the VOID cascade).
- **After DESIGN freeze:** an engineering change reopens only the affected parts and their dependents. Unaffected parts keep their evidence.

Sometimes a later stage changes something an earlier human gate approved. Examples: L3 changes a LAYOUT interface, or a joint goes from heat-set to press-fit. The prototype only says to recheck with `flow.recheck_from` and "applicable earlier-stage checks". The earlier human approval stays recorded as if nothing changed, although the user approved something else. Reopening the whole earlier stage is the other choice, and it throws away approved work the change doesn't touch.

## Decision

An approval covers named items, and a change reopens the approval of the items it changes:

1. **Approvals record their scope.** Each human-gate decision lists the items it approved, such as interfaces, the envelope, parts, joint choices and the concept. It records each item's fingerprint at approval time, computed the way the evidence service fingerprints its inputs.
2. **A change marks only the affected items.** If an approved item's fingerprint differs from the one recorded at approval, that item's approval is `changed_since_approval`. The stage and `flow.stage` stay where they are. Other approved items, and their evidence, stay valid.
3. **Confirmation happens at the next human gate.** The gate packet lists each changed item with a diff against what was approved. Approving the gate re-approves those items; a new decision cites the original one. A stage with a changed item can't freeze or release until the item is confirmed.
4. **A new item is not a change to an approval.** A new part, joint or interface goes through the current stage's checks and shows at the next gate as an addition. No earlier stage reopens.
5. **Existing rules stay.** VOID at the stage's own gate, and the engineering change after freeze (affected parts and dependents), work as in the prototype.

Deciding which items a change affects is CEL in `flow.yaml` (ADR-0014), next to `void_scope`.

## Consequences

- Phase 2 adds an approval-scope field to the decision contract, the fingerprint comparison, and the `changed_since_approval` status. It also adds the flow test "a change to an approved item reopens only that item".
- Gate packets grow a "changed since approval" section.
- This differs from the prototype. The migrate rules can't attach a scope to existing prototype approvals, so migrated decisions have none. The Phase 2 design must say how a decision without a scope is treated, either as covering the whole stage or as needing confirmation at the next gate. That choice is open.
