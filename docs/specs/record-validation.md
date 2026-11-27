---
spec: record-validation
title: Record validation and migration in Phase 2
status: draft
capabilities:
  - record-validate
  - record-migrate
questions:
  - validate-surface
  - record-migrate-tool
  - standards-sourcing-phase
  - storage-layout-adr
rules:
  - RULE-05
  - RULE-08
  - RULE-22
issues:
  closes:
    - id: IR-055
      block: RV-2
      test: test_a_justified_not_applicable_row_is_accepted_by_the_evidence_assessment_and_an_unexplained_one_is_a_finding
    - id: IR-056
      block: RV-1
      test: test_shuffled_columns_and_a_byte_order_mark_read_every_row_and_a_missing_column_is_one_named_finding
    - id: IR-063
      block: RV-3
      test: test_a_trailing_colon_placeholder_text_and_a_missing_file_each_give_a_finding_before_release
    - id: IR-094
      block: RV-5
      test: test_a_welded_torque_path_with_its_joining_operation_validates_and_one_without_is_a_finding
  defers:
    - id: IR-029
      to: assembly-steps-and-coupons
      reason: A subassembly's own placement is a record/assembly change, which that capability owns in Phase 2.
    - id: IR-051
      to: version-snapshots
      reason: Verifying a released version against its seal, and validating its successor, needs the snapshots.
    - id: IR-060
      to: scoped-reapproval
      reason: Binding an approval to its gate, version and evidence digest is the approval scope.
    - id: IR-068
      to: selection-assessment
      reason: >-
        The occurrence resolver serves selection first, then change impact, process checks and drawings; its
        acceptance test runs through those readers.
    - id: IR-077
      to: selection-assessment
      reason: >-
        The flow test that takes an empty project from intent to layout needs the selection digest. RV-6 builds
        the validate half (REQ-6).
    - id: IR-085
      to: result-envelope
      reason: The finding-with-line and status-error test is an envelope test.
    - id: IR-136
      to: assembly-steps-and-coupons
      reason: The cylindrical joint is a record/assembly change.
    - id: IR-047
      to: existing-equipment
      reason: >-
        The not_applicable procurement reason is the record-contract change that IR-003 and RULE-36 put with
        existing equipment in Phase 2. The sourcing order through the standards-data package and parts.search is
        standards-parts-data, which the catalogue puts in Phase 4; the open question standards-sourcing-phase asks
        the owner.
blocks:
  - id: RV-1
    title: Verification rows by header name
    size: S
    requirements: [REQ-1]
    depends_on: []
  - id: RV-2
    title: A not_applicable verification result
    size: M
    requirements: [REQ-2]
    depends_on: []
  - id: RV-3
    title: Evidence paths that name a current file
    size: S
    requirements: [REQ-3]
    depends_on: []
  - id: RV-4
    title: Torque paths from design_rules.py
    size: M
    requirements: [REQ-4, REQ-7]
    depends_on: []
  - id: RV-5
    title: Welded, brazed and soldered torque paths
    size: S
    requirements: [REQ-5]
    depends_on: [RV-4]
  - id: RV-6
    title: Missing inputs only from the stage that produces them
    size: S
    requirements: [REQ-6]
    depends_on: []
  - id: RV-7
    title: Axial retainers from design_rules.py
    size: M
    requirements: [REQ-4, REQ-7]
    depends_on: []
  - id: RV-8
    title: Clearance margins from design_rules.py
    size: S
    requirements: [REQ-4, REQ-7]
    depends_on: []
  - id: RV-9
    title: Visibility bindings from design_rules.py
    size: S
    requirements: [REQ-4, REQ-7]
    depends_on: []
  - id: RV-10
    title: Clearance margins read from a version snapshot
    size: S
    requirements: [REQ-4]
    depends_on: [RV-8, capability:version-snapshots, question:storage-layout-adr]
---

# Record validation and migration in Phase 2

Baseline: pointers checked against `main` at `58dea29e`.

## Capabilities

