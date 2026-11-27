# Phases 0 and 1: gate document

Status: waiting for the owner's review. Written 2026-11-27 against `main` at `311a2a1f`. It replaces the 2026-11-25 version, written at `41598c2`, which is out of date: it listed migrate and evidence as not built. The test-project verification ran at `fb9cb2e`. The 36 commits since then add the envelope, flow and policy contracts and their generated files, tests and docs, and change no hand-written code under `packages/` (`git diff fb9cb2e 311a2a1f -- packages` touches only `benchhand_contracts/{models,schemas,examples}`). Phase 2 stays unmerged until the owner approves this (`docs/design-plan.md`, Steps).

Verdict:

- **Phase 0: partly met.** Everything is on `main` except two probe results. The Codex / ChatGPT desktop app was never run, and Kiro's tools never reach the model.
- **Phase 1: partly met.**
  - On `main`: the record, jobs, provider-protocol, envelope, flow and policy contracts, the record service (read, write, validate, migrate, evidence) and the job service. The services ran against a copy of the test project.
  - Partial: the port of the prototype's record test cases.
  - The current test project can't migrate as it stands. It uses three changes that landed in the prototype after the pinned commit `412b5d9`.

## Exit criteria

Criteria are the bullets of Phase 0 and Phase 1 in `docs/design-plan.md:539-550`. Log numbers refer to the raw logs listed at the end.

### Phase 0: repo and contracts

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 0.1 | Repo with a uv workspace, a pnpm `ui/`, CI, complexity limits, the slopvac prose check, and the repo name only in `release.toml` | met | Workspace of `packages/*`: `pyproject.toml:9`. pnpm: `ui/pnpm-workspace.yaml`. CI steps (ruff, pytest, reference map, wheel tests, ui typecheck, contracts check and drift, prose gate): `.github/workflows/ci.yml:72-89`. Complexity limit 10, enforced with no baseline: `pyproject.toml:34-39`. Repo name: `release.toml:3`. CI run 45987586589 on `311a2a1f` succeeded. CodeQL default setup is configured with 0 open alerts (log 16). The prose gate runs on pull requests only (`ci.yml:84`). |
| 0.2 | Reference material imported with its history | met | `c4aed06`; `reference/` holds 35 prototype `cad-record` test files (`reference/skills/cad-record/tests/`). The prototype's commits sit below the import in `git log` (for example `827ee45`). |
| 0.3 | ADRs for D1 to D17 | met | `docs/adr/0001` to `0017` match D1 to D17 by number (`docs/adr/README.md`). ADR-0018 to 0020 came after. |
| 0.4 | Provider protocol contract, as prose and as `contracts/` | met | `docs/contract/provider-protocol.md`; `contracts/provider/protocol.tsp` and `manifest.tsp`; conformance fixtures for every message shape (`5c7fa30`). |
| 0.5 | Dev probe run by hand in the 7 hosts, results in `docs/client-support.md` | partly met | Rows exist for Claude Code CLI (headless and interactive), Codex CLI, OpenCode (headless; the run aborted at the form), Pi (headless and interactive) and Claude Desktop (`docs/client-support.md:9-16`). Kiro lists the probe tools, and they never reach the model (`:15`). The Codex / ChatGPT desktop row is empty, "manual run needed" (`:17`). Two probe fixes wait for a rerun: Claude Code's form call (`:13`) and the Claude Desktop widget (`:16`). The plan expected the "?" cells settled in Phase 0 (`docs/design-plan.md:647`). |

