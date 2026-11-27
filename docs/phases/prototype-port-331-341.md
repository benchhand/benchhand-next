# Prototype port survey: PRs #331 to #341

Status: survey, written 2026-11-27 against `benchhand-next` `main` at `fb9cb2e` and prototype `main` at `6cdc291e`. The verdict, table and notes describe that state. The note of each PR lists the ports that landed since, under **Ported**.

The prototype pin in `release.toml` is `reference_commit` `412b5d9`. This survey covers `benchhand/benchhand` PRs #331 to #341, which merged after it.

## Verdict

- Eight of the eleven PRs are merged: #331, #332, #333, #334, #335, #337, #340 and #341. #336, #338 and #339 are still open (checked with `gh pr view`), so they are not ported yet and they stay above the pin.
- Nothing is started. No local or `origin` branch of `benchhand-next` holds any of the new names (`existing`, `sub_build`, `no_guideline`, `mates_with`, `family_designation`, `ghost`, in `contracts/` on every branch).
- Six PRs touch a record contract. All six changes are additive. The contract homes exist on `main`, except the release manifest, which has no contract yet (Phase 4).
- Most of the behaviour lands in Phase 4 providers (`checks-process`, `freecad`, `render-chromium`, `kernel-*`) and in code that the map still marks planned. What can be ported now is the contract, the record rules and the evidence rules.
- Move the pin once, to `5dcd2c92` (#341), after the eight PRs are ported. It cannot move earlier without four new map entries, as shown under "Move the pin".

## Summary table

"Home on main" says whether the main home of the contract or rule exists at `fb9cb2e`. "Later" names the phase that owns the rest, from `docs/design-plan.md`, Steps.

| PR | Merge commit | What it changes | Home on main | Later | Contract bump | Effort |
|---|---|---|---|---|---|---|
| #332 render hide or ghost | `90c08bb0` | `part.render`; `--hide`, `--ghost`, `--show` on render and motion | `contracts/record/part.tsp` | Phase 4 (`render-chromium`, `motion`) | `record/part` minor | M (S now) |
| #331 commodity designation | `3a7542dd` | `purchase.designation`, `reference_catalogue`; one identity rule; build guide, BOM and fits data | `part.tsp`, `record/rules/bom.py` | Phase 4 (BOM, guide, fits, drawings), Phase 6 (agent text) | `record/part` minor | M |
| #333 `make_buy: existing` | `2ef059f8` | new sourcing value and `existing.dimensions`; guards; no obligations; selection drops it | `part.tsp`, `rules/interfaces.py`, `rules/assembly.py`, `evidence/obligations.py`, `evidence/fingerprints.py` | Phase 2 (selection, assembly order), Phase 4 (form check, access) | `record/part` minor | L |
| #340 complexity baseline | `4510caa2` | one JSON file of the prototype's ratchet | none | none | none | S (no port) |
| #335 guideline values govern | `dff84b56` | `no_guideline` reason, `warp`, `max_size`, shipped `fdm.accuracy`; printer checks and stack-up | `common.tsp`, `manufacturing-guideline.tsp`, `evidence/guidelines.py` | Phase 4 (`checks-process`, fits) | `record/common` minor, `manufacturing-guideline` minor | L |
| #334 sub-builds and holds | `95999a32` | `install` and `hold` kinds, `sub_build`, cure rules, `quantities.py` | `contracts/record/assembly.tsp` | Phase 2 (order checks), Phase 4 (access, guide, drawings) | `record/assembly` minor | L |
| #337 keep existing out of the product | `2e840b64` | `sourcing.py`, `product.step` and `product.glb`, `product_exports`, `mates_with`, BOM and viewer groups | `evidence/obligations.py`, `evidence/fingerprints.py`, `record/documents.py` | Phase 4 (release, kernel, BOM, drawings), Phase 5 (viewer) | none now; release manifest is new in Phase 4 | L |
| #341 joint check from geometry | `5dcd2c92` | bore or shank from geometry; face contact; `mount.point`; `occ.Adjacency` | `contracts/record/assembly.tsp` (joint) | Phase 4 (`checks-process`, `benchhand-sdk`, `collision-fcl`) | `record/assembly` minor | L (S now) |

Effort scale (my estimate, for the whole port with its tests): S is a day or less, M is a few days, L is a week or more. "S now" means the part that can land on `main` at `fb9cb2e` is small and the rest waits for a phase.

## Per-PR notes

### #332: hide or ghost chosen parts in renders and motion

- **Changes.**
  - `render.py` and `motion.py render` take repeatable `--hide`, `--ghost` and `--show`. Each takes a PN or an occurrence id.
  - A ghost is translucent with visible edges, never an occluder, and stays out of the floor bake and the ambient-occlusion depth pass. A hidden part is not framed. A render that hides every part exits 2.
  - New optional `part.yaml` field `render: shown | ghost | hidden`.
  - `render.json` and `motion-render.json` list `hidden` and `ghosted`, and both enter the cache key.
  - Skill text in `cad-render` and `cad-motion`: ghost or hide a blocking body instead of writing a custom renderer.
  - Tests: a PNG reader fixture, and an exact ambient-occlusion leak check that holds on one GPU only.
- **Homes.**
  - Contract: `contracts/record/part.tsp`. The enum and field are absent at `fb9cb2e`. On main.
  - `render.py`, `render.js`: `providers/render-chromium/`, Phase 4, planned.
  - `motion.py`: `benchhand_core/motion/`, Phase 4, planned.
  - Skill prose: `flow/guides/`, Phase 2, planned.
  - `cad_api.py` and `docs/schemas.md` are generated in the prototype. The map marks `cad_api.py` dropped, so nothing ports.
- **Contract.** `record/part` gains one optional enum property: minor.
- **Port now.** The `render` field with its default text. The plan's section 12a already says renders ghost context parts with a toggle, so the field is the missing contract half. Phase 4 ports the renderer with the test that pins the exact pixels. That test needs a tolerance decision for other GPUs, because the PR itself says the exactness holds on one machine.
- **Order.** Before #337, which sets the default to `ghost` for existing equipment.
- **Ported** in `b87b37f2`: the `render` field, `record/part` 1.1.0.
  - Tests from the PR: none ported. All 24 drive the renderer or the motion renderer, Phase 4: 21 in `skills/cad-render/tests/test_render.py` and 3 in `skills/cad-motion/tests/test_motion_render.py`.
  - New tests: each `render` value validates and any other value is refused (`test_record_validate.py`). A migrate fixture shows that the lamp-arm parts, which have no `render`, keep their bytes and validate (`test_migrate_service.py`).
  - Remains: the `--hide`, `--ghost` and `--show` flags, the `hidden` and `ghosted` lists and their cache key (Phase 4), the skill text (Phase 2 guides), and a tolerance rule for the ambient-occlusion test.

### #331: commodity hardware sourced by designation

- **Changes.**
  - `purchase.designation` is `standard_designation` (standard, size, length, property class, finish) or `family_designation` (heat-set inserts: thread, length, outside diameter, recommended hole). A purchase needs `identity` or `designation`. `purchase.reference_catalogue` lists non-binding examples.
  - `commodity_identity.py` decides which designations identify an item. The size is a whole size and may not embed the length, which also refuses fine-pitch sizes such as `M8x1` (bead `c7q.32`, known side effect). `procurement.open` is honoured.
  - The BOM designation column, the record validator and the build guide read the same lookup. The guide merges commodity rows only when supplier and order code match, and never merges a manufacturer identity.
  - A designation-only catalogue screw needs no manufacturer or supplier on the drawing. A row that also names a manufacturer part number still needs a supplier.
  - `cad-fits/data/commodity.json` and `commodity.py` give modelled dimensions for M2 to M8 hardware, each block with a public source URL.
  - The sourcing researcher agent text and `cad-bom` guidance default commodity families to a designation.
- **Homes.**
  - Contract: `part.tsp`, the `purchase` model. On main.
  - Designation column: `record/rules/bom.py` `procurement_cells` is a direct port of `validate.py` `procurement_cells`, and the PR edits that exact line. On main.
  - Eligibility helper: no map entry yet. Propose `record/rules/bom.py`, with the guide and BOM callers in Phase 4.
  - Purchase checks: `providers/checks-process/`, Phase 4. Build guide: `record/docs/`, Phase 4. BOM: `benchhand_core/bom/`, Phase 4. Drawings: `providers/freecad/`, Phase 4. Fits data: `benchhand_core/fits/`, Phase 4.
  - Agent text: `harness/agents/`, Phase 6. The PR also regenerates four host renderings, which `benchhand install` produces and which need no port.
- **Contract.** `record/part` minor. `identity` leaves `required` and an `anyOf` over `identity` and `designation` replaces it. That is a widening in intent. The breaking-change checker lists a new `anyOf` as `branches-reduced` (rules in `docs/contract/versioning.md`), so argue it in that file as the `obligation_id` widening was.
- **Order.** Independent of the others. It shares `purchased.py` with #333 and `bom.py` with #337, so port it before both.

### #333: `make_buy: existing`

- **Changes.**
  - `make_buy` takes `existing`. The part then needs `existing.dimensions`, a known range with a basis (measured, standard, user-declared, assumed) and sources. It refuses `supplier`, `procurement`, `manufacture` and `intent`. The schema is the only procurement gate.
  - No obligations: no process, purchase, route or form check runs on it. Two record checks skip it. The version 2 demand for `intent` skips it.
  - `selection.assess` drops existing parts and any candidate left empty. A recorded recommendation that names a dropped candidate blocks.
  - Guards `existing.interface_missing` and `existing.installed`, both resolving `@occurrence` references through the assembly inventory.
  - `impact.py`: `existing.dimensions` joins the `geometry` fingerprint domain, and its cited sources join `source`. Parts without `existing` keep their digest.
  - `form_check.py`: process `existing`, keeps the B-rep and STEP read-back checks, no wall scan.
  - Existing occurrences are present from the start and never the base of a build.
  - Skill text says when to record `existing` and what to ask the user.
- **Homes.**
  - Contract: `PartMakeBuy` in `part.tsp`. On main, value absent.
  - Guards: `record/rules/interfaces.py` and `record/rules/assembly.py`, both on main (`Inventory.resolve` already resolves occurrences).
  - Fingerprint: `evidence/fingerprints.py` (`make_buy` at line 271, the `geometry` domain at line 320). On main.
  - Obligations: `evidence/obligations.py`, on main.
  - Selection: `record/selection.py`, Phase 2, not on main.
  - Assembly order: `rules/assembly.py` has the inventory and joints but no operation checks yet, so this part of #333 waits for the Phase 2 port of `assembly_operations.py`.
  - `form_check.py` and `access.py`: `providers/checks-process/` and `benchhand_core/motion/`, Phase 4.
- **Contract.** `record/part` minor: one new enum value and one new optional property. The `if`/`then`/`else` that forbids `procurement` on an existing part is a `constraint-added` change for the checker.
- **Divergence from the plan.** Section 12a says the obligations of an existing part are recorded `not_applicable` with the role as the reason, never skipped. The prototype gives it no obligation. Port the plan's rule and keep the prototype's tests as the cases.
- **Overlap with #341.** #341 replaces the separate existing-equipment branch of the joint check that #333 added. Port #333's `form_check` piece as the skip of the wall scan only, and port the joint rule from #341.

### #340: refresh the complexity ratchet baseline

- **Changes.** One line of `scripts/complexity-baseline.json`. It lists which functions offend the prototype's ratchet.
- **Home.** None. `AGENTS.md` says the ruff complexity limits here are enforced, not ratcheted, so there is no baseline to refresh. No map entry exists or is needed.
- **Port.** None. It passes with the pin move.

### #335: guideline values govern when no calibration exists

- **Changes.**
  - `Context.governing()` returns a calibration, else the guideline interval. A calibration only tightens a limit, and a calibrated miss still fails. `GUIDELINE_PASS_CLASSES` is removed: an applicable guideline settles a check in every service class.
  - A printer check with neither calibration nor guideline value is `not_assessed` with the new reason `no_guideline`. It blocks no gate and is never a pass. A known failure in the same obligation still fails it.
  - A criterion no check reads is an explicit open finding `criterion_unchecked`. A `between` band narrower than the governing spread fails as `criterion_band`. A critical bore with no diameter criterion is `receiving_criterion_missing`.
  - Schemas: `not_assessed` reason gains `no_guideline` and `no_check` (nothing emits `no_check` after round 3). The guideline schema accepts `warp` and `applies_to.max_size`.
  - New shipped set `fdm.accuracy` revision 2: dimensional and hole deviation of -0.5 to 0.5 mm for features up to 100 mm, source Protolabs Network (Hubs), limits marked `disputed`. A larger or unsized feature takes no value from it.
  - `guidelines.py` selects a calibration by size scope, refuses a `max_size` that is not a finite positive length at discovery, and reports an angular size scope.
  - `stackup.py`: the guideline deviation qualifies an uncalibrated printed contributor. With neither, the finding is `stack.capability_not_assessed`, the stack is not assessed and the exit code is 0. The stack recipe seals `basis_revision`, so an older bundle is never reused.
  - `form_check.py` reports the packet result, not `pass`, over a clean fidelity check.
  - Text: test coupons are optional and never a gate.
- **Homes.**
  - Reason enum: `not_assessed_reason` in `contracts/record/common.tsp` (line 499). On main.
  - Guideline contract: `contracts/record/manufacturing-guideline.tsp`. On main.
  - Discovery, validation and scope applicability: `evidence/guidelines.py` and `evidence/guideline_files.py`. On main, marked partial; the map assigns limit resolution to Phase 4.
  - Shipped set: `skills/cad-record/assets/manufacturing/` has `phase: null` in the map. It waits on the open question in the plan (shipped guideline sets as a package asset). The evidence reader takes the directory from its caller today, so the port can ship the file as a test fixture first.
  - `process_checks/core.py`, `additive.py` (556 lines), `secondary.py`, `form_check.py`: `providers/checks-process/`, Phase 4. The dispatch itself is a Phase 2 CEL list.
  - `stackup.py`: `benchhand_core/fits/`, Phase 4.
- **Contract.** `record/common` minor (two enum values). `manufacturing-guideline` minor (one optional property, one characteristic value). Widening the `if` enum of the deviation branch to include `warp` is an `unproven-change` for the checker. Finding codes are free strings in `common/finding` (a pattern, no enum), so the new codes need no bump.
- **Dependencies.** No behaviour depends on #333, but #335 edits files #333 also edits (`manufacturing_intent.py`, `test_process_checks.py`), so port it after. Port it before #341, which edits the same `form_check` report. The later #347 (service-class scope table, outside this range) edits the same area and should follow.

### #334: sub-builds and hold steps

- **Changes.**
  - `assembly.schema` gains kinds `install` and `hold`, a `sub_build` key (a subassembly id or a new id), and `hold` fields `duration`, `fixture`, `orientation` and `cure` (`time`, `temperature`). Conditionals tie the fields to the kinds.
  - `assembly_operations.py` (493 lines) tracks state per build, with its own base and closure. New findings: `assembly.sub_build_unfinished`, `assembly.sub_build_shared`, `assembly.sub_build_unknown`, `assembly.sub_build_not_installed`, `assembly.installed_twice`, `assembly.cure_unsourced` and `assembly.hold_short`. A cure figure counts only with a datasheet source, and a hold that is not a positive time stays unknown.
  - `quantities.py` is a new standard-library module with the units table, `Quantity`, `quantity()`, `unit()` and `convert()`. A quantity interval with one bound is refused.
  - `access.py`: a tool-free hold gets `not_applicable`, an uncited tool on a hold gets a `not_assessed` advisory row, and a cited tool is measured. `hold_reach` is the seam that open #336 extends.
  - The build guide lists hold and install steps and prints only datasheet cure figures. Assembly drawings keep sub-build installs out of item steps.
  - Existing equipment stays in the main build and is never a bench member.
- **Homes.**
  - Contract: `contracts/record/assembly.tsp`, the `assembly_operation` model. On main.
  - Order and sub-build rules: `record/rules/assembly.py`. The file is on main, but it holds the inventory and joint rules only. The map has `assembly_operations.py` as Phase 2, planned, so the pin-state order checks are not ported. #334 lands on top of that Phase 2 port.
  - Units: no home. `evidence/joints.py` has small private converters (`_to_deg_c`, `_quantity_mm`). A shared quantity helper is the natural home, and no map entry names one.
  - Access, build guide, drawings: `benchhand_core/motion/`, `record/docs/`, `providers/freecad/`, all Phase 4.
- **Contract.** `record/assembly` minor: two enum values, new optional properties, new conditional branches (`schema-constrained` for the checker).
- **Conflict with the plan and the test project.** The plan (section 12b) adds a `place` kind with `retained_by`. #334 adds `install` and `hold`. The two cover different cases and need one joint design pass before either is written. `docs/phases/phase-0-1.md` names a `bench` kind and an `instructions` key as coming from #334. Neither exists in the prototype schema at `412b5d9` or `5dcd2c92` (checked with `git show <commit>:…/assembly.schema.json | grep`). The test project's eight `bench` operations and forty `instructions` keys therefore have no schema in the prototype either; see the open questions.
- **Order.** After #333. Before #337, which changes `assembly_sheet.py` and `assembly_check.py` over the same lines.

### #337: keep pre-existing equipment out of the released product

- **Changes.**
  - `sourcing.py`: `delivered` is false only for existing equipment, and `group` returns `made`, `purchased` or `existing`.
  - The build writes `product.step` and `product.glb` with delivered occurrences only. `assembly.step` and `assembly.glb` stay the in-context scene, with GLB nodes grouped by sourcing. `metrics.json` totals count delivered parts only.
  - A new blocking check `product_exports`, and a product-level obligation `cad.product_exports` that release requires. It compares definitions by name and read-back volume, walks every reachable GLB node, refuses a boolean or repeated scene index, and reads unnumbered STEP leaves. The fingerprint includes placements, so moving a delivered occurrence stales it.
  - The release ships `definition/product.step`, puts the in-context scene under `context/`, lists each existing interface under `mates_with`, and refuses a contaminated or missing `product.step`.
  - `cad-bom` writes no row for existing equipment. Assembly drawings draw it as ISO 128 type 05 reference lines with no parts-list item. Renders ghost it by default. The viewer tree nests parts under made, purchased and existing.
  - Release manifest schema gains optional `mates_with`.
  - Open in the PR text: the file names are "still under review" and live in `sourcing.py` and `layout.json`.
- **Homes.**
  - Obligation and fingerprint: `evidence/obligations.py` and `evidence/fingerprints.py` (the `cad.` prefix rule at line 64 gives `geometry`; this check also needs `occurrences`, as `cad.glb_step_agreement` has at line 65). On main.
  - File names: `layout.json` maps to `record/documents.py`, `record/ignore.py`, `migrate/inventory.py` and `evidence/reader.py`, all on main.
  - Release manifest: no contract exists (`contracts/record/` has no release file). `record/release/` is Phase 4, planned. The `mates_with` entry goes into that contract when it is first written.
  - Build, check and mesh code: `providers/kernel-*`, Phase 4. STEP reader: `providers/collision-fcl/`, Phase 4. BOM, drawings, render: Phase 4. Viewer: Phase 5.
  - `sourcing.py`: no map entry yet. Propose `record/` with the Phase 2 `role` field.
- **Contract.** None now beyond a patch to the `render` description in `record/part`. The release manifest contract is written in Phase 4 with `mates_with` from the start.
- **Divergence from the plan.** Section 12a uses a per-occurrence `role` (`product`, `context`, `tooling`) and exports `product.*` and `scene.*`. #337 has no `role`, keeps the in-context scene under the old `assembly.*` names and adds `mates_with`. The plan covers the same ground with more cases. Port the plan's design, keep #337's tests as cases, and decide whether `mates_with` is added to it (open question).
- **Order.** After #332, #333 and #334. It is the last record PR.

### #341: joint check reads bore or shaft from geometry

- **Changes.**
  - Each joint end mates through the bore or shank its geometry has on the joint axis, for made, bought and existing parts alike. The check names the pair with the closest radii and skips edge fillets.
  - A fixed joint end with no cylinder can pass by planar face contact at the joint's datum plane. Each contact patch is judged on its own. A contact the check cannot settle is the new blocking `joint_contact_unknown`. A missing geometry is still `joint_bore_missing`.
  - A fixed joint may declare `mount: {point: [x, y, z]}`. Only fixed joints take it, a null mount is refused, and the point must lie on the patch and on the datum plane. A projected origin may sit in an opening up to 20 mm from its contact.
  - `cadmodel.occ.Adjacency` is one shared edge-to-face index for `holes.py` and `form_check.py`. Segmented coaxial cylinder faces merge, and tangent supports count by underlying surface.
- **Homes.**
  - Contract: `contracts/record/assembly.tsp`, the joint model. On main.
  - Joint check: `providers/checks-process/` (`form_check.py`), Phase 4.
  - `Adjacency`: `benchhand-sdk` (`occ.py`, `holes.py`), Phase 4.
  - `pose.make_joint` refusal of a null mount: `providers/collision-fcl/`, Phase 4. The contract half, where an absent mount differs from a null one, is a schema rule and ports now.
- **Contract.** `record/assembly` minor: one optional property and an `if required mount then type fixed` branch.
- **Port now.** The `mount` property and its conditional. The geometry is the bulk of the work and is Phase 4 (about 500 lines of OCC logic and 360 lines of tests in `test_design.py`).
- **Order.** After #333 and #335, because it rewrites parts of `form_check.py` they touch.

### Open PRs in the range

- #336 (hand work and common tools need no modelled envelope), #338 (one chamfer leg order, diameter fit on partial bores, no ±0 seats) and #339 (docs: one project per variant) are open. They stay above the pin. #334's `hold_reach` is written as the seam that #336 extends, so port it with that shape.
- Beyond the range, `just reference-changes` also lists merged #347, #350, #351 and #352. #347 adds `project_scope.py` and changes the service-class scope that #335 touches, so it is the natural next batch. #352 documents a departure in the prototype's own `docs/engineering.md` and changes nothing in this repository.

## Contract versions

`docs/contract/versioning.md`: an additive change raises the minor version. A narrowing keeps its version until the first release. The breaking-change check compares with the nearest `v*` tag reachable from `HEAD`. The tags `v0.1.0` and `v0.1.1` exist but are not reachable (`git describe --tags` fails), so the check skips today. Expect it to report the new `if`, `anyOf` and `allOf` branches after a release tag exists. That prediction is from the rules table and is untested.

| Contract | Now | After the port | Caused by |
|---|---|---|---|
| `record/part` | 1.0.0 | 1.1.0 (#332), 1.2.0 (#331), 1.3.0 (#333), 1.3.1 (#337, description only) | `render`; `designation`; `existing` |
| `record/assembly` | 1.0.0 | 1.1.0 (#334), 1.2.0 (#341) | `install`, `hold`, `sub_build`; `mount` |
| `record/common` | 1.1.0 | 1.2.0 (#335) | `not_assessed_reason` values |
| `record/manufacturing-guideline` | 1.0.0 | 1.1.0 (#335) | `warp`, `applies_to.max_size` |
| release manifest | none | new, 1.0.0, Phase 4 | `mates_with` |
| `record/bundle-manifest` | 0.1.0, provisional | unchanged | Phase 2 owns it |

New finding codes need no contract bump (`common/finding` fixes only the pattern). A migrate rule is not needed for any of the eight: every new field is optional, and a record without it reads as before. The migrate table (`record/migrate/rules.py`) stays at eleven rows. Evidence rules are needed for #333, #334, #335 and #337, as noted above.

## Order and dependencies

Port in merge order. The chain is:

1. #340. No port. It only moves the pin.
2. #332. Contract field. Needed by #337.
3. #331. Independent. Shares `purchased.py` with #333 and `bom.py` with #337.
4. #333. Needed by #334 (existing equipment in builds), #337 and #341.
5. #335. Shares files with #333, no behaviour dependence. Before #341.
6. #334. Needs #333. Before #337.
7. #337. Needs #332, #333, #334.
8. #341. Needs #333 (it replaces #333's joint branch) and shares `form_check.py` with #335.

Independent pairs, which can run in parallel: #331 with #332, and #335 with #334. Two steps wait for later phases and should not block the pin: the Phase 2 order checks under #334 and #333, and Phase 4 for every provider piece. The ADR-0015 rule is that each prototype change is its own reviewed step, so the pin moves when the last step of the batch is approved, not when each contract lands.

## Move the pin

Move `release.toml` `reference_commit` and `docs/architecture/reference-map.yaml` `reference_commit` together to `5dcd2c929e69556c99bd07522fe75767ab5299c6` (#341). It is the last of the eight merged PRs, so the pin then reflects every one of them. `6cdc291e` (the head of prototype `main`) would also pull in #347, #351 and #352, which are not ported and not surveyed here.

I ran the check in a scratch copy of this repository against `git archive` copies of the prototype at three commits, with no change to the prototype or to this worktree.

| Pin in the scratch copy | Result of `just reference-map` |
|---|---|
| `412b5d9` (current) | passes: `205 entries (9 dropped, 10 partial, 184 planned, 2 ported); coverage checked, its commit verified` |
| `5dcd2c92`, map unchanged | fails, four prototype files have no entry: `cad-fits/scripts/commodity.py`, `cad-record/scripts/commodity_identity.py`, `cad-record/scripts/quantities.py`, `cad-record/scripts/sourcing.py` |
| `6cdc291e`, map unchanged | fails on those four and on `cad-record/scripts/project_scope.py` (#347) |
| `5dcd2c92`, four planned entries added, `--write` run | `209 entries (9 dropped, 10 partial, 188 planned, 2 ported); coverage checked, its commit verified` |
| `5dcd2c92`, no reference copy | the same counts, "coverage not checked" |

What the pin move needs, in one change:

- the new `reference_commit` in both files;
- four map entries, with the homes proposed above: `commodity.py` to `benchhand_core/fits/` (Phase 4), `commodity_identity.py` to `record/rules/bom.py` (Phase 1), `quantities.py` and `sourcing.py` to `record/rules/assembly.py` (Phase 2, to be confirmed);
- `just reference-map --write`, because the check fails when `function-map.md` is out of date;
- a reference copy at the new commit. CI already fetches the SHA that `release.toml` names, so nothing else changes there. A copy at the old commit is then refused: `…holds 412b5d9…, not release.toml's reference_commit 5dcd2c92…`.

The four entries cannot land before the pin moves. An entry that names a path absent from the old reference copy fails the check as "names a path that doesn't exist". A move to an intermediate pin works only if the entries move with it: #331 adds two files, #334 adds `quantities.py`, #337 adds `sourcing.py`. The others add no required file; the new `fdm.accuracy.yaml` and `commodity.json` fall under the existing directory entries `assets/manufacturing/` and `data/`.

After the pin moves, the counts change again as ports land: an entry becomes `partial` or `ported` once its home holds the behaviour, and `check_homes` then requires that home to exist.

## Open questions

- **`bench` and `instructions`.** `docs/phases/phase-0-1.md` says the test project's assembly uses a `bench` kind (PR #334) and an `instructions` key. Merged #334 has neither. The test project record either came from a draft of #334 or was written ahead of the schema. The migrate step on it will keep refusing until the owner says which form the record should take.
- **`place` against `install` and `hold`.** Plan section 12b and #334 both add assembly step kinds. Decide the joint design before the Phase 2 port of `assembly_operations.py`.
- **`role` against `sourcing.delivered`.** The plan's `product`, `context` and `tooling` roles replace #337's single predicate and its names `assembly.step` and `product.step`. Whether `mates_with` joins the plan's release design is unsettled.
- **Existing obligations.** The plan records `not_applicable` with a reason. #333 records none. This survey follows the plan.
- **Ambient-occlusion test in #332.** The exact-pixel check holds on one GPU only, by the PR's own account. It needs a tolerance rule before it joins CI.
- **`fdm.accuracy`.** The shipped set marks its limits `disputed` because its source gives two values. It waits on the package-asset question for the guideline catalog.
- **`M8x1`.** #331 refuses fine-pitch sizes by design of its size rule (bead `c7q.32`). Port it as it stands, with the known limit written into the rule's test.

## How this was checked

- `gh pr view N --repo benchhand/benchhand` for #331 to #341: state, merge commit, files and body.
- `git -C /Users/sjors/personal/dev/cad-agent show` for diffs and file lists at the eight merge commits, schema diffs under `skills/cad-record/schemas/`, and `git log --diff-filter=A` for new files. The checkout was not modified.
- `just reference-changes`, `just reference-map` and the scratch simulation above, run against `git archive` copies of the prototype in a temporary directory that was removed afterwards.
- `docs/architecture/reference-map.yaml`, `function-map.md`, `docs/design-plan.md`, `docs/contract/versioning.md` and `docs/phases/phase-0-1.md`, and `contracts/` and `packages/benchhand-core/` on `main`.
- `git grep` over every local and `origin` branch for the new names in `contracts/`.

Not done: no port was attempted, no contract was built, and the breaking-change check was not run on any new schema. Every bump above is a prediction.