- [`record-validate`](../architecture/capabilities.md#record-validate): check a whole record against its contracts and the cross-document rules, and report findings. Phase 1, partial: the library is on `main` (`packages/benchhand-core/src/benchhand_core/record/validate.py:47`) with no CLI or tool. Tool: `record.validate` (proposed, Phase 3). Contract: `common/finding`.
- [`record-migrate`](../architecture/capabilities.md#record-migrate): migrate a prototype record to record version 3 as a table of rules. Phase 1, built, with the CLI `benchhand record migrate`. Tool: `record.migrate` (unresolved). Contracts: `record/product`, `record/decision`.

Neither is a Phase 2 capability. This spec holds their Phase 2 work: the register's Phase 2 fixes in validate, the rest of the prototype's design rules, and the guard that keeps a migrated record valid as the rules grow.

## Problem and users

Direct edits of `hw/` are caught as findings, not prevented (`docs/design-plan.md:176`), so validate is the user's and the agent's only check on a record edited by hand. The register lists validate bugs that the prototype still has, and the reference map keeps `design_rules.py` for Phase 2 (`docs/architecture/reference-map.yaml:756-761`). Every rule added to validate must also keep the records that migrate produces valid, or a migrated project fails on a rule its prototype passed.

- **The user and the agent** read validate's findings after a direct edit.
- **The flow engine** validates every record before activation (the [flow engine spec](flow-engine.md), REQ-4).
- **Maintainers** port prototype rules and later prototype changes as migrate rows (ADR-0015).

## Requirements

- **REQ-1.** Verification rows are read by header name. A UTF-8 byte-order mark is accepted, and a missing or extra column is one finding that names it. Source: IR-056.
- **REQ-2.** The verification-row result gains `not_applicable`, which requires a reason or a decision id (IR-055). Validate's row coverage counts a justified row as the requirement's row (`packages/benchhand-core/src/benchhand_core/record/rules/verification.py:32-49`). The evidence assessment's verification check (`packages/benchhand-core/src/benchhand_core/record/evidence/assess.py:353-373`) accepts it as stated, and gives a finding for a row without a reason or decision, and for one whose decision id names no decision in the record (RULE-05). Release readiness reads that check in Phase 4, under `release-packaging`.
- **REQ-3.** validate checks the form of each evidence path and that its file exists, so a `pass` row always names a current artifact. A trailing colon, placeholder text and a missing file each give a finding before release. Source: IR-063.
- **REQ-4.** validate carries the rules of the prototype's `design_rules.py`: torque paths, axial retainers, clearance margins and visibility bindings, homed in `record/rules/interfaces.py`. Source: `docs/architecture/reference-map.yaml:756-761`, `docs/design-plan.md:610`.
- **REQ-5.** The torque-path type adds `weld`, `braze` and `solder`, each needing a joining operation on the route. Source: IR-094.
- **REQ-6.** validate reports a missing record document only from the stage that produces it, as it already does for the part records from LAYOUT on (`packages/benchhand-core/src/benchhand_core/record/validate.py:24`). Source: IR-077.
- **REQ-7.** Each rule added here keeps the migrate reference records clean: they still migrate and validate with no findings (`packages/benchhand-core/tests/record/test_migrate_service.py:52`). A new rule's tests use synthetic records, never test-project geometry (RULE-22), and a malformed document gives a named finding, never a crash (RULE-08). Source: `docs/design-plan.md:610`.

## Interfaces

- **MCP tools**, Phase 3: `record.validate` (proposed; which `record.*` tools exist waits on `validate-surface`) and `record.migrate` (unresolved; `record-migrate-tool`).
- **CLI:** `benchhand record migrate`, unchanged. No validate command (`docs/phases/phase-0-1.md:163`).
- **Contracts:**
  - changed: `record/verification-row` gains the `not_applicable` result with its reason or decision (RV-2), a minor bump. Release readiness, which reads it, is `release-packaging` in Phase 4;
  - changed: `record/assembly`'s `torque_path` type (`contracts/record/assembly.tsp:139`) gains `weld`, `braze` and `solder` (RV-5), a minor bump;
  - read: `common/finding`, unchanged.
- **Provider methods:** none.
- **Code:** `record/validate.py` and `record/rules/` in `packages/benchhand-core`.

A contract change here that renames or restructures a prototype field needs a migrate row and a fixture in the same block (`docs/design-plan.md:548`). Both changes above are additions, so neither needs a row.

## Issue register

| Entry | Disposition | Block | Test |
|---|---|---|---|
| IR-055 | contract | RV-2 | `test_a_justified_not_applicable_row_is_accepted_by_the_evidence_assessment_and_an_unexplained_one_is_a_finding` |
| IR-056 | port-fix | RV-1 | `test_shuffled_columns_and_a_byte_order_mark_read_every_row_and_a_missing_column_is_one_named_finding` |
| IR-063 | port-fix | RV-3 | `test_a_trailing_colon_placeholder_text_and_a_missing_file_each_give_a_finding_before_release` |
| IR-094 | contract | RV-5 | `test_a_welded_torque_path_with_its_joining_operation_validates_and_one_without_is_a_finding` |

| Entry | Deferred to | Why |
|---|---|---|
| IR-029 | `assembly-steps-and-coupons` | A record/assembly change that capability owns. |
| IR-051 | `version-snapshots` | Needs sealed versions. |
| IR-060 | `scoped-reapproval` | The approval scope binds it. |
| IR-068 | `selection-assessment` | Its test runs through the readers, selection first. |
| IR-077 | `selection-assessment` | Needs the selection digest; RV-6 builds the validate half. |
| IR-085 | `result-envelope` | An envelope test. |
| IR-136 | `assembly-steps-and-coupons` | A record/assembly change. |
| IR-047 | `existing-equipment` | The not_applicable procurement reason is that capability's contract change. Standards sourcing is `standards-parts-data`, Phase 4 in the catalogue: `standards-sourcing-phase` asks the owner. |

## Prototype behaviour replaced

| Prototype | Inventory | Replaced by | Oracle tests |
|---|---|---|---|
| `validate.py` `read_csv` | `docs/architecture/prototype-inventory.md:2643` | header-name reading (RV-1) | `reference/skills/cad-record/tests/test_validate.py:296` |
| `validate.py` `check_design_rules` | `docs/architecture/prototype-inventory.md:2669` | `record/rules/interfaces.py` (RV-4, RV-7, RV-8, RV-9) | `reference/skills/cad-record/tests/test_design_rules.py:88` |
| `design_rules.py` `clearance_margins` | `docs/architecture/prototype-inventory.md:2223` | RV-8, RV-10 | `reference/skills/cad-record/tests/test_design_rules.py:272-297` |
| `design_rules.py` `torque_path_findings` | `docs/architecture/prototype-inventory.md:2225` | RV-4, RV-5 | `reference/skills/cad-record/tests/test_design_rules.py:127-198` |
| `design_rules.py` `axial_retainer_findings` | `docs/architecture/prototype-inventory.md:2226` | RV-7 | `reference/skills/cad-record/tests/test_design_rules.py:92-114` |
| `design_rules.py` `visibility_findings` | `docs/architecture/prototype-inventory.md:2229` | RV-9 | `reference/skills/cad-record/tests/test_design_rules.py:334-362` |

The reference map leaves `check_motion_cases` and `check_release_readiness` for the Phase 4 motion and release tools (`docs/architecture/reference-map.yaml:888-896`). They stay out of this spec.

## Non-goals

- The `record.validate` and `record.migrate` tools and a validate CLI command: Phase 3, behind `validate-surface` and `record-migrate-tool`.
- The migrate rows of prototype PRs #331 to #341. They land with the contract changes that need them (`docs/phases/prototype-port-331-341.md`), under `existing-equipment` and `assembly-steps-and-coupons`.
- SARIF output of findings, homed in Phase 3 (`docs/architecture/reference-map.yaml:858-860`) behind the open `sarif-export` question.
- Release readiness and motion cases: Phase 4. Release readiness takes RV-2's `not_applicable` rows from the evidence assessment, under `release-packaging`.
- The standards-data sourcing order and `parts.search` of IR-047 and RULE-36: `standards-parts-data`, whose phase `standards-sourcing-phase` asks the owner.

## Open questions

| Question | Blocking | Blocks that wait |
|---|---|---|
| [`validate-surface`](../architecture/capabilities.md#validate-surface) | yes | no Phase 2 block: it names the Phase 3 tools |
| [`record-migrate-tool`](../architecture/capabilities.md#record-migrate-tool) | yes | no Phase 2 block: it decides the Phase 3 MCP path |
| [`standards-sourcing-phase`](../architecture/capabilities.md#standards-sourcing-phase) | yes | no block here: IR-047 is deferred to `existing-equipment` |
| [`storage-layout-adr`](../architecture/capabilities.md#storage-layout-adr) | yes | RV-10, which reads a snapshot under the record's layout |

## Blocks

### RV-1: Verification rows by header name

Size S. No dependencies.

**Scope.** Read `verification.csv` by its header names, strip a UTF-8 byte-order mark, and report a missing or an extra column by name.

**Acceptance.** The IR-056 test in the table above, and the migrate reference test still passes.

### RV-2: A not_applicable verification result

Size M. No dependencies.

**Scope.** Add `not_applicable` to the verification-row result in TypeSpec, with a reason or a decision id that the schema requires, and regenerate. Row coverage counts a justified row. The evidence assessment's verification check accepts it and reports an unexplained row or an unknown decision id. The release integration is `release-packaging`'s.

**Acceptance.** The IR-055 test in the table above: a row with its reason is accepted by the assessment's verification check and covers its requirement, and one that cites a decision the record doesn't have is a finding. Contract tests: a `not_applicable` row without a reason or decision fails the schema. `just contracts-check` records the minor bump.

### RV-3: Evidence paths that name a current file

Size S. No dependencies.

**Scope.** Check each evidence path's form and its file's existence in validate, with the evidence service's path rules.

**Acceptance.** The IR-063 test in the table above.

### RV-4: Torque paths from design_rules.py

Size M. No dependencies.

**Scope.** Port `torque_path_findings` into `record/rules/interfaces.py`, with its findings, as the oracle tests define them.

**Acceptance.** The cases of `reference/skills/cad-record/tests/test_design_rules.py:127-198`, ported against synthetic records. The migrate reference test still passes (REQ-7).

### RV-7: Axial retainers from design_rules.py

Size M. No dependencies.

**Scope.** Port `axial_retainer_findings` into `record/rules/interfaces.py`.

**Acceptance.** The cases of `reference/skills/cad-record/tests/test_design_rules.py:88-114`, ported against synthetic records. The migrate reference test still passes (REQ-7).

### RV-8: Clearance margins from design_rules.py

Size S. No dependencies.

**Scope.** Port `clearance_margins`, with the product default and the interface override, into `record/rules/interfaces.py`.

**Acceptance.** The cases of `reference/skills/cad-record/tests/test_design_rules.py:272-296` and `reference/skills/cad-record/tests/test_design_rules.py:369`, ported against synthetic records. The migrate reference test still passes (REQ-7).

### RV-9: Visibility bindings from design_rules.py

Size S. No dependencies.

**Scope.** Port `visibility_findings` into `record/rules/interfaces.py`.

**Acceptance.** The cases of `reference/skills/cad-record/tests/test_design_rules.py:329-362`, ported against synthetic records. The migrate reference test still passes (REQ-7).

### RV-10: Clearance margins read from a version snapshot

Size S. After RV-8. Needs `version-snapshots`, and waits on `storage-layout-adr` for where a version's record lives.

**Scope.** The clearance-margin rule reads its margins from a sealed version's record as well as from the working record.

**Acceptance.** The case of `reference/skills/cad-record/tests/test_design_rules.py:297`, ported against a synthetic sealed version.

### RV-5: Welded, brazed and soldered torque paths

Size S. After RV-4.

**Scope.** Add the three types to `torque_path` in `contracts/record/assembly.tsp` and regenerate. Require a joining operation on the route for each.

**Acceptance.** The IR-094 test in the table above. `just contracts-check` records the minor bump.

### RV-6: Missing inputs only from the stage that produces them

Size S. No dependencies.

**Scope.** Generalise validate's part-records rule to each record document, so a missing document is a finding only from the stage that produces it.

**Acceptance.** Validate tests: an INTENT-stage record without a layout gives no finding, and a LAYOUT-stage record without one does.
