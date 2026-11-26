# Design flow

The design flow as a state machine: the stages, the gates between them, PROVISIONAL, APPROVED and VOID, the VOID cascade and engineering change.
It is drawn by hand from the prototype's flow at the reference commit and plan section 5. Phase 2 will generate it from `flow.yaml`.

Nothing on this page runs on `main`. The flow engine is Phase 2 work. On `main`, the stage names are the `stage` enum of the record contract, and PROVISIONAL, APPROVED and VOID are the statuses of a gate decision record.

## Stages and gates

```mermaid
stateDiagram-v2
  direction TB
  state "INTENT gate<br/>single human" as intentGate
  state "VARIANT gate<br/>single human" as variantGate
  state "LAYOUT freeze<br/>PROVISIONAL, full check, human" as layoutGate
  state "PARTS gate<br/>PROVISIONAL, full check, human" as partsGate
  state "DETAIL gate<br/>PROVISIONAL, full check, human" as detailGate
  state "ANALYSIS gate<br/>PROVISIONAL, full check, human" as analysisGate
  state "DESIGN freeze<br/>single human" as freezeGate
  state "RELEASE gate<br/>single human" as releaseGate

  [*] --> ground
  ground --> intent
  intent --> intentGate
  intentGate --> specify: APPROVED
  specify --> concept
  concept --> variantGate
  variantGate --> layout: APPROVED
  layout --> layoutGate
  layoutGate --> parts: PROVISIONAL
  parts --> partsGate
  partsGate --> detail: PROVISIONAL
  detail --> detailGate
  detailGate --> bom: PROVISIONAL
  bom --> analysis
  analysis --> analysisGate
  analysisGate --> critique: PROVISIONAL
  critique --> reconcile
  reconcile --> design_freeze
  design_freeze --> freezeGate
  freezeGate --> releaseGate: APPROVED, flow.frozen set
  releaseGate --> release: APPROVED
  release --> [*]

  note right of layoutGate
    PROVISIONAL lets the next stage start.
    The human gate of the same stage
    opens later, after its full check.
  end note
  note right of freezeGate
    Opens only after every stage's
    human gate has passed.
    Nothing is frozen or released before.
  end note

  classDef gate fill:#ede7f6,stroke:#5e35b1,stroke-width:2px,color:#1b1b1b
  class intentGate, variantGate, layoutGate, partsGate, detailGate, analysisGate, freezeGate, releaseGate gate
```

## One two-gate stage

LAYOUT freeze, PARTS, DETAIL and ANALYSIS each approve a built version vN in three steps: PROVISIONAL, the full check, and the human gate.

```mermaid
stateDiagram-v2
  direction TB
  state "Build vN, fast checks 1 to 4" as building
  state "Full check on the same vN<br/>fail-fast step 5, at L2 with the light review" as fullCheck
  state "Human gate open" as humanGate
  state "PROVISIONAL<br/>gate decision, status provisional<br/>flow.stage moves to the next stage" as provisional
  state "APPROVED<br/>gate decision, status approved<br/>cites the provisional decision" as approved
  state "VOID<br/>gate decision, status void<br/>flow.stage back to this stage" as void

  [*] --> building
  building --> building: a fast check fails, fix and build a new version
  building --> provisional: every fast check passes
  provisional --> fullCheck
  fullCheck --> void: fails, or a MAJOR light-review finding
  fullCheck --> humanGate: passes, and the previous stage's human gate passed
  humanGate --> humanGate: empty, declined, cancelled or unanswered, no consent
  humanGate --> fullCheck: the user asks for a finer sweep on the same vN
  humanGate --> void: the user names a change
  humanGate --> approved: explicit user approval, recorded with its channel
  void --> building: build a fixed version in this stage
  approved --> [*]

  note right of provisional
    CEL requires, plan section 5:
    version.fast_checks.all(c, c.status == "pass")
  end note
  note right of approved
    CEL requires, plan section 5:
    full_check.status == "pass"
    && prev_human_gate.approved
    && (policy.mode == "auto" || answer.present)
    Gate modes ask, chat, auto: hw/policy.yaml
  end note

  classDef provisionalState fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
  classDef approvedState fill:#e0f2f1,stroke:#00695c,stroke-width:2px,color:#1b1b1b
  classDef voidState fill:#424242,stroke:#000000,stroke-width:2px,color:#ffffff
  class provisional provisionalState
  class approved approvedState
  class void voidState
```

The single human gates (INTENT, VARIANT, DESIGN freeze and RELEASE) have no PROVISIONAL step. They present a packet, ask the user, and record APPROVED only on explicit approval; `flow.stage` advances only then.

## VOID cascade

An example: the LAYOUT full check on v4 fails while PARTS and DETAIL already run on v4.

```mermaid
stateDiagram-v2
  direction TB
  state "layout PROVISIONAL on v4" as layoutProv
  state "parts PROVISIONAL on v4" as partsProv
  state "detail in work on v4" as detailWork
  state "VOID layout on v4<br/>stop its long jobs by process group" as layoutVoid
  state "Reopened<br/>flow.stage = layout<br/>parts and detail wait for a rebuild" as reopened
  state "layout PROVISIONAL on v5" as layoutProv5

  [*] --> layoutProv
  layoutProv --> partsProv: next stage starts
  partsProv --> detailWork: next stage starts
  detailWork --> layoutVoid: LAYOUT full check fails on v4
  layoutVoid --> reopened: void_scope, CEL, selects the later stages built on v4
  reopened --> layoutProv5: fixed v5 passes the fast checks
  layoutProv5 --> [*]

  note right of layoutVoid
    One void decision supersedes the layout
    and parts provisional decisions on v4.
    Decisions are append-only.
  end note

  classDef provisionalState fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
  classDef voidState fill:#424242,stroke:#000000,stroke-width:2px,color:#ffffff
  class layoutProv, partsProv, layoutProv5 provisionalState
  class layoutVoid voidState
```

