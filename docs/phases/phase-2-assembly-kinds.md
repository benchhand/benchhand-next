# Phase 2: assembly operation kinds

Status: design reviewed by the owner; the owner decided its seven questions on 2026-11-27 (see [Owner decisions](#owner-decisions-2026-11-27)), and ADR-0021 is accepted. No contract or code is changed. Written 2026-11-27 against `main` at `09394c69`. Inputs: the prototype at the pin `412b5d9`, prototype PRs #333, #334, #337 and #341 (merged) and #348 (open), and the test project's `hw/` as read on 2026-11-27 at 17:06. The test project was only read. Nothing of it was copied, and this page gives counts and operation indices, not its content. The decision record is [ADR-0021](../adr/0021-assembly-operation-kinds.md), status accepted.

The owner decided on 2026-11-27 that the assembly operation kinds get one design pass before their contracts and migrate rules (`docs/phases/phase-0-1.md`, Decided, item 2). This is that pass.

## Verdict

- **13 step kinds:** the 10 kinds at the pin, plus `place`, `bench` and `hold`. `install` doesn't become a kind. A finished bench unit goes into its build through a `place` or a joining step whose `part` names the sub-build.
- **Three new keys on an operation:** `sub_build` (#334), `retained_by` (on `place` only) and `instructions` (on every kind, guide text only). `hold` keeps its `duration`, `fixture`, `orientation` and `cure` from #334.
- **These stay off the operation:** `make_buy: existing` (part), `role` (occurrence and subassembly), `mount` (joint), fits by explicit limits (`Drawing.fit`) and `mates_with` (release manifest).
- **Test project:** under these rules the 8 `bench` operations, 14 of the 20 `place` operations and the `instructions` on all 86 operations migrate mechanically. The other 6 `place` operations need a hand edit before the record validates. The 12 `limits_mm` entries migrate once #348 merges.
- **Sealed history:** with `retained_by` checked by the record validator, not the schema, the snapshots v10 to v20 can be read through the in-memory upgrade. Evidence staleness for them can then be computed. That holds once the fits row exists, which needs #348 merged.
- **Order:** first the record contracts of #332, #331, #333 and #335. Then `role`, a port of the pin's order checks with no change of behaviour, these kinds, and `mount`. The fits row comes after #348 merges. The pin moves to `5dcd2c92` once the #331 to #341 batch is in.

## The forms in play

| Form | Where | What it says | State |
|---|---|---|---|
| 10 kinds: `press_fit`, `heat_set`, `retaining_ring`, `insert`, `fasten`, `join`, `close`, `adjust`, `inspect`, `disassemble` | prototype `412b5d9` `assembly.schema.json`; `contracts/record/assembly.tsp:371` | Record order is the sequence. The one occurrence no step installs is the base. Every other uninstalled occurrence fails `assembly.never_installed` (prototype `assembly_operations.py:17-27`). | on `main` |
| `place` with `retained_by` | plan section 12b; test project | Installs a part without making a joint. It names the joint that holds it. | in no prototype commit; `git log --all -S retained_by` in the prototype finds nothing |
| `bench` | test project | Puts a part on the bench, so later steps work on it before it is installed | in no prototype commit |
| `instructions` | test project | Build-guide text on a step | in no prototype commit |
| `install`, `hold`, `sub_build` | #334, `95999a32` | A bench sub-build has its own base, state and closure. `install` puts the unit into the main build. `hold` keeps a part in a fixture for a time. | merged |
| `make_buy: existing` | #333, `2ef059f8` | Equipment the product mounts onto. It is present from the start, never the base of a build, never an operation's `part` (`existing.installed`). | merged |
| `sourcing.delivered`, `product.step`, `assembly.step`, `mates_with` | #337, `2e840b64` | One predicate: only existing equipment is not delivered. The release lists each interface with an existing end under `mates_with`. | merged |
| `role`: `product`, `context`, `tooling` | plan section 12a | Per occurrence or subassembly. It says what the exports do with it. The default comes from `make_buy`. | plan only |
| `mount: {point}` on a fixed joint | #341, `5dcd2c92` | A point on the intended face contact, for the joint check | merged |
| `limits_mm: {hole, shaft, decision}` | test project, a local patch of its plugin | Diameter limits beside a plain-language `fit` | #348 (open) refuses this key and says how to rewrite it in its own form |
| `nominal_mm`, `deviations`, `interference`, `clearance`, `source`, `compliance`, `ribs` | #348 `drawing.schema.json` `$defs/fit` | A fit in exactly one form: an ISO 286 string, or explicit limits with a source | open |

`docs/phases/phase-0-1.md` (Surprises, item 2) says `bench` and `instructions` come from #334. They don't: `git log --all -S'"bench"'` over the schema and `-S'"instructions"'` over the whole prototype find no commit. The test project wrote them ahead of any schema.

### How the test project uses them

These are the counts at 17:06 on 2026-11-27. The record changed while it was being read (from 84 to 86 operations), so treat them as one snapshot.

- 86 operations: 20 `place`, 20 `inspect`, 16 `join`, 10 `fasten`, 8 `bench`, 6 `heat_set`, 2 `adjust`, 2 `press_fit`, 2 `retaining_ring`.
- `bench` (operations 0, 4, 8, 16, 43, 47, 51, 59) has `id`, `kind`, `part` and `instructions` only. Each one starts work on a loose part: inserts, a bush, magnets and a bearing go into it, and a later step installs the finished unit. Under the pin's model, those steps fail `assembly.order`, because their receiving part is absent. #334 solves this problem with sub-builds.
- `place` (20): 14 name `retained_by`, a single step id. Each names a `fasten`, `join` or `retaining_ring` step later in the list. 4 cite an interface, all press fits of a crush-rib seat. 6 have no `retained_by`:
  - 4 move customer-furnished equipment (operations 23, 38, 66, 81): one fits the customer's part into another customer part, one puts a customer part back after the product is on.
  - 2 show a delivered loose tool in its stowed place (operations 42, 85).
- 8 steps install a finished bench unit into the main build: 6 `place` and 2 `join` (operations 24, 29, 32, 36, 67, 72, 75, 79). The membership rule under [Migrate rules](#migrate-rules) computes this list.
- 4 `inspect` steps stand for a cure (operations 13, 20, 56, 63): their acceptance feature is a cured bond, and their instructions describe the wait.
- Customer-furnished equipment: 6 parts in a subassembly whose title says they are not supplied. They are recorded `make_buy: buy`, because `existing` did not exist yet. 6 steps have one of them as `part` (operations 23, 38, 39, 66, 81, 82). 2 of those, 39 and 82, are held by the product's own ties.
- `instructions` is on all 86 operations: a list of 1 to 4 strings.
- `limits_mm` is on 12 fits in `hw/interfaces.yaml` (press, running and locating).
- Sealed snapshots: `bench` from v10, `instructions` from v11, `place` from v12 (with the same 4 unretained customer moves in v12 to v20), `limits_mm` from v16. The latest version is v20.

## Recommended kind set

| Kind | Class | Moves its part | Required | Order | Access | Joint | Source |
|---|---|---|---|---|---|---|---|
| `press_fit`, `heat_set`, `retaining_ring` | joining | yes | `into`, `interface`, `direction`, `acceptance` | yes | yes | yes | pin |
| `insert`, `fasten`, `join` | joining | yes | `into`, `direction`, `acceptance` | yes | yes | yes | pin |
| `place` | installing, no joint | yes | `into`, `direction`, `acceptance`; `retained_by` for a delivered part (validator) | yes | yes | `not_applicable`, naming `retained_by` | plan 12b, test project, #334 `install` |
| `close` | installing, encloses | yes | `into`, `closes` | yes | yes | none | pin |
| `bench` | opens a sub-build | no | `sub_build` | yes | `not_applicable` | none | test project |
| `hold` | dwell | no | `duration`, `fixture`, `orientation` | yes, with `hold_short` and `cure_unsourced` | `not_applicable` without tools (#334) | none | #334 |
| `adjust`, `inspect` | in place | no | `acceptance` | yes | yes | none | pin |
| `disassemble` | removes | yes | `into`, `direction` | yes | yes | none | pin |

"Joint: none" means what the pin does now: no `assembly.joint` obligation (`evidence/obligations.py:552`). Plan Phase 2 asks for placed parts to be marked `not_applicable` with a reason, so `place` gets the row and the others keep none.

On every kind: `id`, `kind`, `part`, optional `sub_build`, `predecessors`, `tools`, `tool_access` and `instructions`, as the pin allows them.

## Decisions

### D1. One kind for installing without a joint

The plan's `place`, #334's `install` and the test project's unit installs all put something in position without making a joint.

| Option | For | Against |
|---|---|---|
| A. `place` for a part, `install` for a sub-build unit (two kinds) | #334's tests port unchanged | Two kinds for the same physical act. The test project installs 2 units by `join` (operations 36, 79), which neither kind can express. |
| **B. `place` takes a part or a sub-build id as `part`. Any joining kind also may.** | One kind. It covers all 8 unit installs of the test project. #334's checks (`sub_build_unfinished`, `sub_build_unknown`, `sub_build_not_installed`, `closed_before_install`) keep their meaning, keyed on "a step whose `part` is a sub-build id". | It diverges from merged #334. A #334 `install` without a retaining step fails validation after migration. No known record has one: `git grep` on prototype `origin/main` (`7f174e32`) finds `sub_build` in code, tests and docs only, never in `examples/`. |
| C. Implicit: the first step in the parent build that moves a sub-build's base installs the unit | No `part` rewrite | The unit is never named. `sub_build_unknown` can't be checked, and a reader can't tell a unit install from a move of one part. |

Recommendation: B. When the `part` of a joining step is a sub-build id, the joint's part end is that sub-build's base occurrence. A sub-build id may be the `part` of `place` and of the joining kinds only, not of `close`, `adjust`, `inspect`, `hold`, `disassemble` or `bench`.

### D2. A sub-build's base

| Option | For | Against |
|---|---|---|
| A. Inferred, as #334: the first uninstalled occurrence the sub-build names | No new kind | The record never says which part is on the bench. The guide can't print the bench setup as a step. The test project's 8 `bench` steps have nowhere to go. |
| **B. A `bench` step opens each sub-build and names its base** | Explicit, and the test project's form. The guide prints it as the first step of the unit. | One more kind. #334 records without one need a rule (see below). |

Recommendation: B, for sub-builds only. The main build keeps the pin's inferred base, so no pin record changes. Rules:

- `sub_build` is required on `bench`.
- Each sub-build has at most one `bench`, and it is the first step of that sub-build in record order.
- Its `part` is an occurrence that no step of that sub-build installs, and whose `role` is `product`.
- A #334 sub-build without a `bench` keeps the inferred base. This is the one case where a base is inferred in a sub-build. It stays so that #334 records need no inserted step. The alternative, a migrate row that inserts a `bench` step, needs the YAML editor to insert a whole list item, and no known record has a #334 sub-build.

### D3. Membership of a sub-build

| Option | For | Against |
|---|---|---|
| **A. A `sub_build` key on every step of the unit (#334)** | Each step says its build. `sub_build_shared` and the per-build closure are checkable. | The test project has no such key, so migration has to add it. |
| B. Derived from `bench` and the `into` chain | No key to write | Every reader and check repeats the derivation. A typo in `into` silently moves a step to another build. |

Recommendation: A. The test project's form is converted once by the `assembly-bench-sub-build` row, which writes the keys. After that, the record states membership and nothing derives it.

### D4. Existing equipment as the `part` of a step

The plan (12b) and #333 (`existing.installed`) say that existing equipment is never a step's `part`, only its `into`. The test project has 6 such steps. In 4 of them the customer moves their own part, and the product's access depends on it: one customer part is off while the product goes on, then it goes back. In the other 2, the customer's part is held by the product's ties.

| Option | For | Against |
|---|---|---|
| A. Keep the rule | Simple. The customer's equipment is fixed context. | The access and interference checks then see a customer part in the path that the real sequence has removed. The test project's sequence can't be written. |
| **B. Allow existing equipment as the `part` of `place` and `disassemble` only** | The checks see the real sequence. A customer part held by product ties gets its retention from those joints. | It narrows a merged prototype guard and changes plan 12b. |
| C. Allow it for any kind | No special case | A joining step on customer equipment would create joint obligations on parts the product doesn't make or buy. |

Recommendation: B. Existing equipment stays present from the start and is never the base of a build (#333). A `place` of an existing occurrence must come after a `disassemble` of it in the same build, or it fails `assembly.installed_twice`. `existing.installed` stays for the joining kinds, `close` and `bench`. This is owner question 1.

### D5. `retained_by`: shape and where it is checked

- **Shape.** A list of step ids (at least one, unique), or an open fact (`Common.fact_open`: `unknown` with a reason, or `not_applicable` with a reason and an optional decision). The test project gives one id per step. A list lets a part held by three thumb screws name all three. The `not_applicable` form covers a delivered loose item, such as the stowed tool of operations 42 and 85, with a stated reason in place of a silent gap.
- **Each id** names a joining step (`press_fit`, `heat_set`, `retaining_ring`, `insert`, `fasten`, `join`) in the same build, later in record order. A step in a sub-build must be retained before its unit is installed. All 14 ids in the test project meet this.
- **Where it is required.** The record validator (`record/rules/assembly.py`) requires it on a `place` whose part has `role: product`. It is optional for `context` and `tooling`, and for a unit install it is required, because a unit is delivered. The schema allows it on `place` and forbids it on every other kind. The schema can't require it, because `role` comes from the part record and the occurrence, which are other documents.

| Option | For | Against |
|---|---|---|
| Required by the schema on every `place` (plan 12b as written) | One rule, checked at read time | It refuses the 4 customer moves and the 2 loose tools. The sealed snapshots v12 to v20 then can't be read, because the in-memory upgrade reads them against the schema (`evidence/reader.py:254-265`), so their staleness is never computed. |
| **Required by the validator for delivered parts** | Customer and tooling moves need no invented retention. Sealed snapshots read. The live record still refuses an unretained delivered part. | The schema alone doesn't show the rule. |

Recommendation: the validator. Owner question 3.

### D6. `role`, `delivered`, export names and `mates_with`

- **`role`** (plan 12a) goes on `occurrences[]` and `subassemblies[]` in `record/assembly`. An explicit occurrence's own `role` wins, then its subassembly's, then the default from its part: `existing` gives `context`, anything else gives `product`. An `existing` part with `role: product` is refused (`assembly.role_conflict`), because it can't be delivered.
- **`delivered`** (#337 `sourcing.delivered`) becomes "the occurrence's role is `product`". #337's `sourcing.group` (`made`, `purchased`, `existing`) stays, keyed on `make_buy`. It is the sourcing group of plan 12a's annotation set. The home is `record/` (`sourcing.py` has no map entry yet; the survey proposes `record/rules/assembly.py`).
- **Export names.** The plan's `product.step` and `scene.step` against #337's `product.step` and `assembly.step`. #337's own code says the names are "still under review" (`sourcing.py`, comment above `PRODUCT_STEP`). Recommendation: the plan's names. Owner question 6.
- **`mates_with`.** Recommendation: it joins the Phase 4 release manifest at 1.0.0, in #337's shape. It has one entry per interface between a `product` occurrence and an `existing` part: the interface, its type, the product-side end, the equipment's PN and title, and its `existing` record. `tooling` is left out, because it doesn't mate in service. Owner question 5.
- **Obligations of an existing part.** The plan records them `not_applicable` with the role as the reason. #333 records none. As the survey says, follow the plan and keep #333's tests as the cases.

### D7. `instructions`

| Option | For | Against |
|---|---|---|
| **A. An optional list of non-blank strings on every kind, read by the build guide and assembly sheets only** | Keeps 86 steps of written guidance. No check reads it, so it can't stand in for a fact. | A new field the prototype doesn't have |
| B. Drop it in migration | Prototype parity | Loses the guidance with no replacement |
| C. Map it to `inspection` | An existing field | `inspection` is one string, and its meaning is the inspection method |

Recommendation: A. It joins no fingerprint domain that a check reads. A change to it stales the build guide only. Owner question 7.

### D8. Cures written as `inspect`

The test project's 4 cure steps are valid `inspect` steps. Migration can't make them `hold` steps, because `duration`, `fixture` and `orientation` are only in the free text. Recommendation: no migrate row. Rewrite them by hand in the project to `hold` with `cure` from the adhesive datasheet, which the joining steps' `consumables` already name, so that `assembly.hold_short` and `assembly.cure_unsourced` apply.

### D9. `mount` (#341)

`mount` is a key of a fixed joint, not a step kind. It ports as #341 has it: an optional `{point}`, allowed only when `type` is `fixed`. Its relation to the kinds: a `place` step's retaining step may have a fixed joint with a `mount` (through `verify_joint`), and the joint check that reads the mount is Phase 4 (`providers/checks-process/`).

### D10. Fits by explicit limits (#348)

The fit belongs to the interface. #348 puts its explicit-limits form on `Drawing.fit` (`contracts/record/drawing.tsp:638`), so it bumps `record/drawing`, not `record/assembly`. It touches the kinds in two places:

- A `place` that cites an interface (4 in the test project, all crush-rib press fits) takes its access exemption from that interface's engagement length, as #348's `access.py` does for a press fit. The `retained_by` steps carry its retention evidence, which agrees with #348's "retention keeps its normal joint-source rule".
- A crush-rib fit (`compliance: crush_rib`) in a `press_fit` step keeps that kind's joint obligations.

Recommendation: port #348 after it merges, as its own step, with the `fit-limits-mm` migrate row below. Owner question 4.

## Per kind

### `place`

- **Fields:** `part` (a `part_ref` or a sub-build id), `into`, `direction`, `acceptance`, optional `interface` (any limit kind), `path`, `retained_by`, `sub_build`, `tools`, `tool_access`, `predecessors`, `instructions`.
- **Forbidden:** `edge_distance`, `engagement`, `torque`, `retention`, `closes`, and the `hold` fields. The joint facts belong to the retaining step.
- **Invariants:** D5 for `retained_by`. D1 for a unit. D4 for existing equipment. An interface it cites must have the placed part at one end.
- **Checks and evidence:**
  - order: the receiving part is present, the part is not yet installed or enclosed, the retaining steps come later in the same build;
  - access: the part's path and tools, with the interface's engagement exemption;
  - joint: `not_applicable`, with the reason naming `retained_by`;
  - the retaining steps' `assembly.joint` coverage names the parts they hold. `assembly.joint` is decided by the record and never stale (`evidence/fingerprints.py:110`, `RECORD_FAMILIES`). The fingerprint of a `place` step's order and access evidence includes its retaining steps, so a change to one stales the placed part's evidence (plan 12b). That change belongs in `evidence/fingerprints.py`; untested;
  - motion reads `joints`, not operations, so `place` changes no motion input;
  - the BOM has no step rows. Release: none;
  - the guide prints "place X into Y, held by step N". The assembly drawing's step sheet shows the part with its retaining step.
- **Migrate:**
  - pin form: none to convert;
  - #334 `install`: `kind: install` becomes `place`, with `part` unchanged. The rule refuses nothing, and the validator reports a delivered unit with no `retained_by`;
  - test-project form: `retained_by: <id>` becomes `[<id>]`. A unit install's `part` becomes the sub-build id (row `assembly-bench-sub-build`). The 6 steps without `retained_by` stay as they are and fail validation until edited by hand ([Test project outcome](#test-project-outcome)).

### `bench`

- **Fields:** `part`, `sub_build`, optional `fixture`, `orientation` (both as `hold` defines them; read by the guide only) and `instructions`.
- **Forbidden:** `into`, `direction`, `interface`, `acceptance`, `path`, `closes`, `retained_by`, the joint facts and `duration`, `cure`.
- **Invariants:** D2.
- **Checks and evidence:**
  - order: first of its build, one per build, part not installed in that build, `role: product`. A breach is `assembly.bench_misplaced`;
  - access: `not_applicable`, "a bench step moves nothing";
  - joint: none. Motion, BOM, release: none;
  - the guide prints the unit's first step with its fixture, orientation and instructions.
- **Migrate:** test-project form: row `assembly-bench-sub-build` adds `sub_build` to each `bench` step and to the unit's steps. Pin and #334: no `bench` exists.

### `hold`

- **Fields:** as #334: `duration` (time), `fixture`, `orientation`, optional `cure: {time, temperature}`, plus `part` (a `part_ref`), `sub_build`, `tools`, `tool_access`, `instructions`.
- **Forbidden:** `into`, `direction`, `path`, `edge_distance`, `retained_by`. The `hold` fields are forbidden on every other kind except `fixture` and `orientation` on `bench`.
- **Invariants:** #334's. A cure figure counts only as a known fact with a datasheet source. A hold time that is not a positive time is unknown. A one-sided interval is refused (`quantities.py`).
- **Checks and evidence:**
  - order: the part is present in the hold's own build. Also `assembly.hold_short` and `assembly.cure_unsourced`;
  - access: `not_applicable` without tools. An uncited tool gets a `not_assessed` advisory row, and a cited envelope is measured. `hold_reach` is the seam that #336 extends; #336 has since merged as `27496080`;
  - joint: none. Motion, BOM, release: none;
  - the guide prints fixture, orientation and hold time, and the cure figures only when they have a datasheet source.
- **Migrate:** #334 form is identical in v3, so it needs no row. The test project has none (D8).

### `sub_build` (key)

- **Shape:** `^[a-z][a-z0-9_-]*$`, a subassembly id or a new id, as #334.
- **Checks:** #334's findings: `sub_build_unfinished`, `sub_build_shared`, `sub_build_unknown`, `sub_build_not_installed`, `installed_twice`, `closed_before_install`, and `never_installed` per build. Assumption: `sub_build_shared` means "installed by steps of two builds". A main-build step into a member of an installed unit is not sharing (the test project's thumb screws into the collar's inserts). Confirm when porting #334's `SubBuildTests`.
- **Nesting:** a sub-build can't be installed into another open sub-build (#334: `install` forbids `sub_build`). The test project doesn't nest.

### `instructions` (key)

- **Shape:** a list of non-blank strings, at least one.
- **Checks:** none. The guide and the assembly sheets print it.
- **Migrate:** none needed. The test-project key is accepted as written.

### Unchanged kinds

`press_fit`, `heat_set`, `retaining_ring`, `insert`, `fasten`, `join`, `close`, `adjust`, `inspect` and `disassemble` keep their pin fields and checks. Three changes reach them:

- the joining kinds may take a sub-build id as `part` (D1);
- `disassemble` may take existing equipment as `part` (D4);
- every kind may carry `sub_build` except `bench`, where it is required, and `instructions`.

## Findings

New record-validator codes, in `record/rules/assembly.py`:

| Code | When |
|---|---|
| `assembly.place_unretained` | a `place` of a `product` part, or of a unit, has no `retained_by` |
| `assembly.retained_by_unknown` | a `retained_by` id names no step |
| `assembly.retained_by_not_joining` | it names a step that is not a joining kind, is in another build, or comes earlier |
| `assembly.bench_misplaced` | two `bench` steps for one sub-build, a `bench` that isn't first in its build, or a `bench` whose part that build installs |
| `assembly.role_conflict` | an `existing` part with `role: product` |

Order findings come from #334 with its codes. #333's `existing.installed` narrows as D4 describes. Finding codes are free strings under the `common/finding` pattern, so none needs a contract bump (survey, "Contract versions").

## Migrate rules

New rows for `RULES` in `record/migrate/rules.py`, one per form and each with a fixture under `migrate_fixtures/<id>/`. The source column follows the table in `docs/contract/record-migration.md`.

| Id | Document | Changes | Refuses | Source |
|---|---|---|---|---|
| `assembly-bench-sub-build` | `hw/assembly.yaml` | adds `sub_build` to each `bench` step and to every step of its unit; sets a unit install's `part` to the sub-build id | `migrate.sub_build_nested`: a unit installed into another open sub-build. `migrate.sub_build_id_taken`: the derived id equals another sub-build's | test project, no prototype commit |
| `assembly-place-retained-by` | `hw/assembly.yaml` | `retained_by: <id>` becomes `[<id>]` | nothing | test project, no prototype commit |
| `assembly-install-place` | `hw/assembly.yaml` | `kind: install` becomes `kind: place` | nothing; the validator reports an unretained unit | #334 (`95999a32`) |
| `fit-limits-mm` | `hw/interfaces.yaml` | each `limits_mm` becomes #348's form: `nominal_mm`, `deviations` (`units: mm`, each side's limits minus the nominal), `source: {kind: decision, decision, reference: <the old fit text>}`; the old `fit` text goes. One info finding per fit, `migrate.fit_limits_review`, says that `compliance: crush_rib` is the author's call and that `nominal_mm` was set from the limits | `migrate.fit_limits_unreadable`: a side with no two bounds, bounds in the wrong order, or no `decision` | test project; lands after #348 merges |

**Membership rule of `assembly-bench-sub-build`.** It walks the steps in record order. A `bench` step opens a sub-build with its `part` as base. The id is the step's id with a trailing `-bench` removed. A later step joins an open sub-build when its `into` is a member, and its `part` then becomes a member. A step with no `into` whose `part` is a member also joins it. A step whose `part` is an open sub-build's base and whose `into` is outside it installs that unit and closes it. Run in memory on the test project, the rule assigns 38 steps and the 8 `bench` steps to 8 sub-builds and finds the 8 unit installs. It nests none and leaves none open.

**The `nominal_mm` of `fit-limits-mm`.** `limits_mm` holds limits, not a basic size, and no single rule recovers the basic size. Taking the shaft's upper limit fits #348's bearing example but not a 5 mm running fit. Taking the hole's lower limit fits the running fit but not the bearing. The row takes the hole's lower limit: the deviations are then exact, and the drawings print limits. The info finding asks for review. Owner question 4 chooses between this and a refusal.

**No row needed.** The pin's 10 kinds, #334's `hold` and `sub_build`, #333's `existing`, #341's `mount`, `role` and `instructions` all have the same form in v3 as in their source.

**Editor prerequisites.** The YAML editor (`migrate/yaml_edit.py`) replaces scalars and removes entries. It can't add a key to a block mapping, and it can't put a flow sequence where a scalar was. `assembly-bench-sub-build`, `assembly-place-retained-by` and `fit-limits-mm` need both. Each new splice gets layout fixtures under `migrate_layout_fixtures/`, like the existing ones.

**Sealed history.** The rows run on snapshots through the in-memory upgrade (`migrate/sealed.py`), which checks the schema and not the validator. With D5, the snapshots v10 to v15 upgrade once the three assembly rows exist, and v16 to v20 once `fit-limits-mm` exists too. Their staleness is then computable. `docs/phases/phase-0-1.md` (Surprises, item 3) found it not computed. This is a prediction from the rule design; untested.

## Test project outcome

With every row above and the record unchanged:

- migrates mechanically: the 8 `bench` steps, the 38 unit steps, the 8 unit installs, the 14 retained `place` steps and the `instructions` on all 86 steps. The 12 fits migrate once #348 has merged;
- fails validation, so apply refuses: 6 `place` steps. The 4 customer moves (operations 23, 38, 66, 81) place `buy` parts without retention. The 2 stowed tools (operations 42, 85) are delivered parts without retention.

Hand edits in the project, each the author's or the user's call:

1. Record the 6 customer-furnished parts as `make_buy: existing` with their `existing.dimensions` ranges and basis (#333 says what to ask the user). `role` then defaults to `context`.
2. Operations 23 and 66 fit a customer part that is present from the start. Remove them and record the removal of the customer part that blocks the product as a `disassemble` before the unit install. Operations 38 and 81 then put it back (D4).
3. Give operations 42 and 85 `retained_by: {status: not_applicable, reason: ...}`.
4. Optional: rewrite the 4 cure steps as `hold` (D8).

## Contract versions

Following the survey's table (`docs/phases/prototype-port-331-341.md`, "Contract versions"), with this design:

| Contract | Now | After | Caused by |
|---|---|---|---|
| `record/part` | 1.0.0 | 1.1.0 (#332), 1.2.0 (#331), 1.3.0 (#333), 1.3.1 (#337, description only) | `render`; `designation`; `existing` |
| `record/assembly` | 1.0.0 | 1.1.0 (`role`), 1.2.0 (kinds), 1.3.0 (#341) | `role` on occurrences and subassemblies; `place`, `bench`, `hold`, `sub_build`, `retained_by`, `instructions`, a sub-build id as `part`; `mount` |
| `record/drawing` | 1.0.0 | 1.1.0 (#348, after it merges) | explicit-limits fit forms |
| `record/common` | 1.1.0 | 1.2.0 (#335) | `not_assessed_reason` values |
| `record/manufacturing-guideline` | 1.0.0 | 1.1.0 (#335) | `warp`, `applies_to.max_size` |
| release manifest | none | 1.0.0 (Phase 4) | `mates_with` from the start |

Differences from the survey: `record/assembly` gains a `role` step, and its kinds step covers #334, plan 12b and the test project. `record/drawing` is new in the table, because #348 is outside the survey's range.

What the breaking-change check will report, from `docs/contract/versioning.md`'s rules table; untested, because no release tag is reachable:

- the new `kind` values are `enum`-widening, so they pass;
- the new `if`/`then` branches are `constraint-added` or `schema-constrained`. Each branch gates on a new kind or a new property, so an old record still validates;
- `part` as a `part_ref` or a sub-build id adds an `anyOf` branch if the union compiles to `anyOf`. If it compiles to `oneOf`, the check reports `unproven-change`.

Argue each in `versioning.md`, as the `obligation_id` widening was.

## Port order

Each step is its own reviewed change (ADR-0015):

1. ADR-0021 accepted, with the owner's answers below (done 2026-11-27).
2. #332: `record/part` 1.1.0.
3. #331: `record/part` 1.2.0. It can run beside #332.
4. #333: `record/part` 1.3.0. Existing obligations `not_applicable` per the plan, and `existing.installed` per D4.
5. #335: `record/common` 1.2.0, `manufacturing-guideline` 1.1.0. It can run beside steps 6 to 8.
6. `role` and `delivered` (plan 12a, #337's record side): `record/assembly` 1.1.0.
7. The pin's order checks (`assembly_operations.py`, Phase 2 in the map) ported into `record/rules/assembly.py` with no change of behaviour, against the prototype's `test_assembly_operations.py` cases at the pin. This gives #334's port a base to differ from.
8. The kinds: `record/assembly` 1.2.0, the validator codes, #334's order findings and `quantities.py`, the editor's two new splices, and the rows `assembly-bench-sub-build`, `assembly-place-retained-by` and `assembly-install-place`.
9. #341 `mount`: `record/assembly` 1.3.0.
10. #337's evidence side: `cad.product_exports` in `evidence/obligations.py` with its `geometry` and `occurrences` fingerprint.
11. The pin move to `5dcd2c92`, with the four map entries the survey lists. `sourcing.py` maps to the `role` home of step 6.
12. After #348 merges: `record/drawing` 1.1.0 and the `fit-limits-mm` row, then a later pin move.

Then the test project's hand edits and a migrate run on a copy.

## Owner decisions (2026-11-27)

The owner took the recommendation on all seven questions (Inbox, "benchhand-next build" thread):

1. **Existing equipment as a step's `part`:** allowed for `place` and `disassemble` only, with a `place` coming after a `disassemble` of it (D4).
2. **`install` folded into `place`,** and joining kinds may install a unit too (D1).
3. **`retained_by`** is required by the validator for delivered parts, not by the schema on every `place` (D5).
4. **Fits by explicit limits:** wait for #348 to merge, then derive `nominal_mm` from the hole's lower limit with an info finding (D10, [Migrate rules](#migrate-rules)).
5. **`mates_with`** goes in the Phase 4 release manifest, in #337's shape, listing interfaces with an `existing` end (D6).
6. **Export names:** the plan's `product.*` and `scene.*` (D6).
7. **`instructions`** is a guide-only field on every step (D7).

## How this was checked

- `gh pr view` and `gh pr diff` for #333, #334, #337, #341 and #348 (`benchhand/benchhand`), read in a temporary directory that was then removed.
- The prototype at `412b5d9` (`.git/agent-scratch/prototype-412b5d9`): `skills/cad-record/scripts/assembly_operations.py` (module docstring, `KINDS`, `REQUIRED`) and its finding codes.
- `git log --all -S` and `git grep` in the prototype checkout for `"bench"`, `retained_by`, `"instructions"`, `limits_mm` and `sub_build`, over all branches and `origin/main` at `7f174e32`. The checkout was not changed.
- The test project's `hw/assembly.yaml`, `hw/interfaces.yaml`, `hw/parts/*/part.yaml` and `hw/versions/*/record/` were parsed in memory with PyYAML, printing counts, keys and indices only. The membership rule was run the same way. Nothing was written.
- `main`:
  - `contracts/record/assembly.tsp`, `drawing.tsp` and `common.tsp`;
  - `record/evidence/obligations.py`, `fingerprints.py` and `reader.py`;
  - `record/migrate/sealed.py` and `yaml_edit.py`, and `record/rules/assembly.py`;
  - `docs/contract/record-migration.md` and `versioning.md`.

Not done: no contract was built, no rule was written, and the breaking-change check was not run. The version numbers and the check results above are predictions.