### Phase 1: contracts and core

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1.1 | Record contracts | met | 20 record contracts in `contracts/record/*.tsp`. With common (2), envelope (1), flow (2), policy contribution (1), jobs (1) and provider (2), 29 schemas are published under `packages/benchhand-contracts/src/benchhand_contracts/schemas/`. |
| 1.2 | Provider protocol contract | met | As 0.4. |
| 1.3 | Envelope, flow and policy contracts | met | Five contracts, each at version 0.1.0, on `main`. The next section lists them, their tests and their review history. Two things stay open for the owner and Phase 2: the merge order of providers' rule lists, and three gaps in the contracts' own scope. See [open items](#open-items-for-the-owner) 1 to 4. |
| 1.4 | Codegen with a CI drift check | met | `just contracts-check` exited 0 on `311a2a1f` (log 19): 30 TypeSpec files formatted, 30 schemas meta-validated, generated files up to date. `ci.yml:81-83` runs the check and the drift step. The breaking-change half is tested (`tests/test_contracts_gen_breaking.py`), but it was skipped on this run: "no release tag reachable from HEAD". It has not yet compared against a real release (no release tag exists). |
| 1.5 | `benchhand-contracts` | met | Generated models and validators (`packages/benchhand-contracts/src/benchhand_contracts/validation.py:55`); the 2 wheel tests install it in a fresh venv and pass (log 12c). |
| 1.6 | Record service: typed reads and writes | met | `packages/benchhand-core/src/benchhand_core/record/store.py:313` (`read_record`), `:330` (`load_record`), `:457` (`save_record`, which checks file identity and round trip before touching a file); 39 tests in `tests/record/test_record_store.py`. On the migrated copy: 26 parts and 45 decisions read, 0 read errors. |
| 1.7 | `validate` | met | `record/validate.py:43`; 54 tests in `test_record_validate.py`. On the migrated copy: 0 findings. On the unmigrated copy: 364, the designed refusal. |
| 1.8 | `migrate` | met at the pinned commit | `record/migrate/service.py:674` (`migrate`) and `:822` (`undo`); 11 rules in `record/migrate/rules.py:28`; 81 tests in `test_migrate_service.py` and `test_migrate_rules.py`. Dry run, apply, undo, and resume after a stop all ran on the test-project copy ([Verification](#verification-on-the-test-project)). It refuses the current project until three prototype changes are ported. |
| 1.9 | `evidence` | met as a library, one gap on real data | `record/evidence/assess.py:383` (`assess`), `reader.py:394` (`read_built_version`); 128 tests, with lamp-arm goldens pinned to `412b5d9` (`tests/record/evidence/lamp_arm_*.412b5d9.json`). It reads and assesses; nothing writes evidence, and no CLI or tool calls it yet. On the test project, build staleness is not computed for v10, v17 or v18. |
| 1.10 | Keep migrate extendable; port each later prototype change by its own step | partly met | The mechanism exists: one table row and one fixture per prototype change (`docs/contract/record-migration.md:51`) and `just reference-changes`. Nothing has been ported since `412b5d9` (`release.toml:9`). Since then 13 prototype PRs merged and 26 are open (log 03). The owner decided on 2026-11-27 that the port of #331 to #341 is the first Phase 2 work (see Decided). A survey of #331 to #341 is on `main`: `docs/phases/prototype-port-331-341.md`. |
| 1.11 | Port the `cad-agent` record test cases as acceptance fixtures | partly met | Ported: the validator cases that still hold (`test_record_validate.py:1`), the evidence cases (`test_evidence.py:1-5`) with the lamp-arm goldens, one fixture pair per migrate rule, and the process and run-record cases of the job service (`test_job_process.py:1`, `test_job_recovery.py:1`). The prototype has 35 `cad-record` test files and no list says which are ported; only `test_evidence.py` is cited by path. Version and release cases wait for Phases 2 and 4. `examples/lamp-arm/` exists only under `reference/`. |
| 1.12 | Job service | met | `packages/benchhand-core/src/benchhand_core/jobs/service.py:119`; 40 tests. Live on the copy: a shell job ended `succeeded` and returned its result, and `sleep 30` ended `cancelled` with exit -15 (log 18). |
| n/a | Versioning (snapshot, seal, verify) and release packaging | moved | Moved out of Phase 1 by the owner on 2026-11-25: versioning to Phase 2, release packaging to Phase 4 (`docs/design-plan.md:547`). |

Tests at `311a2a1f`: `just check` exited 0 (log 19): 951 passed and 2 deselected (376 under `packages/`, 575 under `tests/`), then 2 wheel tests passed. 0 tests skipped. I ran `uv sync --all-packages` and `pnpm --dir contracts install` first; without them the workspace packages don't import and the contract tests skip. `just typecheck` and `just lint` passed inside the same run, and `just reference-map` passed (205 entries) with `BENCHHAND_REFERENCE_DIR` set to a checkout of `412b5d9`; it can't verify that commit, because the checkout has no `.git` or stamp. The earlier run at `fb9cb2e` gave 658 passed.

### Built ahead, waiting for their gate

These are later phases. They are not part of the Phase 0 and 1 criteria, and they are not on `main`.

| Work | Where | State | Phase |
|---|---|---|---|
| Provider runtime (framing, initialize negotiation, hook dispatch, cancel, progress, artifacts, conformance kit) | unmerged local branch | 7 commits ahead, tip `92099ba4a2887e449b60cbe6283b77b73b2344cb` | 4 |
| FreeCAD (`freecad-versions.toml`, managed install) | unmerged local branch | 13 commits ahead, tip `aa7591cda002ac1d376b3a49cc99d191bab3e717` | 4 |

Also on `main`, outside the criteria: the architecture pages and function map (`docs/architecture/`), the D2 domain-model diagrams, the CEL research (`research/`), and ADR-0019 and ADR-0020.

### Envelope, flow and policy contracts (criterion 1.3)

Criterion 1.3 is met. The last fix is `ad8d889d`, and `main` is at `311a2a1f`.

Contracts, all at `x-version` 0.1.0. None has appeared in a release tag, so none has a published version to break:

| Contract | Source | Published schema |
|---|---|---|
| `envelope/envelope` | `contracts/envelope/envelope.tsp` | `packages/benchhand-contracts/src/benchhand_contracts/schemas/envelope/envelope.schema.json` |
| `flow/flow` | `contracts/flow/flow.tsp` | `.../schemas/flow/flow.schema.json` |
| `flow/rules` | `contracts/flow/rules.tsp` | `.../schemas/flow/rules.schema.json` |
| `common/cel` | `contracts/common/cel.tsp` | `.../schemas/common/cel.schema.json` |
| `policy/contribution` | `contracts/policy/contribution.tsp` | `.../schemas/policy/contribution.schema.json` |

`contracts/record/policy.tsp` also changed: a policy names its rigor. Reference pages: `docs/contract/envelope.md`, `flow.md` and `policy.md`; versioning notes at `docs/contract/versioning.md:104`.

What they fix:

- **Envelope:** a result carries a status. Only an `ok` result carries a verdict, and only a pending result carries a job handle. A refusal gives a reason and a next action. An error carries a finding. An artifact path is absolute.
- **Flow:** `flow.yaml` lists every record stage, with at least one gate and one edge. A staged gate needs every step. A human channel names who decided and quotes them, and `by` and `quote` share one `NonblankText`, which refuses whitespace-only text. An auto decision quotes nobody. A void names the user and the provisional decision it withdraws. A gate decision through a form is refused.
- **Rule lists:** one `*.celpolicy` file per list, in the restricted profile of ADR-0020: a name and one first-match match block, with `condition` and `output`. Each match list has exactly one unconditional choice. The compiler checks that it is last.
- **Policy contribution:** a provider contributes rule lists by kind, each as `{file, rules_version}`, and gate requirements.

Tests: `uv run pytest --collect-only -q tests/test_flow_contract.py tests/test_policy_contract.py tests/test_envelope_contract.py` collects 249 cases from 64 test functions (log 19 ran them in the full suite):

| File | Cases | Test functions | Covers |
|---|---|---|---|
| `tests/test_flow_contract.py` | 199 | 42 | the prototype flow and its four rule lists, every human gate, stage coverage, gate-decision identity, the schema's refusals |
| `tests/test_policy_contract.py` | 39 | 16 | the contribution shape, the merge (fall-through, ordering, reserved values, rigor union, no waiver) |
| `tests/test_envelope_contract.py` | 11 | 6 | each status's example, verdict, refusal, job handle, error, artifact path |

`tests/test_rule_lists.py` (8 cases) tests the helper that evaluates the lists. Three of the test names carry the decisions below: `test_a_prototype_staged_human_gate_passes_only_on_an_approval_that_cites_its_decisions`, `test_a_result_outside_its_kinds_domain_is_unknown_never_a_pass` and `test_rigor_gives_the_union_of_every_lists_messages_each_once_in_evaluation_order`.

Fixture: `tests/fixtures/flow/prototype-412b5d9/` holds the prototype's flow as `flow.yaml` and its four rule lists, `checks-by-iteration`, `dispatch`, `fidelity` and `rigor`, as `*.celpolicy`. The tests validate them against the schemas and evaluate them with cel-expr-python 0.1.4 (`pyproject.toml:20`; `tests/rule_lists.py`), a dev-only stand-in for the cel-go-compiled bundle that Phase 2 builds. The cases come from the prototype's behaviour: the check list at each iteration, the handler for each owned family, the fidelity at each stage, and the rigor refusal.

Review history: the branch had two GPT reviews. Between them, the rule lists were aligned with ADR-0020's profile, the merge of providers' lists was written, and the branch was rebased onto `main`, with the generated files regenerated and not merged by hand. The second review gave nine findings. The final worker fixed all nine in 12 local commits, and the supervisor checked the result. The fixes:

- four staged gates cite their provisional decision, and the decision that accepts unproved intervals;
- the motion checks run only when the version has an independent joint;
- the test helper fails on a non-bool condition and on an evaluation error;
- the rigor result is the union of messages, each once;
- `by` and `quote` refuse whitespace-only text;
- the out-of-domain rule for fidelity and dispatch results;
- exactly one unconditional choice per match list;
- the refusal of a literal `"none"` fidelity in the flow's own list.

The editor's "STOP" findings on `flow.yaml` are a false positive. It matched the file name to an unrelated schema. `test_the_prototype_flow_validates` passes against ours.

Results on `main` at `311a2a1f`: `just check` exited 0 (log 19). The contract tests ran in the full suite with 0 skipped.

Not decided, and not built:

- The merge order of providers' rule lists is a proposal, in the contracts and in a test helper (`merged()` in `tests/rule_lists.py`). Open item 1.
- The loader, the interpreter and the evaluator are Phase 2. Open items 2 to 4 name three gaps they inherit.

## Decided

The owner decided these on 2026-11-27.

1. **The gate's scope for migrate.** The Phase 1 gate proves migrate at the pin `412b5d9` and on the stripped copy of the test project (steps 4 to 8 below). Porting prototype PRs #331 to #341 is the first Phase 2 work, in `docs/phases/prototype-port-331-341.md`.
2. **The assembly operation kinds get one design pass at the start of Phase 2**, before their contracts and migrate rules. The kinds are `bench` and `instructions` in the test project, `place` in the plan (section 12b), and `install`, `hold` and `sub_build` in #334.
3. **Licence, CLA and repo tooling, merged.** On `main` at `b84b3c2c`:
   - the repo is MPL-2.0 with REUSE: `LICENSE`, `LICENSES/` and `REUSE.toml`, with `reuse lint` in `just check`, the pre-commit hook and CI;
   - the CLA is the org's hosted cla-assistant.io, org-linked, and `CLA.md` is the Benchhand gist's text;
   - prek hooks and the CI scanners (gitleaks, osv-scanner, Trivy config, actionlint, zizmor, pinact) run, as `docs/tooling.md` describes.

   The `relicense` commit that `git log main` also finds is the prototype's (`2f6cef77`, in the imported history under `reference/`).

## Verification on the test project

Source: `/Users/sjors/personal/dev/benchhand-test-project/hw`, 4,220 files, 418 MB, 26 parts, 45 decisions, `record_version: 2`, stage `detail`, latest build v18. The project has moved since the 2026-11-25 run, which saw 29 parts.

The original was only read. I copied it to a `mktemp -d` directory (`diff -rq` found the copy identical, log 00), ran everything on copies, and deleted the directory at the end. Raw logs are in `.git/agent-scratch/phase-gate/` in the main repo's git dir, not committed.

`main` has no `record validate` and no evidence command. `benchhand --help` lists `version` and `record`, and `record` has only `migrate` (`packages/benchhand/src/benchhand/cli.py:21,29`). I ran `validate()` and `assess()` through the Python API with the driver scripts kept beside the logs. `benchhand` below means `uv run benchhand` from this worktree.

| Step | Command | Exit | Result |
|---|---|---|---|
| 1. Before migrate | `validate.py <project>` (`read_record`, `validate`) | 1 | 50 read errors, 364 findings: 211 `decision.reference`, 150 `record.schema`, 2 `record.unreadable`, 1 `record.version_unsupported`. 26 parts read, 0 decisions read. Log 01. |
| 2. Migrate, dry run | `benchhand record migrate hw` | 1 | Refused. 49 files would change; 18 `migrate.gate_decision` (info); 7 `record.schema` errors: 6 `limits_mm` keys in `hw/interfaces.yaml` and 1 `bench` kind at `hw/assembly.yaml#/operations/0/kind`. Log 02. |
| 3. Migrate, apply | `benchhand record migrate --apply hw` | 1 | `refused: 0 of 49 files`. `hw/` stayed byte-identical, with no backup and no lock. Log 04. |
| 4. Strip what v3 can't hold | `strip.py` on a second copy | 0 | Dropped 8 `bench` and 18 `place` operations (76 to 50), every `instructions` key and 6 `limits_mm` keys. The dry run then ended `ready: 49 files`, exit 0. Log 05. |
| 5. Apply on the stripped copy | `benchhand record migrate --apply hw` | 0 | `applied: 49 of 49 files`. The preimages went to `.benchhand/migrate-backups/<UTC>/` with `manifest.json` and `COMPLETE`; the command printed its `--undo` line. `diff -rq` listed exactly 49 changed files, so the other 4,171 are byte-identical. Log 06. |
| 6. Validate after | `validate.py <project>` | 0 | `record_version: 3`; 0 read errors, 0 findings; 26 parts, 45 decisions read. Log 07. |
| 7. Undo | `benchhand record migrate --undo <backup>` | 0 | `undone: 49 files`; `diff -rq` against the pre-apply tree found no difference; the backup stays. Log 10. |
| 8. Stop mid-apply, then recover | `crash_apply.py <project> N` kills the apply after N written files, as `test_migrate_service.py::_crash_after` does | | Log 11. |
| 8a. Stop after 1 file | rerun `--apply` | 1 | `migrate.locked`, naming `--resume` and `--undo`. |
| 8b. | `--apply --resume` | 0 | `applied: 48 of 48 files`, one backup, tree identical to a clean apply. |
| 8c. Stop after 25 files | rerun `--apply`, then `--apply --resume` | 1, 0 | Same refusal; resume wrote 24 files; identical to the clean apply. |
| 8d. Stop after 25 files | `--undo <backup>` | 0 | `undone: 25 files`; identical to the original. |
| 9. Evidence, v18 | `evidence.py <project> v18 [<prototype guidelines>]` (`read_built_version`, `assess`) | 0 | 558 obligations: 27 pass, 6 stale, 453 unknown, 72 waived. One finding: `evidence.staleness_not_computed` (error). The acceptance digest formed. The result is the same with and without the shipped guideline sets. Logs 08. |
| 10. Evidence, v17 and v10 | same | 0 | Same tally. v17: 1 packet collected. v10: 3 packets, 37 `packet.unexpected` warnings, plus the same error. Logs 09. |
| 11. Jobs | `jobs_smoke.py <project>` | 0 | See criterion 1.12. Log 18. |

### Surprises

1. **No validate or evidence command.** Only `record migrate` exists as a CLI. The plan's CLI lists (D1 and Phase 3) name neither. The record operations arrive as `record.*` MCP tools in Phase 3.
2. **The test project is ahead of the pin.** It uses `bench` operations (prototype #334), `instructions` keys on operations (#334), and `limits_mm` on fits (open PR #348). It also uses `place` operations, which the plan schedules for Phase 2 (section 12b). Migrate refuses it, correctly, until the contracts and rules for these exist.
3. **The sealed snapshots carry the same keys.** The v18 and v17 snapshots hold `limits_mm`, and the v10 snapshot holds a `bench` operation. The in-memory upgrade can't read them, so staleness comes back `not_computed` with one error per version. For v18 the error names `interfaces.yaml: /interfaces/19/limits/locating_fit`.
4. **Packets don't change the tally.** v10, v17 and v18 give identical counts (27, 6, 453, 72) although they collect 3, 1 and 0 packets. I did not trace why. A likely cause is the missing staleness, which is an assumption.
5. **The breaking-change check had nothing to compare.** `contracts-check` printed "no release tag reachable from HEAD; skipping the breaking-change check".
6. **The shipped guideline sets aren't a package asset.** `read_built_version` takes a directory (`record/evidence/reader.py:394`). I passed the prototype copy's `skills/cad-record/assets/manufacturing/guidelines`.

## Open items for the owner

1. **Composing policy providers' rule lists** (`docs/adr/0020-cel-rule-pipeline.md:207-213`; `docs/design-plan.md:162,648`). The contracts branch proposes the following, pending confirmation:
   - per kind, evaluate the contributed lists in ascending provider name, then the flow's own list;
   - for `checks_by_iteration`, `dispatch` and `fidelity`, the first list whose output is not the kind's no-match value (`[]`, `"unknown"`, `"none"`) wins;
   - for `rigor`, every list must give true;
   - a contributed list ends with its kind's no-match value.

   The owner confirms or changes this composition and its order. It is still open in ADR-0020 (`docs/adr/0020-cel-rule-pipeline.md:207-213`) and in `docs/contract/policy.md`. Phase 2 builds the merge after it is decided.
2. **`explanation` is not in ADR-0020's restricted profile.** Dispatch findings therefore lose their "no handler for ..." text, which the prototype's dispatch list carried. The route to get it back is an amendment of ADR-0020 that adds `explanation` to the profile, then a contract change. The contracts don't need it for anything else.
3. **How the gate request cites an interval-acceptance decision.** `GateDecisionRequest` has `provisional`, the provisional decision, and no field for the decision that accepts unproved intervals. The fixture uses a test variable, `answer.cites` (`tests/fixtures/flow/prototype-412b5d9/flow.yaml`, at each staged gate). Either the request gets a field, or the engine supplies the citation. This is a Phase 2 choice.
4. **The out-of-domain rule has no implementation yet.** A fidelity outside F0 to F3, or a dispatch handler that no handler has, is UNKNOWN with a finding that names the value, never a pass. The rule is in the contract text (`contracts/flow/rules.tsp`, `docs/contract/flow.md`) and in the test helper (`tests/rule_lists.py`). The Phase 2 evaluator implements it. A literal `"none"` in the flow's own fidelity list is refused by the Phase 2 loader, because no schema can express it.
5. **53 `basis: inferred` entries in the reference map.** They are entries of `docs/architecture/reference-map.yaml` whose home the plan's behavioural reference map doesn't name (header, `:18`). They are not in the migrate output, which has no such notion. They cover 127 prototype files, which is the "about 130" (`inferred.py`, log 13). By status: 36 `planned`, 7 `partial`, 9 `dropped` and 1 `ported`. By phase: 8 in Phase 1, 15 in Phase 2, 5 in Phase 3, 13 in Phase 4, 1 each in Phases 5 and 6, and 10 with no phase. The owner confirms or corrects the homes. The 10 with no phase need a phase first.
6. **Probe gaps.** Run the Codex / ChatGPT desktop app, and settle Kiro's tool exposure (`docs/client-support.md:15,17`). The 2026-11-25 document records both as paused at the owner's request.
7. **Advance the pin.** 13 merged and 26 open prototype PRs follow `412b5d9`. The owner has decided that #331 to #341 are ported first (see Decided). Which of the other open PRs follow, and when `release.toml` `reference_commit` moves, stay open (ADR-0015, `just reference-changes`).
8. **Scope of decisions that migrate leaves unscoped** (ADR-0019, line 31). Migrated decisions carry no approval scope. Phase 2 must treat them either as covering the whole stage or as needing confirmation at the next gate.
9. **Shipped guideline sets** become a package asset when the guideline catalog is ported (`docs/design-plan.md:649`). Until then the caller names the directory.
10. **No ledger of ported test cases.** Criterion 1.11 can't be checked mechanically. Adding a `tests` field to the reference map is a possible fix; the owner decides.
11. **Gaps the architecture pages list.** Each is a plan gap, not a Phase 1 defect:
   - the middleware chain, the provider host, `viewer-ocp` and `policy-default` have no phase (`docs/architecture/containers.md:181`);
   - the envelope and the annotation set each appear in two phases (`docs/architecture/layers.md`, "Where the plan and the code differ");
   - a freeze without a digest, artifact placement and the migrate entry point are open (`docs/architecture/data-flow.md:344-351`).
12. **Beads** `benchhand-fct` (drawing fixes, Phase 4) and `benchhand-3fc` (ignore rules for setup, release and validate) carry over from the 2026-11-25 document. I did not recheck them.

## What Phase 2 starts with

1. The port of prototype PRs #331 to #341, as its own reviewed steps (`docs/phases/prototype-port-331-341.md`). Each step has a contract change, a migrate rule, a fixture and a pin move.
2. One design pass on the assembly operation kinds (`bench`, `instructions`, `place`, `install`, `hold`, `sub_build`), before their contracts and migrate rules. Then the other changes the test project needs:
   - `make_buy: existing` and the occurrence `role` (#333, #337);
   - fits by explicit limits (#348, still open in the prototype).

   The annotation set and test-coupon evidence follow (plan Phase 2).
3. The owner's answers to open items 1, 3 and 8, and to item 2 if the explanation text is wanted.
4. Version snapshots, seal and verify. Evidence staleness for v10 to v18 depends on reading these snapshots, and the freeze and `--since-version` baselines use them.
5. `flow.yaml` and its interpreter, the CEL pipeline of ADR-0020 and the rule lists, on the contracts of criterion 1.3. A literal `"none"` fidelity fails at load, and an out-of-domain result is recorded as UNKNOWN (open item 4). ADR-0020 leaves four choices to Phase 2: where a user's bundle lives, how a scope is declared, the first profile's extensions, and the enum lint (`docs/adr/0020-cel-rule-pipeline.md:214-217`).
6. Decision records, the VOID cascade, scoped approvals (ADR-0019), and `flow/guides/*.md`.

## Raw logs

In `.git/agent-scratch/phase-gate/`: `00-copy` to `18-jobs-smoke`, the driver scripts (`validate.py`, `evidence.py`, `strip.py`, `crash_apply.py`, `jobs_smoke.py`, `inferred.py`), and the evidence results as JSON.

Log 19, the `just check` run at `311a2a1f`, is `agent-scratch/gate-check.log` in this worktree's git dir.