Each reopened later stage is rebuilt on the fixed version. Its human gate stays closed until its own full check passes on a version built from the fix.

## Engineering change after the freeze

```mermaid
stateDiagram-v2
  direction LR
  state "DESIGN freeze APPROVED<br/>flow.frozen: version, manifest_sha256,<br/>decision, evidence_sha256" as frozen
  state "Engineering change open<br/>flow.change: decision, baseline_version,<br/>affected_parts" as change
  state "detail, affected parts only<br/>two gates, as L3" as ecoDetail
  state "analysis, affected cases only<br/>two gates, as L4" as ecoAnalysis
  state "New version, frozen again<br/>new flow.frozen anchor" as refreeze
  state "RELEASE gate" as releaseGate

  [*] --> frozen
  frozen --> releaseGate: no change
  frozen --> change: change decision approved
  change --> ecoDetail
  ecoDetail --> ecoAnalysis
  ecoAnalysis --> refreeze
  refreeze --> releaseGate
  releaseGate --> [*]

  note right of change
    Open: plan section 5 and the
    Phase 2 steps don't say how
    flow.yaml models a change.
  end note

  classDef approvedState fill:#e0f2f1,stroke:#00695c,stroke-width:2px,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  class frozen approvedState
  class change, ecoDetail, ecoAnalysis, refreeze open
```

## Legend

- White states are stages, named by the record contract's `stage` enum. Purple states are gates.
- Blue is PROVISIONAL, teal is APPROVED and dark grey is VOID. These are the three statuses of a gate decision, `kind: gate`, in `hw/decisions/`.
- **Open** (red, dotted): engineering change. The record contract has `flow.change`, and the prototype reopens affected parts as L3 and then affected cases as L4. Neither the plan nor an ADR says how `flow.yaml` represents it; the in-review migrate lane refuses frozen records until "the Phase 2 flow engine can record an engineering change". The plan's [Open questions](../design-plan.md#open-questions) don't list it.
- The VOID cascade example uses v4 and v5 for illustration.
- In the prototype the statuses were MADR `proposed`, `accepted` and `rejected`. The record contract renames them `provisional`, `approved` and `void`.

## Sources

- Prototype `benchhand/benchhand` at `release.toml` `reference_commit` `412b5d9`:
  - [`skills/cad-flow/references/flow.md` "Stages, gates, and durable outputs"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/references/flow.md#stages-gates-and-durable-outputs): the stage order, the stage enum and the gate per stage.
  - [`skills/cad-flow/references/flow.md` "Gate control"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/references/flow.md#gate-control): the single human gates, the three steps of a two-gate stage, the VOID causes and the cascade, and "no consent" on a cancelled or unanswered question.
  - [`skills/cad-flow/references/flow.md` "Stage loop and recheck boundary"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/references/flow.md#stage-loop-and-recheck-boundary): after the freeze, reopen only affected parts, then build a new version and freeze it again.
  - [`skills/cad-flow/SKILL.md` "Workflow" and "Delegation"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/SKILL.md): the stage list in step 3, and the ECO row ("As L3, then as L4").
- `docs/design-plan.md`:
  - [Context](../design-plan.md#context): `flow.md` "Gate control" defines PROVISIONAL, APPROVED and VOID.
  - [5. Flow engine and rules (D14)](../design-plan.md#5-flow-engine-and-rules-d14):
    - `flow.yaml` holds the nodes, gates and edges, with the gate kinds `single-human` and `provisional+full+human`.
    - The CEL `requires` examples for PROVISIONAL and APPROVED, and the CEL `void_scope`.
    - The interpreter is the normal writer of `flow.stage` and `hw/decisions/`.
  - [Decisions](../design-plan.md#decisions), D3: the gate modes in `hw/policy.yaml`.
  - [Steps (phased)](../design-plan.md#steps-phased), Phase 2: `flow.yaml`, the interpreter, CEL guards, decision records and the VOID cascade.
  - [Verification](../design-plan.md#verification), "Flow tests".
- `docs/adr/`: [0003](../adr/0003-gates-guide.md) (gates guide; modes ask, chat, auto) and [0014](../adr/0014-flow-rules-cel.md) (the flow is data, the rules are CEL), each under "Decision".
- `docs/contract/record-migration.md`: [Decision record format](../contract/record-migration.md#decision-record-format): `kind: gate` with `approved`, `provisional` or `void`, and the prototype's MADR statuses.
- Contracts on `main`: `contracts/record/common.tsp` (`stage`), `contracts/record/product.tsp` (`flow.frozen`, `flow.change`), `contracts/record/decision.tsp` (gate statuses).
- In review: `docs/contract/record-migration.md` "Dry run and apply", its "Frozen records" paragraph, on branch `pi-subagents/task-1-c25b8e0-b8d5-s0-t0`.
