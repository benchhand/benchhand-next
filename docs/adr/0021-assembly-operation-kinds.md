# ADR-0021: Assembly operation kinds

Status: proposed. Source: the design pass the owner asked for on 2026-11-27 (`docs/phases/phase-0-1.md`, Decided, item 2). The design, its alternatives and the evidence are in [`docs/phases/phase-2-assembly-kinds.md`](../phases/phase-2-assembly-kinds.md). It refines sections 12a and 12b of [the plan](../design-plan.md).

## Context

Assembly steps come in four forms that don't agree:

- **The pin, `412b5d9`:** 10 kinds and one inferred base per assembly.
- **Plan section 12b:** adds `place` with `retained_by`.
- **Prototype #334:** adds `install`, `hold` and bench sub-builds (`sub_build`).
- **The test project:** uses `place`, a `bench` kind and an `instructions` key. No prototype commit has these.

Prototype #333 adds `make_buy: existing`, which may never be a step's `part`. The test project moves customer equipment in 6 steps. Migrate refuses the test project until one design covers all four forms.

## Decision

1. **13 kinds:** the pin's 10, plus `place`, `bench` and `hold`.
2. **`place` installs without a joint.** Its `part` is a part or a bench unit (a sub-build id). The joining kinds may also install a unit. #334's `install` becomes `place`.
3. **`retained_by`** is a list of later joining steps in the same build, or an open fact with a reason. The record validator requires it when the placed part is delivered (`role: product`). The schema doesn't require it, so sealed snapshots stay readable.
4. **`bench` opens a sub-build** and names its base. Steps of the unit carry #334's `sub_build` key. The main build keeps the pin's inferred base.
5. **`hold`** is as #334 has it: `duration`, `fixture`, `orientation` and an optional `cure` with datasheet-sourced figures.
6. **`instructions`** is an optional list of strings on every kind. Only the build guide and the assembly sheets read it.
7. **Existing equipment** may be the `part` of `place` and `disassemble` only. It stays present from the start and is never a base.
8. **Off the step:** `role` goes on occurrences and subassemblies (plan 12a), `mount` on fixed joints (#341), fits by explicit limits on `Drawing.fit` (#348), and `mates_with` in the Phase 4 release manifest.
9. **New migrate rows:**
   - `assembly-bench-sub-build`;
   - `assembly-place-retained-by`;
   - `assembly-install-place`;
   - `fit-limits-mm`, after #348 merges.

   The YAML editor gains two splices for them: a key added to a block mapping, and a flow sequence put where a scalar was.

## Consequences

- `record/assembly` goes to 1.1.0 (`role`), 1.2.0 (the kinds) and 1.3.0 (`mount`). `record/drawing` goes to 1.1.0 (#348).
- The pin's order checks are ported unchanged before the kinds land, so that #334's port has a base to differ from.
- This diverges from merged #334 (`install`) and #333 (`existing.installed`). It also changes the wording of plan 12b (`retained_by` required on every `place`). The design document lists these as owner questions 1 to 3.
- The test project needs hand edits before it migrates: 4 steps changed or removed, 2 `disassemble` steps added, and 6 parts recorded as `existing`. The design document lists them.
